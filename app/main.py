import asyncio
import datetime
import email.mime.text
import os
import platform
import secrets
import shutil
import smtplib
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

import aiosqlite
import bcrypt
import discord
import psutil
import uvicorn
from discord.ext import commands
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

PROCESS_START = datetime.datetime.utcnow()

from database import (
    DB_PATH, init_db, get_config, set_config,
    get_guild_config, set_guild_config, get_all_guild_config,
    db_rows, db_one, db_exec, log_mod_action,
)

VERSION = (Path(__file__).parent / "VERSION").read_text().strip()
SECRET_KEY_PATH = Path("/app/data/secret.key")


def load_secret_key() -> str:
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_text().strip()
    key = secrets.token_hex(32)
    SECRET_KEY_PATH.write_text(key)
    return key


SECRET_KEY = load_secret_key()


def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_pw(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ── Discord Bot ───────────────────────────────────────────────────────────────

COGS = [
    "cogs.moderation",
    "cogs.leveling",
    "cogs.welcome",
    "cogs.automod",
    "cogs.reaction_roles",
    "cogs.logging_cog",
    "cogs.custom_commands",
    "cogs.tickets",
    "cogs.giveaways",
    "cogs.notifications",
    "cogs.freestuff",
]


class BotManager:
    """Aggregates multiple discord.py Bot instances behind a shared API."""

    def __init__(self):
        self._bots: dict[int, commands.Bot] = {}

    def _ready_bots(self) -> list:
        return [b for b in self._bots.values() if b.is_ready()]

    def _bot_for_guild(self, guild_id: int):
        for b in self._bots.values():
            if b.get_guild(guild_id):
                return b
        return None

    @property
    def guilds(self) -> list:
        seen: set[int] = set()
        result = []
        for b in self._bots.values():
            for g in b.guilds:
                if g.id not in seen:
                    seen.add(g.id)
                    result.append(g)
        return result

    def get_guild(self, guild_id: int):
        for b in self._bots.values():
            g = b.get_guild(guild_id)
            if g:
                return g
        return None

    def get_channel(self, channel_id: int):
        for b in self._bots.values():
            c = b.get_channel(channel_id)
            if c:
                return c
        return None

    def is_ready(self) -> bool:
        return any(b.is_ready() for b in self._bots.values())

    @property
    def latency(self) -> float:
        ready = self._ready_bots()
        if not ready:
            return float("inf")
        return sum(b.latency for b in ready) / len(ready)

    @property
    def user(self):
        for b in self._ready_bots():
            return b.user
        return None

    @property
    def application_id(self):
        for b in self._ready_bots():
            return b.application_id
        return None

    @property
    def cogs(self) -> dict:
        result: dict = {}
        for b in self._bots.values():
            result.update(b.cogs)
        return result


bot = BotManager()


async def _run_single_bot(token_id: int, token: str):
    intents = discord.Intents.all()
    instance = commands.Bot(command_prefix="!", intents=intents)

    @instance.event
    async def on_ready():
        await instance.tree.sync()
        print(f"Phobos v{VERSION} online als {instance.user} [ID {token_id}]")

    bot._bots[token_id] = instance
    try:
        async with instance:
            for cog in COGS:
                try:
                    await instance.load_extension(cog)
                except Exception as e:
                    print(f"[Token-ID {token_id}] Fehler beim Laden von {cog}: {e}")
            await instance.start(token)
    finally:
        bot._bots.pop(token_id, None)


async def run_bot():
    print("Warte auf Discord Tokens...")
    while True:
        tokens = await db_rows("SELECT id, token FROM bot_tokens WHERE enabled=1")
        if not tokens:
            legacy = await get_config("discord_token")
            if legacy:
                tokens = [{"id": 0, "token": legacy}]
        if tokens:
            break
        await asyncio.sleep(5)
    await asyncio.gather(*[
        asyncio.create_task(_run_single_bot(t["id"], t["token"])) for t in tokens
    ])


# ── Web UI ────────────────────────────────────────────────────────────────────

web = FastAPI()
web.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="phobos_session")
templates = Jinja2Templates(directory="templates")

ACTION_COLORS = {
    "ban": "#ef4444", "kick": "#f97316", "timeout": "#eab308",
    "warn": "#3b82f6", "unban": "#22c55e", "clear": "#8b5cf6",
    "automod:warn": "#94a3b8", "automod:timeout": "#94a3b8",
    "automod:kick": "#94a3b8", "automod:ban": "#94a3b8",
}


def session(request: Request) -> dict:
    return {
        "username": request.session.get("username"),
        "role": request.session.get("role"),
        "user_id": request.session.get("user_id"),
        "version": VERSION,
        **{p: request.session.get(p, False) for p in PERM_COLS},
    }


PERM_COLS = ["perm_settings", "perm_tokens", "perm_users", "perm_bots"]


def auth_redirect(request: Request) -> Optional[RedirectResponse]:
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=302)
    return None


def admin_redirect(request: Request) -> Optional[RedirectResponse]:
    r = auth_redirect(request)
    if r:
        return r
    if request.session.get("role") != "admin":
        return RedirectResponse("/", status_code=302)
    return None


async def has_perm(request: Request, perm: str) -> bool:
    if request.session.get("role") == "admin":
        return True
    if perm not in PERM_COLS:
        return False
    return bool(request.session.get(perm, False))


async def perm_redirect(request: Request, perm: str) -> Optional[RedirectResponse]:
    if not await has_perm(request, perm):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    return None


async def _token_configured() -> bool:
    if await db_rows("SELECT id FROM bot_tokens WHERE enabled=1 LIMIT 1"):
        return True
    return bool(await get_config("discord_token"))


async def _guild_list(request: Request) -> list:
    all_guilds = [
        {"id": str(g.id), "name": g.name, "members": g.member_count,
         "icon": str(g.icon.url) if g.icon else None}
        for g in bot.guilds
    ]
    if request.session.get("role") == "admin":
        return all_guilds
    user_id = request.session.get("user_id")
    perms = await db_rows(
        "SELECT guild_id FROM user_guild_permissions WHERE user_id=?", (user_id,)
    )
    allowed = {p["guild_id"] for p in perms}
    return [g for g in all_guilds if g["id"] in allowed]


async def _guild_access(request: Request, guild_id) -> bool:
    if request.session.get("role") == "admin":
        return True
    row = await db_one(
        "SELECT 1 FROM user_guild_permissions WHERE user_id=? AND guild_id=?",
        (request.session.get("user_id"), str(guild_id)),
    )
    return bool(row)


# ── Auth ──────────────────────────────────────────────────────────────────────

@web.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {
        "request": request, "error": error, "version": VERSION,
    })


@web.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = await db_one("SELECT * FROM users WHERE username=?", (username.strip(),))
    if not user or not verify_pw(password, user["password_hash"]):
        return RedirectResponse("/login?error=Ungültige+Zugangsdaten", status_code=302)
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["role"] = user["role"]
    if user["role"] == "admin":
        for p in PERM_COLS:
            request.session[p] = True
    else:
        custom = await db_one(
            "SELECT r.* FROM roles r JOIN users u ON r.id=u.custom_role_id WHERE u.id=?",
            (user["id"],),
        )
        for p in PERM_COLS:
            request.session[p] = bool(custom.get(p, 0)) if custom else False
    return RedirectResponse("/", status_code=302)


@web.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# ── Password Reset ─────────────────────────────────────────────────────────────

async def _send_reset_email(to_addr: str, reset_url: str):
    host = await get_config("smtp_host") or ""
    port = int(await get_config("smtp_port") or 587)
    user = await get_config("smtp_user") or ""
    pw   = await get_config("smtp_pass") or ""
    frm  = await get_config("smtp_from") or user
    if not host or not user:
        raise ValueError("SMTP nicht konfiguriert")

    def _send():
        msg = email.mime.text.MIMEText(
            f"Hallo,\n\nKlicke diesen Link um dein Passwort zurückzusetzen:\n{reset_url}\n\n"
            f"Der Link ist 1 Stunde gültig.\n\nPhobos Bot",
            "plain", "utf-8",
        )
        msg["Subject"] = "Phobos Bot – Passwort zurücksetzen"
        msg["From"] = frm
        msg["To"] = to_addr
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.ehlo()
            s.starttls()
            s.login(user, pw)
            s.sendmail(frm, [to_addr], msg.as_string())

    await asyncio.to_thread(_send)


@web.get("/forgot-password", response_class=HTMLResponse)
async def forgot_pw_page(request: Request, error: str = "", success: str = ""):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("forgot_password.html", {
        "request": request, "error": error, "success": success, "version": VERSION,
    })


@web.post("/forgot-password")
async def forgot_pw_submit(request: Request, email_addr: str = Form(...)):
    user = await db_one("SELECT id, email FROM users WHERE email=?", (email_addr.strip(),))
    if user and user.get("email"):
        token = secrets.token_urlsafe(32)
        expires = (datetime.datetime.utcnow() + datetime.timedelta(hours=1)).isoformat()
        await db_exec(
            "INSERT OR REPLACE INTO password_reset_tokens (token,user_id,expires_at) VALUES (?,?,?)",
            (token, user["id"], expires),
        )
        base = await get_config("base_url") or ""
        reset_url = f"{base.rstrip('/')}/reset-password?token={token}"
        try:
            await _send_reset_email(email_addr.strip(), reset_url)
        except Exception as e:
            return RedirectResponse(f"/forgot-password?error={urllib.parse.quote(str(e))}", status_code=302)
    # always show success to prevent user enumeration
    return RedirectResponse(
        "/forgot-password?success=Falls+diese+E-Mail+registriert+ist+wurde+ein+Link+gesendet",
        status_code=302,
    )


@web.get("/reset-password", response_class=HTMLResponse)
async def reset_pw_page(request: Request, token: str = "", error: str = ""):
    if not token:
        return RedirectResponse("/login", status_code=302)
    row = await db_one(
        "SELECT user_id FROM password_reset_tokens WHERE token=? AND expires_at > ?",
        (token, datetime.datetime.utcnow().isoformat()),
    )
    if not row:
        return RedirectResponse("/login?error=Link+ungültig+oder+abgelaufen", status_code=302)
    return templates.TemplateResponse("reset_password.html", {
        "request": request, "token": token, "error": error, "version": VERSION,
    })


@web.post("/reset-password")
async def reset_pw_submit(request: Request, token: str = Form(...), password: str = Form(...), password2: str = Form(...)):
    if password != password2:
        return RedirectResponse(f"/reset-password?token={token}&error=Passwörter+stimmen+nicht+überein", status_code=302)
    if len(password) < 6:
        return RedirectResponse(f"/reset-password?token={token}&error=Mindestens+6+Zeichen", status_code=302)
    row = await db_one(
        "SELECT user_id FROM password_reset_tokens WHERE token=? AND expires_at > ?",
        (token, datetime.datetime.utcnow().isoformat()),
    )
    if not row:
        return RedirectResponse("/login?error=Link+ungültig+oder+abgelaufen", status_code=302)
    await db_exec("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(password), row["user_id"]))
    await db_exec("DELETE FROM password_reset_tokens WHERE token=?", (token,))
    return RedirectResponse("/login?success=Passwort+erfolgreich+geändert", status_code=302)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@web.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if r := auth_redirect(request): return r
    actions = await db_rows("SELECT * FROM mod_actions ORDER BY timestamp DESC LIMIT 50")
    stats = {r["action"]: r["count"] for r in await db_rows(
        "SELECT action, COUNT(*) as count FROM mod_actions GROUP BY action"
    )}
    token_set = await _token_configured()
    guilds = await _guild_list(request)
    return templates.TemplateResponse("index.html", {
        **session(request), "request": request,
        "actions": actions, "stats": stats, "colors": ACTION_COLORS,
        "token_set": token_set, "guilds": guilds, "active": "dashboard",
        "bot_online": bot.is_ready(),
    })


# ── Settings ──────────────────────────────────────────────────────────────────

@web.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False, error: str = "", success: str = ""):
    if r := auth_redirect(request): return r
    token = await get_config("discord_token")
    masked = ("•" * 40 + token[-6:]) if token else None
    all_users = (
        await db_rows("SELECT id, username, role, created_at FROM users ORDER BY created_at")
        if request.session.get("role") == "admin" else []
    )
    return templates.TemplateResponse("settings.html", {
        **session(request), "request": request,
        "masked": masked, "saved": saved, "token_set": bool(token),
        "users": all_users, "error": error, "success": success,
        "guilds": await _guild_list(request), "active": "settings",
    })


@web.post("/settings")
async def settings_save(request: Request, token: str = Form(...)):
    if r := auth_redirect(request): return r
    if token.strip():
        await set_config("discord_token", token.strip())
    return RedirectResponse("/settings?saved=true", status_code=303)


@web.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, error: str = "", success: str = ""):
    if r := admin_redirect(request): return r
    all_users = await db_rows("SELECT id, username, role, email, created_at, custom_role_id FROM users ORDER BY created_at")
    token_set = await _token_configured()
    admin_count = sum(1 for u in all_users if u["role"] == "admin")
    all_guilds = [{"id": str(g.id), "name": g.name} for g in bot.guilds]
    perm_rows = await db_rows("SELECT user_id, guild_id FROM user_guild_permissions")
    user_perms: dict[int, set] = {}
    for p in perm_rows:
        user_perms.setdefault(p["user_id"], set()).add(str(p["guild_id"]))
    all_roles = await db_rows("SELECT id, name, color FROM roles ORDER BY name")
    return templates.TemplateResponse("users.html", {
        **session(request), "request": request,
        "users": all_users, "error": error, "success": success,
        "guilds": await _guild_list(request), "token_set": token_set, "active": "users",
        "admin_count": admin_count,
        "all_guilds": all_guilds,
        "user_perms": user_perms,
        "all_roles": all_roles,
    })


@web.post("/users/create")
async def users_create(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form(...), next: str = "/users"):
    if r := admin_redirect(request): return r
    dest = next if next in ("/users", "/settings") else "/users"
    if len(password) < 6:
        return RedirectResponse(f"{dest}?error=Passwort+mindestens+6+Zeichen", status_code=302)
    try:
        await db_exec(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            (username.strip(), hash_pw(password), role),
        )
    except Exception:
        return RedirectResponse(f"{dest}?error=Benutzername+bereits+vergeben", status_code=302)
    return RedirectResponse(f"{dest}?success=Benutzer+erstellt", status_code=302)


@web.post("/users/role/{user_id}")
async def users_role(request: Request, user_id: int, role: str = Form(...)):
    if r := admin_redirect(request): return r
    if role not in ("admin", "moderator"):
        return RedirectResponse("/users?error=Ungültige+Rolle", status_code=302)
    if role == "moderator":
        other_admins = await db_one(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND id!=?", (user_id,)
        )
        if not other_admins or other_admins[0] == 0:
            return RedirectResponse("/users?error=Letzter+Admin+kann+nicht+herabgestuft+werden", status_code=302)
    await db_exec("UPDATE users SET role=? WHERE id=?", (role, user_id))
    return RedirectResponse("/users?success=Rolle+geändert", status_code=302)


@web.post("/users/delete/{user_id}")
async def users_delete(request: Request, user_id: int, next: str = "/users"):
    if r := admin_redirect(request): return r
    dest = next if next in ("/users", "/settings") else "/users"
    is_self = user_id == request.session.get("user_id")
    if is_self:
        # allow self-deletion only if another admin still exists
        other_admins = await db_one(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND id!=?", (user_id,)
        )
        if not other_admins or other_admins[0] == 0:
            return RedirectResponse(f"{dest}?error=Letzter+Admin+kann+nicht+gelöscht+werden", status_code=302)
    await db_exec("DELETE FROM users WHERE id=?", (user_id,))
    if is_self:
        request.session.clear()
        return RedirectResponse("/login?success=Konto+gelöscht", status_code=302)
    return RedirectResponse(f"{dest}?success=Benutzer+gelöscht", status_code=302)


@web.post("/users/{user_id}/guilds")
async def users_guilds_save(request: Request, user_id: int):
    if r := admin_redirect(request): return r
    form = await request.form()
    guild_ids = form.getlist("guild_ids")
    valid_ids = {str(g.id) for g in bot.guilds}
    await db_exec("DELETE FROM user_guild_permissions WHERE user_id=?", (user_id,))
    for gid in guild_ids:
        if gid in valid_ids:
            await db_exec(
                "INSERT OR IGNORE INTO user_guild_permissions (user_id, guild_id) VALUES (?,?)",
                (user_id, gid),
            )
    return RedirectResponse("/users?success=Serverrechte+gespeichert", status_code=302)


def _cgroup_ram() -> tuple[int, int] | None:
    """Return (used_bytes, limit_bytes) from cgroup memory, or None if unavailable."""
    NO_LIMIT = 2 ** 62
    # cgroups v2 (modern Docker / systemd)
    try:
        limit = int(Path("/sys/fs/cgroup/memory.max").read_text().strip())
        used  = int(Path("/sys/fs/cgroup/memory.current").read_text().strip())
        if 0 < limit < NO_LIMIT:
            return used, limit
    except Exception:
        pass
    # cgroups v1 (older Docker)
    try:
        limit = int(Path("/sys/fs/cgroup/memory/memory.limit_in_bytes").read_text().strip())
        used  = int(Path("/sys/fs/cgroup/memory/memory.usage_in_bytes").read_text().strip())
        if 0 < limit < NO_LIMIT:
            return used, limit
    except Exception:
        pass
    return None


def get_system_stats() -> dict:
    proc = psutil.Process()
    uptime = datetime.datetime.utcnow() - PROCESS_START
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s = divmod(rem, 60)

    cg = _cgroup_ram()
    if cg:
        ram_used  = cg[0] // (1024 ** 2)
        ram_total = cg[1] // (1024 ** 2)
        ram_pct   = round(cg[0] / cg[1] * 100, 1)
    else:
        vm = psutil.virtual_memory()
        ram_used  = vm.used  // (1024 ** 2)
        ram_total = vm.total // (1024 ** 2)
        ram_pct   = round(vm.percent, 1)

    return {
        "cpu": psutil.cpu_percent(interval=0.1),
        "ram_used": ram_used,
        "ram_total": ram_total,
        "ram_pct": ram_pct,
        "proc_ram": proc.memory_info().rss // (1024 ** 2),
        "uptime": f"{h}h {m}m {s}s",
        "latency": round(bot.latency * 1000, 1) if bot.is_ready() else None,
        "guild_count": len(bot.guilds),
        "member_count": sum(g.member_count or 0 for g in bot.guilds),
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
    }


def get_invite_url() -> str:
    cid = bot.application_id or (bot.user.id if bot.user else None)
    if cid:
        return (f"https://discord.com/api/oauth2/authorize"
                f"?client_id={cid}&permissions=8&scope=bot%20applications.commands")
    return ""


# ── Bot Design ────────────────────────────────────────────────────────────────

@web.get("/bot/design", response_class=HTMLResponse)
async def bot_design_page(request: Request, guild_id: str = "", success: str = "", error: str = ""):
    if r := auth_redirect(request): return r
    token_set = await _token_configured()
    target = bot._bot_for_guild(int(guild_id)) if guild_id else None
    if target is None:
        ready = bot._ready_bots()
        target = ready[0] if ready else None
    current_name = target.user.name if target and target.user else None
    current_avatar = str(target.user.display_avatar.url) if target and target.user else None
    bot_online = target is not None and target.is_ready()
    return templates.TemplateResponse("bot_design.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": "bot_design_" + guild_id if guild_id else "bot_design",
        "success": success, "error": error,
        "current_name": current_name, "current_avatar": current_avatar,
        "bot_online": bot_online, "guild_id": guild_id,
    })


@web.post("/bot/design")
async def bot_design_save(
    request: Request,
    bot_name: str = Form(""),
    guild_id: str = Form(""),
    avatar: UploadFile = File(None),
):
    if r := auth_redirect(request): return r
    target = bot._bot_for_guild(int(guild_id)) if guild_id else None
    if target is None:
        ready = bot._ready_bots()
        target = ready[0] if ready else None
    redirect_base = f"/bot/design?guild_id={guild_id}" if guild_id else "/bot/design"
    if not target or not target.is_ready():
        return RedirectResponse(f"{redirect_base}&error=Bot+ist+offline", status_code=302)
    try:
        kwargs = {}
        if bot_name.strip() and bot_name.strip() != target.user.name:
            kwargs["username"] = bot_name.strip()
        if avatar and avatar.filename:
            content = await avatar.read()
            if content:
                kwargs["avatar"] = content
        if kwargs:
            await target.user.edit(**kwargs)
        else:
            return RedirectResponse(f"{redirect_base}&error=Keine+Änderungen", status_code=302)
    except discord.HTTPException as e:
        msg = str(e)[:80].replace(" ", "+")
        return RedirectResponse(f"{redirect_base}&error={msg}", status_code=302)
    return RedirectResponse(f"{redirect_base}&success=Gespeichert", status_code=302)


# ── Bot Info ──────────────────────────────────────────────────────────────────

@web.get("/bot/info", response_class=HTMLResponse)
async def bot_info_page(request: Request):
    if r := auth_redirect(request): return r
    token_set = await _token_configured()
    return templates.TemplateResponse("bot_info.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": "bot_info", "stats": get_system_stats(),
        "bot_online": bot.is_ready(), "version": VERSION,
        "bot_name": bot.user.name if bot.user else "—",
        "bot_id": str(bot.user.id) if bot.user else "—",
    })


# ── Update Check ──────────────────────────────────────────────────────────────

_UPDATE_CACHE: dict = {"latest": None, "at": None}
_GITHUB_VERSION_URL = "https://raw.githubusercontent.com/LucyWolf/phobos-bot/main/app/VERSION"


def _ver_tuple(v: str):
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except Exception:
        return (0,)


async def check_latest_version(force: bool = False) -> str | None:
    now = datetime.datetime.utcnow()
    cached_at = _UPDATE_CACHE["at"]
    if not force and cached_at and (now - cached_at).total_seconds() < 300:
        return _UPDATE_CACHE["latest"]
    try:
        def _fetch():
            with urllib.request.urlopen(_GITHUB_VERSION_URL, timeout=5) as r:
                return r.read().decode().strip()
        latest = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        _UPDATE_CACHE["latest"] = latest
        _UPDATE_CACHE["at"] = now
        return latest
    except Exception:
        return _UPDATE_CACHE.get("latest")


@web.get("/api/version")
async def api_version(request: Request, force: int = 0):
    if not session(request).get("username"):
        return JSONResponse({"current": VERSION, "latest": None, "update_available": False})
    latest = await check_latest_version(force=bool(force))
    update_available = bool(latest and _ver_tuple(latest) > _ver_tuple(VERSION))
    checked_at = _UPDATE_CACHE["at"].strftime("%H:%M:%S") if _UPDATE_CACHE["at"] else None
    return JSONResponse({
        "current": VERSION,
        "latest": latest,
        "update_available": update_available,
        "checked_at": checked_at,
    })


@web.get("/bot/update", response_class=HTMLResponse)
async def bot_update_page(request: Request, success: str = "", error: str = ""):
    if r := auth_redirect(request): return r
    if session(request).get("role") != "admin":
        return RedirectResponse("/", status_code=302)
    token_set = await _token_configured()
    latest = await check_latest_version()
    update_available = bool(latest and _ver_tuple(latest) > _ver_tuple(VERSION))
    return templates.TemplateResponse("bot_update.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": "bot_update",
        "current_version": VERSION, "latest_version": latest,
        "update_available": update_available,
        "success": success, "error": error,
    })


@web.post("/bot/update/apply")
async def bot_update_apply(request: Request):
    if r := auth_redirect(request): return r
    if session(request).get("role") != "admin":
        return RedirectResponse("/", status_code=302)
    try:
        tar_url = "https://github.com/LucyWolf/phobos-bot/archive/refs/heads/main.tar.gz"

        def _download_and_apply():
            with tempfile.TemporaryDirectory() as tmp:
                tar_path = os.path.join(tmp, "update.tar.gz")
                urllib.request.urlretrieve(tar_url, tar_path)
                with tarfile.open(tar_path, "r:gz") as tf:
                    tf.extractall(tmp)
                # Find extracted root dir (e.g. phobos-bot-main)
                dirs = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
                if not dirs:
                    raise RuntimeError("Archiv leer")
                src_app = os.path.join(tmp, dirs[0], "app")
                dst = "/app"
                skip = {"data"}  # never overwrite database / persistent data
                for item in os.listdir(src_app):
                    if item in skip:
                        continue
                    s = os.path.join(src_app, item)
                    d = os.path.join(dst, item)
                    if os.path.isfile(s):
                        shutil.copy2(s, d)
                    elif os.path.isdir(s):
                        if os.path.exists(d):
                            shutil.rmtree(d)
                        shutil.copytree(s, d)

        await asyncio.get_event_loop().run_in_executor(None, _download_and_apply)
        # Restart Python process in-place (works in Docker without rebuild)
        asyncio.get_event_loop().call_later(1.5, lambda: os.execv(sys.executable, [sys.executable] + sys.argv))
        return RedirectResponse("/bot/update?success=1", status_code=302)
    except Exception as e:
        msg = urllib.parse.quote(str(e)[:120])
        return RedirectResponse(f"/bot/update?error={msg}", status_code=302)


# ── Free Stuff ────────────────────────────────────────────────────────────────

@web.get("/servers/{guild_id}/freestuff", response_class=HTMLResponse)
async def freestuff_page(request: Request, guild_id: str, success: str = "", error: str = ""):
    if r := auth_redirect(request): return r
    token_set = await _token_configured()
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    cfg = await db_one("SELECT * FROM freestuff_channels WHERE guild_id=?", (guild_id,))
    return templates.TemplateResponse("freestuff.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": f"server_{guild_id}",
        "guild_id": guild_id, "guild_name": guild.name,
        "channels": channels, "cfg": cfg,
        "success": success, "error": error,
    })


@web.post("/servers/{guild_id}/freestuff/save")
async def freestuff_save(
    request: Request, guild_id: str,
    channel_id: str = Form(...),
    platforms: list[str] = Form(default=[]),
    deal_max_price: str = Form(""),
    deal_min_discount: str = Form("75"),
    deal_channel_id: str = Form(""),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    valid = {"epic", "steam", "gog", "humble", "ea", "ubisoft", "battlenet", "itchio"}
    plat_str = ",".join(p for p in platforms if p in valid)
    if not plat_str:
        plat_str = "epic"
    try:
        max_price = float(deal_max_price.replace(",", ".")) if deal_max_price.strip() else None
    except ValueError:
        max_price = None
    min_disc = max(0, min(100, int(deal_min_discount or 75)))
    deal_ch = deal_channel_id if deal_channel_id else None
    await db_exec(
        """INSERT INTO freestuff_channels
               (guild_id, channel_id, platforms, deal_max_price, deal_min_discount, deal_channel_id)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(guild_id) DO UPDATE SET
               channel_id=excluded.channel_id,
               platforms=excluded.platforms,
               deal_max_price=excluded.deal_max_price,
               deal_min_discount=excluded.deal_min_discount,
               deal_channel_id=excluded.deal_channel_id""",
        (guild_id, channel_id, plat_str, max_price, min_disc, deal_ch),
    )
    return RedirectResponse(f"/servers/{guild_id}/freestuff?success=1", status_code=302)


@web.post("/servers/{guild_id}/freestuff/disable")
async def freestuff_disable(request: Request, guild_id: str):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM freestuff_channels WHERE guild_id=?", (guild_id,))
    return RedirectResponse(f"/servers/{guild_id}/freestuff?success=1", status_code=302)


# ── Notifications ─────────────────────────────────────────────────────────────

@web.get("/servers/{guild_id}/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request, guild_id: str, success: str = "", error: str = ""):
    if r := auth_redirect(request): return r
    token_set = await _token_configured()
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    subs = await db_rows("SELECT * FROM notifications WHERE guild_id=? ORDER BY platform, target_name", (guild_id,))
    twitch_id = await get_config("twitch_client_id") or ""
    return templates.TemplateResponse("notifications.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": f"server_{guild_id}",
        "guild_id": guild_id, "guild_name": guild.name,
        "channels": channels, "subs": subs,
        "twitch_configured": bool(twitch_id),
        "success": success, "error": error,
    })


@web.post("/servers/{guild_id}/notifications/add")
async def notifications_add(
    request: Request, guild_id: str,
    platform: str = Form(...),
    target: str = Form(...),
    target_name: str = Form(""),
    discord_channel_id: str = Form(...),
    custom_message: str = Form(""),
    next_url: str = Form(""),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    target = target.strip()
    if not target or not discord_channel_id:
        return RedirectResponse(f"/servers/{guild_id}/notifications?error=Pflichtfelder+fehlen", status_code=302)
    # Normalize YouTube channel URL to ID
    if platform == "youtube" and "youtube.com" in target:
        parts = target.rstrip("/").split("/")
        target = parts[-1]
    existing = await db_rows(
        "SELECT id FROM notifications WHERE guild_id=? AND platform=? AND target=?",
        (guild_id, platform, target.lower() if platform == "twitch" else target),
    )
    if existing:
        dest = next_url or f"/servers/{guild_id}/notifications"
        return RedirectResponse(f"{dest}?error=Bereits+eingetragen", status_code=302)
    await db_exec(
        "INSERT INTO notifications (guild_id,platform,discord_channel_id,target,target_name,custom_message) VALUES (?,?,?,?,?,?)",
        (guild_id, platform, discord_channel_id, target.lower() if platform == "twitch" else target,
         target_name.strip(), custom_message.strip()),
    )
    dest = next_url or f"/servers/{guild_id}/notifications"
    return RedirectResponse(f"{dest}&success=1" if "?" in dest else f"{dest}?success=1", status_code=302)


@web.post("/servers/{guild_id}/notifications/delete/{nid}")
async def notifications_delete(request: Request, guild_id: str, nid: int, next_url: str = Form("")):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM notifications WHERE id=? AND guild_id=?", (nid, guild_id))
    dest = next_url or f"/servers/{guild_id}/notifications"
    return RedirectResponse(f"{dest}&success=1" if "?" in dest else f"{dest}?success=1", status_code=302)


@web.get("/settings/notifications", response_class=HTMLResponse)
async def notif_settings_page(request: Request, saved: bool = False, error: str = ""):
    if r := auth_redirect(request): return r
    if session(request).get("role") != "admin":
        return RedirectResponse("/", status_code=302)
    token_set = await _token_configured()
    return templates.TemplateResponse("notif_settings.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": "notif_settings",
        "twitch_client_id": await get_config("twitch_client_id") or "",
        "saved": saved, "error": error,
    })


@web.post("/settings/notifications")
async def notif_settings_save(
    request: Request,
    twitch_client_id: str = Form(""),
    twitch_client_secret: str = Form(""),
):
    if r := auth_redirect(request): return r
    if session(request).get("role") != "admin":
        return RedirectResponse("/", status_code=302)
    if twitch_client_id.strip():
        await set_config("twitch_client_id", twitch_client_id.strip())
    if twitch_client_secret.strip():
        await set_config("twitch_client_secret", twitch_client_secret.strip())
    return RedirectResponse("/settings/notifications?saved=1", status_code=302)


# ── SMTP Settings ─────────────────────────────────────────────────────────────

@web.get("/settings/smtp", response_class=HTMLResponse)
async def smtp_settings_page(request: Request, saved: bool = False, error: str = "", test_ok: bool = False):
    if r := admin_redirect(request): return r
    token_set = await _token_configured()
    return templates.TemplateResponse("smtp_settings.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set, "active": "smtp",
        "smtp_host":  await get_config("smtp_host") or "",
        "smtp_port":  await get_config("smtp_port") or "587",
        "smtp_user":  await get_config("smtp_user") or "",
        "smtp_from":  await get_config("smtp_from") or "",
        "base_url":   await get_config("base_url") or "",
        "saved": saved, "error": error, "test_ok": test_ok,
    })


@web.post("/settings/smtp")
async def smtp_settings_save(
    request: Request,
    smtp_host: str = Form(""), smtp_port: str = Form("587"),
    smtp_user: str = Form(""), smtp_pass: str = Form(""),
    smtp_from: str = Form(""), base_url: str = Form(""),
):
    if r := admin_redirect(request): return r
    for key, val in [
        ("smtp_host", smtp_host), ("smtp_port", smtp_port),
        ("smtp_user", smtp_user), ("smtp_from", smtp_from),
        ("base_url", base_url),
    ]:
        await set_config(key, val.strip())
    if smtp_pass.strip():
        await set_config("smtp_pass", smtp_pass.strip())
    return RedirectResponse("/settings/smtp?saved=1", status_code=302)


@web.post("/settings/smtp/test")
async def smtp_test(request: Request, test_email: str = Form(...)):
    if r := admin_redirect(request): return r
    try:
        await _send_reset_email(test_email.strip(), "https://example.com/test-link")
        return RedirectResponse("/settings/smtp?test_ok=1", status_code=302)
    except Exception as e:
        return RedirectResponse(f"/settings/smtp?error={urllib.parse.quote(str(e))}", status_code=302)


# ── Token Management ──────────────────────────────────────────────────────────

@web.get("/settings/tokens", response_class=HTMLResponse)
async def tokens_page(request: Request, success: str = "", error: str = ""):
    if r := admin_redirect(request): return r
    token_rows = await db_rows("SELECT id, label, token, enabled, created_at FROM bot_tokens ORDER BY id")
    for t in token_rows:
        tok = t["token"]
        t["masked"] = ("•" * 40 + tok[-6:]) if len(tok) > 6 else "•" * len(tok)
        t["running"] = t["id"] in bot._bots
    legacy_token = await get_config("discord_token")
    token_set = await _token_configured()
    return templates.TemplateResponse("tokens.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": "tokens", "tokens": token_rows,
        "legacy_token": bool(legacy_token),
        "legacy_running": 0 in bot._bots,
        "success": success, "error": error,
    })


@web.post("/settings/tokens/add")
async def tokens_add(request: Request, label: str = Form("Bot"), token: str = Form(...)):
    if r := admin_redirect(request): return r
    token = token.strip()
    if not token:
        return RedirectResponse("/settings/tokens?error=Token+darf+nicht+leer+sein", status_code=302)
    await db_exec(
        "INSERT INTO bot_tokens (label, token) VALUES (?, ?)",
        (label.strip() or "Bot", token),
    )
    return RedirectResponse(
        "/settings/tokens?success=Token+hinzugefügt.+Neustart+erforderlich+um+ihn+zu+aktivieren.",
        status_code=302,
    )


@web.post("/settings/tokens/delete/{token_id}")
async def tokens_delete(request: Request, token_id: int):
    if r := admin_redirect(request): return r
    await db_exec("DELETE FROM bot_tokens WHERE id=?", (token_id,))
    return RedirectResponse(
        "/settings/tokens?success=Token+gelöscht.+Neustart+erforderlich.",
        status_code=302,
    )


@web.post("/settings/tokens/toggle/{token_id}")
async def tokens_toggle(request: Request, token_id: int):
    if r := admin_redirect(request): return r
    await db_exec("UPDATE bot_tokens SET enabled = NOT enabled WHERE id=?", (token_id,))
    return RedirectResponse(
        "/settings/tokens?success=Status+geändert.+Neustart+erforderlich.",
        status_code=302,
    )


# ── User Email ─────────────────────────────────────────────────────────────────

@web.post("/users/email/{user_id}")
async def users_set_email(request: Request, user_id: int, email_addr: str = Form(...)):
    if r := admin_redirect(request): return r
    await db_exec("UPDATE users SET email=? WHERE id=?", (email_addr.strip(), user_id))
    return RedirectResponse("/users?success=E-Mail+gespeichert", status_code=302)


# ── Roles ─────────────────────────────────────────────────────────────────────

@web.get("/roles", response_class=HTMLResponse)
async def roles_page(request: Request, success: str = "", error: str = ""):
    if r := admin_redirect(request): return r
    token_set = await _token_configured()
    all_roles = await db_rows("SELECT * FROM roles ORDER BY name")
    all_users = await db_rows("SELECT id, username, role, custom_role_id FROM users ORDER BY username")
    return templates.TemplateResponse("roles.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": "roles", "success": success, "error": error,
        "all_roles": all_roles, "all_users": all_users,
    })


@web.post("/roles/create")
async def roles_create(request: Request,
    name: str = Form(...), color: str = Form("#6366f1"),
    perm_settings: int = Form(0), perm_tokens: int = Form(0),
    perm_users: int = Form(0), perm_bots: int = Form(0),
):
    if r := admin_redirect(request): return r
    try:
        await db_exec(
            "INSERT INTO roles (name,color,perm_settings,perm_tokens,perm_users,perm_bots) VALUES (?,?,?,?,?,?)",
            (name.strip(), color, perm_settings, perm_tokens, perm_users, perm_bots),
        )
    except Exception:
        return RedirectResponse("/roles?error=Name+bereits+vergeben", status_code=302)
    return RedirectResponse("/roles?success=Rolle+erstellt", status_code=302)


@web.post("/roles/edit/{role_id}")
async def roles_edit(request: Request, role_id: int,
    name: str = Form(...), color: str = Form("#6366f1"),
    perm_settings: int = Form(0), perm_tokens: int = Form(0),
    perm_users: int = Form(0), perm_bots: int = Form(0),
):
    if r := admin_redirect(request): return r
    try:
        await db_exec(
            "UPDATE roles SET name=?,color=?,perm_settings=?,perm_tokens=?,perm_users=?,perm_bots=? WHERE id=?",
            (name.strip(), color, perm_settings, perm_tokens, perm_users, perm_bots, role_id),
        )
    except Exception:
        return RedirectResponse("/roles?error=Name+bereits+vergeben", status_code=302)
    return RedirectResponse("/roles?success=Rolle+gespeichert", status_code=302)


@web.post("/roles/delete/{role_id}")
async def roles_delete(request: Request, role_id: int):
    if r := admin_redirect(request): return r
    await db_exec("UPDATE users SET custom_role_id=NULL WHERE custom_role_id=?", (role_id,))
    await db_exec("DELETE FROM roles WHERE id=?", (role_id,))
    return RedirectResponse("/roles?success=Rolle+gelöscht", status_code=302)


@web.post("/users/{user_id}/custom_role")
async def users_set_custom_role(request: Request, user_id: int, custom_role_id: str = Form("")):
    if r := admin_redirect(request): return r
    role_id = int(custom_role_id) if custom_role_id.isdigit() else None
    await db_exec("UPDATE users SET custom_role_id=? WHERE id=?", (role_id, user_id))
    return RedirectResponse("/users?success=Rolle+zugewiesen", status_code=302)


# ── Servers List ──────────────────────────────────────────────────────────────

@web.get("/servers", response_class=HTMLResponse)
async def servers_list(request: Request, success: str = ""):
    if r := auth_redirect(request): return r
    guilds = await _guild_list(request)
    token_set = await _token_configured()
    invite_url = get_invite_url()
    return templates.TemplateResponse("servers_list.html", {
        **session(request), "request": request,
        "guilds": guilds, "token_set": token_set,
        "invite_url": invite_url, "bot_online": bot.is_ready(),
        "active": "servers", "success": success,
    })


@web.get("/servers/{guild_id}/log", response_class=HTMLResponse)
async def server_log_page(request: Request, guild_id: str, success: str = ""):
    if r := auth_redirect(request): return r
    token_set = await _token_configured()
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    log_channel = await get_guild_config(int(guild_id), "log_channel") or ""
    logs = await db_rows(
        "SELECT icon, title, description, created_at FROM server_logs WHERE guild_id=? ORDER BY id DESC LIMIT 200",
        (guild_id,),
    )
    return templates.TemplateResponse("server_log.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": f"server_{guild_id}",
        "guild_id": guild_id, "guild_name": guild.name,
        "channels": channels, "log_channel": log_channel,
        "logs": logs, "success": success,
    })


@web.post("/servers/{guild_id}/log/save")
async def server_log_save(request: Request, guild_id: str, log_channel: str = Form("")):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    from database import set_guild_config
    await set_guild_config(int(guild_id), "log_channel", log_channel)
    return RedirectResponse(f"/servers/{guild_id}/log?success=1", status_code=302)


@web.post("/servers/{guild_id}/leave")
async def server_leave(request: Request, guild_id: int):
    if r := admin_redirect(request): return r
    guild = bot.get_guild(guild_id)
    if guild:
        await guild.leave()
    return RedirectResponse("/servers?success=Server+verlassen", status_code=302)


# ── Leaderboard ───────────────────────────────────────────────────────────────

@web.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard_page(request: Request, guild_id: str = ""):
    if r := auth_redirect(request): return r
    guilds = await _guild_list(request)
    token_set = await _token_configured()

    if not guild_id and guilds:
        guild_id = guilds[0]["id"]

    selected_guild = None
    leaderboard = []

    if guild_id:
        guild = bot.get_guild(int(guild_id))
        if guild:
            selected_guild = {"id": str(guild.id), "name": guild.name,
                              "icon": str(guild.icon.url) if guild.icon else None}
            lb = await db_rows(
                "SELECT * FROM levels WHERE guild_id=? ORDER BY xp DESC LIMIT 50", (int(guild_id),)
            )
            for i, e in enumerate(lb, 1):
                m = guild.get_member(e["user_id"])
                e["username"] = str(m) if m else f"#{e['user_id']}"
                e["avatar"] = str(m.display_avatar.url) if m else None
                e["rank"] = i
            leaderboard = lb

    return templates.TemplateResponse("leaderboard.html", {
        **session(request), "request": request,
        "guilds": guilds, "token_set": token_set, "active": "leaderboard",
        "selected_guild": selected_guild, "selected_guild_id": guild_id,
        "leaderboard": leaderboard, "bot_online": bot.is_ready(),
    })


# ── Server Config ─────────────────────────────────────────────────────────────

@web.get("/servers/{guild_id}", response_class=HTMLResponse)
async def server_config(
    request: Request, guild_id: int,
    saved: bool = False, tab: str = "config", error: str = "", success: str = "",
):
    if r := auth_redirect(request): return r
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse("/", status_code=302)
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)

    token_set = await _token_configured()
    cfg = await get_all_guild_config(guild_id)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    roles = [{"id": str(ro.id), "name": ro.name} for ro in guild.roles if not ro.is_default()]
    categories = [{"id": str(c.id), "name": c.name} for c in guild.categories]

    # Reaction roles
    rr_list = await db_rows("SELECT * FROM reaction_roles WHERE guild_id=? ORDER BY id", (guild_id,))
    for rr in rr_list:
        ch = guild.get_channel(rr["channel_id"])
        ro = guild.get_role(rr["role_id"])
        rr["channel_name"] = f"#{ch.name}" if ch else "?"
        rr["role_name"] = ro.name if ro else "?"

    # Custom commands
    cmd_list = await db_rows(
        "SELECT * FROM custom_commands WHERE guild_id=? ORDER BY trigger", (guild_id,)
    )

    # Leaderboard
    lb = await db_rows(
        "SELECT * FROM levels WHERE guild_id=? ORDER BY xp DESC LIMIT 20", (guild_id,)
    )
    for i, e in enumerate(lb, 1):
        m = guild.get_member(e["user_id"])
        e["username"] = str(m) if m else f"#{e['user_id']}"
        e["rank"] = i

    # Warnings grouped by user
    warn_groups = await db_rows(
        "SELECT user_id, COUNT(*) as count, MAX(timestamp) as last FROM warnings "
        "WHERE guild_id=? GROUP BY user_id ORDER BY count DESC",
        (guild_id,),
    )
    for wg in warn_groups:
        m = guild.get_member(wg["user_id"])
        wg["username"] = str(m) if m else f"#{wg['user_id']}"

    # Open tickets
    ticket_list = await db_rows(
        "SELECT * FROM tickets WHERE guild_id=? AND status='open' ORDER BY created_at DESC",
        (guild_id,),
    )
    for t in ticket_list:
        m = guild.get_member(t["user_id"])
        t["username"] = str(m) if m else f"#{t['user_id']}"
        ch = guild.get_channel(t["channel_id"])
        t["channel_name"] = f"#{ch.name}" if ch else "Gelöscht"

    # Active giveaways
    ga_list = await db_rows(
        "SELECT * FROM giveaways WHERE guild_id=? AND ended=0 ORDER BY ends_at", (guild_id,)
    )
    for g in ga_list:
        ch = guild.get_channel(g["channel_id"])
        g["channel_name"] = f"#{ch.name}" if ch else "?"

    # Notifications
    subs = await db_rows(
        "SELECT * FROM notifications WHERE guild_id=? ORDER BY platform, target_name", (str(guild_id),)
    )
    twitch_configured = bool(await get_config("twitch_client_id"))

    # Dashboard users & server access
    all_users = await db_rows("SELECT id, username, role FROM users ORDER BY role DESC, username")
    perm_rows = await db_rows(
        "SELECT user_id FROM user_guild_permissions WHERE guild_id=?", (str(guild_id),)
    )
    server_perms = {p["user_id"] for p in perm_rows}

    return templates.TemplateResponse("server_config.html", {
        **session(request), "request": request,
        "guild": {"id": str(guild.id), "name": guild.name,
                  "icon": str(guild.icon.url) if guild.icon else None},
        "cfg": cfg, "channels": channels, "roles": roles, "categories": categories,
        "token_set": token_set, "saved": saved,
        "active": f"server_{guild_id}",
        "guilds": await _guild_list(request),
        "tab": tab, "error": error, "success": success,
        "rr_list": rr_list, "cmd_list": cmd_list,
        "leaderboard": lb, "warn_groups": warn_groups,
        "ticket_list": ticket_list, "ga_list": ga_list,
        "subs": subs, "twitch_configured": twitch_configured,
        "all_users": all_users, "server_perms": server_perms,
    })


@web.post("/servers/{guild_id}")
async def server_config_save(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    text_keys = [
        "welcome_channel", "welcome_message", "leave_channel", "leave_message", "autorole",
        "log_channel", "level_channel",
        "automod_spam_threshold", "automod_banned_words", "automod_action",
        "ticket_support_role", "ticket_category",
    ]
    checkbox_keys = ["leveling_enabled", "automod_enabled", "automod_links"]
    for key in text_keys:
        await set_guild_config(guild_id, key, str(form.get(key, "")))
    for key in checkbox_keys:
        await set_guild_config(guild_id, key, "1" if form.get(key) else "0")
    return RedirectResponse(f"/servers/{guild_id}?tab=config&saved=true", status_code=303)


# ── Server User Access ────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/users/{user_id}/grant")
async def server_grant_user(request: Request, guild_id: int, user_id: int):
    if r := admin_redirect(request): return r
    await db_exec(
        "INSERT OR IGNORE INTO user_guild_permissions (user_id, guild_id) VALUES (?,?)",
        (user_id, str(guild_id)),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=users&success=Zugriff+gewährt", status_code=302)


@web.post("/servers/{guild_id}/users/{user_id}/revoke")
async def server_revoke_user(request: Request, guild_id: int, user_id: int):
    if r := admin_redirect(request): return r
    await db_exec(
        "DELETE FROM user_guild_permissions WHERE user_id=? AND guild_id=?",
        (user_id, str(guild_id)),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=users&success=Zugriff+entzogen", status_code=302)


# ── Reaction Roles ────────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/reaction_roles/add")
async def rr_add(
    request: Request, guild_id: int,
    channel_id: str = Form(...), message_id: str = Form(...),
    emoji: str = Form(...), role_id: str = Form(...),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    try:
        await db_exec(
            "INSERT INTO reaction_roles (guild_id,channel_id,message_id,emoji,role_id) VALUES (?,?,?,?,?)",
            (guild_id, int(channel_id), int(message_id), emoji.strip(), int(role_id)),
        )
    except Exception:
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Ungültige+Eingabe", status_code=302)
    return RedirectResponse(f"/servers/{guild_id}?tab=rr&success=Reaction+Role+hinzugefügt", status_code=302)


@web.post("/servers/{guild_id}/reaction_roles/{rr_id}/delete")
async def rr_delete(request: Request, guild_id: int, rr_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM reaction_roles WHERE id=? AND guild_id=?", (rr_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=rr", status_code=302)


# ── Custom Commands ───────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/commands/add")
async def cmd_add(
    request: Request, guild_id: int,
    trigger: str = Form(...), response: str = Form(...),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    trigger = trigger.lower().strip("!").strip()
    try:
        await db_exec(
            "INSERT INTO custom_commands (guild_id,trigger,response) VALUES (?,?,?)",
            (guild_id, trigger, response),
        )
    except Exception:
        await db_exec(
            "UPDATE custom_commands SET response=? WHERE guild_id=? AND trigger=?",
            (response, guild_id, trigger),
        )
    return RedirectResponse(f"/servers/{guild_id}?tab=commands&success=Command+gespeichert", status_code=302)


@web.post("/servers/{guild_id}/commands/{cmd_id}/delete")
async def cmd_delete(request: Request, guild_id: int, cmd_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM custom_commands WHERE id=? AND guild_id=?", (cmd_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=commands", status_code=302)


# ── Giveaways ─────────────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/giveaways/start")
async def giveaway_start_web(
    request: Request, guild_id: int,
    channel_id: str = Form(...), prize: str = Form(...),
    duration: int = Form(...), winners: int = Form(1),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    channel = bot.get_channel(int(channel_id))
    if not channel:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=giveaways&error=Kanal+nicht+gefunden", status_code=302
        )
    ends_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=duration)
    embed = discord.Embed(
        title=f"🎉 GIVEAWAY: {prize}",
        description=(
            f"Reagiere mit 🎉 um teilzunehmen!\n\n"
            f"**Gewinner:** {winners}\n"
            f"**Endet:** {discord.utils.format_dt(ends_at, 'R')}"
        ),
        color=0x7c3aed,
    )
    embed.set_footer(text=f"Endet am {ends_at.strftime('%d.%m.%Y %H:%M')} UTC")
    msg = await channel.send(embed=embed)
    await msg.add_reaction("🎉")

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO giveaways (guild_id,channel_id,message_id,prize,winners,ends_at,created_by) "
            "VALUES (?,?,?,?,?,?,?)",
            (guild_id, channel.id, msg.id, prize, winners,
             ends_at.isoformat(), request.session.get("user_id") or 0),
        )
        await db.commit()
        gid = cur.lastrowid

    g = await db_one("SELECT * FROM giveaways WHERE id=?", (gid,))
    cog = bot.cogs.get("Giveaways")
    if cog and g:
        cog._schedule(g)

    return RedirectResponse(
        f"/servers/{guild_id}?tab=giveaways&success=Giveaway+gestartet", status_code=302
    )


@web.post("/servers/{guild_id}/giveaways/{gid}/end")
async def giveaway_end_web(request: Request, guild_id: int, gid: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    cog = bot.cogs.get("Giveaways")
    if cog:
        await cog._end_giveaway(gid)
    return RedirectResponse(f"/servers/{guild_id}?tab=giveaways", status_code=302)


@web.post("/servers/{guild_id}/giveaways/{gid}/reroll")
async def giveaway_reroll_web(request: Request, guild_id: int, gid: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec("UPDATE giveaways SET ended=0 WHERE id=? AND guild_id=?", (gid, guild_id))
    cog = bot.cogs.get("Giveaways")
    if cog:
        await cog._end_giveaway(gid)
    return RedirectResponse(f"/servers/{guild_id}?tab=giveaways", status_code=302)


# ── Warnings ──────────────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/warnings/{user_id}/clear")
async def warnings_clear(request: Request, guild_id: int, user_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM warnings WHERE user_id=? AND guild_id=?", (user_id, guild_id))
    return RedirectResponse(
        f"/servers/{guild_id}?tab=warnings&success=Warnungen+gelöscht", status_code=302
    )


# ── API ───────────────────────────────────────────────────────────────────────

@web.get("/api/actions")
async def api_actions():
    return await db_rows("SELECT * FROM mod_actions ORDER BY timestamp DESC LIMIT 100")


@web.get("/api/guilds")
async def api_guilds():
    return [{"id": str(g.id), "name": g.name, "members": g.member_count} for g in bot.guilds]


# ── Startup ───────────────────────────────────────────────────────────────────

async def main():
    await init_db()

    user_count = (await db_one("SELECT COUNT(*) as c FROM users") or {}).get("c", 0)
    if user_count == 0:
        await db_exec(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            ("admin", hash_pw("admin"), "admin"),
        )
        print("Standard-Admin erstellt: admin / admin")

    server = uvicorn.Server(uvicorn.Config(web, host="0.0.0.0", port=8080, log_level="warning"))
    await asyncio.gather(server.serve(), run_bot())


asyncio.run(main())
