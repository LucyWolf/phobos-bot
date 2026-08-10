import asyncio
import datetime
import os
import platform
import secrets
import shutil
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

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

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


@bot.event
async def on_ready():
    for cog in COGS:
        try:
            await bot.load_extension(cog)
        except Exception as e:
            print(f"Fehler beim Laden von {cog}: {e}")
    await bot.tree.sync()
    print(f"Phobos v{VERSION} online als {bot.user}")


async def run_bot():
    print("Warte auf Discord Token...")
    while True:
        token = await get_config("discord_token")
        if token:
            break
        await asyncio.sleep(5)
    async with bot:
        await bot.start(token)


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
    }


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


def _guild_list(request: Request) -> list:
    return [
        {"id": str(g.id), "name": g.name, "members": g.member_count,
         "icon": str(g.icon.url) if g.icon else None}
        for g in bot.guilds
    ]


# ── Auth ──────────────────────────────────────────────────────────────────────

@web.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=302)
    count = (await db_one("SELECT COUNT(*) as c FROM users") or {}).get("c", 0)
    return templates.TemplateResponse("login.html", {
        "request": request, "error": error,
        "default_creds": count == 1, "version": VERSION,
    })


@web.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = await db_one("SELECT * FROM users WHERE username=?", (username.strip(),))
    if not user or not verify_pw(password, user["password_hash"]):
        return RedirectResponse("/login?error=Ungültige+Zugangsdaten", status_code=302)
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["role"] = user["role"]
    return RedirectResponse("/", status_code=302)


@web.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@web.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if r := auth_redirect(request): return r
    actions = await db_rows("SELECT * FROM mod_actions ORDER BY timestamp DESC LIMIT 50")
    stats = {r["action"]: r["count"] for r in await db_rows(
        "SELECT action, COUNT(*) as count FROM mod_actions GROUP BY action"
    )}
    token_set = bool(await get_config("discord_token"))
    guilds = _guild_list(request)
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
        "guilds": _guild_list(request), "active": "settings",
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
    all_users = await db_rows("SELECT id, username, role, created_at FROM users ORDER BY created_at")
    token_set = bool(await get_config("discord_token"))
    return templates.TemplateResponse("users.html", {
        **session(request), "request": request,
        "users": all_users, "error": error, "success": success,
        "guilds": _guild_list(request), "token_set": token_set, "active": "users",
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


@web.post("/users/delete/{user_id}")
async def users_delete(request: Request, user_id: int, next: str = "/users"):
    if r := admin_redirect(request): return r
    dest = next if next in ("/users", "/settings") else "/users"
    if user_id == request.session.get("user_id"):
        return RedirectResponse(f"{dest}?error=Du+kannst+dich+nicht+selbst+löschen", status_code=302)
    await db_exec("DELETE FROM users WHERE id=?", (user_id,))
    return RedirectResponse(f"{dest}?success=Benutzer+gelöscht", status_code=302)


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
async def bot_design_page(request: Request, success: str = "", error: str = ""):
    if r := auth_redirect(request): return r
    token_set = bool(await get_config("discord_token"))
    current_name = bot.user.name if bot.user else None
    current_avatar = str(bot.user.display_avatar.url) if bot.user else None
    return templates.TemplateResponse("bot_design.html", {
        **session(request), "request": request,
        "guilds": _guild_list(request), "token_set": token_set,
        "active": "bot_design", "success": success, "error": error,
        "current_name": current_name, "current_avatar": current_avatar,
        "bot_online": bot.is_ready(),
    })


@web.post("/bot/design")
async def bot_design_save(
    request: Request,
    bot_name: str = Form(""),
    avatar: UploadFile = File(None),
):
    if r := auth_redirect(request): return r
    if not bot.is_ready():
        return RedirectResponse("/bot/design?error=Bot+ist+offline", status_code=302)
    try:
        kwargs = {}
        if bot_name.strip() and bot_name.strip() != bot.user.name:
            kwargs["username"] = bot_name.strip()
        if avatar and avatar.filename:
            content = await avatar.read()
            if content:
                kwargs["avatar"] = content
        if kwargs:
            await bot.user.edit(**kwargs)
        else:
            return RedirectResponse("/bot/design?error=Keine+Änderungen", status_code=302)
    except discord.HTTPException as e:
        msg = str(e)[:80].replace(" ", "+")
        return RedirectResponse(f"/bot/design?error={msg}", status_code=302)
    return RedirectResponse("/bot/design?success=Gespeichert", status_code=302)


# ── Bot Info ──────────────────────────────────────────────────────────────────

@web.get("/bot/info", response_class=HTMLResponse)
async def bot_info_page(request: Request):
    if r := auth_redirect(request): return r
    token_set = bool(await get_config("discord_token"))
    return templates.TemplateResponse("bot_info.html", {
        **session(request), "request": request,
        "guilds": _guild_list(request), "token_set": token_set,
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
    token_set = bool(await get_config("discord_token"))
    latest = await check_latest_version()
    update_available = bool(latest and _ver_tuple(latest) > _ver_tuple(VERSION))
    return templates.TemplateResponse("bot_update.html", {
        **session(request), "request": request,
        "guilds": _guild_list(request), "token_set": token_set,
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
    token_set = bool(await get_config("discord_token"))
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    cfg = await db_one("SELECT * FROM freestuff_channels WHERE guild_id=?", (guild_id,))
    return templates.TemplateResponse("freestuff.html", {
        **session(request), "request": request,
        "guilds": _guild_list(request), "token_set": token_set,
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
    plat_str = ",".join(p for p in platforms if p in ("epic", "steam", "gog", "humble"))
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
    await db_exec("DELETE FROM freestuff_channels WHERE guild_id=?", (guild_id,))
    return RedirectResponse(f"/servers/{guild_id}/freestuff?success=1", status_code=302)


# ── Notifications ─────────────────────────────────────────────────────────────

@web.get("/servers/{guild_id}/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request, guild_id: str, success: str = "", error: str = ""):
    if r := auth_redirect(request): return r
    token_set = bool(await get_config("discord_token"))
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    subs = await db_rows("SELECT * FROM notifications WHERE guild_id=? ORDER BY platform, target_name", (guild_id,))
    twitch_id = await get_config("twitch_client_id") or ""
    return templates.TemplateResponse("notifications.html", {
        **session(request), "request": request,
        "guilds": _guild_list(request), "token_set": token_set,
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
):
    if r := auth_redirect(request): return r
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
        return RedirectResponse(f"/servers/{guild_id}/notifications?error=Bereits+eingetragen", status_code=302)
    await db_exec(
        "INSERT INTO notifications (guild_id,platform,discord_channel_id,target,target_name,custom_message) VALUES (?,?,?,?,?,?)",
        (guild_id, platform, discord_channel_id, target.lower() if platform == "twitch" else target,
         target_name.strip(), custom_message.strip()),
    )
    return RedirectResponse(f"/servers/{guild_id}/notifications?success=1", status_code=302)


@web.post("/servers/{guild_id}/notifications/delete/{nid}")
async def notifications_delete(request: Request, guild_id: str, nid: int):
    if r := auth_redirect(request): return r
    await db_exec("DELETE FROM notifications WHERE id=? AND guild_id=?", (nid, guild_id))
    return RedirectResponse(f"/servers/{guild_id}/notifications?success=1", status_code=302)


@web.get("/settings/notifications", response_class=HTMLResponse)
async def notif_settings_page(request: Request, saved: bool = False, error: str = ""):
    if r := auth_redirect(request): return r
    if session(request).get("role") != "admin":
        return RedirectResponse("/", status_code=302)
    token_set = bool(await get_config("discord_token"))
    return templates.TemplateResponse("notif_settings.html", {
        **session(request), "request": request,
        "guilds": _guild_list(request), "token_set": token_set,
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


# ── Servers List ──────────────────────────────────────────────────────────────

@web.get("/servers", response_class=HTMLResponse)
async def servers_list(request: Request):
    if r := auth_redirect(request): return r
    guilds = _guild_list(request)
    token_set = bool(await get_config("discord_token"))
    invite_url = get_invite_url()
    return templates.TemplateResponse("servers_list.html", {
        **session(request), "request": request,
        "guilds": guilds, "token_set": token_set,
        "invite_url": invite_url, "bot_online": bot.is_ready(),
        "active": "servers",
    })


# ── Leaderboard ───────────────────────────────────────────────────────────────

@web.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard_page(request: Request, guild_id: str = ""):
    if r := auth_redirect(request): return r
    guilds = _guild_list(request)
    token_set = bool(await get_config("discord_token"))

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

    token_set = bool(await get_config("discord_token"))
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

    return templates.TemplateResponse("server_config.html", {
        **session(request), "request": request,
        "guild": {"id": str(guild.id), "name": guild.name,
                  "icon": str(guild.icon.url) if guild.icon else None},
        "cfg": cfg, "channels": channels, "roles": roles, "categories": categories,
        "token_set": token_set, "saved": saved,
        "active": f"server_{guild_id}",
        "guilds": _guild_list(request),
        "tab": tab, "error": error, "success": success,
        "rr_list": rr_list, "cmd_list": cmd_list,
        "leaderboard": lb, "warn_groups": warn_groups,
        "ticket_list": ticket_list, "ga_list": ga_list,
    })


@web.post("/servers/{guild_id}")
async def server_config_save(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
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


# ── Reaction Roles ────────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/reaction_roles/add")
async def rr_add(
    request: Request, guild_id: int,
    channel_id: str = Form(...), message_id: str = Form(...),
    emoji: str = Form(...), role_id: str = Form(...),
):
    if r := auth_redirect(request): return r
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
    await db_exec("DELETE FROM reaction_roles WHERE id=? AND guild_id=?", (rr_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=rr", status_code=302)


# ── Custom Commands ───────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/commands/add")
async def cmd_add(
    request: Request, guild_id: int,
    trigger: str = Form(...), response: str = Form(...),
):
    if r := auth_redirect(request): return r
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
    cog = bot.cogs.get("Giveaways")
    if cog:
        await cog._end_giveaway(gid)
    return RedirectResponse(f"/servers/{guild_id}?tab=giveaways", status_code=302)


@web.post("/servers/{guild_id}/giveaways/{gid}/reroll")
async def giveaway_reroll_web(request: Request, guild_id: int, gid: int):
    if r := auth_redirect(request): return r
    await db_exec("UPDATE giveaways SET ended=0 WHERE id=? AND guild_id=?", (gid, guild_id))
    cog = bot.cogs.get("Giveaways")
    if cog:
        await cog._end_giveaway(gid)
    return RedirectResponse(f"/servers/{guild_id}?tab=giveaways", status_code=302)


# ── Warnings ──────────────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/warnings/{user_id}/clear")
async def warnings_clear(request: Request, guild_id: int, user_id: int):
    if r := auth_redirect(request): return r
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
