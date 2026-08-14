import asyncio
import datetime
import email.mime.text
import io
import json as _djson
import os
import socket as _dsock
from contextvars import ContextVar
from zoneinfo import ZoneInfo
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

from PIL import Image

import aiosqlite
import bcrypt
import discord
import psutil
from cogs.tickets import OpenTicketView as _TicketView
from i18n import get_tr
import uvicorn
from discord.ext import commands
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

PROCESS_START = datetime.datetime.utcnow()

from database import (
    DB_PATH, init_db, get_config, set_config,
    get_guild_config, set_guild_config, get_all_guild_config,
    db_rows, db_one, db_exec, db_insert, log_mod_action,
)

VERSION = (Path(__file__).parent / "VERSION").read_text().strip()
SECRET_KEY_PATH = Path("/app/data/secret.key")
AVATARS_DIR = Path("/app/data/avatars")


def load_secret_key() -> str:
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_text().strip()
    key = secrets.token_hex(32)
    SECRET_KEY_PATH.write_text(key)
    return key


SECRET_KEY = load_secret_key()


def _docker_api(method: str, path: str) -> tuple[int, bytes]:
    """Minimal Docker Engine API client over Unix socket."""
    try:
        sock = _dsock.socket(_dsock.AF_UNIX, _dsock.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect("/var/run/docker.sock")
        req = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        sock.sendall(req.encode())
        data = b""
        while True:
            chunk = sock.recv(32768)
            if not chunk:
                break
            data += chunk
        sock.close()
        idx = data.find(b"\r\n\r\n")
        code = int(data.split(b" ", 2)[1]) if b" " in data else 0
        return code, data[idx + 4:] if idx != -1 else b""
    except Exception:
        return 0, b""


def _get_compose_dir() -> str | None:
    """Return docker-compose project working dir from own container labels, or None."""
    if not os.path.exists("/var/run/docker.sock"):
        return None
    try:
        hostname = os.environ.get("HOSTNAME", "")
        code, body = _docker_api("GET", f"/v1.43/containers/{hostname}/json")
        if code == 200:
            info = _djson.loads(body)
            labels = (info.get("Config") or {}).get("Labels") or {}
            return labels.get("com.docker.compose.project.working_dir")
    except Exception:
        pass
    return None


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
    "cogs.auto_delete",
    "cogs.temp_voice",
    "cogs.scheduler",
    "cogs.birthday",
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
    except discord.errors.LoginFailure:
        print(f"[Token-ID {token_id}] ❌ Ungültiger Token – Bot wird übersprungen.")
    except Exception as e:
        print(f"[Token-ID {token_id}] ❌ Bot-Fehler: {e}")
    finally:
        bot._bots.pop(token_id, None)


async def _stop_bot(token_id: int):
    instance = bot._bots.get(token_id)
    if instance:
        await instance.close()


async def _start_bot_by_id(token_id: int):
    row = await db_one("SELECT id, token FROM bot_tokens WHERE id=? AND enabled=1", (token_id,))
    if row:
        await _run_single_bot(row["id"], row["token"])


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

_request_tz: ContextVar[ZoneInfo] = ContextVar("request_tz", default=ZoneInfo("Europe/Berlin"))


def _fmt_dt(value) -> str:
    if not value:
        return ""
    try:
        s = str(value).replace(" ", "T")
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(_request_tz.get()).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)[:16]


class TZMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            tz_str = request.session.get("user_tz", "Europe/Berlin")
        except Exception:
            tz_str = "Europe/Berlin"
        try:
            token = _request_tz.set(ZoneInfo(tz_str))
        except Exception:
            token = _request_tz.set(ZoneInfo("Europe/Berlin"))
        response = await call_next(request)
        _request_tz.reset(token)
        return response


web = FastAPI()
# TZMiddleware added first → inner (runs after SessionMiddleware populates session)
web.add_middleware(TZMiddleware)
web.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="phobos_session")
templates = Jinja2Templates(directory="templates")
templates.env.filters["dt"] = _fmt_dt

def _log_bar_class(icon: str) -> str:
    _map = {
        "📥": "bar-green", "✅": "bar-green", "🔊": "bar-green", "📁": "bar-green",
        "📤": "bar-red",   "🔨": "bar-red",   "🔇": "bar-red",   "🗑️": "bar-red",
        "✏️": "bar-yellow", "🔀": "bar-amber",
        "⏱️": "bar-amber",
        "🏷️": "bar-blue",
        "✏": "bar-purple", "🔑": "bar-purple",
        "💎": "bar-pink",
    }
    for k, v in _map.items():
        if icon and k in icon:
            return v
    return "bar-gray"

templates.env.filters["log_bar_class"] = _log_bar_class

_app_name: str = "Phobos Bot"

def _set_app_name(name: str):
    global _app_name
    _app_name = name or "Phobos Bot"
    templates.env.globals["app_name"] = _app_name

_set_app_name("Phobos Bot")


ACTION_COLORS = {
    "ban": "#ef4444", "kick": "#f97316", "timeout": "#eab308",
    "warn": "#3b82f6", "unban": "#22c55e", "clear": "#8b5cf6",
    "automod:warn": "#94a3b8", "automod:timeout": "#94a3b8",
    "automod:kick": "#94a3b8", "automod:ban": "#94a3b8",
}


def session(request: Request) -> dict:
    lang = request.session.get("lang", "de")
    uid = request.session.get("user_id")
    return {
        "username": request.session.get("username"),
        "display_name": request.session.get("display_name") or request.session.get("username"),
        "role": request.session.get("role"),
        "user_id": uid,
        "version": VERSION,
        "lang": lang,
        "user_tz": request.session.get("user_tz", "Europe/Berlin"),
        "tr": get_tr(lang),
        "has_avatar": bool(uid and (AVATARS_DIR / f"{uid}.jpg").exists()),
        **{p: request.session.get(p, False) for p in PERM_COLS},
    }


PERM_COLS = ["perm_settings", "perm_tokens", "perm_users", "perm_bots",
             "perm_streaming", "perm_smtp", "perm_updates", "perm_server"]


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
    if request.session.get(perm, False):
        return True
    # Session may be stale (role updated after login) — re-check from DB
    uid = request.session.get("user_id")
    if uid:
        row = await db_one(
            "SELECT r.* FROM users u JOIN roles r ON r.id=u.custom_role_id WHERE u.id=?",
            (uid,),
        )
        if row:
            for p in PERM_COLS:
                request.session[p] = bool(row.get(p, 0))
            return bool(row.get(perm, 0))
    return False


async def perm_redirect(request: Request, perm: str) -> Optional[RedirectResponse]:
    if not await has_perm(request, perm):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    return None


async def _token_configured() -> bool:
    if await db_rows("SELECT id FROM bot_tokens WHERE enabled=1 LIMIT 1"):
        return True
    return bool(await get_config("discord_token"))


async def _token_guild_ids(user_id: int) -> set[str]:
    """Guild IDs reachable via bot tokens assigned to this user."""
    token_rows = await db_rows(
        "SELECT t.id FROM bot_tokens t "
        "JOIN bot_token_users tu ON tu.token_id=t.id "
        "WHERE tu.user_id=? AND t.enabled=1",
        (user_id,),
    )
    ids: set[str] = set()
    for tr in token_rows:
        token_bot = bot._bots.get(tr["id"])
        if token_bot:
            for g in token_bot.guilds:
                ids.add(str(g.id))
    return ids


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
    allowed |= await _token_guild_ids(user_id)
    return [g for g in all_guilds if g["id"] in allowed]


async def _guild_access(request: Request, guild_id) -> bool:
    if request.session.get("role") == "admin":
        return True
    uid = request.session.get("user_id")
    row = await db_one(
        "SELECT 1 FROM user_guild_permissions WHERE user_id=? AND guild_id=?",
        (uid, str(guild_id)),
    )
    if row:
        return True
    return str(guild_id) in await _token_guild_ids(uid)


# ── Auth ──────────────────────────────────────────────────────────────────────

@web.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = "", success: str = ""):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {
        "request": request, "error": error, "success": success, "version": VERSION,
    })


@web.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = await db_one("SELECT * FROM users WHERE username=?", (username.strip(),))
    if not user or not verify_pw(password, user["password_hash"]):
        return RedirectResponse("/login?error=Ungültige+Zugangsdaten", status_code=302)
    if not user.get("active", 1):
        return RedirectResponse("/login?error=Dein+Konto+ist+deaktiviert", status_code=302)
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["display_name"] = user.get("display_name") or ""
    request.session["role"] = user["role"]
    request.session["lang"] = user.get("language") or "de"
    user_tz = user.get("timezone") or await get_config("timezone") or "Europe/Berlin"
    request.session["user_tz"] = user_tz
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


@web.post("/settings/language")
async def set_language(request: Request, lang: str = Form("de")):
    if lang not in ("de", "en"):
        lang = "de"
    request.session["lang"] = lang
    uid = request.session.get("user_id")
    if uid:
        await db_exec("UPDATE users SET language=? WHERE id=?", (lang, uid))
    referer = request.headers.get("referer", "/")
    return RedirectResponse(referer, status_code=302)


# ── Profile ───────────────────────────────────────────────────────────────────

TZONES = [
    "Europe/Berlin", "Europe/Vienna", "Europe/Zurich", "Europe/London",
    "Europe/Paris", "Europe/Amsterdam", "Europe/Brussels", "Europe/Warsaw",
    "Europe/Bucharest", "Europe/Helsinki", "Europe/Moscow",
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Toronto", "America/Sao_Paulo",
    "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata", "Asia/Dubai",
    "Australia/Sydney", "Pacific/Auckland", "UTC",
]


@web.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, success: str = "", error: str = ""):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    user = await db_one("SELECT * FROM users WHERE id=?", (uid,))
    token_set = await _token_configured()
    return templates.TemplateResponse("profile.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": "profile", "user": user, "tzones": TZONES,
        "success": success, "error": error,
    })


@web.post("/profile/info")
async def profile_info_save(
    request: Request,
    display_name: str = Form(""),
    position: str = Form(""),
    email: str = Form(""),
):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    await db_exec(
        "UPDATE users SET display_name=?, position=?, email=? WHERE id=?",
        (display_name.strip(), position.strip(), email.strip(), uid),
    )
    request.session["display_name"] = display_name.strip()
    return RedirectResponse("/profile?success=Profil+gespeichert", status_code=302)


@web.post("/profile/preferences")
async def profile_prefs_save(
    request: Request,
    lang: str = Form("de"),
    timezone: str = Form("Europe/Berlin"),
):
    if r := auth_redirect(request): return r
    if lang not in ("de", "en"):
        lang = "de"
    try:
        ZoneInfo(timezone)
    except Exception:
        timezone = "Europe/Berlin"
    uid = request.session.get("user_id")
    await db_exec("UPDATE users SET language=?, timezone=? WHERE id=?", (lang, timezone, uid))
    request.session["lang"] = lang
    request.session["user_tz"] = timezone
    return RedirectResponse("/profile?success=Einstellungen+gespeichert", status_code=302)


@web.post("/profile/password")
async def profile_password_save(
    request: Request,
    pw_current: str = Form(...),
    pw_new: str = Form(...),
    pw_confirm: str = Form(...),
):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    user = await db_one("SELECT * FROM users WHERE id=?", (uid,))
    if not user or not verify_pw(pw_current, user["password_hash"]):
        return RedirectResponse("/profile?error=Aktuelles+Passwort+falsch", status_code=302)
    if pw_new != pw_confirm:
        return RedirectResponse("/profile?error=Passwörter+stimmen+nicht+überein", status_code=302)
    if len(pw_new) < 6:
        return RedirectResponse("/profile?error=Passwort+zu+kurz+(min.+6+Zeichen)", status_code=302)
    await db_exec("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(pw_new), uid))
    return RedirectResponse("/profile?success=Passwort+geändert", status_code=302)


@web.post("/profile/delete")
async def profile_delete(
    request: Request,
    pw1: str = Form(...),
    pw2: str = Form(...),
):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    user = await db_one("SELECT * FROM users WHERE id=?", (uid,))
    if not user:
        return RedirectResponse("/login", status_code=302)
    if pw1 != pw2:
        return RedirectResponse("/profile?error=Passwörter+stimmen+nicht+überein", status_code=302)
    if not verify_pw(pw1, user["password_hash"]):
        return RedirectResponse("/profile?error=Passwort+falsch", status_code=302)
    # Prevent deleting last admin
    if user["role"] == "admin":
        admin_count = await db_one("SELECT COUNT(*) as c FROM users WHERE role='admin'")
        if (admin_count or {}).get("c", 0) <= 1:
            return RedirectResponse("/profile?error=Du+bist+der+letzte+Admin+–+Konto+kann+nicht+gelöscht+werden", status_code=302)
    await db_exec("DELETE FROM users WHERE id=?", (uid,))
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@web.get("/avatar/{user_id}")
async def avatar_serve(user_id: int):
    path = AVATARS_DIR / f"{user_id}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(path), media_type="image/jpeg")


@web.post("/profile/avatar")
async def profile_avatar_upload(request: Request, avatar: UploadFile = File(...)):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    data = await avatar.read()
    if len(data) > 2 * 1024 * 1024:
        return RedirectResponse("/profile?error=Datei+zu+groß+(max.+2+MB)", status_code=302)
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((256, 256), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        (AVATARS_DIR / f"{uid}.jpg").write_bytes(buf.getvalue())
    except Exception:
        return RedirectResponse("/profile?error=Ungültiges+Bildformat", status_code=302)
    return RedirectResponse("/profile?success=Profilbild+gespeichert", status_code=302)


@web.post("/profile/avatar/delete")
async def profile_avatar_delete(request: Request):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    path = AVATARS_DIR / f"{uid}.jpg"
    if path.exists():
        path.unlink()
    return RedirectResponse("/profile?success=Profilbild+gelöscht", status_code=302)


# ── Backup / Restore ───────────────────────────────────────────────────────────

_BACKUP_FEATURE_TABLES = [
    "reaction_roles", "custom_commands", "auto_delete_channels",
    "temp_voice_config", "notifications", "freestuff_channels",
    "birthdays", "warnings",
]


async def _build_user_backup(target_user_id: int, exported_by: str) -> dict:
    user = await db_one("SELECT * FROM users WHERE id=?", (target_user_id,))
    if not user:
        return {}
    token_links = await db_rows(
        "SELECT token_id FROM bot_token_users WHERE user_id=?", (target_user_id,)
    )
    token_ids = [r["token_id"] for r in token_links]
    tokens = []
    for tid in token_ids:
        t = await db_one("SELECT * FROM bot_tokens WHERE id=?", (tid,))
        if t:
            tokens.append(t)
    scheduled = await db_rows(
        "SELECT * FROM scheduled_messages WHERE sent=0"
    )
    data: dict = {
        "meta": {
            "version": "1.0", "type": "user",
            "app_version": VERSION,
            "exported_at": datetime.datetime.utcnow().isoformat(),
            "exported_by": exported_by,
            "username": user["username"],
        },
        "user": dict(user),
        "bot_tokens": tokens,
        "bot_token_users": await db_rows(
            "SELECT * FROM bot_token_users WHERE user_id=?", (target_user_id,)
        ),
        "user_guild_permissions": await db_rows(
            "SELECT * FROM user_guild_permissions WHERE user_id=?", (target_user_id,)
        ),
        "guild_configs": await db_rows("SELECT * FROM guild_configs"),
        "scheduled_messages": scheduled,
    }
    for tbl in _BACKUP_FEATURE_TABLES:
        data[tbl] = await db_rows(f"SELECT * FROM {tbl}")
    return data


async def _build_full_backup(exported_by: str) -> dict:
    scheduled = await db_rows("SELECT * FROM scheduled_messages WHERE sent=0")
    data: dict = {
        "meta": {
            "version": "1.0", "type": "full",
            "app_version": VERSION,
            "exported_at": datetime.datetime.utcnow().isoformat(),
            "exported_by": exported_by,
        },
        "users": await db_rows("SELECT * FROM users"),
        "roles": await db_rows("SELECT * FROM roles"),
        "bot_tokens": await db_rows("SELECT * FROM bot_tokens"),
        "bot_token_users": await db_rows("SELECT * FROM bot_token_users"),
        "user_guild_permissions": await db_rows("SELECT * FROM user_guild_permissions"),
        "guild_configs": await db_rows("SELECT * FROM guild_configs"),
        "scheduled_messages": scheduled,
        "config": await db_rows(
            "SELECT * FROM config WHERE key NOT IN ('discord_token','smtp_pass')"
        ),
    }
    for tbl in _BACKUP_FEATURE_TABLES:
        data[tbl] = await db_rows(f"SELECT * FROM {tbl}")
    return data


def _json_dl(data: dict, filename: str) -> Response:
    content = _djson.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@web.get("/backup/export")
async def backup_export_own(request: Request):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    uname = request.session.get("username", "user")
    data = await _build_user_backup(uid, uname)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    return _json_dl(data, f"backup_{uname}_{ts}.json")


@web.get("/admin/backup/user/{user_id}")
async def backup_export_user(request: Request, user_id: int):
    if r := admin_redirect(request): return r
    by = request.session.get("username", "admin")
    data = await _build_user_backup(user_id, by)
    if not data:
        return RedirectResponse("/users?error=Benutzer+nicht+gefunden", status_code=302)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    uname = data["meta"]["username"]
    return _json_dl(data, f"backup_{uname}_{ts}.json")


@web.get("/admin/backup/all")
async def backup_export_all(request: Request):
    if r := admin_redirect(request): return r
    by = request.session.get("username", "admin")
    data = await _build_full_backup(by)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    return _json_dl(data, f"backup_full_{ts}.json")


@web.post("/admin/backup/restore")
async def backup_restore(request: Request, backup_file: UploadFile = File(...)):
    if r := admin_redirect(request): return r
    try:
        raw = await backup_file.read()
        data = _djson.loads(raw)
    except Exception:
        return RedirectResponse("/users?error=Ungültige+Backup-Datei+(kein+gültiges+JSON)", status_code=302)

    meta = data.get("meta", {})
    if not meta.get("version"):
        return RedirectResponse("/users?error=Kein+gültiges+Phobos-Backup", status_code=302)

    restored: list[str] = []

    async with aiosqlite.connect(DB_PATH) as db:

        # 1. Roles (full backup only)
        for row in data.get("roles", []):
            try:
                await db.execute("""
                    INSERT INTO roles
                        (name,color,perm_settings,perm_tokens,perm_users,perm_bots,
                         perm_streaming,perm_smtp,perm_updates,perm_server)
                    VALUES
                        (:name,:color,:perm_settings,:perm_tokens,:perm_users,:perm_bots,
                         :perm_streaming,:perm_smtp,:perm_updates,:perm_server)
                    ON CONFLICT(name) DO UPDATE SET
                        color=excluded.color,perm_settings=excluded.perm_settings,
                        perm_tokens=excluded.perm_tokens,perm_users=excluded.perm_users,
                        perm_bots=excluded.perm_bots,perm_streaming=excluded.perm_streaming,
                        perm_smtp=excluded.perm_smtp,perm_updates=excluded.perm_updates,
                        perm_server=excluded.perm_server
                """, row)
            except Exception:
                pass
        if data.get("roles"):
            restored.append("Rollen")

        # 2. Users — build old_id → new_id map
        users_list = data.get("users", [])
        if "user" in data:
            users_list = [data["user"]]
        old_uid_map: dict[int, int] = {}

        for u in users_list:
            old_id = u.get("id")
            try:
                ex = await db.execute("SELECT id FROM users WHERE username=?", (u["username"],))
                ex = await ex.fetchone()
                if ex:
                    await db.execute(
                        "UPDATE users SET display_name=?,position=?,email=?,role=?,language=?,timezone=? WHERE username=?",
                        (u.get("display_name",""), u.get("position",""), u.get("email",""),
                         u.get("role","moderator"), u.get("language","de"), u.get("timezone",""),
                         u["username"]),
                    )
                    new_id = ex[0]
                else:
                    cur = await db.execute(
                        "INSERT INTO users (username,password_hash,role,email,display_name,position,language,timezone) VALUES (?,?,?,?,?,?,?,?)",
                        (u["username"], u.get("password_hash",""), u.get("role","moderator"),
                         u.get("email",""), u.get("display_name",""), u.get("position",""),
                         u.get("language","de"), u.get("timezone","")),
                    )
                    new_id = cur.lastrowid
                if old_id is not None:
                    old_uid_map[old_id] = new_id
            except Exception:
                pass
        if users_list:
            restored.append("Benutzer")

        # 3. Bot tokens — old_id → new_id map
        old_tid_map: dict[int, int] = {}
        for t in data.get("bot_tokens", []):
            old_id = t.get("id")
            try:
                ex = await db.execute("SELECT id FROM bot_tokens WHERE token=?", (t["token"],))
                ex = await ex.fetchone()
                if ex:
                    new_id = ex[0]
                else:
                    cur = await db.execute(
                        "INSERT INTO bot_tokens (label,token,enabled) VALUES (?,?,?)",
                        (t.get("label","Bot"), t["token"], t.get("enabled",1)),
                    )
                    new_id = cur.lastrowid
                if old_id is not None:
                    old_tid_map[old_id] = new_id
            except Exception:
                pass
        if data.get("bot_tokens"):
            restored.append("Bot-Tokens")

        # 4. bot_token_users
        for btu in data.get("bot_token_users", []):
            old_t = btu.get("token_id")
            old_u = btu.get("user_id")
            new_t = old_tid_map.get(old_t, old_t)
            new_u = old_uid_map.get(old_u, old_u)
            try:
                await db.execute(
                    "INSERT OR IGNORE INTO bot_token_users (token_id,user_id) VALUES (?,?)",
                    (new_t, new_u),
                )
            except Exception:
                pass

        # 5. user_guild_permissions
        for p in data.get("user_guild_permissions", []):
            old_u = p.get("user_id")
            new_u = old_uid_map.get(old_u, old_u)
            try:
                await db.execute(
                    "INSERT OR IGNORE INTO user_guild_permissions (user_id,guild_id) VALUES (?,?)",
                    (new_u, p["guild_id"]),
                )
            except Exception:
                pass

        # 6. Guild configs
        for gc in data.get("guild_configs", []):
            try:
                await db.execute(
                    "INSERT INTO guild_configs (guild_id,key,value) VALUES (?,?,?) "
                    "ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",
                    (gc["guild_id"], gc["key"], gc["value"]),
                )
            except Exception:
                pass
        if data.get("guild_configs"):
            restored.append("Server-Konfiguration")

        # 7. Feature tables
        _tbl_insert = {
            "reaction_roles":
                "INSERT OR IGNORE INTO reaction_roles (guild_id,channel_id,message_id,emoji,role_id) VALUES (:guild_id,:channel_id,:message_id,:emoji,:role_id)",
            "custom_commands":
                "INSERT INTO custom_commands (guild_id,trigger,response) VALUES (:guild_id,:trigger,:response) ON CONFLICT(guild_id,trigger) DO UPDATE SET response=excluded.response",
            "auto_delete_channels":
                "INSERT INTO auto_delete_channels (guild_id,channel_id,delay_seconds) VALUES (:guild_id,:channel_id,:delay_seconds) ON CONFLICT(guild_id,channel_id) DO UPDATE SET delay_seconds=excluded.delay_seconds",
            "temp_voice_config":
                "INSERT INTO temp_voice_config (guild_id,trigger_channel_id,category_id,name_template,user_limit) VALUES (:guild_id,:trigger_channel_id,:category_id,:name_template,:user_limit) ON CONFLICT(guild_id,trigger_channel_id) DO UPDATE SET category_id=excluded.category_id,name_template=excluded.name_template,user_limit=excluded.user_limit",
            "scheduled_messages":
                "INSERT OR IGNORE INTO scheduled_messages (guild_id,channel_id,message,send_at,sent) VALUES (:guild_id,:channel_id,:message,:send_at,:sent)",
            "notifications":
                "INSERT OR IGNORE INTO notifications (guild_id,platform,discord_channel_id,target,target_name,last_id,live,custom_message) VALUES (:guild_id,:platform,:discord_channel_id,:target,:target_name,:last_id,0,:custom_message)",
            "freestuff_channels":
                "INSERT INTO freestuff_channels (guild_id,channel_id,platforms,deal_max_price,deal_min_discount,deal_channel_id) VALUES (:guild_id,:channel_id,:platforms,:deal_max_price,:deal_min_discount,:deal_channel_id) ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,platforms=excluded.platforms,deal_max_price=excluded.deal_max_price,deal_min_discount=excluded.deal_min_discount,deal_channel_id=excluded.deal_channel_id",
            "birthdays":
                "INSERT OR REPLACE INTO birthdays (user_id,guild_id,birthday) VALUES (:user_id,:guild_id,:birthday)",
            "warnings":
                "INSERT OR IGNORE INTO warnings (user_id,guild_id,moderator_id,reason,timestamp) VALUES (:user_id,:guild_id,:moderator_id,:reason,:timestamp)",
        }
        for tbl, sql in _tbl_insert.items():
            rows = data.get(tbl, [])
            for row in rows:
                try:
                    await db.execute(sql, row)
                except Exception:
                    pass
            if rows:
                restored.append(tbl.replace("_", " ").title())

        # 8. Global config (full backup only, skip sensitive keys)
        _skip_cfg = {"discord_token", "smtp_pass", "secret_key"}
        for row in data.get("config", []):
            if row.get("key") in _skip_cfg:
                continue
            try:
                await db.execute(
                    "INSERT INTO config (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (row["key"], row["value"]),
                )
            except Exception:
                pass

        await db.commit()

    summary = ", ".join(restored) if restored else "Nichts"
    return RedirectResponse(
        f"/users?success=Backup+eingespielt:+{urllib.parse.quote(summary)}", status_code=302
    )


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
            f"Der Link ist 1 Stunde gültig.\n\n{_app_name}",
            "plain", "utf-8",
        )
        msg["Subject"] = f"{_app_name} – Passwort zurücksetzen"
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
async def dashboard(request: Request, error: str = ""):
    if r := auth_redirect(request): return r
    is_admin = request.session.get("role") == "admin"
    guilds = await _guild_list(request)
    total_members = sum((g["members"] or 0) for g in guilds)
    if is_admin:
        actions = await db_rows("SELECT * FROM mod_actions ORDER BY timestamp DESC LIMIT 15")
        stats = {r["action"]: r["count"] for r in await db_rows(
            "SELECT action, COUNT(*) as count FROM mod_actions GROUP BY action"
        )}
    else:
        gids = tuple(int(g["id"]) for g in guilds)
        if gids:
            ph = ",".join("?" * len(gids))
            actions = await db_rows(
                f"SELECT * FROM mod_actions WHERE guild_id IN ({ph}) ORDER BY timestamp DESC LIMIT 15", gids
            )
            stats = {r["action"]: r["count"] for r in await db_rows(
                f"SELECT action, COUNT(*) as count FROM mod_actions WHERE guild_id IN ({ph}) GROUP BY action", gids
            )}
        else:
            actions, stats = [], {}
    token_set = await _token_configured()
    delta = datetime.datetime.utcnow() - PROCESS_START
    h, rem = divmod(int(delta.total_seconds()), 3600)
    uptime_str = f"{h}h {rem // 60}m" if h else f"{rem // 60}m"
    local_hour = datetime.datetime.now(_request_tz.get()).hour
    return templates.TemplateResponse("index.html", {
        **session(request), "request": request,
        "actions": actions, "stats": stats, "colors": ACTION_COLORS,
        "token_set": token_set, "guilds": guilds, "active": "dashboard",
        "bot_online": bot.is_ready(),
        "uptime_str": uptime_str,
        "total_members": total_members,
        "local_hour": local_hour,
        "error": error,
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
    current_tz = await get_config("timezone") or "Europe/Berlin"
    smtp_host = await get_config("smtp_host") or ""
    smtp_port = await get_config("smtp_port") or "587"
    smtp_user = await get_config("smtp_user") or ""
    smtp_from = await get_config("smtp_from") or ""
    base_url  = await get_config("base_url") or ""
    twitch_client_id = await get_config("twitch_client_id") or ""
    return templates.TemplateResponse("settings.html", {
        **session(request), "request": request,
        "masked": masked, "saved": saved, "token_set": bool(token),
        "users": all_users, "error": error, "success": success,
        "guilds": await _guild_list(request), "active": "settings",
        "current_tz": current_tz,
        "smtp_host": smtp_host, "smtp_port": smtp_port,
        "smtp_user": smtp_user, "smtp_from": smtp_from, "base_url": base_url,
        "twitch_client_id": twitch_client_id,
    })


@web.post("/settings")
async def settings_save(request: Request, token: str = Form(...)):
    if r := auth_redirect(request): return r
    if token.strip():
        await set_config("discord_token", token.strip())
    return RedirectResponse("/settings?saved=true", status_code=303)


@web.post("/settings/timezone")
async def settings_timezone_save(request: Request, timezone: str = Form(...)):
    if r := auth_redirect(request): return r
    if r := await perm_redirect(request, "perm_settings"): return r
    try:
        ZoneInfo(timezone)
    except Exception:
        return RedirectResponse("/settings?error=Ungültige+Zeitzone", status_code=302)
    await set_config("timezone", timezone)
    return RedirectResponse("/settings?success=Zeitzone+gespeichert", status_code=302)


@web.post("/settings/app-name")
async def settings_app_name_save(request: Request, app_name: str = Form(...)):
    if r := admin_redirect(request): return r
    name = app_name.strip()[:64] or "Phobos Bot"
    await set_config("app_name", name)
    _set_app_name(name)
    return RedirectResponse("/settings?success=App-Name+gespeichert", status_code=302)


@web.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, error: str = "", success: str = ""):
    if r := admin_redirect(request): return r
    all_users = await db_rows("SELECT id, username, role, email, created_at, custom_role_id, active FROM users ORDER BY created_at")
    token_set = await _token_configured()
    admin_count = sum(1 for u in all_users if u["role"] == "admin")
    all_guilds = [{"id": str(g.id), "name": g.name} for g in bot.guilds]
    perm_rows = await db_rows("SELECT user_id, guild_id FROM user_guild_permissions")
    user_perms: dict[int, set] = {}
    for p in perm_rows:
        user_perms.setdefault(p["user_id"], set()).add(str(p["guild_id"]))
    all_roles = await db_rows("SELECT * FROM roles ORDER BY name")
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
            "SELECT COUNT(*) as c FROM users WHERE role='admin' AND id!=?", (user_id,)
        )
        if not other_admins or other_admins.get("c", 0) == 0:
            return RedirectResponse("/users?error=Letzter+Admin+kann+nicht+herabgestuft+werden", status_code=302)
    await db_exec("UPDATE users SET role=? WHERE id=?", (role, user_id))
    return RedirectResponse("/users?success=Rolle+geändert", status_code=302)


@web.post("/users/delete/{user_id}")
async def users_delete(request: Request, user_id: int, next: str = "/users"):
    if r := admin_redirect(request): return r
    dest = next if next in ("/users", "/settings") else "/users"
    is_self = user_id == request.session.get("user_id")
    if is_self:
        other_admins = await db_one(
            "SELECT COUNT(*) as c FROM users WHERE role='admin' AND id!=?", (user_id,)
        )
        if not other_admins or other_admins.get("c", 0) == 0:
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


@web.post("/users/{user_id}/set-password")
async def users_set_password(request: Request, user_id: int, new_pw: str = Form(...)):
    if r := admin_redirect(request): return r
    if len(new_pw) < 6:
        return RedirectResponse("/users?error=Passwort+mindestens+6+Zeichen", status_code=302)
    await db_exec("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(new_pw), user_id))
    return RedirectResponse("/users?success=Passwort+geändert", status_code=302)


@web.post("/users/{user_id}/toggle-active")
async def users_toggle_active(request: Request, user_id: int):
    if r := admin_redirect(request): return r
    if user_id == request.session.get("user_id"):
        return RedirectResponse("/users?error=Eigenes+Konto+kann+nicht+deaktiviert+werden", status_code=302)
    user = await db_one("SELECT active FROM users WHERE id=?", (user_id,))
    if not user:
        return RedirectResponse("/users?error=Benutzer+nicht+gefunden", status_code=302)
    new_active = 0 if user.get("active", 1) else 1
    await db_exec("UPDATE users SET active=? WHERE id=?", (new_active, user_id))
    return RedirectResponse(f"/users?success={'Konto+aktiviert' if new_active else 'Konto+deaktiviert'}", status_code=302)


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


@web.get("/ping")
async def ping():
    return JSONResponse({"ok": True})


# ── Invite / Self-Registration ─────────────────────────────────────────────────

@web.get("/admin/invite/generate")
async def admin_invite_generate(request: Request):
    if r := admin_redirect(request): return r
    code = secrets.token_urlsafe(16)
    expires_at = (datetime.datetime.utcnow() + datetime.timedelta(minutes=5)).isoformat()
    await db_exec("DELETE FROM invite_codes")
    await db_exec("INSERT INTO invite_codes (code, expires_at) VALUES (?, ?)", (code, expires_at))
    return JSONResponse({"code": code, "expires_at": expires_at})


@web.post("/admin/invite/revoke")
async def admin_invite_revoke(request: Request):
    if r := admin_redirect(request): return r
    await db_exec("DELETE FROM invite_codes WHERE used=0")
    return JSONResponse({"ok": True})


@web.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, code: str = "", error: str = ""):
    if not code:
        return RedirectResponse("/login", status_code=302)
    inv = await db_one("SELECT * FROM invite_codes WHERE code=? AND used=0", (code,))
    if not inv:
        return templates.TemplateResponse("register.html", {
            "request": request, "code": code,
            "error": "Ungültiger oder bereits verwendeter Einladungscode.",
            "valid": False,
        })
    if datetime.datetime.utcnow() > datetime.datetime.fromisoformat(inv["expires_at"]):
        return templates.TemplateResponse("register.html", {
            "request": request, "code": code,
            "error": "Einladungscode ist abgelaufen (5 Minuten).",
            "valid": False,
        })
    return templates.TemplateResponse("register.html", {
        "request": request, "code": code, "error": error, "valid": True,
    })


@web.post("/register")
async def register_submit(
    request: Request,
    code: str = Form(...),
    username: str = Form(...),
    email_addr: str = Form(...),
    password: str = Form(...),
    pw_confirm: str = Form(...),
):
    inv = await db_one("SELECT * FROM invite_codes WHERE code=? AND used=0", (code,))
    if not inv or datetime.datetime.utcnow() > datetime.datetime.fromisoformat(inv["expires_at"]):
        return templates.TemplateResponse("register.html", {
            "request": request, "code": code,
            "error": "Code ungültig oder abgelaufen.", "valid": False,
        })
    if len(username.strip()) < 3:
        return templates.TemplateResponse("register.html", {
            "request": request, "code": code, "valid": True,
            "error": "Benutzername muss mindestens 3 Zeichen lang sein.",
        })
    if not email_addr.strip() or "@" not in email_addr:
        return templates.TemplateResponse("register.html", {
            "request": request, "code": code, "valid": True,
            "error": "Bitte eine gültige E-Mail-Adresse eingeben.",
        })
    if len(password) < 6:
        return templates.TemplateResponse("register.html", {
            "request": request, "code": code, "valid": True,
            "error": "Passwort muss mindestens 6 Zeichen lang sein.",
        })
    if password != pw_confirm:
        return templates.TemplateResponse("register.html", {
            "request": request, "code": code, "valid": True,
            "error": "Passwörter stimmen nicht überein.",
        })
    try:
        await db_exec(
            "INSERT INTO users (username, password_hash, role, email) VALUES (?, ?, ?, ?)",
            (username.strip(), hash_pw(password), "moderator", email_addr.strip()),
        )
    except Exception:
        return templates.TemplateResponse("register.html", {
            "request": request, "code": code, "valid": True,
            "error": "Benutzername bereits vergeben.",
        })
    await db_exec("UPDATE invite_codes SET used=1 WHERE code=?", (code,))
    return RedirectResponse(
        "/login?success=Registrierung+erfolgreich+–+bitte+einloggen", status_code=302
    )


@web.get("/bot/update", response_class=HTMLResponse)
async def bot_update_page(request: Request, success: str = "", error: str = ""):
    if r := auth_redirect(request): return r
    if r := await perm_redirect(request, "perm_updates"): return r
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


_update_status: dict = {"logs": [], "done": False, "error": ""}


def _ulog(msg: str, t: str = "info"):
    _update_status["logs"].append({"t": t, "msg": msg})


_UPDATE_IN_PROGRESS_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Phobos Bot – Update</title>
<style>
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:#0f1117; color:#e2e8f0; font-family:system-ui,sans-serif;
         display:flex; align-items:center; justify-content:center;
         min-height:100vh; padding:1rem; }
  .box { max-width:660px; width:100%; }
  .title-row { display:flex; align-items:center; gap:0.75rem; margin-bottom:1.25rem; }
  .spinner { width:24px; height:24px; border:3px solid rgba(124,58,237,.3);
             border-top-color:#7c3aed; border-radius:50%;
             animation:spin 0.9s linear infinite; flex-shrink:0; }
  @keyframes spin { to { transform:rotate(360deg); } }
  h2 { font-size:1.15rem; font-weight:700; }
  /* terminal */
  .term {
    background:#000; border:1px solid #1e2030; border-radius:0.5rem;
    overflow:hidden;
  }
  .term-bar {
    background:#1a1d27; padding:0.45rem 0.9rem;
    display:flex; align-items:center; gap:0.45rem;
    border-bottom:1px solid #1e2030;
  }
  .tb { width:10px; height:10px; border-radius:50%; }
  .tb-r { background:#ef4444; } .tb-y { background:#eab308; } .tb-g { background:#22c55e; }
  .term-title { font-size:0.72rem; color:#64748b; margin-left:0.5rem; font-family:monospace; }
  .term-body {
    padding:0.85rem 1rem; font-size:0.8rem; font-family:'Courier New',Courier,monospace;
    line-height:1.6; min-height:280px; max-height:520px; overflow-y:auto;
    display:flex; flex-direction:column; gap:0;
    white-space:pre-wrap; word-break:break-all;
  }
  .t-cmd      { color:#a78bfa; font-weight:700; margin-top:0.5rem; }
  .t-cmd:first-child { margin-top:0; }
  .t-info     { color:#94a3b8; }
  .t-progress { color:#38bdf8; }
  .t-file     { color:#4b5563; }
  .t-ok       { color:#22c55e; font-weight:600; }
  .t-warn     { color:#eab308; }
  .t-err      { color:#ef4444; font-weight:700; }
  .t-restart  { color:#f97316; font-weight:700; }
  .cursor { display:inline-block; width:8px; height:14px; background:#a78bfa;
            animation:blink 1s step-end infinite; vertical-align:text-bottom; }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
  .hint { text-align:center; color:#475569; font-size:0.75rem; margin-top:0.9rem; }
  #status-bar { font-size:0.75rem; color:#64748b; text-align:right; margin-top:0.4rem; font-family:monospace; }
</style>
</head>
<body>
<div class="box">
  <div class="title-row">
    <div class="spinner" id="spin"></div>
    <h2>🔄 Update wird durchgeführt</h2>
  </div>
  <div class="term">
    <div class="term-bar">
      <span class="tb tb-r"></span><span class="tb tb-y"></span><span class="tb tb-g"></span>
      <span class="term-title">phobos-bot — update</span>
    </div>
    <div class="term-body" id="log"><span class="cursor"></span></div>
  </div>
  <div id="status-bar"></div>
  <p class="hint" id="hint">Bitte warten – der Server startet automatisch neu.</p>
</div>
<script>
const log    = document.getElementById('log');
const spin   = document.getElementById('spin');
const hint   = document.getElementById('hint');
const sbar   = document.getElementById('status-bar');
let offset   = 0;
let restarting = false;
let waitTries  = 0;

function addLine(msg, t) {
  const cursor = log.querySelector('.cursor');
  if (cursor) cursor.remove();
  const d = document.createElement('div');
  d.className = 't-' + t;
  d.textContent = msg;
  log.appendChild(d);
  if (!restarting) {
    const c = document.createElement('span');
    c.className = 'cursor';
    log.appendChild(c);
  }
  log.scrollTop = log.scrollHeight;
}

function waitForServer() {
  fetch('/ping', {cache:'no-store'})
    .then(r => r.json())
    .then(d => {
      if (d.ok) {
        addLine('[+] Running 1/1', 'ok');
        addLine(' ✔ Container phobos-bot-phobos  Started', 'ok');
        addLine('✅  Server wieder online – weiterleiten…', 'ok');
        setTimeout(() => { window.location = '/'; }, 1500);
      } else retry();
    })
    .catch(() => retry());
}
function retry() {
  waitTries++;
  hint.textContent = 'Warte auf Neustart… (' + waitTries + ')';
  if (waitTries === 5)  addLine('  ⏳  Neustart dauert länger – bitte warten…', 'info');
  if (waitTries === 15) addLine('  ⏳  Server verbindet sich mit Discord…', 'info');
  if (waitTries === 30) addLine('  ⚠   Startet noch – falls nötig: docker compose restart', 'warn');
  if (waitTries < 120) setTimeout(waitForServer, 2500);
  else { addLine('❌  Timeout – bitte Container manuell neu starten.', 'err'); spin.style.display='none'; }
}

function poll() {
  fetch('/bot/update/status?offset=' + offset, {cache:'no-store'})
    .then(r => r.json())
    .then(d => {
      d.logs.forEach(l => addLine(l.msg, l.t));
      offset += d.logs.length;
      sbar.textContent = offset + ' Zeilen';

      if (d.error) {
        spin.style.display = 'none';
        hint.textContent = 'Update fehlgeschlagen.';
        const cursor = log.querySelector('.cursor');
        if (cursor) cursor.remove();
        return;
      }
      if (d.done) {
        spin.style.display = 'none';
        restarting = true;
        const cursor = log.querySelector('.cursor');
        if (cursor) cursor.remove();
        setTimeout(waitForServer, 8000);
      } else {
        setTimeout(poll, 600);
      }
    })
    .catch(() => {
      if (!restarting) {
        restarting = true;
        const cursor = log.querySelector('.cursor');
        if (cursor) cursor.remove();
        addLine('🚀  Verbindung unterbrochen – Server startet neu…', 'restart');
        setTimeout(waitForServer, 8000);
      }
    });
}
setTimeout(poll, 400);
</script>
</body>
</html>"""


@web.get("/bot/update/status")
async def bot_update_status(request: Request, offset: int = 0):
    if r := auth_redirect(request): return r
    logs = _update_status.get("logs", [])
    return JSONResponse({
        "logs": logs[offset:],
        "total": len(logs),
        "done": _update_status.get("done", False),
        "error": _update_status.get("error", ""),
    })


@web.post("/bot/update/apply")
async def bot_update_apply(request: Request):
    if r := auth_redirect(request): return r
    if r := await perm_redirect(request, "perm_updates"): return r

    async def _do_update():
        global _update_status
        _update_status = {"logs": [], "done": False, "error": ""}

        async def _run(cmd: list, cwd: str | None = None) -> int:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    _ulog(line, "info")
            return await proc.wait()

        try:
            _ulog("$ phobos-bot update — " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "cmd")

            # Fetch latest commits
            _ulog("$ git -C /repo fetch origin main", "cmd")
            rc = await _run(["git", "-C", "/repo", "fetch", "origin", "main"])
            if rc != 0:
                raise RuntimeError(f"git fetch fehlgeschlagen (exit {rc})")

            # Hard-reset to remote HEAD (handles any local drift)
            _ulog("$ git -C /repo reset --hard origin/main", "cmd")
            rc = await _run(["git", "-C", "/repo", "reset", "--hard", "origin/main"])
            if rc != 0:
                raise RuntimeError(f"git reset fehlgeschlagen (exit {rc})")
            _ulog("  ✓  Code aktualisiert", "ok")

            compose_dir = await asyncio.get_event_loop().run_in_executor(None, _get_compose_dir)
            if compose_dir:
                _ulog("$ docker-compose restart", "cmd")
                rc = await _run(["docker-compose", "restart"], cwd=compose_dir)
                _update_status["done"] = True
            else:
                _ulog("$ exec python " + " ".join(sys.argv), "cmd")
                _ulog("  🚀  Server wird neu gestartet…", "restart")
                _update_status["done"] = True
                await asyncio.sleep(1)
                os.execv(sys.executable, [sys.executable] + sys.argv)

        except Exception as e:
            _ulog(f"❌  Fehler: {e}", "err")
            _update_status["error"] = str(e)[:300]

    asyncio.create_task(_do_update())
    return HTMLResponse(_UPDATE_IN_PROGRESS_HTML)


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


@web.post("/servers/{guild_id}/freestuff/test")
async def freestuff_test(request: Request, guild_id: str):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    cfg = await db_one("SELECT * FROM freestuff_channels WHERE guild_id=?", (guild_id,))
    if not cfg:
        return RedirectResponse(
            f"/servers/{guild_id}/freestuff?error=Noch+nicht+konfiguriert", status_code=302
        )
    # Find the bot that is connected to this guild
    target_bot = None
    for b in bot._bots.values():
        if b.get_guild(int(guild_id)):
            target_bot = b
            break
    if not target_bot:
        return RedirectResponse(
            f"/servers/{guild_id}/freestuff?error=Bot+nicht+mit+diesem+Server+verbunden", status_code=302
        )
    cog = target_bot.cogs.get("FreeStuff")
    if not cog:
        return RedirectResponse(
            f"/servers/{guild_id}/freestuff?error=FreeStuff-Modul+nicht+geladen", status_code=302
        )
    ch = target_bot.get_channel(int(cfg["channel_id"]))
    if not ch:
        return RedirectResponse(
            f"/servers/{guild_id}/freestuff?error=Kanal+nicht+gefunden", status_code=302
        )
    try:
        platforms = set((cfg["platforms"] or "epic").split(","))
        games = await cog._fetch_free(platforms)
        games = [g for g in games if g["platform"] in platforms]
        if not games:
            return RedirectResponse(
                f"/servers/{guild_id}/freestuff?error=Aktuell+keine+Gratis-Spiele+gefunden", status_code=302
            )
        for game in games:
            await cog._send_embed(ch, game, is_deal=False)
        return RedirectResponse(
            f"/servers/{guild_id}/freestuff?success={len(games)}+Spiel(e)+in+den+Kanal+gesendet",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            f"/servers/{guild_id}/freestuff?error={urllib.parse.quote(str(e)[:120])}", status_code=302
        )


# ── Auto-Delete ───────────────────────────────────────────────────────────────

async def _reload_auto_delete():
    for b in bot._bots.values():
        cog = b.cogs.get("AutoDelete")
        if cog:
            await cog.reload()

@web.post("/servers/{guild_id}/auto-delete/save")
async def auto_delete_save(request: Request, guild_id: str):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    channel_ids = form.getlist("channel_id")
    delay_values = form.getlist("delay_seconds")
    await db_exec("DELETE FROM auto_delete_channels WHERE guild_id=?", (guild_id,))
    for cid, delay in zip(channel_ids, delay_values):
        if cid and delay and int(delay) > 0:
            await db_exec(
                "INSERT OR REPLACE INTO auto_delete_channels (guild_id, channel_id, delay_seconds) VALUES (?,?,?)",
                (guild_id, cid, int(delay)),
            )
    await _reload_auto_delete()
    return RedirectResponse(f"/servers/{guild_id}?tab=autodelete&success=Gespeichert", status_code=302)

@web.post("/servers/{guild_id}/auto-delete/delete/{entry_id}")
async def auto_delete_remove(request: Request, guild_id: str, entry_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM auto_delete_channels WHERE id=? AND guild_id=?", (entry_id, guild_id))
    await _reload_auto_delete()
    return RedirectResponse(f"/servers/{guild_id}?tab=autodelete&success=Gelöscht", status_code=302)


# ── Scheduled Messages ────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/scheduled/add")
async def scheduled_add(request: Request, guild_id: str):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    channel_id = form.get("channel_id", "")
    message = form.get("message", "").strip()
    send_at = form.get("send_at", "")
    if channel_id and message and send_at:
        await db_exec(
            "INSERT INTO scheduled_messages (guild_id, channel_id, message, send_at) VALUES (?,?,?,?)",
            (guild_id, channel_id, message, send_at),
        )
    return RedirectResponse(f"/servers/{guild_id}?tab=scheduled&success=Geplant", status_code=302)

@web.post("/servers/{guild_id}/scheduled/delete/{msg_id}")
async def scheduled_delete(request: Request, guild_id: str, msg_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM scheduled_messages WHERE id=? AND guild_id=?", (msg_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=scheduled&success=Gelöscht", status_code=302)


# ── Temp Voice ────────────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/tempvoice/add")
async def tempvoice_add(request: Request, guild_id: str):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    trigger = form.get("trigger_channel_id", "")
    category = form.get("category_id", "")
    name_tpl = form.get("name_template", "{user}'s Channel") or "{user}'s Channel"
    user_limit = int(form.get("user_limit") or 0)
    if trigger:
        await db_exec(
            "INSERT OR REPLACE INTO temp_voice_config (guild_id, trigger_channel_id, category_id, name_template, user_limit) VALUES (?,?,?,?,?)",
            (guild_id, trigger, category, name_tpl, user_limit),
        )
    return RedirectResponse(f"/servers/{guild_id}?tab=tempvoice&success=Gespeichert", status_code=302)

@web.post("/servers/{guild_id}/tempvoice/delete/{config_id}")
async def tempvoice_delete(request: Request, guild_id: str, config_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM temp_voice_config WHERE id=? AND guild_id=?", (config_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=tempvoice&success=Gelöscht", status_code=302)


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
    uid = request.session.get("user_id")
    srv_role = request.session.get("role")
    if srv_role == "admin":
        twitch_apis = await db_rows("SELECT * FROM twitch_apis ORDER BY created_at")
    else:
        twitch_apis = await db_rows(
            """SELECT DISTINCT ta.* FROM twitch_apis ta
               LEFT JOIN twitch_api_access taa ON taa.api_id = ta.id
               WHERE ta.owner_id=? OR taa.user_id=?
               ORDER BY ta.created_at""",
            (uid, uid),
        )
    current_api_cfg = await db_one(
        "SELECT value FROM guild_configs WHERE guild_id=? AND key='twitch_api_id'", (guild_id,)
    )
    current_api_id = int(current_api_cfg["value"]) if current_api_cfg else (twitch_apis[0]["id"] if twitch_apis else 0)
    return templates.TemplateResponse("notifications.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": f"server_{guild_id}",
        "guild_id": guild_id, "guild_name": guild.name,
        "channels": channels, "subs": subs,
        "twitch_apis": twitch_apis,
        "current_api_id": current_api_id,
        "twitch_configured": bool(twitch_apis),
        "success": success, "error": error,
    })


@web.post("/servers/{guild_id}/notifications/api")
async def notifications_set_api(request: Request, guild_id: str, twitch_api_id: str = Form("")):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    if twitch_api_id.strip():
        await set_guild_config(int(guild_id), "twitch_api_id", twitch_api_id.strip())
    return RedirectResponse(f"/servers/{guild_id}/notifications?success=API+gespeichert", status_code=302)


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
async def notif_settings_page(request: Request, saved: bool = False, error: str = "", success: str = ""):
    if r := auth_redirect(request): return r
    if r := await perm_redirect(request, "perm_streaming"): return r
    token_set = await _token_configured()
    uid = request.session.get("user_id")
    role = request.session.get("role")
    if role == "admin":
        twitch_apis = await db_rows("SELECT * FROM twitch_apis ORDER BY owner_id, created_at")
    else:
        twitch_apis = await db_rows(
            """SELECT DISTINCT ta.* FROM twitch_apis ta
               LEFT JOIN twitch_api_access taa ON taa.api_id = ta.id
               WHERE ta.owner_id=? OR taa.user_id=?
               ORDER BY ta.created_at""",
            (uid, uid),
        )
    all_users_map = {u["id"]: u["username"] for u in await db_rows("SELECT id, username FROM users")}
    # attach owner name and list of users with granted access
    access_rows = await db_rows("SELECT api_id, user_id FROM twitch_api_access")
    access_map: dict[int, list] = {}
    for ar in access_rows:
        access_map.setdefault(ar["api_id"], []).append(ar["user_id"])
    for a in twitch_apis:
        a["owner_name"] = all_users_map.get(a["owner_id"], "—")
        a["is_own"] = (a["owner_id"] == uid) or (role == "admin")
        granted_ids = access_map.get(a["id"], [])
        a["granted_users"] = [{"id": gid, "username": all_users_map.get(gid, str(gid))} for gid in granted_ids]
    # users available to grant (all except self and already granted)
    all_users = await db_rows("SELECT id, username FROM users ORDER BY username")
    return templates.TemplateResponse("notif_settings.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": "notif_settings",
        "twitch_apis": twitch_apis,
        "all_users": all_users,
        "saved": saved, "error": error, "success": success,
    })


@web.post("/settings/notifications/{api_id}/access/add")
async def notif_api_access_add(request: Request, api_id: int, grant_user_id: int = Form(...)):
    if r := auth_redirect(request): return r
    if r := await perm_redirect(request, "perm_streaming"): return r
    uid = request.session.get("user_id")
    role = request.session.get("role")
    api = await db_one("SELECT * FROM twitch_apis WHERE id=?", (api_id,))
    if not api or (role != "admin" and api["owner_id"] != uid):
        return RedirectResponse("/settings/notifications?error=Keine+Berechtigung", status_code=302)
    await db_exec(
        "INSERT OR IGNORE INTO twitch_api_access (api_id, user_id) VALUES (?,?)",
        (api_id, grant_user_id),
    )
    return RedirectResponse("/settings/notifications?success=Zugriff+gewaehrt", status_code=302)


@web.post("/settings/notifications/{api_id}/access/remove/{target_uid}")
async def notif_api_access_remove(request: Request, api_id: int, target_uid: int):
    if r := auth_redirect(request): return r
    if r := await perm_redirect(request, "perm_streaming"): return r
    uid = request.session.get("user_id")
    role = request.session.get("role")
    api = await db_one("SELECT * FROM twitch_apis WHERE id=?", (api_id,))
    if not api or (role != "admin" and api["owner_id"] != uid):
        return RedirectResponse("/settings/notifications?error=Keine+Berechtigung", status_code=302)
    await db_exec(
        "DELETE FROM twitch_api_access WHERE api_id=? AND user_id=?",
        (api_id, target_uid),
    )
    return RedirectResponse("/settings/notifications?success=Zugriff+entzogen", status_code=302)


@web.post("/settings/notifications/add")
async def notif_api_add(
    request: Request,
    label: str = Form("Standard"),
    twitch_client_id: str = Form(""),
    twitch_client_secret: str = Form(""),
):
    if r := auth_redirect(request): return r
    if r := await perm_redirect(request, "perm_streaming"): return r
    cid = twitch_client_id.strip()
    sec = twitch_client_secret.strip()
    if not cid or not sec:
        return RedirectResponse("/settings/notifications?error=Client-ID+und+Secret+erforderlich", status_code=302)
    uid = request.session.get("user_id")
    try:
        await db_exec(
            "INSERT INTO twitch_apis (owner_id, label, client_id, client_secret) VALUES (?,?,?,?)",
            (uid, label.strip() or "Meine API", cid, sec),
        )
    except Exception as e:
        return RedirectResponse(f"/settings/notifications?error={str(e)}", status_code=302)
    return RedirectResponse("/settings/notifications?success=API+hinzugefuegt", status_code=302)


@web.post("/settings/notifications/edit/{api_id}")
async def notif_api_edit(
    request: Request, api_id: int,
    label: str = Form(""),
    twitch_client_id: str = Form(""),
    twitch_client_secret: str = Form(""),
):
    if r := auth_redirect(request): return r
    if r := await perm_redirect(request, "perm_streaming"): return r
    uid = request.session.get("user_id")
    role = request.session.get("role")
    api = await db_one("SELECT * FROM twitch_apis WHERE id=?", (api_id,))
    if not api or (role != "admin" and api["owner_id"] != uid):
        return RedirectResponse("/settings/notifications?error=Keine+Berechtigung", status_code=302)
    if label.strip():
        await db_exec("UPDATE twitch_apis SET label=? WHERE id=?", (label.strip(), api_id))
    if twitch_client_id.strip():
        await db_exec("UPDATE twitch_apis SET client_id=? WHERE id=?", (twitch_client_id.strip(), api_id))
    if twitch_client_secret.strip():
        await db_exec("UPDATE twitch_apis SET client_secret=? WHERE id=?", (twitch_client_secret.strip(), api_id))
    return RedirectResponse("/settings/notifications?success=API+aktualisiert", status_code=302)


@web.post("/settings/notifications/delete/{api_id}")
async def notif_api_delete(request: Request, api_id: int):
    if r := auth_redirect(request): return r
    if r := await perm_redirect(request, "perm_streaming"): return r
    uid = request.session.get("user_id")
    role = request.session.get("role")
    api = await db_one("SELECT * FROM twitch_apis WHERE id=?", (api_id,))
    if not api or (role != "admin" and api["owner_id"] != uid):
        return RedirectResponse("/settings/notifications?error=Keine+Berechtigung", status_code=302)
    await db_exec("DELETE FROM twitch_apis WHERE id=?", (api_id,))
    return RedirectResponse("/settings/notifications?success=API+gelöscht", status_code=302)


# ── SMTP Settings ─────────────────────────────────────────────────────────────

@web.get("/settings/smtp", response_class=HTMLResponse)
async def smtp_settings_page(request: Request, saved: bool = False, error: str = "", test_ok: bool = False):
    if r := auth_redirect(request): return r
    if r := await perm_redirect(request, "perm_smtp"): return r
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
    if r := auth_redirect(request): return r
    if r := await perm_redirect(request, "perm_smtp"): return r
    for key, val in [
        ("smtp_host", smtp_host), ("smtp_port", smtp_port),
        ("smtp_user", smtp_user), ("smtp_from", smtp_from),
        ("base_url", base_url),
    ]:
        await set_config(key, val.strip())
    if smtp_pass.strip():
        await set_config("smtp_pass", smtp_pass.strip())
    return RedirectResponse("/settings?success=SMTP+gespeichert", status_code=302)


@web.post("/settings/smtp/test")
async def smtp_test(request: Request, test_email: str = Form(...)):
    if r := auth_redirect(request): return r
    if r := await perm_redirect(request, "perm_smtp"): return r
    try:
        await _send_reset_email(test_email.strip(), "https://example.com/test-link")
        return RedirectResponse("/settings?success=Test-E-Mail+gesendet", status_code=302)
    except Exception as e:
        return RedirectResponse(f"/settings?error={urllib.parse.quote(str(e))}", status_code=302)


# ── Token Management ──────────────────────────────────────────────────────────

@web.get("/settings/tokens", response_class=HTMLResponse)
async def tokens_page(request: Request, success: str = "", error: str = ""):
    if r := auth_redirect(request): return r
    is_admin = request.session.get("role") == "admin"
    uid = request.session.get("user_id")
    if is_admin:
        token_rows = await db_rows(
            "SELECT id, label, token, enabled, created_at FROM bot_tokens ORDER BY id"
        )
        all_users = await db_rows("SELECT id, username FROM users ORDER BY username")
        tu_rows = await db_rows("SELECT token_id, user_id FROM bot_token_users")
        token_users: dict[int, set] = {}
        for r in tu_rows:
            token_users.setdefault(r["token_id"], set()).add(r["user_id"])
    else:
        token_rows = await db_rows(
            "SELECT t.id, t.label, t.token, t.enabled, t.created_at FROM bot_tokens t "
            "WHERE EXISTS (SELECT 1 FROM bot_token_users tu WHERE tu.token_id=t.id AND tu.user_id=?) ORDER BY t.id",
            (uid,),
        )
        all_users = []
        token_users = {}
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
        "all_users": all_users,
        "token_users": token_users,
    })


@web.post("/settings/tokens/add")
async def tokens_add(request: Request):
    if r := auth_redirect(request): return r
    form = await request.form()
    label = (form.get("label") or "Bot").strip()
    token = (form.get("token") or "").strip()
    if not token:
        return RedirectResponse("/settings/tokens?error=Token+darf+nicht+leer+sein", status_code=302)
    uid = request.session.get("user_id")
    is_admin = request.session.get("role") == "admin"
    token_id = await db_insert(
        "INSERT INTO bot_tokens (label, token, owner_id) VALUES (?, ?, ?)",
        (label or "Bot", token, uid),
    )
    if is_admin:
        user_ids = form.getlist("user_ids")
        valid = {str(u["id"]) for u in await db_rows("SELECT id FROM users")}
        for uid_s in user_ids:
            if uid_s in valid:
                await db_exec(
                    "INSERT OR IGNORE INTO bot_token_users (token_id, user_id) VALUES (?,?)",
                    (token_id, int(uid_s)),
                )
    else:
        await db_exec(
            "INSERT OR IGNORE INTO bot_token_users (token_id, user_id) VALUES (?,?)",
            (token_id, uid),
        )
    asyncio.create_task(_start_bot_by_id(token_id))
    return RedirectResponse(
        "/settings/tokens?success=Token+hinzugefügt+und+Bot+wird+gestartet.",
        status_code=302,
    )


@web.post("/settings/tokens/users/{token_id}")
async def tokens_set_users(request: Request, token_id: int):
    if r := admin_redirect(request): return r
    form = await request.form()
    user_ids = form.getlist("user_ids")
    valid = {str(u["id"]) for u in await db_rows("SELECT id FROM users")}
    await db_exec("DELETE FROM bot_token_users WHERE token_id=?", (token_id,))
    for uid_s in user_ids:
        if uid_s in valid:
            await db_exec(
                "INSERT OR IGNORE INTO bot_token_users (token_id, user_id) VALUES (?,?)",
                (token_id, int(uid_s)),
            )
    return RedirectResponse("/settings/tokens?success=Benutzer+aktualisiert", status_code=302)


@web.post("/settings/tokens/delete/{token_id}")
async def tokens_delete(request: Request, token_id: int):
    if r := auth_redirect(request): return r
    is_admin = request.session.get("role") == "admin"
    uid = request.session.get("user_id")
    allowed = is_admin
    if not is_admin:
        allowed = bool(await db_one(
            "SELECT 1 FROM bot_token_users WHERE token_id=? AND user_id=?", (token_id, uid)
        ))
    if allowed:
        await _stop_bot(token_id)
        await db_exec("DELETE FROM bot_tokens WHERE id=?", (token_id,))
        await db_exec("DELETE FROM bot_token_users WHERE token_id=?", (token_id,))
    return RedirectResponse("/settings/tokens?success=Token+gelöscht.", status_code=302)


@web.post("/settings/tokens/rename/{token_id}")
async def tokens_rename(request: Request, token_id: int):
    if r := auth_redirect(request): return r
    form = await request.form()
    label = (form.get("label") or "").strip()
    if not label:
        return RedirectResponse("/settings/tokens?error=Bezeichnung+darf+nicht+leer+sein", status_code=302)
    is_admin = request.session.get("role") == "admin"
    uid = request.session.get("user_id")
    if is_admin:
        await db_exec("UPDATE bot_tokens SET label=? WHERE id=?", (label, token_id))
    else:
        assigned = await db_one(
            "SELECT 1 FROM bot_token_users WHERE token_id=? AND user_id=?", (token_id, uid)
        )
        if assigned:
            await db_exec("UPDATE bot_tokens SET label=? WHERE id=?", (label, token_id))
    return RedirectResponse("/settings/tokens?success=Bezeichnung+gespeichert", status_code=302)


@web.post("/settings/tokens/toggle/{token_id}")
async def tokens_toggle(request: Request, token_id: int):
    if r := auth_redirect(request): return r
    is_admin = request.session.get("role") == "admin"
    uid = request.session.get("user_id")
    allowed = is_admin
    if not is_admin:
        allowed = bool(await db_one(
            "SELECT 1 FROM bot_token_users WHERE token_id=? AND user_id=?", (token_id, uid)
        ))
    if allowed:
        row = await db_one("SELECT enabled FROM bot_tokens WHERE id=?", (token_id,))
        if row:
            new_enabled = 0 if row["enabled"] else 1
            await db_exec("UPDATE bot_tokens SET enabled=? WHERE id=?", (new_enabled, token_id))
            if new_enabled:
                asyncio.create_task(_start_bot_by_id(token_id))
            else:
                await _stop_bot(token_id)
    return RedirectResponse("/settings/tokens?success=Status+geändert.", status_code=302)


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
    return RedirectResponse(f"/users{'?success=' + success if success else ''}{'?error=' + error if error else ''}", status_code=302)


@web.post("/roles/create")
async def roles_create(request: Request,
    name: str = Form(...), color: str = Form("#6366f1"),
    perm_settings: int = Form(0), perm_tokens: int = Form(0),
    perm_users: int = Form(0), perm_bots: int = Form(0),
    perm_streaming: int = Form(0), perm_smtp: int = Form(0), perm_updates: int = Form(0),
    perm_server: int = Form(0),
):
    if r := admin_redirect(request): return r
    try:
        await db_exec(
            "INSERT INTO roles (name,color,perm_settings,perm_tokens,perm_users,perm_bots,"
            "perm_streaming,perm_smtp,perm_updates,perm_server) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (name.strip(), color, perm_settings, perm_tokens, perm_users, perm_bots,
             perm_streaming, perm_smtp, perm_updates, perm_server),
        )
    except Exception:
        return RedirectResponse("/users?error=Rollenname+bereits+vergeben", status_code=302)
    return RedirectResponse("/users?success=Rolle+erstellt", status_code=302)


@web.post("/roles/edit/{role_id}")
async def roles_edit(request: Request, role_id: int,
    name: str = Form(...), color: str = Form("#6366f1"),
    perm_settings: int = Form(0), perm_tokens: int = Form(0),
    perm_users: int = Form(0), perm_bots: int = Form(0),
    perm_streaming: int = Form(0), perm_smtp: int = Form(0), perm_updates: int = Form(0),
    perm_server: int = Form(0),
):
    if r := admin_redirect(request): return r
    try:
        await db_exec(
            "UPDATE roles SET name=?,color=?,perm_settings=?,perm_tokens=?,perm_users=?,perm_bots=?,"
            "perm_streaming=?,perm_smtp=?,perm_updates=?,perm_server=? WHERE id=?",
            (name.strip(), color, perm_settings, perm_tokens, perm_users, perm_bots,
             perm_streaming, perm_smtp, perm_updates, perm_server, role_id),
        )
    except Exception:
        return RedirectResponse("/users?error=Rollenname+bereits+vergeben", status_code=302)
    return RedirectResponse("/users?success=Rolle+gespeichert", status_code=302)


@web.post("/roles/delete/{role_id}")
async def roles_delete(request: Request, role_id: int):
    if r := admin_redirect(request): return r
    await db_exec("UPDATE users SET custom_role_id=NULL WHERE custom_role_id=?", (role_id,))
    await db_exec("DELETE FROM roles WHERE id=?", (role_id,))
    return RedirectResponse("/users?success=Rolle+gelöscht", status_code=302)


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
    exclude_raw = await get_guild_config(int(guild_id), "log_exclude_channels") or ""
    log_exclude_channels = [c.strip() for c in exclude_raw.split(",") if c.strip()]
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
        "log_exclude_channels": log_exclude_channels,
        "logs": logs, "success": success,
    })


@web.post("/servers/{guild_id}/log/save")
async def server_log_save(request: Request, guild_id: str):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    log_channel = form.get("log_channel", "")
    exclude_channels = ",".join(form.getlist("log_exclude_channels"))
    from database import set_guild_config
    await set_guild_config(int(guild_id), "log_channel", log_channel)
    await set_guild_config(int(guild_id), "log_exclude_channels", exclude_channels)
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
    guild_ok = await _guild_access(request, guild_id)
    if not guild_ok and not await has_perm(request, "perm_server"):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse("/", status_code=302)
    if not guild_ok:
        return RedirectResponse("/servers", status_code=302)

    token_set = await _token_configured()
    cfg = await get_all_guild_config(guild_id)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    voice_channels = [{"id": str(c.id), "name": c.name} for c in guild.voice_channels]
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

    # Ticket panels
    ticket_panels = await db_rows(
        "SELECT * FROM ticket_panels WHERE guild_id=? ORDER BY created_at DESC", (guild_id,)
    )
    for p in ticket_panels:
        if p.get("channel_id"):
            try:
                ch = guild.get_channel(int(p["channel_id"]))
                p["channel_name"] = ch.name if ch else None
            except (ValueError, TypeError):
                p["channel_name"] = None

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
    twitch_configured = bool(await db_rows("SELECT 1 FROM twitch_apis LIMIT 1"))

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
        "ticket_panels": ticket_panels, "ticket_list": ticket_list, "ga_list": ga_list,
        "subs": subs, "twitch_configured": twitch_configured,
        "all_users": all_users, "server_perms": server_perms,
        "auto_delete_entries": await db_rows(
            "SELECT * FROM auto_delete_channels WHERE guild_id=?", (str(guild_id),)
        ),
        "voice_channels": voice_channels,
        "tempvoice_configs": await db_rows(
            "SELECT * FROM temp_voice_config WHERE guild_id=?", (str(guild_id),)
        ),
        "scheduled_messages": await db_rows(
            "SELECT * FROM scheduled_messages WHERE guild_id=? AND sent=0 ORDER BY send_at", (str(guild_id),)
        ),
        "birthdays": await db_rows(
            "SELECT * FROM birthdays WHERE guild_id=? ORDER BY birthday", (str(guild_id),)
        ),
    })


@web.post("/servers/{guild_id}")
async def server_config_save(request: Request, guild_id: int):
    guild_ok = await _guild_access(request, guild_id)
    if not guild_ok and not await has_perm(request, "perm_server"):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    if not guild_ok:
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    text_keys = [
        "welcome_channel", "welcome_message", "leave_channel", "leave_message", "autorole",
        "welcome_card_circle_color", "welcome_card_text_color", "welcome_card_username_color",
        "birthday_channel", "birthday_message",
        "log_channel", "level_channel",
        "automod_spam_threshold", "automod_banned_words", "automod_action",
        "ticket_support_role", "ticket_category",
    ]
    checkbox_keys = ["leveling_enabled", "automod_enabled", "automod_links", "welcome_card_enabled"]
    for key in text_keys:
        await set_guild_config(guild_id, key, str(form.get(key, "")))
    for key in checkbox_keys:
        await set_guild_config(guild_id, key, "1" if form.get(key) else "0")
    return RedirectResponse(f"/servers/{guild_id}?tab=config&saved=true", status_code=303)


# ── Ticket Panels ────────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/tickets/panels/create")
async def tickets_panel_create(request: Request, guild_id: int, name: str = Form(...)):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    name = name.strip()
    if not name:
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Name+erforderlich", status_code=302)
    await db_exec(
        "INSERT INTO ticket_panels (guild_id, name, button_label, description, emoji) VALUES (?,?,?,?,?)",
        (guild_id, name, "Ticket öffnen", "Klicke unten um ein Ticket zu öffnen.", "🎫"),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=tickets&success=Panel+erstellt", status_code=302)


@web.post("/servers/{guild_id}/tickets/panels/{panel_id}/update")
async def tickets_panel_update(
    request: Request, guild_id: int, panel_id: int,
    name: str = Form(""), button_label: str = Form("Ticket öffnen"),
    description: str = Form(""), emoji: str = Form("🎫"),
    support_role_id: str = Form(""), category_id: str = Form(""),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec(
        "UPDATE ticket_panels SET name=?, button_label=?, description=?, emoji=?, "
        "support_role_id=?, category_id=? WHERE id=? AND guild_id=?",
        (name.strip(), button_label.strip() or "Ticket öffnen",
         description.strip(), emoji.strip() or "🎫",
         support_role_id, category_id, panel_id, guild_id),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=tickets&success=Panel+gespeichert", status_code=302)


@web.post("/servers/{guild_id}/tickets/panels/{panel_id}/delete")
async def tickets_panel_delete(request: Request, guild_id: int, panel_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    panel = await db_one("SELECT * FROM ticket_panels WHERE id=? AND guild_id=?", (panel_id, guild_id))
    if panel and panel.get("message_id") and panel.get("channel_id"):
        try:
            b = bot._bot_for_guild(guild_id)
            if b:
                ch = b.get_channel(int(panel["channel_id"]))
                if ch:
                    msg = await ch.fetch_message(int(panel["message_id"]))
                    await msg.delete()
        except Exception:
            pass
    await db_exec("DELETE FROM ticket_panels WHERE id=? AND guild_id=?", (panel_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=tickets&success=Panel+gelöscht", status_code=302)


@web.post("/servers/{guild_id}/tickets/panels/{panel_id}/publish")
async def tickets_panel_publish(
    request: Request, guild_id: int, panel_id: int,
    channel_id: str = Form(...),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    panel = await db_one("SELECT * FROM ticket_panels WHERE id=? AND guild_id=?", (panel_id, guild_id))
    if not panel:
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Panel+nicht+gefunden", status_code=302)
    b = bot._bot_for_guild(guild_id)
    if not b:
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Bot+nicht+verbunden", status_code=302)
    try:
        ch = b.get_channel(int(channel_id))
    except (ValueError, TypeError):
        ch = None
    if not ch:
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Kanal+nicht+gefunden", status_code=302)
    # Remove old panel message if any
    if panel.get("message_id") and panel.get("channel_id"):
        try:
            old_ch = b.get_channel(int(panel["channel_id"]))
            if old_ch:
                old_msg = await old_ch.fetch_message(int(panel["message_id"]))
                await old_msg.delete()
        except Exception:
            pass
    label = panel.get("button_label") or "Ticket öffnen"
    emoji = panel.get("emoji") or "🎫"
    embed = discord.Embed(
        title=f"{emoji} {panel['name']}",
        description=panel.get("description") or "Klicke unten um ein Ticket zu öffnen.",
        color=0x7C3AED,
    )
    view = _TicketView(panel_id, label, emoji)
    msg = await ch.send(embed=embed, view=view)
    b.add_view(view)
    await db_exec(
        "UPDATE ticket_panels SET status='published', channel_id=?, message_id=? WHERE id=?",
        (str(channel_id), str(msg.id), panel_id),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=tickets&success=Panel+veröffentlicht", status_code=302)


@web.post("/servers/{guild_id}/tickets/panels/{panel_id}/unpublish")
async def tickets_panel_unpublish(request: Request, guild_id: int, panel_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec(
        "UPDATE ticket_panels SET status='draft', message_id='' WHERE id=? AND guild_id=?",
        (panel_id, guild_id),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=tickets&success=Panel+deaktiviert", status_code=302)


@web.post("/servers/{guild_id}/tickets/{ticket_id}/close")
async def ticket_close(request: Request, guild_id: int, ticket_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    ticket = await db_one("SELECT * FROM tickets WHERE id=? AND guild_id=?", (ticket_id, guild_id))
    if ticket:
        b = bot._bot_for_guild(guild_id)
        if b:
            ch = b.get_channel(ticket["channel_id"])
            if ch:
                try:
                    await ch.delete(reason="Ticket via Dashboard geschlossen")
                except Exception:
                    pass
        await db_exec(
            "UPDATE tickets SET status='closed' WHERE id=? AND guild_id=?",
            (ticket_id, guild_id),
        )
    return RedirectResponse(f"/servers/{guild_id}?tab=tickets&success=Ticket+geschlossen", status_code=302)


@web.post("/servers/{guild_id}/tickets/{ticket_id}/delete")
async def ticket_delete(request: Request, guild_id: int, ticket_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM tickets WHERE id=? AND guild_id=?", (ticket_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=tickets&success=Ticket+gelöscht", status_code=302)


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
    stored_name = await get_config("app_name")
    if stored_name:
        _set_app_name(stored_name)

    user_count = (await db_one("SELECT COUNT(*) as c FROM users") or {}).get("c", 0)
    if user_count == 0:
        await db_exec(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            ("admin", hash_pw("admin"), "admin"),
        )
        print("Standard-Admin erstellt: admin / admin")

    server = uvicorn.Server(uvicorn.Config(web, host="0.0.0.0", port=8080, log_level="warning"))
    # Bot runs as independent background task — crashes there never kill the web server
    asyncio.create_task(run_bot())
    await server.serve()


asyncio.run(main())
