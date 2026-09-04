"""Phobos Bot - dashboard + web server (FastAPI) and the Discord bot process itself.

Everything below is grouped under "# ── Section Name ──" header comments, in the order
listed here - search for one (e.g. "── AMP Gameserver") to jump straight to it instead of
scrolling. Route groups generally follow the shape: GET page -> POST save/add -> POST edit ->
POST delete, mirroring the dashboard tab they belong to.

  Discord Bot                 - BotManager (multi-token registry), per-token connect/reconnect
                                loop, run_bot() startup
  Web UI                      - shared Jinja filters (dt/dtlocal/js/jsraw/log_bar_class), the
                                global error handler, and the core auth/guild-access helpers
                                (session, auth_redirect, admin_redirect, _guild_access,
                                _guild_list) used by nearly every route below
  Auth                        - login, 2FA verification, logout
  Profile                     - own-account settings: password, language, timezone, avatar,
                                2FA
  Backup / Restore            - full/per-user/per-guild JSON export + import
                                (_BACKUP_FEATURE_TABLES/_BACKUP_TBL_INSERT list every table a
                                guild backup covers - add new feature tables there)
  Password Reset              - forgot-password email flow
  Dashboard                   - the "/" home page (recent mod actions, guild overview)
  Settings                    - Discord bot token, default app name/avatar
  Bot Design                  - bot name/avatar editor (per guild if multi-token, else global)
  Bot Info                    - status/uptime/system-stats page
  Update Check                - GitHub-version polling + the git/Docker or Android in-app
                                updater
  Invite / Self-Registration  - admin invite links, self-service signup via a code
  AMP Gameserver              - CubeCoders AMP connection + per-instance custom Discord
                                commands
  Free Stuff                  - free-game/deal channel config (Epic/Steam/GOG/...)
  Auto-Delete                 - scheduled message deletion per channel
  Scheduled Messages          - one-off messages sent at a future time
  Discord Events              - native Discord scheduled events + reminders + recurrence
  Temp Voice                  - auto-created temporary voice channels
  Notifications               - Twitch live-stream alerts
  SMTP Settings               - outgoing mail config (used for password resets)
  Token Management            - add/rename/enable/disable Discord bot tokens
  User Email                  - per-user email address (admin-set, used for password resets)
  Servers List                - the "/servers" overview page
  Leaderboard                 - standalone "/leaderboard" page + its XP-curve helper
  Server Config               - the big per-guild "/servers/{id}" page: gathers every tab's
                                data for the GET route, plus the generic multi-tab save route
  Auto-Kick reminders         - reminder DMs sent before the auto-kick tab's kick delay fires
  Auto-Mod word-list presets  - reusable "+"-button word categories for the banned-words field
  Level roles                 - level-threshold -> role assignments
  Level rewards               - level-threshold -> free-text prize announcements
  Reset a member's XP         - dashboard XP wipe for one member
  Ticket Panels               - ticket panel CRUD, publish/unpublish, block-parsing helpers
                                shared with Embed Posts below
  Embed Posts                 - standalone multi-block embed messages, editable after posting
  Server User Access          - grant/revoke one moderator's access to one specific guild
  Reaction Roles              - reaction-role message CRUD
  Custom Commands             - admin-defined "!trigger" -> response text
  Giveaways                   - start/end/reroll a giveaway from the dashboard
  Warnings                    - clear a member's warnings
  API                         - small JSON endpoints used by the dashboard's own JS
  Startup                     - app init, static asset routes, uvicorn entrypoint
"""
from __future__ import annotations

import asyncio
import base64
import calendar
import datetime
import email.mime.text
import io
import json as _djson
import math
import os
import socket as _dsock
import traceback
from contextvars import ContextVar
try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Chaquopy (Android) bundles Python 3.8, which predates the stdlib zoneinfo module (3.9+).
    # pytz is used instead there - pure Python, no native build needed, and it ships the full
    # IANA tz database inside the package itself (there's no system tzdata to fall back on
    # under Android, unlike Docker/Termux).
    from pytz import timezone as ZoneInfo
import platform
import re
import secrets
import shutil
import smtplib
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional

from PIL import Image

import aiosqlite
import bcrypt
import discord
try:
    import psutil
except ImportError:
    # No prebuilt Android wheel and no C toolchain available under Chaquopy - the rest of the
    # bot doesn't need it, only get_system_stats() below (the Bot-Info dashboard page) does.
    psutil = None
from cogs.tickets import OpenTicketView as _TicketView, close_ticket_channel as _close_ticket_channel
from cogs.leveling import xp_for_level as _xp_for_level, cumulative_xp_for_level as _cumulative_xp_for_level
from i18n import get_tr
import uvicorn
from discord.ext import commands
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
import markupsafe
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

PROCESS_START = datetime.datetime.utcnow()

from database import (
    DB_PATH, init_db, get_config, set_config,
    get_guild_config, set_guild_config, get_all_guild_config,
    db_rows, db_one, db_exec, db_exec_rowcount, db_insert, log_mod_action,
)
import totp

VERSION = (Path(__file__).parent / "VERSION").read_text().strip()
# Defaults to the Docker container path - override via PHOBOS_DATA_DIR for non-Docker setups
# (e.g. running directly under Termux on Android, where /app/data doesn't exist/isn't writable).
DATA_DIR = Path(os.environ.get("PHOBOS_DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
# Set by PhobosService.kt before starting Python - distinguishes the Android/Chaquopy build
# from Termux (both use PHOBOS_DATA_DIR/PHOBOS_DB_PATH) since only Android needs the
# APK-download update flow instead of the git-based one (no /repo, no git, no docker there).
IS_ANDROID = os.environ.get("PHOBOS_PLATFORM") == "android"
SECRET_KEY_PATH = DATA_DIR / "secret.key"
AVATARS_DIR = DATA_DIR / "avatars"


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
    "cogs.amp",
    "cogs.auto_kick",
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
    """Runs one bot instance. Auto-reconnects after unexpected disconnects (e.g. a
    discord.py gateway hiccup) as long as the token stays enabled - only an invalid
    token or an explicit disable/delete stops the retry loop for good."""
    while True:
        intents = discord.Intents.all()
        instance = commands.Bot(command_prefix="!", intents=intents)

        @instance.event
        async def on_ready():
            await instance.tree.sync()
            print(f"Phobos v{VERSION} online als {instance.user} [ID {token_id}]")

        bot._bots[token_id] = instance
        login_failed = False
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
            login_failed = True
        except Exception as e:
            print(f"[Token-ID {token_id}] ❌ Bot-Fehler: {e}")
        finally:
            bot._bots.pop(token_id, None)

        if login_failed:
            return

        if token_id:
            row = await db_one("SELECT enabled FROM bot_tokens WHERE id=?", (token_id,))
            if not row or not row.get("enabled", 1):
                return  # deaktiviert/gelöscht - absichtlich beendet, nicht neu verbinden

        print(f"[Token-ID {token_id}] 🔄 Verbindung verloren, versuche in 10s erneut zu verbinden…")
        await asyncio.sleep(10)


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


def _aware(dt_naive: datetime.datetime, tz) -> datetime.datetime:
    """Attach a timezone to a naive datetime - correctly for both zoneinfo.ZoneInfo and pytz
    (the Android fallback). Plain .replace(tzinfo=pytz_tz) gives wrong UTC offsets; pytz needs
    .localize() instead. zoneinfo.ZoneInfo has no .localize, so this only branches under pytz."""
    return tz.localize(dt_naive) if hasattr(tz, "localize") else dt_naive.replace(tzinfo=tz)


def _add_recurrence_interval(dt: datetime.datetime, recurrence: str) -> datetime.datetime:
    """Advances a (timezone-aware) datetime by one event_series recurrence step. "monthly"
    clamps the day to the target month's actual length (Jan 31 + 1 month -> Feb 28/29, not an
    invalid Mar 3 rollover) instead of using a fixed day count, since months vary in length.
    Duplicated (not imported) in cogs/scheduler.py, which is the actual caller - matches this
    project's established pattern of small self-contained helpers over cross-module imports
    between main.py and dynamically-loaded cogs (see e.g. _parse_ticket_blocks)."""
    if recurrence == "daily":
        return dt + datetime.timedelta(days=1)
    if recurrence == "weekly":
        return dt + datetime.timedelta(days=7)
    if recurrence == "monthly":
        month = dt.month + 1
        year = dt.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(dt.day, calendar.monthrange(year, month)[1])
        return dt.replace(year=year, month=month, day=day)
    return dt


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


def _fmt_dt_local(value) -> str:
    """Format for <input type=datetime-local> value= (YYYY-MM-DDTHH:MM), in the request's timezone."""
    if not value:
        return ""
    try:
        s = str(value).replace(" ", "T")
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(_request_tz.get()).strftime("%Y-%m-%dT%H:%M")
    except Exception:
        return ""


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


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Stamps every response with Cache-Control: no-store so the browser never serves a stale
    page after a deploy - requested after this bit repeatedly during this session (a JS/HTML
    bug that had already been fixed in the code kept appearing to persist because the browser
    was still showing the previous version). No static file mount exists in this app (avatars
    etc. are served through their own dynamic routes, not StaticFiles), so there's nothing here
    that would actually benefit from caching in the first place."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


class SessionValidityMiddleware(BaseHTTPMiddleware):
    """Re-checks role/active status from the DB on every request — otherwise a
    deactivated or demoted user keeps full access for the rest of their
    (up to 14 day) session cookie lifetime."""
    async def dispatch(self, request: Request, call_next):
        try:
            uid = request.session.get("user_id")
        except Exception:
            uid = None
        if uid:
            row = await db_one("SELECT role, active FROM users WHERE id=?", (uid,))
            if not row or not row.get("active", 1):
                request.session.clear()
            elif row["role"] != request.session.get("role"):
                request.session["role"] = row["role"]
        return await call_next(request)


web = FastAPI()


@web.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    # A per-request exception here doesn't crash the whole process, so PhobosService's
    # crash.log mechanism (Android's only way to see errors without adb/logcat) never sees it -
    # write the same kind of traceback file for these too, so a plain "Internal Server Error" in
    # the browser is diagnosable the same way a full process crash already is.
    try:
        with open(DATA_DIR / "web_errors.log", "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.datetime.now()}  {request.method} {request.url.path} ===\n")
            f.write(traceback.format_exc())
    except Exception:
        pass
    return Response("Internal Server Error", status_code=500)


# TZMiddleware/SessionValidityMiddleware added first → inner (run after SessionMiddleware populates session)
web.add_middleware(TZMiddleware)
web.add_middleware(SessionValidityMiddleware)
web.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="phobos_session")
web.add_middleware(NoCacheMiddleware)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
def _js_attr(value) -> str:
    """JSON-encode value for embedding as a JS string literal inside a double-quoted HTML
    attribute (e.g. onclick="fn({{ value | js }})"). Safe regardless of Jinja autoescape,
    since the result is HTML-attribute-escaped here and marked safe."""
    encoded = _djson.dumps("" if value is None else str(value))
    escaped = encoded.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
    return markupsafe.Markup(escaped)


def _js_raw(value) -> str:
    """JSON-encode value for embedding as a JS string literal inside a <script> element's
    text content (e.g. const X = {{ value | jsraw }};). Do NOT use inside HTML attributes -
    entities are not decoded in <script> content, so no HTML-escaping is applied here."""
    encoded = _djson.dumps("" if value is None else str(value))
    return markupsafe.Markup(encoded.replace("</", "<\\/"))


templates.env.filters["dt"] = _fmt_dt
templates.env.filters["dtlocal"] = _fmt_dt_local
templates.env.filters["js"] = _js_attr
templates.env.filters["jsraw"] = _js_raw

def _log_bar_class(icon: str) -> str:
    _map = {
        "📥": "bar-green", "✅": "bar-green", "🔊": "bar-green", "📁": "bar-green",
        "📤": "bar-red",   "🔨": "bar-red",   "🔇": "bar-red",   "🗑️": "bar-red",
        "✏️": "bar-yellow", "🔀": "bar-amber",
        "⏱️": "bar-amber",
        "🏷️": "bar-blue",
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
        "sidebar_collapsed": request.session.get("sidebar_collapsed", False),
        "nav_settings_open": request.session.get("nav_settings_open", False),
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


async def _complete_login(request: Request, user: dict) -> None:
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["display_name"] = user.get("display_name") or ""
    request.session["role"] = user["role"]
    request.session["lang"] = user.get("language") or "de"
    user_tz = user.get("timezone") or await get_config("timezone") or "Europe/Berlin"
    request.session["user_tz"] = user_tz
    request.session["sidebar_collapsed"] = bool(user.get("sidebar_collapsed"))
    request.session["nav_settings_open"] = bool(user.get("nav_settings_open"))


def _totp_lock_remaining_minutes(user: dict) -> int:
    """Minutes left on an active TOTP lockout, or 0 if not locked."""
    locked_until = user.get("totp_locked_until")
    if not locked_until:
        return 0
    try:
        lock_dt = datetime.datetime.fromisoformat(locked_until)
    except ValueError:
        return 0
    remaining_seconds = (lock_dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    if remaining_seconds <= 0:
        return 0
    return math.ceil(remaining_seconds / 60)


@web.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = await db_one("SELECT * FROM users WHERE username=?", (username.strip(),))
    if not user or not verify_pw(password, user["password_hash"]):
        return RedirectResponse("/login?error=Ungültige+Zugangsdaten", status_code=302)
    if not user.get("active", 1):
        return RedirectResponse("/login?error=Dein+Konto+ist+deaktiviert", status_code=302)
    if user.get("totp_enabled"):
        remaining = _totp_lock_remaining_minutes(user)
        if remaining:
            return RedirectResponse(
                f"/login?error=Zu+viele+Fehlversuche+–+bitte+in+{remaining}+Minute(n)+erneut+versuchen",
                status_code=302,
            )
        request.session["pending_2fa_user_id"] = user["id"]
        return RedirectResponse("/login/2fa", status_code=302)
    await _complete_login(request, user)
    return RedirectResponse("/", status_code=302)


@web.get("/login/2fa", response_class=HTMLResponse)
async def login_2fa_page(request: Request, error: str = ""):
    if not request.session.get("pending_2fa_user_id"):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("login_2fa.html", {
        "request": request, "error": error, "version": VERSION,
    })


@web.post("/login/2fa")
async def login_2fa_submit(request: Request, code: str = Form(...)):
    uid = request.session.get("pending_2fa_user_id")
    if not uid:
        return RedirectResponse("/login", status_code=302)
    user = await db_one("SELECT * FROM users WHERE id=?", (uid,))
    if not user or not user.get("totp_enabled"):
        request.session.pop("pending_2fa_user_id", None)
        return RedirectResponse("/login", status_code=302)

    remaining = _totp_lock_remaining_minutes(user)
    if remaining:
        request.session.pop("pending_2fa_user_id", None)
        return RedirectResponse(
            f"/login?error=Zu+viele+Fehlversuche+–+bitte+in+{remaining}+Minute(n)+erneut+versuchen",
            status_code=302,
        )

    code = code.strip()
    ok = totp.verify_totp(user["totp_secret"], code)
    if not ok:
        backup_rows = await db_rows(
            "SELECT * FROM totp_backup_codes WHERE user_id=? AND used=0", (uid,)
        )
        for row in backup_rows:
            if verify_pw(code.lower(), row["code_hash"]):
                await db_exec("UPDATE totp_backup_codes SET used=1 WHERE id=?", (row["id"],))
                ok = True
                break

    if not ok:
        fail_count = (user.get("totp_fail_count") or 0) + 1
        if fail_count >= 5:
            lock_until = (
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
            ).isoformat()
            await db_exec(
                "UPDATE users SET totp_fail_count=0, totp_locked_until=? WHERE id=?",
                (lock_until, uid),
            )
            request.session.pop("pending_2fa_user_id", None)
            return RedirectResponse(
                "/login?error=Zu+viele+Fehlversuche+–+bitte+in+15+Minute(n)+erneut+versuchen",
                status_code=302,
            )
        await db_exec("UPDATE users SET totp_fail_count=? WHERE id=?", (fail_count, uid))
        return RedirectResponse("/login/2fa?error=Ungültiger+Code", status_code=302)

    if user.get("totp_fail_count"):
        await db_exec("UPDATE users SET totp_fail_count=0, totp_locked_until=NULL WHERE id=?", (uid,))
    request.session.pop("pending_2fa_user_id", None)
    await _complete_login(request, user)
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


@web.post("/profile/ui-state")
async def profile_ui_state_save(
    request: Request,
    sidebar_collapsed: str = Form(None),
    nav_settings_open: str = Form(None),
):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    if sidebar_collapsed is not None:
        val = sidebar_collapsed == "1"
        await db_exec("UPDATE users SET sidebar_collapsed=? WHERE id=?", (int(val), uid))
        request.session["sidebar_collapsed"] = val
    if nav_settings_open is not None:
        val = nav_settings_open == "1"
        await db_exec("UPDATE users SET nav_settings_open=? WHERE id=?", (int(val), uid))
        request.session["nav_settings_open"] = val
    return JSONResponse({"ok": True})


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


@web.get("/profile/2fa/setup", response_class=HTMLResponse)
async def profile_2fa_setup_page(request: Request, error: str = ""):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    user = await db_one("SELECT * FROM users WHERE id=?", (uid,))
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user.get("totp_enabled"):
        return RedirectResponse("/profile", status_code=302)
    secret = request.session.get("pending_totp_secret")
    if not secret:
        secret = totp.generate_secret()
        request.session["pending_totp_secret"] = secret
    uri = totp.provisioning_uri(secret, user["username"])
    return templates.TemplateResponse("profile_2fa_setup.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": await _token_configured(),
        "active": "profile", "secret": secret, "qr": totp.qr_data_uri(uri), "error": error,
    })


@web.post("/profile/2fa/setup")
async def profile_2fa_setup_confirm(request: Request, code: str = Form(...)):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    secret = request.session.get("pending_totp_secret")
    if not secret:
        return RedirectResponse("/profile/2fa/setup", status_code=302)
    if not totp.verify_totp(secret, code):
        return RedirectResponse("/profile/2fa/setup?error=Ungültiger+Code", status_code=302)

    await db_exec(
        "UPDATE users SET totp_secret=?, totp_enabled=1, totp_fail_count=0, totp_locked_until=NULL WHERE id=?",
        (secret, uid),
    )
    request.session.pop("pending_totp_secret", None)
    codes = await _regenerate_backup_codes(uid)
    return templates.TemplateResponse("profile_2fa_backup_codes.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": await _token_configured(),
        "active": "profile", "codes": codes,
    })


async def _regenerate_backup_codes(uid: int) -> list[str]:
    await db_exec("DELETE FROM totp_backup_codes WHERE user_id=?", (uid,))
    codes = totp.generate_backup_codes()
    for c in codes:
        await db_exec(
            "INSERT INTO totp_backup_codes (user_id, code_hash) VALUES (?,?)",
            (uid, hash_pw(c)),
        )
    return codes


@web.post("/profile/2fa/backup-codes/regenerate")
async def profile_2fa_backup_codes_regenerate(request: Request, password: str = Form(...)):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    user = await db_one("SELECT * FROM users WHERE id=?", (uid,))
    if not user or not user.get("totp_enabled"):
        return RedirectResponse("/profile", status_code=302)
    if not verify_pw(password, user["password_hash"]):
        return RedirectResponse("/profile?error=Passwort+falsch", status_code=302)
    codes = await _regenerate_backup_codes(uid)
    return templates.TemplateResponse("profile_2fa_backup_codes.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": await _token_configured(),
        "active": "profile", "codes": codes,
    })


@web.post("/profile/2fa/disable")
async def profile_2fa_disable(request: Request, password: str = Form(...)):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    user = await db_one("SELECT * FROM users WHERE id=?", (uid,))
    if not user or not verify_pw(password, user["password_hash"]):
        return RedirectResponse("/profile?error=Passwort+falsch", status_code=302)
    await db_exec(
        "UPDATE users SET totp_secret=NULL, totp_enabled=0, totp_fail_count=0, totp_locked_until=NULL WHERE id=?",
        (uid,),
    )
    await db_exec("DELETE FROM totp_backup_codes WHERE user_id=?", (uid,))
    return RedirectResponse("/profile?success=Zwei-Faktor-Authentifizierung+deaktiviert", status_code=302)


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
async def avatar_serve(request: Request, user_id: int):
    if r := auth_redirect(request): return r
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
    "birthdays", "warnings", "ticket_panels",
    # Added later than the others - level_roles/level_rewards/automod_word_presets predate
    # ticket_panels being added to this list (v1.7.0) but were never added themselves, meaning
    # a full backup+restore silently dropped every configured level role, level reward, and
    # custom Auto-Mod word-list category with no indication anything was lost.
    "level_roles", "level_rewards", "automod_word_presets",
    # Same gap, same fix, for the AMP gameserver connection (added to the project well after
    # these tables were first audited for this list - never went back and added it). A full or
    # per-server backup/restore silently dropped the entire AMP connection (URL, credentials,
    # command channel) AND every custom per-instance Discord command name, with zero indication
    # anything was lost - particularly relevant for the server-backup feature specifically, since
    # its whole purpose is transferring a server's configuration onto another guild (e.g. the
    # planned hosting model, see phobos_hosting_business_model memory).
    "amp_configs", "amp_instance_commands",
    # Same gap, same fix, for Embed-Nachrichten posts - never added when the feature shipped.
    "embed_posts",
]

# Shared between the full-backup restore (/admin/backup/restore) and the per-server restore
# (/servers/{guild_id}/backup/restore) - was previously defined inline inside backup_restore()
# only, duplicating it for the new per-server path would have let the two drift out of sync.
_BACKUP_TBL_INSERT = {
    # A plain "OR IGNORE" never actually triggered here - reaction_roles had no unique index
    # to ignore against, so restoring the same (or an overlapping) backup more than once
    # silently piled up duplicate rows every time (confirmed live). database.py now backfills
    # a UNIQUE(guild_id,message_id,emoji) index (deduplicating any pre-existing rows first) -
    # this upserts on that instead, matching the semantics of the app-level dedup that
    # rr_add/rr_remove already apply for a live INSERT/UPDATE (v1.7.6).
    "reaction_roles":
        "INSERT INTO reaction_roles (guild_id,channel_id,message_id,emoji,role_id) VALUES (:guild_id,:channel_id,:message_id,:emoji,:role_id) "
        "ON CONFLICT(guild_id,message_id,emoji) DO UPDATE SET channel_id=excluded.channel_id, role_id=excluded.role_id",
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
        "INSERT INTO freestuff_channels (guild_id,channel_id,platforms,deal_max_price,deal_min_discount,deal_channel_id,deal_platforms) VALUES (:guild_id,:channel_id,:platforms,:deal_max_price,:deal_min_discount,:deal_channel_id,:deal_platforms) ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,platforms=excluded.platforms,deal_max_price=excluded.deal_max_price,deal_min_discount=excluded.deal_min_discount,deal_channel_id=excluded.deal_channel_id,deal_platforms=excluded.deal_platforms",
    "birthdays":
        "INSERT OR REPLACE INTO birthdays (user_id,guild_id,birthday) VALUES (:user_id,:guild_id,:birthday)",
    "warnings":
        "INSERT OR IGNORE INTO warnings (user_id,guild_id,moderator_id,reason,timestamp) VALUES (:user_id,:guild_id,:moderator_id,:reason,:timestamp)",
    # status/channel_id/message_id are deliberately NOT restored (left at their table
    # defaults: 'draft' / '' / '') - a backed-up "published" panel could easily point at
    # a Discord message that no longer exists by the time it's restored (channel/message
    # deleted, days or weeks later). Same safety principle as notifications' live=0
    # above: every restored panel comes back as an unpublished draft the admin has to
    # consciously re-publish, rather than risk the bot creating tickets around a message
    # that was never actually re-created.
    "ticket_panels":
        "INSERT INTO ticket_panels (guild_id,name,description,ticket_message,button_label,emoji,support_role_id,category_id) "
        "VALUES (:guild_id,:name,:description,:ticket_message,:button_label,:emoji,:support_role_id,:category_id)",
    "level_roles":
        "INSERT OR IGNORE INTO level_roles (guild_id,level,role_id) VALUES (:guild_id,:level,:role_id)",
    "level_rewards":
        "INSERT OR IGNORE INTO level_rewards (guild_id,level,reward) VALUES (:guild_id,:level,:reward)",
    "automod_word_presets":
        "INSERT INTO automod_word_presets (guild_id,label,words) VALUES (:guild_id,:label,:words)",
    # Credentials ARE included here, deliberately - the same precedent as bot_tokens (the actual
    # Discord bot secret token) above, which is already backed up in full. This project's backup
    # system is a self-hosted admin tool, not a multi-tenant SaaS with per-tenant secrecy
    # boundaries - discord_token/smtp_pass are the ones explicitly excluded elsewhere, and that's
    # for a different reason (single global values meant to be set fresh per install), not a
    # blanket "never back up secrets" rule.
    "amp_configs":
        "INSERT INTO amp_configs (guild_id,label,url,username,password,command_channel_id) "
        "VALUES (:guild_id,:label,:url,:username,:password,:command_channel_id) "
        "ON CONFLICT(guild_id) DO UPDATE SET label=excluded.label, url=excluded.url, "
        "username=excluded.username, password=excluded.password, command_channel_id=excluded.command_channel_id",
    # `prefix` is hardcoded to '' rather than read from the row (same "extra unused dict keys are
    # harmless" pattern already used above for e.g. notifications' `live`) - it's a dead column
    # kept only for schema compatibility (see database.py's migration comment), always ''.
    "amp_instance_commands":
        "INSERT INTO amp_instance_commands (guild_id,instance_id,prefix,start_name,stop_name,restart_name) "
        "VALUES (:guild_id,:instance_id,'',:start_name,:stop_name,:restart_name) "
        "ON CONFLICT(guild_id,instance_id) DO UPDATE SET start_name=excluded.start_name, "
        "stop_name=excluded.stop_name, restart_name=excluded.restart_name",
    # message_id is deliberately NOT restored (left at its table default '') - same reasoning
    # as ticket_panels above: a backed-up post could easily point at a Discord message that no
    # longer exists by restore time. embed_post_update() already knows how to (re)post fresh
    # for a row with an empty message_id, so the very next edit through the dashboard puts a
    # real message behind it instead of silently saving content with nothing live in Discord.
    "embed_posts":
        "INSERT INTO embed_posts (guild_id,name,channel_id,content,image_url,footer_text) "
        "VALUES (:guild_id,:name,:channel_id,:content,:image_url,:footer_text)",
}


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
    scheduled = []
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
        "scheduled_messages": scheduled,
    }
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


async def _build_guild_backup(guild_id: int, exported_by: str) -> dict:
    """Exports just one Discord server's own configuration - no dashboard users, tokens, or
    other guilds' data. Meant to be portable: a restore can target ANY guild the admin
    chooses, not just the one this was exported from, so guild_id is deliberately NOT baked
    into the export as anything other than informational metadata."""
    guild = bot.get_guild(guild_id)
    gid_str = str(guild_id)
    data: dict = {
        "meta": {
            "version": "1.0", "type": "guild",
            "app_version": VERSION,
            "exported_at": datetime.datetime.utcnow().isoformat(),
            "exported_by": exported_by,
            "source_guild_id": gid_str,
            "source_guild_name": guild.name if guild else None,
        },
        "guild_configs": await db_rows(
            "SELECT key, value FROM guild_configs WHERE guild_id=?", (guild_id,)
        ),
        "scheduled_messages": await db_rows(
            "SELECT * FROM scheduled_messages WHERE guild_id=? AND sent=0", (gid_str,)
        ),
    }
    for tbl in _BACKUP_FEATURE_TABLES:
        data[tbl] = await db_rows(f"SELECT * FROM {tbl} WHERE guild_id=?", (gid_str,))
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
        if not isinstance(data, dict):
            # Valid JSON that isn't a JSON *object* (a bare array/string/number/null/bool) -
            # json.loads() succeeds for all of those, so the except above never fires, but the
            # very next line's data.get(...) would then raise an unhandled AttributeError
            # instead of showing the same "not a valid backup" message a parse failure gets.
            raise ValueError("not a JSON object")
    except Exception:
        return RedirectResponse("/users?error=Ungültige+Backup-Datei+(kein+gültiges+JSON)", status_code=302)

    meta = data.get("meta", {})
    if not meta.get("version"):
        return RedirectResponse("/users?error=Kein+gültiges+Phobos-Backup", status_code=302)

    restored: list[str] = []

    async with aiosqlite.connect(DB_PATH) as db:

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
        _restored_presets_guilds: set = set()
        _restored_amp_cmd_guilds: set = set()
        for tbl, sql in _BACKUP_TBL_INSERT.items():
            rows = data.get(tbl, [])
            for row in rows:
                try:
                    # A backup taken before ticket_message existed as its own field won't have
                    # the key at all - the named-parameter INSERT below would otherwise raise
                    # (missing :ticket_message) and silently drop the WHOLE panel, not just the
                    # new field. Same one-time fallback as the DB migration itself: default it
                    # to the panel's existing description instead of losing the row.
                    if tbl == "ticket_panels" and "ticket_message" not in row:
                        row = {**row, "ticket_message": row.get("description", "")}
                    await db.execute(sql, row)
                except Exception:
                    pass
            if rows:
                restored.append(tbl.replace("_", " ").title())
            if tbl == "automod_word_presets" and rows:
                # Unlike the insert loop just above (each row already wrapped in its own
                # try/except), this re-iterates the same list without that protection - a
                # malformed row (not a dict, or missing "guild_id") would otherwise raise here
                # even though the actual insert for that row already failed harmlessly above.
                for row in rows:
                    try:
                        _restored_presets_guilds.add(row["guild_id"])
                    except (TypeError, KeyError):
                        pass
            if tbl == "amp_instance_commands" and rows:
                # Same re-iteration-without-protection caveat as automod_word_presets above -
                # rows already validated by the insert loop, this just collects which guilds to
                # resync afterward. Restored DB rows alone don't make Discord aware of anything -
                # they need an explicit tree.sync(guild=...) call, which resync_guild_commands()
                # does, same as every other write path that touches this table (the dashboard
                # save route, amp_delete_web). Without this, on_ready()'s own auto-resync
                # wouldn't help either: it only fires resync_guild_commands() when
                # ensure_default_commands() actually inserts something NEW - a restored row
                # that already exists for its instance_id means nothing "changed" from its
                # point of view, so the recovered commands would otherwise sit inert in the DB
                # forever, invisible in Discord, until an admin happened to manually re-save
                # that exact instance's command names.
                for row in rows:
                    try:
                        _restored_amp_cmd_guilds.add(row["guild_id"])
                    except (TypeError, KeyError):
                        pass

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

    # auto_delete_channels rows written above bypass the AutoDelete cog's in-memory
    # self._configs cache - without this, a restored config would silently stay inactive
    # until the next bot reconnect (same reload the save/edit/delete routes already trigger).
    if "auto_delete_channels" in data:
        await _reload_auto_delete()

    # Run after the restore transaction above has committed (set_guild_config opens its own
    # connection and commits independently - calling it from inside the still-open `db` block
    # would race against that uncommitted transaction). Without this, a guild that's never
    # opened its Auto-Mod tab before would get the 4 hardcoded starter presets seeded alongside
    # these just-restored ones the first time an admin visits it - server_config()'s seeding
    # check only looks at whether this flag is set, not whether the table already has rows.
    for gid in _restored_presets_guilds:
        await set_guild_config(int(gid), "automod_presets_seeded", "1")

    for gid in _restored_amp_cmd_guilds:
        try:
            guild_bot = bot._bot_for_guild(int(gid))
            amp_cog = guild_bot.cogs.get("AMP") if guild_bot else None
            if amp_cog:
                await amp_cog.resync_guild_commands(int(gid))
        except Exception:
            pass  # best-effort, same as every other post-restore reload here

    summary = ", ".join(restored) if restored else "Nichts"
    return RedirectResponse(
        f"/users?success=Backup+eingespielt:+{urllib.parse.quote(summary)}", status_code=302
    )


@web.get("/servers/{guild_id}/backup")
async def server_backup_export(request: Request, guild_id: int):
    if r := admin_redirect(request): return r
    by = request.session.get("username", "admin")
    data = await _build_guild_backup(guild_id, by)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    guild = bot.get_guild(guild_id)
    # Sanitized for use in a filename - a guild name can contain characters (/, quotes, emoji)
    # that would be awkward or invalid in one, unlike the guild_id fallback which is already
    # filename-safe on its own.
    name_part = re.sub(r"[^\w\-]+", "_", guild.name).strip("_") if guild else str(guild_id)
    return _json_dl(data, f"backup_server_{name_part or guild_id}_{ts}.json")


@web.post("/servers/{guild_id}/backup/restore")
async def server_backup_restore(request: Request, guild_id: int, backup_file: UploadFile = File(...)):
    if r := admin_redirect(request): return r
    try:
        raw = await backup_file.read()
        data = _djson.loads(raw)
        if not isinstance(data, dict):
            # Same guard as backup_restore() above - valid JSON that isn't an object (a bare
            # array/string/number/etc.) would otherwise pass this try/except and crash the
            # next line's data.get(...) with an unhandled AttributeError.
            raise ValueError("not a JSON object")
    except Exception:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=config&error=Ungültige+Backup-Datei+(kein+gültiges+JSON)",
            status_code=302,
        )

    meta = data.get("meta", {})
    if meta.get("type") != "guild":
        # Deliberately strict, not just "does it have a version" like the full-backup restore
        # above - a full/user-type backup's feature-table rows span EVERY guild on the whole
        # platform mixed together with no per-row grouping. Restoring one of those here would
        # silently rewrite the guild_id on ALL of them to this one target guild, merging every
        # other server's tickets/reaction-roles/etc. into it.
        return RedirectResponse(
            f"/servers/{guild_id}?tab=config&error=Das+ist+kein+Server-Backup+(falscher+Typ)",
            status_code=302,
        )

    gid_str = str(guild_id)
    restored: list[str] = []
    restored_presets = False
    restored_amp_cmds = False

    async with aiosqlite.connect(DB_PATH) as db:
        for gc in data.get("guild_configs", []):
            try:
                await db.execute(
                    "INSERT INTO guild_configs (guild_id,key,value) VALUES (?,?,?) "
                    "ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",
                    (guild_id, gc["key"], gc["value"]),
                )
            except Exception:
                pass
        if data.get("guild_configs"):
            restored.append("Server-Konfiguration")

        # Freely portable to any target guild (per explicit product decision) - every row's own
        # guild_id from the export is intentionally ignored and overwritten with the URL's
        # guild_id instead, rather than trusting whatever the file says. Reuses the exact same
        # INSERT statements as the full-backup restore (_BACKUP_TBL_INSERT) so the two restore
        # paths can't drift apart on how a given table is handled.
        for tbl, sql in _BACKUP_TBL_INSERT.items():
            rows = data.get(tbl, [])
            for row in rows:
                try:
                    # The dict-spread has to be inside this try, not before it - a malformed
                    # backup file with a non-object entry in this list (a bare string/number)
                    # would otherwise raise an unhandled TypeError right here ({**row, ...}
                    # requires a mapping) instead of just skipping that one bad row like every
                    # other malformed-row case in this loop already does.
                    merged = {**row, "guild_id": gid_str}
                    if tbl == "ticket_panels" and "ticket_message" not in row:
                        # Same pre-ticket_message backup fallback as the full-backup restore
                        # path above - default to the existing description instead of losing
                        # the whole panel to a missing named parameter.
                        merged["ticket_message"] = row.get("description", "")
                    await db.execute(sql, merged)
                except Exception:
                    pass
            if rows:
                restored.append(tbl.replace("_", " ").title())
            if tbl == "automod_word_presets" and rows:
                restored_presets = True
            if tbl == "amp_instance_commands" and rows:
                restored_amp_cmds = True

        await db.commit()

    if "auto_delete_channels" in data:
        await _reload_auto_delete()
    if restored_presets:
        # Same fix as the full-backup restore above - without it, this guild would get the 4
        # hardcoded starter presets seeded alongside these just-restored ones the first time
        # its Auto-Mod tab is opened, if it's never been opened before.
        await set_guild_config(guild_id, "automod_presets_seeded", "1")
    if restored_amp_cmds:
        # Same reasoning as the full-backup restore above - restored rows alone don't register
        # anything with Discord, they need an explicit guild-command resync.
        try:
            guild_bot = bot._bot_for_guild(guild_id)
            amp_cog = guild_bot.cogs.get("AMP") if guild_bot else None
            if amp_cog:
                await amp_cog.resync_guild_commands(guild_id)
        except Exception:
            pass

    summary = ", ".join(restored) if restored else "Nichts"
    return RedirectResponse(
        f"/servers/{guild_id}?tab=config&success=Server-Backup+eingespielt:+{urllib.parse.quote(summary)}",
        status_code=302,
    )


# ── Password Reset ─────────────────────────────────────────────────────────────

async def _send_reset_email(to_addr: str, reset_url: str):
    host = await get_config("smtp_host") or ""
    try:
        port = int(await get_config("smtp_port") or 587)
    except (ValueError, TypeError):
        # smtp_settings_save validates this now, but a value saved before that guard existed
        # could still be sitting in the DB - same defense-in-depth already applied elsewhere
        # in the project for config values that are validated at save time but read unguarded.
        port = 587
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
    if r := admin_redirect(request): return r
    if token.strip():
        await set_config("discord_token", token.strip())
    return RedirectResponse("/settings?saved=true", status_code=303)


@web.post("/settings/timezone")
async def settings_timezone_save(request: Request, timezone: str = Form(...)):
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r
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
    all_users = await db_rows("SELECT id, username, role, email, created_at, active FROM users ORDER BY created_at")
    token_set = await _token_configured()
    admin_count = sum(1 for u in all_users if u["role"] == "admin")
    all_guilds = [{"id": str(g.id), "name": g.name} for g in bot.guilds]
    perm_rows = await db_rows("SELECT user_id, guild_id FROM user_guild_permissions")
    user_perms: dict[int, set] = {}
    for p in perm_rows:
        user_perms.setdefault(p["user_id"], set()).add(str(p["guild_id"]))
    return templates.TemplateResponse("users.html", {
        **session(request), "request": request,
        "users": all_users, "error": error, "success": success,
        "guilds": await _guild_list(request), "token_set": token_set, "active": "users",
        "admin_count": admin_count,
        "all_guilds": all_guilds,
        "user_perms": user_perms,
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


def _proc_stats():
    """Fallback for get_system_stats() when psutil isn't available (Android/Chaquopy has no
    prebuilt wheel and no C toolchain to build it) - reads the same /proc files psutil itself
    reads on Linux under the hood, so this is genuine system data, not an approximation. Returns
    None if /proc isn't readable (SELinux policy on some Android builds/versions could plausibly
    block even these aggregate, no-other-app-info files - degrades to the 0-fallback if so)."""
    try:
        meminfo = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            meminfo[key] = int(rest.strip().split()[0])  # value is in kB
        total_kb = meminfo["MemTotal"]
        # MemAvailable is the modern, accurate "how much can actually be freed for use" figure
        # (kernel 3.14+) - MemFree alone undercounts reclaimable cache/buffers as "used".
        avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        used_kb = total_kb - avail_kb

        def _cpu_sample():
            fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
            nums = [int(x) for x in fields]
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)  # idle + iowait
            return sum(nums), idle

        total1, idle1 = _cpu_sample()
        time.sleep(0.1)
        total2, idle2 = _cpu_sample()
        total_delta = total2 - total1
        cpu_pct = round((1 - (idle2 - idle1) / total_delta) * 100, 1) if total_delta > 0 else 0

        rss_kb = 0
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                rss_kb = int(line.split()[1])
                break

        return {
            "cpu": cpu_pct,
            "ram_used": used_kb // 1024,
            "ram_total": total_kb // 1024,
            "ram_pct": round(used_kb / total_kb * 100, 1) if total_kb else 0,
            "proc_ram": rss_kb // 1024,
        }
    except Exception:
        return None


def _os_display_string() -> str:
    # platform.system()/release() report the LINUX KERNEL underneath Android (e.g. "Linux
    # 3.18.19"), which is technically accurate but reads like some ancient generic Linux distro
    # rather than "this is a phone" - confusing on the Bot-Info page (confirmed live: exactly
    # this confusion, on exactly this device). Chaquopy exposes the real Android APIs via its
    # `java` bridge module (not importable outside Chaquopy, hence the local import + IS_ANDROID
    # gate) - android.os.Build.VERSION.RELEASE is the actual Android version string ("6.0" etc.).
    if IS_ANDROID:
        try:
            from java import jclass
            version = jclass("android.os.Build$VERSION").RELEASE
            return f"Android {version}"
        except Exception:
            return "Android"
    return f"{platform.system()} {platform.release()}"


def get_system_stats() -> dict:
    uptime = datetime.datetime.utcnow() - PROCESS_START
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s = divmod(rem, 60)

    # 0 rather than None for all four - the template does numeric comparisons/min() on these
    # (e.g. `{% if stats.cpu > 80 %}`) that would raise on None instead of just rendering "0%".
    cpu = ram_used = ram_total = ram_pct = proc_ram = 0
    if psutil:
        proc = psutil.Process()
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
        cpu = psutil.cpu_percent(interval=0.1)
        proc_ram = proc.memory_info().rss // (1024 ** 2)
    else:
        fallback = _proc_stats()
        if fallback:
            cpu, ram_used, ram_total, ram_pct, proc_ram = (
                fallback["cpu"], fallback["ram_used"], fallback["ram_total"],
                fallback["ram_pct"], fallback["proc_ram"],
            )

    return {
        "cpu": cpu,
        "ram_used": ram_used,
        "ram_total": ram_total,
        "ram_pct": ram_pct,
        "proc_ram": proc_ram,
        "uptime": f"{h}h {m}m {s}s",
        "latency": round(bot.latency * 1000, 1) if bot.is_ready() else None,
        "guild_count": len(bot.guilds),
        "member_count": sum(g.member_count or 0 for g in bot.guilds),
        "hostname": platform.node(),
        "os": _os_display_string(),
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
    try:
        target = bot._bot_for_guild(int(guild_id)) if guild_id else None
    except (ValueError, TypeError):
        target = None
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
        "enabled_features": await _get_enabled_features(guild_id) if guild_id else None,
    })


@web.post("/bot/design")
async def bot_design_save(
    request: Request,
    bot_name: str = Form(""),
    guild_id: str = Form(""),
    avatar: UploadFile = File(None),
):
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r
    try:
        target = bot._bot_for_guild(int(guild_id)) if guild_id else None
    except (ValueError, TypeError):
        target = None
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
        return RedirectResponse(f"{redirect_base}&error={urllib.parse.quote(str(e)[:80])}", status_code=302)
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


@web.get("/bot/info/stats")
async def bot_info_stats(request: Request):
    if r := auth_redirect(request): return r
    return JSONResponse(get_system_stats())


# ── Update Check ──────────────────────────────────────────────────────────────

_UPDATE_CACHE: dict = {"latest": None, "at": None}
# The GitHub Contents API is used instead of raw.githubusercontent.com because the latter
# sits behind a CDN that caches responses for up to 5 minutes REGARDLESS of query strings
# (a cache-busting ?t=... param does not defeat it, verified directly) - with this project's
# frequent version bumps, the update check could stay stuck on a stale VERSION for minutes
# after every single push. The Contents API caches for only 60s and reflects new commits fast.
_GITHUB_VERSION_URL = "https://api.github.com/repos/LucyWolf/phobos-bot/contents/app/VERSION?ref=main"


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
            req = urllib.request.Request(
                _GITHUB_VERSION_URL,
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = _djson.loads(r.read().decode())
            return base64.b64decode(data["content"]).decode().strip()
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
    if r := admin_redirect(request): return r
    token_set = await _token_configured()
    latest = await check_latest_version()
    update_available = bool(latest and _ver_tuple(latest) > _ver_tuple(VERSION))
    return templates.TemplateResponse("bot_update.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": "bot_update",
        "current_version": VERSION, "latest_version": latest,
        "update_available": update_available,
        "is_android": IS_ANDROID,
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
const IS_ANDROID = __IS_ANDROID__;
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

// Android: the OLD server doesn't go down on its own the instant the download finishes - it
// keeps serving this exact page until the user actually confirms the install dialog and the OS
// replaces the app. So "reachable" right now doesn't mean anything yet; this waits to actually
// SEE the old process die first, and only treats a later reachable ping (the NEW build coming
// back up) as the real "update finished" signal - otherwise it'd redirect immediately, before
// the user has even tapped Install.
let androidSawDown = false;
let androidTries = 0;
function waitForAndroidRestart() {
  fetch('/ping', {cache:'no-store'})
    .then(r => r.json())
    .then(d => {
      if (d.ok && androidSawDown) {
        addLine('✅  Neue Version läuft – weiterleiten…', 'ok');
        setTimeout(() => { window.location = '/'; }, 1500);
        return;
      }
      if (!d.ok) androidSawDown = true;
      androidRetry();
    })
    .catch(() => { androidSawDown = true; androidRetry(); });
}
function androidRetry() {
  androidTries++;
  if (!androidSawDown) {
    hint.textContent = '📲  Installationsdialog sollte auf dem Handy erschienen sein – bitte dort bestätigen.';
  } else {
    hint.textContent = 'Warte auf Neustart der App auf dem Handy… (' + androidTries + ')';
    if (androidTries % 10 === 0) {
      addLine('  ⏳  Alte Version beendet – App auf dem Handy öffnen und "Start Bot" tippen, falls nötig.', 'info');
    }
  }
  if (androidTries < 300) setTimeout(waitForAndroidRestart, 2500);
  else { addLine('❌  Timeout – App auf dem Handy öffnen und manuell starten.', 'err'); spin.style.display='none'; }
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
        if (IS_ANDROID) {
          hint.textContent = '📲  Installationsdialog sollte gleich auf dem Handy erscheinen – bitte dort bestätigen.';
          setTimeout(waitForAndroidRestart, 2500);
        } else {
          setTimeout(waitForServer, 8000);
        }
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
        if (IS_ANDROID) {
          androidSawDown = true;
          setTimeout(waitForAndroidRestart, 2500);
        } else {
          setTimeout(waitForServer, 8000);
        }
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


# The release TAG stays fixed forever (deliberately not tied to a bot version, to avoid exactly
# the confusion an earlier "android-v1.6.16-debug" tag name caused) while its one asset gets
# replaced on every Android-related commit - see CLAUDE.md/android/README.md history - so this
# URL never needs updating even as VERSION keeps climbing. Public repo, no auth needed.
_ANDROID_APK_URL = (
    "https://github.com/LucyWolf/phobos-bot/releases/download/"
    "android-debug/phobos-bot.apk"
)


def _reap_stray_zombies():
    """Best-effort, non-blocking cleanup for any child process that has already exited but was
    never waited on. This process runs as PID 1 inside the container (no init system like tini
    - confirmed live via `docker exec ... cat /proc/1/cmdline`, it's directly `python main.py`)
    - PID 1 is responsible for reaping EVERY one of its children, including ones it never
    explicitly tracked itself (e.g. a helper process `git` spawns internally for an HTTPS
    fetch, which becomes an orphan reparented to PID 1 if it outlives git's own exit - asyncio's
    subprocess machinery only reaps the exact PID it launched via create_subprocess_exec, it has
    no way to know about such a grandchild). Confirmed live: 70 stray zombie `git` processes had
    accumulated across this project's many update cycles in one long session, all with comm=git
    and an already-empty cmdline (the telltale sign of an unreaped, already-exited child) -
    os.waitpid(-1, os.WNOHANG) reaps ALL of this process's exited children in one sweep,
    regardless of whether _run() below was the one that spawned them. Non-blocking (WNOHANG)
    so it only ever cleans up processes that already exited, never waits on a still-running one."""
    try:
        while True:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
    except ChildProcessError:
        pass  # no children at all left to reap


async def _do_git_update():
    global _update_status, _update_running
    _update_status = {"logs": [], "done": False, "error": ""}
    _reap_stray_zombies()  # clean up anything left over from earlier update runs first

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
        rc = await proc.wait()
        _reap_stray_zombies()
        return rc

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
    finally:
        _update_running = False


async def _do_android_update():
    global _update_status, _update_running
    _update_status = {"logs": [], "done": False, "error": ""}

    def _download():
        req = urllib.request.Request(_ANDROID_APK_URL, headers={"User-Agent": "phobos-bot"})
        tmp_path = DATA_DIR / "update.apk.part"
        apk_path = DATA_DIR / "update.apk"
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            written = 0
            last_pct = -1
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
                    if total:
                        pct = (written * 100) // total
                        if pct != last_pct and pct % 10 == 0:
                            _ulog(f"  {pct}%  ({written // 1024}KB / {total // 1024}KB)", "progress")
                            last_pct = pct
            if total and written != total:
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError(f"Download unvollständig ({written}/{total} Bytes)")
        # Renamed into place only once fully written - MainActivity's poll loop watches for
        # update.apk specifically, so a half-downloaded file (still named .part) never
        # accidentally triggers an install of a broken APK.
        tmp_path.rename(apk_path)
        return written

    try:
        _ulog("$ phobos-bot android-update — " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "cmd")
        _ulog(f"$ curl -L -o update.apk {_ANDROID_APK_URL}", "cmd")
        size = await asyncio.get_event_loop().run_in_executor(None, _download)
        _ulog(f"  ✓  {size // 1024}KB heruntergeladen", "ok")
        _ulog("  📲  Installationsdialog wird auf dem Handy geöffnet…", "restart")
        _update_status["done"] = True
    except Exception as e:
        _ulog(f"❌  Fehler: {e}", "err")
        _update_status["error"] = str(e)[:300]
    finally:
        _update_running = False


_update_running = False


@web.post("/bot/update/apply")
async def bot_update_apply(request: Request):
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r

    # Without this, a double-click (or two people hitting "Jetzt updaten" on two devices at
    # once) starts two concurrent updates that both reassign the shared `_update_status` global
    # at the top of _do_git_update()/_do_android_update() - the second reassignment would
    # silently swallow the first update's in-flight progress/done/error state, corrupting what
    # gets shown to whichever page is still polling it. A second click while one is already
    # running just re-attaches to the same in-progress update instead of starting a new one.
    global _update_running
    if not _update_running:
        _update_running = True
        if IS_ANDROID:
            asyncio.create_task(_do_android_update())
        else:
            asyncio.create_task(_do_git_update())
    html = _UPDATE_IN_PROGRESS_HTML.replace("__IS_ANDROID__", "true" if IS_ANDROID else "false")
    return HTMLResponse(html)


# ── AMP Gameserver ────────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/amp/save")
async def amp_save(
    request: Request, guild_id: int,
    label: str = Form(""), url: str = Form(""),
    username: str = Form(""), password: str = Form(""),
    command_channel_id: str = Form(""),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    url = url.strip().rstrip("/")
    if url and not (url.startswith("http://") or url.startswith("https://")):
        return RedirectResponse(
            f"/servers/{guild_id}?tab=amp&error=URL+muss+mit+http://+oder+https://+beginnen", status_code=302
        )
    if not url or not username.strip():
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=URL+und+Nutzername+erforderlich", status_code=302)
    command_channel_id = command_channel_id.strip()
    if command_channel_id and command_channel_id not in {str(c.id) for c in guild.text_channels}:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Ungültiger+Kanal", status_code=302)
    # A blank password field means "keep the existing one" (same convention as SMTP/Twitch
    # credential forms elsewhere) - only overwrite it if the admin actually typed something,
    # so re-saving the label/URL doesn't silently wipe out a previously stored password.
    existing = await db_one("SELECT password FROM amp_configs WHERE guild_id=?", (str(guild_id),))
    final_password = password.strip() or (existing["password"] if existing else "")
    await db_exec(
        "INSERT INTO amp_configs (guild_id,label,url,username,password,command_channel_id) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET label=excluded.label, url=excluded.url, "
        "username=excluded.username, password=excluded.password, command_channel_id=excluded.command_channel_id",
        (str(guild_id), label.strip(), url, username.strip(), final_password, command_channel_id),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=amp&success=Gespeichert", status_code=302)


async def _amp_cfg_for_guild(guild_id: int):
    return await db_one("SELECT * FROM amp_configs WHERE guild_id=?", (str(guild_id),))


# Maps cogs.amp.AMP_APP_STATES's category keys to their translated dashboard label - kept here
# (not in the cog) since it needs i18n's tr dict, which the cog has no access to.
# Just 4 broad stages now (was 14 in v1.14.19-23, collapsed per explicit request - see
# cogs.amp.AMP_APP_STATES's comment for why finer-grained AppState detail turned out unreliable).
_AMP_STATE_TR_KEYS = {
    "online": "amp_status_online", "offline": "amp_status_offline",
    "busy": "amp_status_busy", "error": "amp_status_error_state",
}


def _amp_state_label(state: str, tr: dict) -> str:
    return tr.get(_AMP_STATE_TR_KEYS.get(state, "amp_status_offline"), state)


@web.post("/servers/{guild_id}/amp/start")
async def amp_start_web(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    cfg = await _amp_cfg_for_guild(guild_id)
    if not cfg or not cfg.get("url"):
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Kein+Gameserver+verknüpft", status_code=302)
    amp_cog = bot.cogs.get("AMP")
    if not amp_cog:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Bot+nicht+verbunden", status_code=302)
    ok, error = await amp_cog._set_running(cfg, start=True)
    if not ok:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error={urllib.parse.quote(error[:150])}", status_code=302)
    return RedirectResponse(f"/servers/{guild_id}?tab=amp&success=Startbefehl+gesendet", status_code=302)


@web.post("/servers/{guild_id}/amp/stop")
async def amp_stop_web(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    cfg = await _amp_cfg_for_guild(guild_id)
    if not cfg or not cfg.get("url"):
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Kein+Gameserver+verknüpft", status_code=302)
    amp_cog = bot.cogs.get("AMP")
    if not amp_cog:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Bot+nicht+verbunden", status_code=302)
    ok, error = await amp_cog._set_running(cfg, start=False)
    if not ok:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error={urllib.parse.quote(error[:150])}", status_code=302)
    return RedirectResponse(f"/servers/{guild_id}?tab=amp&success=Stoppbefehl+gesendet", status_code=302)


@web.post("/servers/{guild_id}/amp/restart")
async def amp_restart_web(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    cfg = await _amp_cfg_for_guild(guild_id)
    if not cfg or not cfg.get("url"):
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Kein+Gameserver+verknüpft", status_code=302)
    amp_cog = bot.cogs.get("AMP")
    if not amp_cog:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Bot+nicht+verbunden", status_code=302)
    ok, error = await amp_cog._restart(cfg)
    if not ok:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error={urllib.parse.quote(error[:150])}", status_code=302)
    return RedirectResponse(f"/servers/{guild_id}?tab=amp&success=Neustart-Befehl+gesendet", status_code=302)


@web.post("/servers/{guild_id}/amp/delete")
async def amp_delete_web(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM amp_configs WHERE guild_id=?", (str(guild_id),))
    had_custom_commands = await db_exec_rowcount(
        "DELETE FROM amp_instance_commands WHERE guild_id=?", (str(guild_id),)
    )
    if had_custom_commands:
        # Removes any custom /prefix-* commands this guild had - otherwise they'd linger,
        # pointing at a connection that no longer exists.
        guild_bot = bot._bot_for_guild(guild_id)
        amp_cog = guild_bot.cogs.get("AMP") if guild_bot else None
        if amp_cog:
            await amp_cog.resync_guild_commands(guild_id)
    return RedirectResponse(f"/servers/{guild_id}?tab=amp&success=Verbindung+gelöscht", status_code=302)


@web.post("/servers/{guild_id}/amp/instance/{instance_id}/command-name")
async def amp_instance_command_name(
    request: Request, guild_id: int, instance_id: str,
    start_name: str = Form(""), stop_name: str = Form(""), restart_name: str = Form(""),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild_bot = bot._bot_for_guild(guild_id)
    amp_cog = guild_bot.cogs.get("AMP") if guild_bot else None
    if not amp_cog:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Bot+nicht+verbunden", status_code=302)
    cfg = await _amp_cfg_for_guild(guild_id)
    if cfg and cfg.get("url"):
        # Same "cfg exists but url could theoretically be empty" guard every other _amp_cfg_
        # for_guild() caller in this file applies (e.g. amp_start_web right below) - normal
        # dashboard usage can never produce such a row (amp_save() rejects an empty URL before
        # ever writing one), but a crafted/corrupted backup restore could (the amp_configs
        # insert in _BACKUP_TBL_INSERT doesn't itself re-validate non-empty). This route was the
        # one place still checking bare `if cfg:` instead.
        is_ads, conn_error = await _amp_is_ads_instance(amp_cog, cfg, instance_id)
        if conn_error:
            # Fail CLOSED here, unlike the action routes below (which just show the connection
            # error and stop, nothing gets persisted either way): this specific check exists
            # because a saved custom command is a PERSISTENT way to later trigger an action
            # against whatever instance_id it names - if AMP can't be reached right now to
            # confirm this instance_id isn't the ADS's own, saving anyway would let exactly the
            # unsafe case through unverified, armed and waiting for the connection to come back.
            return RedirectResponse(f"/servers/{guild_id}?tab=amp&error={urllib.parse.quote(conn_error[:150])}", status_code=302)
        if is_ads:
            # Same reasoning as above, just for the confirmed (not merely unverifiable) case - a
            # custom command saved against the ADS's own instance_id would be a PERSISTENT way to
            # trigger an unverified action against it (worse than a one-off crafted POST to
            # /start etc., since it'd sit there as a real slash command anyone with manage_guild
            # could use going forward).
            return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Nicht+erlaubt", status_code=302)

    validated = {}
    for field, raw in (("start_name", start_name), ("stop_name", stop_name), ("restart_name", restart_name)):
        raw = raw.strip()
        if not raw:
            validated[field] = ""
            continue
        valid = amp_cog._valid_command_name(raw)
        if not valid:
            return RedirectResponse(
                f"/servers/{guild_id}?tab=amp&error=Ungültiger+Befehlsname+(nur+a-z,+0-9,+-,+_,+max.+32+Zeichen)",
                status_code=302,
            )
        validated[field] = valid

    # A plain per-column UNIQUE index can't express "unique across any of these 3 columns, for
    # any instance in this guild" - checked here instead. Own three values must also not
    # collide with each other (e.g. the same name typed for both start and stop).
    new_names = [v for v in validated.values() if v]
    if len(new_names) != len(set(new_names)):
        return RedirectResponse(
            f"/servers/{guild_id}?tab=amp&error=Die+drei+Befehlsnamen+müssen+sich+voneinander+unterscheiden",
            status_code=302,
        )
    if new_names:
        other_rows = await db_rows(
            "SELECT start_name, stop_name, restart_name FROM amp_instance_commands "
            "WHERE guild_id=? AND instance_id!=?",
            (str(guild_id), instance_id),
        )
        used = {row[col] for row in other_rows for col in ("start_name", "stop_name", "restart_name") if row[col]}
        if used & set(new_names):
            return RedirectResponse(
                f"/servers/{guild_id}?tab=amp&error=Befehlsname+wird+bereits+von+einer+anderen+Instanz+genutzt",
                status_code=302,
            )

    if not any(validated.values()):
        await db_exec(
            "DELETE FROM amp_instance_commands WHERE guild_id=? AND instance_id=?",
            (str(guild_id), instance_id),
        )
    else:
        await db_exec(
            "INSERT INTO amp_instance_commands (guild_id, instance_id, prefix, start_name, stop_name, restart_name) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(guild_id, instance_id) DO UPDATE SET "
            "start_name=excluded.start_name, stop_name=excluded.stop_name, restart_name=excluded.restart_name",
            (str(guild_id), instance_id, "", validated["start_name"], validated["stop_name"], validated["restart_name"]),
        )
    await amp_cog.resync_guild_commands(guild_id)
    return RedirectResponse(f"/servers/{guild_id}?tab=amp&success=Befehlsnamen+gespeichert", status_code=302)


@web.get("/servers/{guild_id}/amp/instances.json")
async def amp_instances_json(request: Request, guild_id: int):
    # Polled client-side (see server_config.html's amp tab) so a game's status tile updates
    # live in place without the admin having to manually reload the whole page to see the
    # current state.
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return JSONResponse({"instances": []}, status_code=403)
    cfg = await _amp_cfg_for_guild(guild_id)
    amp_cog = bot.cogs.get("AMP")
    if not cfg or not cfg.get("url") or not amp_cog:
        return JSONResponse({"instances": []})
    listing = await amp_cog._list_instances(cfg)
    tr = get_tr(request.session.get("lang", "de"))
    return JSONResponse({"instances": [
        {"id": i["id"], "color": i["color"], "label": _amp_state_label(i["state"], tr), "app_state": i["app_state"]}
        for i in listing["instances"]
    ]})


async def _amp_is_ads_instance(amp_cog, cfg: dict, instance_id: str) -> tuple[bool, str | None]:
    """Returns (is_ads, connection_error). The template never renders Start/Stop/Restart forms
    for the ADS controller's own tile (game_instances excludes module=='ADS'), and the Discord
    command path excludes it too via _resolve_target() - but that's UI/command-layer protection
    only. A hand-crafted POST straight to these three routes could still target the ADS's own
    instance_id, and ADSModule's {method}Instance calls were never verified to make sense
    against the ADS's own instance name (unlike a real game instance) - worst case it could
    affect the whole AMP connection for every hosted game at once. Checked here too so that
    safety guarantee doesn't depend on the admin only ever clicking the rendered buttons.
    connection_error is surfaced separately (rather than just treating a failed lookup as
    "not the ADS, proceed") so callers can bail out immediately with the real error instead of
    proceeding to _instance_action(), which would then make its own, equally doomed second
    login attempt against a connection that's already known to be down - the same "two round
    trips feels like the bot is hanging" issue fixed for cogs/amp.py's Discord command path in
    the same v1.14.47 round this was found in."""
    listing = await amp_cog._list_instances(cfg)
    if listing.get("connection_error"):
        return False, listing["error"]
    match = next((i for i in listing["instances"] if i["id"] == instance_id), None)
    return bool(match and match.get("module") == "ADS"), None


@web.post("/servers/{guild_id}/amp/instance/{instance_id}/start")
async def amp_instance_start_web(request: Request, guild_id: int, instance_id: str, instance_name: str = Form("")):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    cfg = await _amp_cfg_for_guild(guild_id)
    if not cfg or not cfg.get("url"):
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Kein+Gameserver+verknüpft", status_code=302)
    amp_cog = bot.cogs.get("AMP")
    if not amp_cog:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Bot+nicht+verbunden", status_code=302)
    is_ads, conn_error = await _amp_is_ads_instance(amp_cog, cfg, instance_id)
    if conn_error:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error={urllib.parse.quote(conn_error[:150])}", status_code=302)
    if is_ads:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Nicht+erlaubt", status_code=302)
    ok, error = await amp_cog._instance_action(cfg, instance_name, "Start")
    if not ok:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error={urllib.parse.quote(error[:150])}", status_code=302)
    return RedirectResponse(f"/servers/{guild_id}?tab=amp&success=Startbefehl+gesendet", status_code=302)


@web.post("/servers/{guild_id}/amp/instance/{instance_id}/stop")
async def amp_instance_stop_web(request: Request, guild_id: int, instance_id: str, instance_name: str = Form("")):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    cfg = await _amp_cfg_for_guild(guild_id)
    if not cfg or not cfg.get("url"):
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Kein+Gameserver+verknüpft", status_code=302)
    amp_cog = bot.cogs.get("AMP")
    if not amp_cog:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Bot+nicht+verbunden", status_code=302)
    is_ads, conn_error = await _amp_is_ads_instance(amp_cog, cfg, instance_id)
    if conn_error:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error={urllib.parse.quote(conn_error[:150])}", status_code=302)
    if is_ads:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Nicht+erlaubt", status_code=302)
    ok, error = await amp_cog._instance_action(cfg, instance_name, "Stop")
    if not ok:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error={urllib.parse.quote(error[:150])}", status_code=302)
    return RedirectResponse(f"/servers/{guild_id}?tab=amp&success=Stoppbefehl+gesendet", status_code=302)


@web.post("/servers/{guild_id}/amp/instance/{instance_id}/restart")
async def amp_instance_restart_web(request: Request, guild_id: int, instance_id: str, instance_name: str = Form("")):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    cfg = await _amp_cfg_for_guild(guild_id)
    if not cfg or not cfg.get("url"):
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Kein+Gameserver+verknüpft", status_code=302)
    amp_cog = bot.cogs.get("AMP")
    if not amp_cog:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Bot+nicht+verbunden", status_code=302)
    is_ads, conn_error = await _amp_is_ads_instance(amp_cog, cfg, instance_id)
    if conn_error:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error={urllib.parse.quote(conn_error[:150])}", status_code=302)
    if is_ads:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error=Nicht+erlaubt", status_code=302)
    ok, error = await amp_cog._instance_action(cfg, instance_name, "Restart")
    if not ok:
        return RedirectResponse(f"/servers/{guild_id}?tab=amp&error={urllib.parse.quote(error[:150])}", status_code=302)
    return RedirectResponse(f"/servers/{guild_id}?tab=amp&success=Neustart-Befehl+gesendet", status_code=302)


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
        "enabled_features": await _get_enabled_features(guild_id),
    })


DEAL_PLATFORMS = {"steam", "gog", "humble", "fanatical", "gmg"}  # only ones with a CheapShark price API


@web.post("/servers/{guild_id}/freestuff/save")
async def freestuff_save(
    request: Request, guild_id: str,
    channel_id: str = Form(""),
    platforms: List[str] = Form(default=[]),
    deal_max_price: str = Form(""),
    deal_min_discount: str = Form("75"),
    deal_channel_id: str = Form(""),
    deal_platforms: List[str] = Form(default=[]),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    valid_channel_ids = {str(c.id) for c in guild.text_channels}
    if channel_id and channel_id not in valid_channel_ids:
        return RedirectResponse(f"/servers/{guild_id}/freestuff?error=Ungültiger+Kanal", status_code=302)
    if deal_channel_id and deal_channel_id not in valid_channel_ids:
        return RedirectResponse(f"/servers/{guild_id}/freestuff?error=Ungültiger+Deal-Kanal", status_code=302)

    valid = {"epic", "steam", "gog", "humble", "fanatical", "gmg", "ea", "ubisoft", "battlenet", "itchio"}
    plat_str = ",".join(p for p in platforms if p in valid)
    if not plat_str:
        plat_str = "epic"
    try:
        max_price = float(deal_max_price.replace(",", ".")) if deal_max_price.strip() else None
    except ValueError:
        max_price = None
    try:
        min_disc = max(0, min(100, int(deal_min_discount or 75)))
    except ValueError:
        min_disc = 75
    deal_ch = deal_channel_id if deal_channel_id else None
    deal_plat_str = ",".join(p for p in deal_platforms if p in DEAL_PLATFORMS)
    if deal_ch and max_price and not deal_plat_str:
        # A deal channel + max price alone don't do anything without at least one selected
        # platform (check_loop only fetches deals for platforms actually in deal_platforms) -
        # the platform checkboxes start unchecked by design (v1.4.26), so this is an easy
        # trap to fall into: saving would otherwise silently produce a config the dashboard
        # status line shows as "active" while it never actually posts anything.
        return RedirectResponse(
            f"/servers/{guild_id}/freestuff?error=Bitte+mindestens+eine+Angebots-Plattform+wählen",
            status_code=302,
        )
    await db_exec(
        """INSERT INTO freestuff_channels
               (guild_id, channel_id, platforms, deal_max_price, deal_min_discount, deal_channel_id, deal_platforms)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(guild_id) DO UPDATE SET
               channel_id=excluded.channel_id,
               platforms=excluded.platforms,
               deal_max_price=excluded.deal_max_price,
               deal_min_discount=excluded.deal_min_discount,
               deal_channel_id=excluded.deal_channel_id,
               deal_platforms=excluded.deal_platforms""",
        (guild_id, channel_id, plat_str, max_price, min_disc, deal_ch, deal_plat_str),
    )
    return RedirectResponse(f"/servers/{guild_id}/freestuff?success=Gespeichert", status_code=302)


@web.post("/servers/{guild_id}/freestuff/test")
async def freestuff_test(request: Request, guild_id: str):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    cfg = await db_one("SELECT * FROM freestuff_channels WHERE guild_id=?", (guild_id,))
    if not cfg or not cfg.get("channel_id"):
        return RedirectResponse(
            f"/servers/{guild_id}/freestuff?error=Gratis-Spiele-Kanal+nicht+konfiguriert", status_code=302
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
async def auto_delete_save(request: Request, guild_id: str, channel_id: str = Form(""), delay_seconds: str = Form("")):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(int(guild_id))
    if not guild or channel_id not in {str(c.id) for c in guild.text_channels}:
        return RedirectResponse(f"/servers/{guild_id}?tab=autodelete&error=Ungültiger+Kanal", status_code=302)
    try:
        delay_int = int(delay_seconds)
    except (ValueError, TypeError):
        delay_int = 0
    if delay_int <= 0:
        # Used to silently save nothing here while still reporting "Gespeichert" — an
        # empty/invalid/zero delay is a form mistake, not a valid setting, so say so instead
        # of pretending it worked. (Turning an *existing* entry off has its own ✕ button
        # in the table above — this form is only for adding a new channel.)
        return RedirectResponse(
            f"/servers/{guild_id}?tab=autodelete&error=Ungültige+Verzögerung", status_code=302
        )
    await db_exec(
        "INSERT INTO auto_delete_channels (guild_id, channel_id, delay_seconds) VALUES (?,?,?) "
        "ON CONFLICT(guild_id, channel_id) DO UPDATE SET delay_seconds=excluded.delay_seconds",
        (guild_id, channel_id, delay_int),
    )
    await _reload_auto_delete()
    return RedirectResponse(f"/servers/{guild_id}?tab=autodelete&success=Gespeichert", status_code=302)

@web.post("/servers/{guild_id}/auto-delete/edit/{entry_id}")
async def auto_delete_edit(request: Request, guild_id: str, entry_id: int, channel_id: str = Form(""), delay_seconds: str = Form("")):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(int(guild_id))
    if not guild or channel_id not in {str(c.id) for c in guild.text_channels}:
        return RedirectResponse(f"/servers/{guild_id}?tab=autodelete&error=Ungültiger+Kanal", status_code=302)
    try:
        delay_int = int(delay_seconds)
    except (ValueError, TypeError):
        delay_int = 0
    if delay_int <= 0:
        return RedirectResponse(f"/servers/{guild_id}?tab=autodelete&error=Ungültige+Verzögerung", status_code=302)
    try:
        await db_exec(
            "UPDATE auto_delete_channels SET channel_id=?, delay_seconds=? WHERE id=? AND guild_id=?",
            (channel_id, delay_int, entry_id, guild_id),
        )
    except Exception:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=autodelete&error=Für+diesen+Kanal+existiert+schon+eine+Regel", status_code=302
        )
    await _reload_auto_delete()
    return RedirectResponse(f"/servers/{guild_id}?tab=autodelete&success=Gespeichert", status_code=303)

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
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    channel_id = form.get("channel_id", "")
    message = form.get("message", "").strip()
    send_at = form.get("send_at", "")
    if channel_id and channel_id not in {str(c.id) for c in guild.text_channels}:
        return RedirectResponse(f"/servers/{guild_id}?tab=scheduled&error=Ungültiger+Kanal", status_code=302)
    if channel_id and message and send_at:
        await db_exec(
            "INSERT INTO scheduled_messages (guild_id, channel_id, message, send_at) VALUES (?,?,?,?)",
            (guild_id, channel_id, message, send_at),
        )
    return RedirectResponse(f"/servers/{guild_id}?tab=scheduled&success=Geplant", status_code=302)

@web.post("/servers/{guild_id}/scheduled/edit/{msg_id}")
async def scheduled_edit(request: Request, guild_id: str, msg_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    channel_id = form.get("channel_id", "")
    message = form.get("message", "").strip()
    send_at = form.get("send_at", "")
    if channel_id and channel_id not in {str(c.id) for c in guild.text_channels}:
        return RedirectResponse(f"/servers/{guild_id}?tab=scheduled&error=Ungültiger+Kanal", status_code=302)
    if channel_id and message and send_at:
        existing = await db_one(
            "SELECT event_id FROM scheduled_messages WHERE id=? AND guild_id=?", (msg_id, guild_id)
        )
        if existing and existing.get("event_id"):
            # This row is an event reminder/announcement - the edit form pre-fills send_at in
            # the viewer's own dashboard timezone (see _add_event_send_at_fields), so the
            # submitted value must be interpreted the same way and re-normalized back to
            # Europe/Berlin, matching the storage convention events_create/edit rely on. A
            # plain (non-event) scheduled message has no such convention, so it's stored as-is.
            try:
                send_dt = _aware(datetime.datetime.fromisoformat(send_at), _request_tz.get())
                send_at = send_dt.astimezone(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%dT%H:%M")
            except ValueError:
                return RedirectResponse(f"/servers/{guild_id}?tab=scheduled&error=Ungültiger+Zeitpunkt", status_code=302)
        updated = await db_exec_rowcount(
            "UPDATE scheduled_messages SET channel_id=?, message=?, send_at=? WHERE id=? AND guild_id=? AND sent=0",
            (channel_id, message, send_at, msg_id, guild_id),
        )
        if not updated:
            # The AND sent=0 guard means this silently affects 0 rows if the scheduler's own
            # 1-minute tick already sent this message in the time between the admin loading the
            # edit form and submitting it - a real, if narrow, race (not just a raw-POST edge
            # case) for anything scheduled to fire soon. Previously showed "Gespeichert" anyway,
            # implying the edit took effect when the message had already gone out with the OLD
            # content/time.
            return RedirectResponse(f"/servers/{guild_id}?tab=scheduled&error=Nachricht+wurde+bereits+gesendet", status_code=302)
    return RedirectResponse(f"/servers/{guild_id}?tab=scheduled&success=Gespeichert", status_code=302)

@web.post("/servers/{guild_id}/scheduled/delete/{msg_id}")
async def scheduled_delete(request: Request, guild_id: str, msg_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM scheduled_messages WHERE id=? AND guild_id=?", (msg_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=scheduled&success=Gelöscht", status_code=302)


# ── Discord Events ───────────────────────────────────────────────────────────

_EVENT_START_MESSAGE = "🔴 Das Event startet jetzt!"
_EVENT_END_MESSAGE = "🏁 Das Event ist jetzt beendet!"


def _add_event_send_at_fields(row: dict) -> None:
    """event_id-linked scheduled_messages rows store send_at as a naive Europe/Berlin
    wall-clock string (see events_create/events_edit) - the generic `dt`/`dtlocal` filters
    can't be reused here since they assume UTC for naive values, which would apply the wrong
    offset. Adds send_at_display (pretty, for read-only display) and send_at_edit (datetime-
    local input format) in the viewer's own configured dashboard timezone."""
    try:
        send_dt = _aware(datetime.datetime.fromisoformat(row["send_at"]), ZoneInfo("Europe/Berlin"))
        local_dt = send_dt.astimezone(_request_tz.get())
        row["send_at_display"] = local_dt.strftime("%d.%m.%Y %H:%M")
        row["send_at_edit"] = local_dt.strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        row["send_at_display"] = row["send_at"]
        row["send_at_edit"] = row["send_at"]


def _add_series_next_start_display(row: dict) -> None:
    """Same Europe/Berlin wall-clock storage convention as _add_event_send_at_fields above,
    applied to event_series.next_start_at."""
    try:
        next_dt = _aware(datetime.datetime.fromisoformat(row["next_start_at"]), ZoneInfo("Europe/Berlin"))
        row["next_start_display"] = next_dt.astimezone(_request_tz.get()).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        row["next_start_display"] = row["next_start_at"]


async def _event_series_list(guild_id) -> list[dict]:
    rows = await db_rows(
        "SELECT * FROM event_series WHERE guild_id=? AND active=1 ORDER BY next_start_at", (str(guild_id),)
    )
    for row in rows:
        _add_series_next_start_display(row)
    return rows


async def _event_reminders_by_event(guild_id) -> dict[str, list[dict]]:
    rows = await db_rows(
        "SELECT * FROM scheduled_messages WHERE guild_id=? AND sent=0 AND event_id IS NOT NULL ORDER BY send_at",
        (str(guild_id),),
    )
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        _add_event_send_at_fields(row)
        grouped.setdefault(row["event_id"], []).append(row)
    return grouped


@web.post("/servers/{guild_id}/events/create")
async def events_create(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Server+nicht+gefunden", status_code=302)

    form = await request.form()
    name = form.get("name", "").strip()
    description = form.get("description", "").strip()
    start_at = form.get("start_at", "")
    end_at = form.get("end_at", "")
    entity_type = form.get("entity_type", "voice")
    channel_id = form.get("channel_id", "")
    location = form.get("location", "").strip()
    announce_channel_id = form.get("announce_channel_id", "")
    notify_end = form.get("notify_end") == "1"
    recurrence = form.get("recurrence", "")
    if recurrence not in ("daily", "weekly", "monthly"):
        recurrence = ""

    reminders = []
    for off, msg in zip(form.getlist("reminder_offset"), form.getlist("reminder_message")):
        msg = msg.strip()
        if not off or not msg:
            continue
        try:
            off_min = int(off)
        except ValueError:
            continue
        if off_min < 0:
            continue
        reminders.append((off_min, msg))

    if not name or not start_at:
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Name+und+Start+erforderlich", status_code=302)
    if (reminders or notify_end) and not announce_channel_id:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=events&error=Ankündigungskanal+für+Erinnerungen/Ende-Benachrichtigung+erforderlich",
            status_code=302,
        )
    if announce_channel_id and announce_channel_id not in {str(c.id) for c in guild.text_channels}:
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Ungültiger+Ankündigungskanal", status_code=302)

    tz = _request_tz.get()
    try:
        start_dt = _aware(datetime.datetime.fromisoformat(start_at), tz)
    except ValueError:
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Ungültiger+Startzeitpunkt", status_code=302)
    end_dt = None
    if end_at:
        try:
            end_dt = _aware(datetime.datetime.fromisoformat(end_at), tz)
        except ValueError:
            return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Ungültiger+Endzeitpunkt", status_code=302)
    if notify_end and not end_dt:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=events&error=Für+Ende-Benachrichtigung+muss+ein+Enddatum+gesetzt+sein",
            status_code=302,
        )

    kwargs = {
        "name": name,
        "description": description or None,
        "start_time": start_dt,
        "privacy_level": discord.PrivacyLevel.guild_only,
    }
    if entity_type == "external":
        if not end_dt:
            return RedirectResponse(
                f"/servers/{guild_id}?tab=events&error=Ende+für+externe+Events+erforderlich",
                status_code=302,
            )
        kwargs["entity_type"] = discord.EntityType.external
        kwargs["location"] = location or guild.name
        kwargs["end_time"] = end_dt
    else:
        try:
            channel = guild.get_channel(int(channel_id))
        except (ValueError, TypeError):
            channel = None
        if not channel:
            return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Kanal+nicht+gefunden", status_code=302)
        kwargs["entity_type"] = discord.EntityType.voice
        kwargs["channel"] = channel
        if end_dt:
            kwargs["end_time"] = end_dt

    try:
        event = await guild.create_scheduled_event(**kwargs)
    except discord.HTTPException as e:
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Discord-Fehler:+{e.text}", status_code=302)

    if announce_channel_id:
        berlin_tz = ZoneInfo("Europe/Berlin")
        entries = [(0, _EVENT_START_MESSAGE)] + reminders
        for off_min, msg in entries:
            fire_at = (start_dt - datetime.timedelta(minutes=off_min)).astimezone(berlin_tz)
            await db_exec(
                "INSERT INTO scheduled_messages (guild_id, channel_id, message, send_at, event_id) VALUES (?,?,?,?,?)",
                (str(guild_id), announce_channel_id, msg, fire_at.strftime("%Y-%m-%dT%H:%M"), str(event.id)),
            )
        if notify_end and end_dt:
            fire_at_end = end_dt.astimezone(berlin_tz)
            await db_exec(
                "INSERT INTO scheduled_messages (guild_id, channel_id, message, send_at, event_id) VALUES (?,?,?,?,?)",
                (str(guild_id), announce_channel_id, _EVENT_END_MESSAGE, fire_at_end.strftime("%Y-%m-%dT%H:%M"), str(event.id)),
            )

    # User-requested ("ich will bei den events wiederholende sachen da auch eintragen können") -
    # this first occurrence is created exactly as before; a series row just records everything
    # needed to recreate the NEXT one (cogs/scheduler.py's periodic check does the actual
    # recreating, see database.py's event_series migration comment for why - no native
    # discord.py support to build on here).
    if recurrence:
        berlin_tz = ZoneInfo("Europe/Berlin")
        duration_minutes = int((end_dt - start_dt).total_seconds() // 60) if end_dt else None
        next_start = _add_recurrence_interval(start_dt, recurrence).astimezone(berlin_tz)
        series_id = await db_insert(
            "INSERT INTO event_series (guild_id, name, description, entity_type, channel_id, location, "
            "duration_minutes, announce_channel_id, notify_end, recurrence, next_start_at, last_discord_event_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(guild_id), name, description, entity_type, channel_id, location, duration_minutes,
             announce_channel_id, int(notify_end), recurrence,
             next_start.strftime("%Y-%m-%dT%H:%M"), str(event.id)),
        )
        for off_min, msg in reminders:
            await db_exec(
                "INSERT INTO event_series_reminders (series_id, offset_minutes, message) VALUES (?,?,?)",
                (series_id, off_min, msg),
            )

    return RedirectResponse(f"/servers/{guild_id}?tab=events&success=Event+erstellt", status_code=302)


@web.post("/servers/{guild_id}/events/edit/{event_id}")
async def events_edit(request: Request, guild_id: int, event_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Server+nicht+gefunden", status_code=302)
    try:
        event = await guild.fetch_scheduled_event(event_id)
    except discord.NotFound:
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Event+nicht+gefunden", status_code=302)
    if event.status != discord.EventStatus.scheduled:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=events&error=Event+läuft+bereits+oder+ist+beendet,+nur+noch+löschbar",
            status_code=302,
        )

    form = await request.form()
    name = form.get("name", "").strip()
    description = form.get("description", "").strip()
    start_at = form.get("start_at", "")
    end_at = form.get("end_at", "")
    channel_id = form.get("channel_id", "")
    location = form.get("location", "").strip()

    if not name or not start_at:
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Name+und+Start+erforderlich", status_code=302)

    tz = _request_tz.get()
    try:
        start_dt = _aware(datetime.datetime.fromisoformat(start_at), tz)
    except ValueError:
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Ungültiger+Startzeitpunkt", status_code=302)
    end_dt = None
    if end_at:
        try:
            end_dt = _aware(datetime.datetime.fromisoformat(end_at), tz)
        except ValueError:
            return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Ungültiger+Endzeitpunkt", status_code=302)

    kwargs = {
        "name": name,
        "description": description or None,
        "start_time": start_dt,
    }
    if event.entity_type == discord.EntityType.external:
        if not end_dt:
            return RedirectResponse(
                f"/servers/{guild_id}?tab=events&error=Ende+für+externe+Events+erforderlich",
                status_code=302,
            )
        kwargs["location"] = location or guild.name
        kwargs["end_time"] = end_dt
    else:
        try:
            channel = guild.get_channel(int(channel_id))
        except (ValueError, TypeError):
            channel = None
        if not channel:
            return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Kanal+nicht+gefunden", status_code=302)
        kwargs["channel"] = channel
        kwargs["end_time"] = end_dt  # explicit None clears an existing end time

    old_start_dt = event.start_time

    try:
        await event.edit(**kwargs)
    except discord.HTTPException as e:
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Discord-Fehler:+{e.text}", status_code=302)

    berlin_tz = ZoneInfo("Europe/Berlin")
    pending = await db_rows(
        "SELECT * FROM scheduled_messages WHERE event_id=? AND sent=0", (str(event_id),)
    )
    for row in pending:
        if row["message"] == _EVENT_END_MESSAGE:
            if not end_dt:
                await db_exec("DELETE FROM scheduled_messages WHERE id=?", (row["id"],))
                continue
            new_send_dt = end_dt.astimezone(berlin_tz)
        else:
            try:
                old_send_dt = _aware(datetime.datetime.fromisoformat(row["send_at"]), berlin_tz)
            except ValueError:
                continue
            offset = old_start_dt.astimezone(berlin_tz) - old_send_dt
            new_send_dt = start_dt.astimezone(berlin_tz) - offset
        await db_exec(
            "UPDATE scheduled_messages SET send_at=? WHERE id=?",
            (new_send_dt.strftime("%Y-%m-%dT%H:%M"), row["id"]),
        )

    return RedirectResponse(f"/servers/{guild_id}?tab=events&success=Event+aktualisiert", status_code=302)


@web.post("/servers/{guild_id}/events/delete/{event_id}")
async def events_delete(request: Request, guild_id: int, event_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Server+nicht+gefunden", status_code=302)
    try:
        event = await guild.fetch_scheduled_event(event_id)
        await event.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException as e:
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Discord-Fehler:+{e.text}", status_code=302)
    await db_exec("DELETE FROM scheduled_messages WHERE event_id=? AND sent=0", (str(event_id),))
    return RedirectResponse(f"/servers/{guild_id}?tab=events&success=Event+gelöscht", status_code=302)


@web.post("/servers/{guild_id}/events/series/delete/{series_id}")
async def events_series_delete(request: Request, guild_id: int, series_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    # Only stops FUTURE occurrences from being created - deliberately does not touch the
    # already-created current/most recent Discord event or its pending reminders, same
    # "don't retroactively undo something already live" principle as e.g. deleting a ticket
    # panel not affecting tickets already opened from it.
    await db_exec("DELETE FROM event_series WHERE id=? AND guild_id=?", (series_id, str(guild_id)))
    await db_exec("DELETE FROM event_series_reminders WHERE series_id=?", (series_id,))
    return RedirectResponse(f"/servers/{guild_id}?tab=events&success=Wiederholung+beendet", status_code=302)


# ── Temp Voice ────────────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/tempvoice/add")
async def tempvoice_add(request: Request, guild_id: str):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    trigger = form.get("trigger_channel_id", "")
    category = form.get("category_id", "")
    name_tpl = form.get("name_template", "{user}'s Channel") or "{user}'s Channel"
    try:
        user_limit = max(0, min(99, int(form.get("user_limit") or 0)))
    except (ValueError, TypeError):
        user_limit = 0
    if trigger not in {str(c.id) for c in guild.voice_channels}:
        return RedirectResponse(f"/servers/{guild_id}?tab=tempvoice&error=Ungültiger+Kanal", status_code=302)
    if category and category not in {str(c.id) for c in guild.categories}:
        return RedirectResponse(f"/servers/{guild_id}?tab=tempvoice&error=Ungültige+Kategorie", status_code=302)
    await db_exec(
        "INSERT OR REPLACE INTO temp_voice_config (guild_id, trigger_channel_id, category_id, name_template, user_limit) VALUES (?,?,?,?,?)",
        (guild_id, trigger, category, name_tpl, user_limit),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=tempvoice&success=Gespeichert", status_code=302)

@web.post("/servers/{guild_id}/tempvoice/edit/{config_id}")
async def tempvoice_edit(request: Request, guild_id: str, config_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    trigger = form.get("trigger_channel_id", "")
    category = form.get("category_id", "")
    name_tpl = form.get("name_template", "{user}'s Channel") or "{user}'s Channel"
    try:
        user_limit = max(0, min(99, int(form.get("user_limit") or 0)))
    except (ValueError, TypeError):
        user_limit = 0
    if trigger not in {str(c.id) for c in guild.voice_channels}:
        return RedirectResponse(f"/servers/{guild_id}?tab=tempvoice&error=Ungültiger+Kanal", status_code=302)
    if category and category not in {str(c.id) for c in guild.categories}:
        return RedirectResponse(f"/servers/{guild_id}?tab=tempvoice&error=Ungültige+Kategorie", status_code=302)
    try:
        await db_exec(
            "UPDATE temp_voice_config SET trigger_channel_id=?, category_id=?, name_template=?, user_limit=? "
            "WHERE id=? AND guild_id=?",
            (trigger, category, name_tpl, user_limit, config_id, guild_id),
        )
    except Exception:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=tempvoice&error=Für+diesen+Kanal+existiert+schon+ein+Trigger", status_code=302
        )
    return RedirectResponse(f"/servers/{guild_id}?tab=tempvoice&success=Gespeichert", status_code=303)

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
    # Mirror twitch_loop()'s own auto-select rule exactly (cogs/notifications.py): it only
    # auto-picks an API when exactly one is registered GLOBALLY - with 2+ and nothing
    # explicitly saved for this guild, the loop skips the guild entirely. Must use the global
    # count here, not len(twitch_apis) - that list is role-scoped (a moderator may only see
    # one of several globally-registered APIs), so it alone can't tell whether the cog would
    # actually auto-select. Getting this wrong would show an API as "selected" in the dropdown
    # that was never actually saved, while notifications silently never fire.
    global_api_count = (await db_one("SELECT COUNT(*) AS c FROM twitch_apis"))["c"]
    if current_api_cfg:
        current_api_id = int(current_api_cfg["value"])
    elif global_api_count == 1 and twitch_apis:
        current_api_id = twitch_apis[0]["id"]
    else:
        current_api_id = 0
    api_unresolved = global_api_count > 1 and not current_api_cfg
    return templates.TemplateResponse("notifications.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": f"server_{guild_id}",
        "guild_id": guild_id, "guild_name": guild.name,
        "channels": channels, "subs": subs,
        "twitch_apis": twitch_apis,
        "current_api_id": current_api_id,
        "api_unresolved": api_unresolved,
        "twitch_configured": bool(twitch_apis),
        "success": success, "error": error,
        "enabled_features": await _get_enabled_features(guild_id),
    })


@web.post("/servers/{guild_id}/notifications/api")
async def notifications_set_api(request: Request, guild_id: str, twitch_api_id: str = Form("")):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    if twitch_api_id.strip():
        role = request.session.get("role")
        uid = request.session.get("user_id")
        if role == "admin":
            allowed = await db_one("SELECT 1 FROM twitch_apis WHERE id=?", (twitch_api_id.strip(),))
        else:
            allowed = await db_one(
                """SELECT 1 FROM twitch_apis ta
                   LEFT JOIN twitch_api_access taa ON taa.api_id = ta.id
                   WHERE ta.id=? AND (ta.owner_id=? OR taa.user_id=?)""",
                (twitch_api_id.strip(), uid, uid),
            )
        if not allowed:
            return RedirectResponse(f"/servers/{guild_id}/notifications?error=Ungültige+API", status_code=302)
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
    guild = bot.get_guild(int(guild_id))
    if not guild or discord_channel_id not in {str(c.id) for c in guild.text_channels}:
        return RedirectResponse(f"/servers/{guild_id}/notifications?error=Ungültiger+Kanal", status_code=302)
    # Normalize YouTube channel URL to ID
    if platform == "youtube" and "youtube.com" in target:
        parts = target.rstrip("/").split("/")
        target = parts[-1]
    # Normalize a pasted Twitch channel URL (e.g. https://www.twitch.tv/ninja) to the login name
    if platform == "twitch" and "twitch.tv" in target:
        target = target.split("?")[0].rstrip("/").split("/")[-1]
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


@web.post("/servers/{guild_id}/notifications/edit/{nid}")
async def notifications_edit(
    request: Request, guild_id: str, nid: int,
    target: str = Form(...),
    target_name: str = Form(""),
    discord_channel_id: str = Form(...),
    custom_message: str = Form(""),
    next_url: str = Form(""),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    existing_sub = await db_one("SELECT platform, target FROM notifications WHERE id=? AND guild_id=?", (nid, guild_id))
    if not existing_sub:
        return RedirectResponse(f"/servers/{guild_id}/notifications?error=Nicht+gefunden", status_code=302)
    platform = existing_sub["platform"]
    target = target.strip()
    if not target or not discord_channel_id:
        return RedirectResponse(f"/servers/{guild_id}/notifications?error=Pflichtfelder+fehlen", status_code=302)
    guild = bot.get_guild(int(guild_id))
    if not guild or discord_channel_id not in {str(c.id) for c in guild.text_channels}:
        return RedirectResponse(f"/servers/{guild_id}/notifications?error=Ungültiger+Kanal", status_code=302)
    # Normalize YouTube channel URL to ID
    if platform == "youtube" and "youtube.com" in target:
        target = target.rstrip("/").split("/")[-1]
    # Normalize a pasted Twitch channel URL (e.g. https://www.twitch.tv/ninja) to the login name
    if platform == "twitch" and "twitch.tv" in target:
        target = target.split("?")[0].rstrip("/").split("/")[-1]
    target_norm = target.lower() if platform == "twitch" else target
    dup = await db_rows(
        "SELECT id FROM notifications WHERE guild_id=? AND platform=? AND target=? AND id!=?",
        (guild_id, platform, target_norm, nid),
    )
    if dup:
        dest = next_url or f"/servers/{guild_id}/notifications"
        return RedirectResponse(f"{dest}?error=Bereits+eingetragen", status_code=302)
    if target_norm != existing_sub["target"]:
        # Target changed - reset live-tracking state, otherwise stale state from the
        # previous streamer could suppress the first real notification for the new one.
        await db_exec(
            "UPDATE notifications SET discord_channel_id=?, target=?, target_name=?, custom_message=?, live=0, last_id='' WHERE id=? AND guild_id=?",
            (discord_channel_id, target_norm, target_name.strip(), custom_message.strip(), nid, guild_id),
        )
    else:
        await db_exec(
            "UPDATE notifications SET discord_channel_id=?, target=?, target_name=?, custom_message=? WHERE id=? AND guild_id=?",
            (discord_channel_id, target_norm, target_name.strip(), custom_message.strip(), nid, guild_id),
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
    if r := admin_redirect(request): return r
    token_set = await _token_configured()
    # admin_redirect above guarantees role=='admin' for anyone reaching this point - the
    # owner/access-scoped query this used to fall back to for non-admins is unreachable dead
    # code since notif_settings_page became admin-only (same cleanup as tokens_page above).
    twitch_apis = await db_rows("SELECT * FROM twitch_apis ORDER BY owner_id, created_at")
    all_users_map = {u["id"]: u["username"] for u in await db_rows("SELECT id, username FROM users")}
    # attach owner name and list of users with granted access
    access_rows = await db_rows("SELECT api_id, user_id FROM twitch_api_access")
    access_map: dict[int, list] = {}
    for ar in access_rows:
        access_map.setdefault(ar["api_id"], []).append(ar["user_id"])
    for a in twitch_apis:
        a["owner_name"] = all_users_map.get(a["owner_id"], "—")
        a["is_own"] = True
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
    if r := admin_redirect(request): return r
    api = await db_one("SELECT * FROM twitch_apis WHERE id=?", (api_id,))
    if not api:
        return RedirectResponse("/settings/notifications?error=Keine+Berechtigung", status_code=302)
    await db_exec(
        "INSERT OR IGNORE INTO twitch_api_access (api_id, user_id) VALUES (?,?)",
        (api_id, grant_user_id),
    )
    return RedirectResponse("/settings/notifications?success=Zugriff+gewaehrt", status_code=302)


@web.post("/settings/notifications/{api_id}/access/remove/{target_uid}")
async def notif_api_access_remove(request: Request, api_id: int, target_uid: int):
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r
    api = await db_one("SELECT * FROM twitch_apis WHERE id=?", (api_id,))
    if not api:
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
    if r := admin_redirect(request): return r
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
        return RedirectResponse(f"/settings/notifications?error={urllib.parse.quote(str(e)[:120])}", status_code=302)
    return RedirectResponse("/settings/notifications?success=API+hinzugefuegt", status_code=302)


@web.post("/settings/notifications/edit/{api_id}")
async def notif_api_edit(
    request: Request, api_id: int,
    label: str = Form(""),
    twitch_client_id: str = Form(""),
    twitch_client_secret: str = Form(""),
):
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r
    api = await db_one("SELECT * FROM twitch_apis WHERE id=?", (api_id,))
    if not api:
        return RedirectResponse("/settings/notifications?error=Keine+Berechtigung", status_code=302)
    if label.strip():
        await db_exec("UPDATE twitch_apis SET label=? WHERE id=?", (label.strip(), api_id))
    creds_changed = bool(twitch_client_id.strip() or twitch_client_secret.strip())
    if twitch_client_id.strip():
        await db_exec("UPDATE twitch_apis SET client_id=? WHERE id=?", (twitch_client_id.strip(), api_id))
    if twitch_client_secret.strip():
        await db_exec("UPDATE twitch_apis SET client_secret=? WHERE id=?", (twitch_client_secret.strip(), api_id))
    if creds_changed:
        # A cached OAuth token from the old credentials could otherwise keep being used for
        # up to an hour (see Notifications.reset_token_cache) even though they were just
        # changed here, e.g. specifically to replace a compromised/regenerated secret.
        for b in bot._bots.values():
            cog = b.cogs.get("Notifications")
            if cog:
                cog.reset_token_cache(api_id)
    return RedirectResponse("/settings/notifications?success=API+aktualisiert", status_code=302)


@web.post("/settings/notifications/delete/{api_id}")
async def notif_api_delete(request: Request, api_id: int):
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r
    api = await db_one("SELECT * FROM twitch_apis WHERE id=?", (api_id,))
    if not api:
        return RedirectResponse("/settings/notifications?error=Keine+Berechtigung", status_code=302)
    await db_exec("DELETE FROM twitch_apis WHERE id=?", (api_id,))
    await db_exec("DELETE FROM twitch_api_access WHERE api_id=?", (api_id,))
    # Guilds that had this API selected would otherwise be left pointing at a
    # dead twitch_api_id — streaming silently stops working with no visible error.
    await db_exec("DELETE FROM guild_configs WHERE key='twitch_api_id' AND value=?", (str(api_id),))
    return RedirectResponse("/settings/notifications?success=API+gelöscht", status_code=302)


# ── SMTP Settings ─────────────────────────────────────────────────────────────

@web.get("/settings/smtp", response_class=HTMLResponse)
async def smtp_settings_page(request: Request, saved: bool = False, error: str = "", test_ok: bool = False):
    if r := auth_redirect(request): return r
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
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r
    if smtp_port.strip():
        try:
            if not (1 <= int(smtp_port.strip()) <= 65535):
                raise ValueError
        except ValueError:
            # _send_reset_email() does int(get_config("smtp_port") or 587) completely
            # unguarded - a non-numeric value saved here would raise there instead, and
            # forgot_pw_submit only shows that exception's message when the submitted email
            # actually belongs to a registered user (the no-such-user path always shows the
            # generic "an email was sent if this address is registered" success message to
            # prevent enumeration) - a broken port value would silently defeat that
            # protection by making a real account distinguishable via the resulting error.
            return RedirectResponse("/settings/smtp?error=Ungültiger+SMTP-Port", status_code=302)
    for key, val in [
        ("smtp_host", smtp_host), ("smtp_port", smtp_port),
        ("smtp_user", smtp_user), ("smtp_from", smtp_from),
        ("base_url", base_url),
    ]:
        await set_config(key, val.strip())
    if smtp_pass.strip():
        await set_config("smtp_pass", smtp_pass.strip())
    # Redirects back to the SMTP page itself (not the general /settings page, which shows
    # unrelated App-Name/Zeitzone cards) - confirmed live as confusing: after saving SMTP,
    # landing on a page about the app name looked like a wrong/unrelated destination.
    return RedirectResponse("/settings/smtp?saved=true", status_code=302)


@web.post("/settings/smtp/test")
async def smtp_test(request: Request, test_email: str = Form(...)):
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r
    # The link used to always be a hard-coded, deliberately non-functional placeholder
    # (https://example.com/test-link) - confirmed live to be confusing: an admin who clicked it
    # (reasonably, to check the email actually arrived and looks right) landed on a genuinely
    # unreachable domain and read that as the test having failed, even though sending itself
    # had already succeeded by that point. Using base_url (when configured) with a token that's
    # deliberately invalid gives a much more representative preview instead: reset_pw_page()
    # already handles an unrecognized token gracefully (redirects to /login with a friendly
    # "link invalid or expired" message, not a crash) - so this now lands the admin on their
    # own actually-reachable dashboard, which also incidentally doubles as a live check that
    # base_url itself points somewhere real. Falls back to the old placeholder only when
    # base_url isn't set at all, since a bare "/reset-password?token=..." relative path
    # wouldn't be a valid clickable link in an email either.
    base = await get_config("base_url") or ""
    test_link = f"{base.rstrip('/')}/reset-password?token=test-preview-token" if base else "https://example.com/test-link"
    try:
        await _send_reset_email(test_email.strip(), test_link)
        return RedirectResponse("/settings/smtp?test_ok=true", status_code=302)
    except Exception as e:
        return RedirectResponse(f"/settings/smtp?error={urllib.parse.quote(str(e))}", status_code=302)


# ── Token Management ──────────────────────────────────────────────────────────

@web.get("/settings/tokens", response_class=HTMLResponse)
async def tokens_page(request: Request, success: str = "", error: str = ""):
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r
    # admin_redirect above already guarantees role=='admin' for anyone reaching this point -
    # the non-admin branch this used to have (a per-user-assigned-tokens-only view) has been
    # unreachable since tokens_page became admin-only (v1.5.0), per the already-documented
    # dead code (v1.5.1: "unreachable code... left in place, out of scope for that round").
    # Removed now rather than left as permanent technical debt.
    token_rows = await db_rows(
        "SELECT id, label, token, enabled, created_at FROM bot_tokens ORDER BY id"
    )
    all_users = await db_rows("SELECT id, username FROM users ORDER BY username")
    tu_rows = await db_rows("SELECT token_id, user_id FROM bot_token_users")
    token_users: dict[int, set] = {}
    for r in tu_rows:
        token_users.setdefault(r["token_id"], set()).add(r["user_id"])
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
    if r := admin_redirect(request): return r
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
    if r := admin_redirect(request): return r
    # admin_redirect guarantees admin here - the per-assigned-user allowance check this had
    # was unreachable dead code (same cleanup as tokens_page above).
    await db_exec("UPDATE bot_tokens SET enabled=0 WHERE id=?", (token_id,))
    await _stop_bot(token_id)
    await db_exec("DELETE FROM bot_tokens WHERE id=?", (token_id,))
    await db_exec("DELETE FROM bot_token_users WHERE token_id=?", (token_id,))
    return RedirectResponse("/settings/tokens?success=Token+gelöscht.", status_code=302)


@web.post("/settings/tokens/rename/{token_id}")
async def tokens_rename(request: Request, token_id: int):
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r
    form = await request.form()
    label = (form.get("label") or "").strip()
    if not label:
        return RedirectResponse("/settings/tokens?error=Bezeichnung+darf+nicht+leer+sein", status_code=302)
    await db_exec("UPDATE bot_tokens SET label=? WHERE id=?", (label, token_id))
    return RedirectResponse("/settings/tokens?success=Bezeichnung+gespeichert", status_code=302)


@web.post("/settings/tokens/toggle/{token_id}")
async def tokens_toggle(request: Request, token_id: int):
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r
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


LOG_LIMIT_OPTIONS = (10, 50, 100, 200)


@web.get("/servers/{guild_id}/log", response_class=HTMLResponse)
async def server_log_page(request: Request, guild_id: str, success: str = "", error: str = "", limit: Optional[int] = None):
    if r := auth_redirect(request): return r
    token_set = await _token_configured()
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    uid = request.session.get("user_id")
    if limit is not None and limit in LOG_LIMIT_OPTIONS:
        if uid:
            await db_exec("UPDATE users SET log_limit=? WHERE id=?", (limit, uid))
    else:
        user_row = await db_one("SELECT log_limit FROM users WHERE id=?", (uid,)) if uid else None
        limit = (user_row or {}).get("log_limit") or 200
    if limit not in LOG_LIMIT_OPTIONS:
        limit = 200
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    log_channel = await get_guild_config(int(guild_id), "log_channel") or ""
    exclude_raw = await get_guild_config(int(guild_id), "log_exclude_channels") or ""
    log_exclude_channels = [c.strip() for c in exclude_raw.split(",") if c.strip()]
    logs = await db_rows(
        "SELECT icon, title, description, created_at FROM server_logs WHERE guild_id=? ORDER BY id DESC LIMIT ?",
        (guild_id, limit),
    )
    return templates.TemplateResponse("server_log.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": f"server_{guild_id}",
        "guild_id": guild_id, "guild_name": guild.name,
        "channels": channels, "log_channel": log_channel,
        "log_exclude_channels": log_exclude_channels,
        "logs": logs, "success": success, "error": error,
        "log_limit": limit, "log_limit_options": LOG_LIMIT_OPTIONS,
        "enabled_features": await _get_enabled_features(guild_id),
    })


@web.post("/servers/{guild_id}/log/save")
async def server_log_save(request: Request, guild_id: str):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    valid_channel_ids = {str(c.id) for c in guild.text_channels}

    form = await request.form()
    log_channel = form.get("log_channel", "")
    if log_channel and log_channel not in valid_channel_ids:
        return RedirectResponse(f"/servers/{guild_id}/log?error=Ungültiger+Log-Kanal", status_code=302)
    exclude_channels = ",".join(c for c in form.getlist("log_exclude_channels") if c in valid_channel_ids)

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

async def _guild_text_curve(guild_id: int) -> tuple[int, int, int]:
    # Mirrors cogs.leveling.Leveling._get_curve("text") - kept independent since this route
    # doesn't have a cog instance to call, just the same three config keys and defaults.
    defaults = (5, 50, 100)
    keys = ("leveling_curve_quad", "leveling_curve_linear", "leveling_curve_base")
    values = []
    for key, default in zip(keys, defaults):
        raw = await get_guild_config(guild_id, key)
        try:
            values.append(int(raw) if raw else default)
        except ValueError:
            values.append(default)
    return tuple(values)


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
                "SELECT * FROM levels WHERE guild_id=? ORDER BY xp DESC, voice_xp DESC LIMIT 50", (int(guild_id),)
            )
            quad, linear, base = await _guild_text_curve(int(guild_id))
            for i, e in enumerate(lb, 1):
                m = guild.get_member(e["user_id"])
                e["username"] = str(m) if m else f"#{e['user_id']}"
                e["avatar"] = str(m.display_avatar.url) if m else None
                e["rank"] = i
                # Closed-form cumulative instead of summing xp_for_level() in a loop - same
                # O(level) blowup risk cogs.leveling.level_from_xp() had, just here it'd run
                # once per leaderboard ROW (up to 50) on every page load instead of per XP
                # grant, and a slow synchronous loop here blocks the whole dashboard's event
                # loop for everyone, not just the one Discord interaction.
                needed = _xp_for_level(e["level"], quad, linear, base)
                # Clamped to 0 - the stored level only catches up to a curve change on the
                # member's next XP grant, so right after an admin makes the curve harder this
                # can briefly go negative for members who leveled up under the old curve.
                in_level = max(0, e["xp"] - _cumulative_xp_for_level(e["level"], quad, linear, base))
                e["xp_needed"] = needed
                e["xp_in_level"] = in_level
                e["pct"] = min(int(in_level * 100 / needed), 100) if needed else 0
            leaderboard = lb

    return templates.TemplateResponse("leaderboard.html", {
        **session(request), "request": request,
        "guilds": guilds, "token_set": token_set, "active": "leaderboard",
        "selected_guild": selected_guild, "selected_guild_id": guild_id,
        "leaderboard": leaderboard, "bot_online": bot.is_ready(),
    })


# ── Server Config ─────────────────────────────────────────────────────────────

# Seeded once per guild the first time its automod tab is loaded (see server_config below) -
# after that, these live in automod_word_presets and are fully user-editable, this list is
# never referenced again.
_AUTOMOD_DEFAULT_PRESETS = [
    ("Spam-Floskeln", "kostenlos gewinnen, jetzt klicken, garantiert gewinnen, schnell geld verdienen"),
    ("Nitro-Köder", "kostenloser nitro, gratis nitro, nitro generator, free nitro"),
    ("Krypto-Scam", "bitcoin verdoppeln, krypto investment, garantierter gewinn, airdrop claim"),
    ("NS-Bezüge", "hitler, nazi, hakenkreuz"),
]


# Mirrors the labels in _server_subnav.html's ssnav-item links for the tabs that live inside
# server_config.html itself (not the ones that are real separate pages, like Streaming/Log) -
# keep both in sync if a tab is renamed. Used to show the active tab's own name in the page
# header instead of a static guild name, since every tab switch here is a real page reload
# (a plain <a href="?tab=..."> link, not client-side-only JS) and can render this correctly.
_SERVER_CONFIG_TAB_LABELS = {
    "config": "⚙️ Config", "automod": "🛡️ Spam-Schutz", "leveling": "🏆 Leveling",
    "rr": "🎭 Reaction Roles", "commands": "📢 Commands", "tickets": "🎫 Tickets",
    "giveaways": "🎉 Giveaways", "warnings": "⚠️ Warnungen", "users": "👥 Nutzer",
    "tempvoice": "🔊 Temp-Voice", "scheduled": "📅 Geplant", "events": "🗓️ Events",
    "birthday": "🎂 Geburtstage", "autodelete": "🗑️ Auto-Delete",
    "amp": "🎮 Gameserver", "autokick": "🚪 Auto-Kick", "embeds": "📨 Embed-Nachrichten",
}

# Features an admin can hide from THIS server's own sidebar to cut down on clutter for
# servers that only use a handful of them - "config" (base settings), "users" (access
# control) and "botdesign" (bot identity) are deliberately left out of this list and stay
# permanently visible, since they're structural/administrative rather than a feature someone
# would opt in or out of. Hiding a tab here only removes its sidebar link - a bookmarked or
# manually-typed URL to it still works, this is about decluttering navigation, not gating
# access (that's what user_guild_permissions/admin-only routes already handle separately).
_TOGGLEABLE_FEATURES = {
    "automod": "🛡️ Spam-Schutz", "leveling": "🏆 Leveling", "rr": "🎭 Reaction Roles",
    "commands": "📢 Commands", "tickets": "🎫 Tickets", "giveaways": "🎉 Giveaways",
    "warnings": "⚠️ Warnungen", "tempvoice": "🔊 Temp-Voice", "scheduled": "📅 Geplant",
    "events": "🗓️ Events", "birthday": "🎂 Geburtstage", "autodelete": "🗑️ Auto-Delete",
    "amp": "🎮 Gameserver", "notifications": "🟣 Streaming", "freestuff": "🎁 Free Stuff",
    "log": "📋 Log", "autokick": "🚪 Auto-Kick", "embeds": "📨 Embed-Nachrichten",
}


async def _get_enabled_features(guild_id) -> set:
    # No stored value at all = never customized yet. An explicitly saved empty string (every
    # checkbox unticked) is a real, deliberate "hide all optional tabs" choice and has to stay
    # empty rather than falling back to any default.
    raw = await get_guild_config(int(guild_id), "enabled_features")
    if raw is not None:
        return {f for f in raw.split(",") if f}
    # No enabled_features key yet - distinguish a genuinely new server (no guild_configs rows
    # at all) from one that predates this feature but already has other settings saved. Only
    # the latter falls back to "show everything", so upgrading doesn't retroactively hide tabs
    # an admin already relies on; a brand-new server starts with nothing shown until the admin
    # actively enables features, per request.
    # automod_presets_seeded is excluded: it's written automatically the first time this guild's
    # Auto-Mod tab is rendered (see server_config()), not from any deliberate admin action - a
    # guild's very first-ever page load would otherwise already count as "has config" before the
    # admin touched anything, defeating the "new server starts empty" default entirely.
    has_any_config = await db_one(
        "SELECT 1 FROM guild_configs WHERE guild_id=? AND key != 'automod_presets_seeded' LIMIT 1",
        (int(guild_id),),
    )
    if has_any_config:
        return set(_TOGGLEABLE_FEATURES.keys())
    return set()


@web.get("/servers/{guild_id}", response_class=HTMLResponse)
async def server_config(
    request: Request, guild_id: int,
    saved: bool = False, tab: str = "config", error: str = "", success: str = "",
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse("/", status_code=302)

    token_set = await _token_configured()
    cfg = await get_all_guild_config(guild_id)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    voice_channels = [{"id": str(c.id), "name": c.name} for c in guild.voice_channels]
    roles = [{"id": str(ro.id), "name": ro.name} for ro in guild.roles if not ro.is_default()]
    categories = [{"id": str(c.id), "name": c.name} for c in guild.categories]
    leveling_channels = [c.strip() for c in cfg.get("leveling_channels", "").split(",") if c.strip()]

    # Level roles
    level_roles = await db_rows(
        "SELECT * FROM level_roles WHERE guild_id=? ORDER BY level", (str(guild_id),)
    )
    for lr in level_roles:
        ro = guild.get_role(int(lr["role_id"]))
        lr["role_name"] = ro.name if ro else "?"

    # Level rewards
    level_rewards = await db_rows(
        "SELECT * FROM level_rewards WHERE guild_id=? ORDER BY level", (str(guild_id),)
    )

    # Auto-Kick reminders
    auto_kick_reminders = await db_rows(
        "SELECT * FROM auto_kick_reminders WHERE guild_id=? ORDER BY hours", (str(guild_id),)
    )

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
        "SELECT * FROM levels WHERE guild_id=? ORDER BY xp DESC, voice_xp DESC LIMIT 20", (guild_id,)
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

    # Birthdays
    _birthdays = await db_rows(
        "SELECT * FROM birthdays WHERE guild_id=? ORDER BY birthday", (str(guild_id),)
    )
    for b in _birthdays:
        m = guild.get_member(int(b["user_id"]))
        b["username"] = str(m) if m else f"#{b['user_id']}"

    # Scheduled messages (event-linked rows get send_at_display/send_at_edit - see
    # _add_event_send_at_fields; plain, non-event scheduled messages are left untouched, that
    # feature stores/edits send_at as raw, unconverted browser-local text with no normalization)
    _scheduled_messages = await db_rows(
        "SELECT * FROM scheduled_messages WHERE guild_id=? AND sent=0 ORDER BY send_at", (str(guild_id),)
    )
    for sm in _scheduled_messages:
        if sm.get("event_id"):
            _add_event_send_at_fields(sm)

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
        p["description_blocks"] = _parse_ticket_blocks(p.get("description")) or [""]
        p["ticket_message_blocks"] = _parse_ticket_blocks(p.get("ticket_message")) or [""]

    embed_posts = await db_rows(
        "SELECT * FROM embed_posts WHERE guild_id=? ORDER BY created_at DESC", (guild_id,)
    )
    for ep in embed_posts:
        if ep.get("channel_id"):
            try:
                ch = guild.get_channel(int(ep["channel_id"]))
                ep["channel_name"] = ch.name if ch else None
            except (ValueError, TypeError):
                ep["channel_name"] = None
        ep["content_blocks"] = _parse_ticket_blocks(ep.get("content")) or [""]

    # Open tickets
    ticket_list = await db_rows(
        "SELECT * FROM tickets WHERE guild_id=? AND status='open' ORDER BY created_at DESC",
        (guild_id,),
    )
    _tr_tickets = get_tr(request.session.get("lang", "de"))
    for t in ticket_list:
        m = guild.get_member(t["user_id"])
        t["username"] = str(m) if m else f"#{t['user_id']}"
        ch = guild.get_channel(t["channel_id"])
        t["channel_name"] = f"#{ch.name}" if ch else _tr_tickets["tickets_channel_deleted"]

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

    # Seeded once per guild, tracked separately from "table is empty" - otherwise a user who
    # deliberately deletes every preset would see the defaults silently reappear on next load.
    if not await get_guild_config(guild_id, "automod_presets_seeded"):
        for label, words in _AUTOMOD_DEFAULT_PRESETS:
            await db_exec(
                "INSERT INTO automod_word_presets (guild_id, label, words) VALUES (?,?,?)",
                (str(guild_id), label, words),
            )
        await set_guild_config(guild_id, "automod_presets_seeded", "1")
    automod_presets = await db_rows(
        "SELECT * FROM automod_word_presets WHERE guild_id=? ORDER BY id", (str(guild_id),)
    )

    amp_cfg = await db_one("SELECT * FROM amp_configs WHERE guild_id=?", (str(guild_id),))
    amp_status = None
    amp_instances = None
    amp_instances_error = None
    amp_connection_error = None
    amp_raw_debug = None
    if tab == "amp" and amp_cfg and amp_cfg.get("url"):
        # Only fetched when the amp tab is actually being viewed - every OTHER tab load would
        # otherwise pay for a live login+status round-trip to an external AMP instance it has
        # nothing to do with, every single time any tab on this page is opened.
        amp_cog = bot.cogs.get("AMP")
        if amp_cog:
            # A connection can be a single standalone AMP instance OR the main ADS controller
            # managing several game instances underneath it - try instance discovery first,
            # only fall back to the single-connection status view (amp_status) if none were
            # found (a genuinely standalone connection, or the discovery call itself failed).
            # The discovery error is surfaced in the dashboard (amp_instances_error) rather than
            # silently swallowed, since ADSModule.GetInstances()'s exact response shape was never
            # verified against a real ADS instance - without this, a genuine parsing/API mismatch
            # would look identical to "this connection just has no ADS layer", with no way for
            # the admin to tell the difference or report back what actually went wrong.
            listing = await amp_cog._list_instances(amp_cfg)
            amp_raw_debug = listing.get("raw_debug")
            if listing["instances"]:
                amp_instances = listing["instances"]
                # Auto-provisions default /{slug}-start/-stop/-restart commands for any instance
                # discovered here that doesn't have custom command names yet (e.g. a game added
                # to AMP after the bot's own on_ready already ran) - "wenn neue server dazu
                # kommen das der auch automatich das genau so macht". Resolved via
                # _bot_for_guild rather than the plain `amp_cog` above (which comes from
                # bot.cogs.get("AMP"), BotManager's dict.update()-merged view across all bot
                # instances - fine for the read-only _list_instances() call above since that
                # only talks to the external AMP API, but ensure_default_commands ultimately
                # touches self.bot.tree for a resync, which must be the bot instance actually
                # serving THIS guild, not an arbitrary one from the merge).
                guild_bot_for_sync = bot._bot_for_guild(guild_id)
                sync_cog = guild_bot_for_sync.cogs.get("AMP") if guild_bot_for_sync else None
                if sync_cog:
                    try:
                        await sync_cog.ensure_default_commands(guild_id, amp_instances)
                    except Exception:
                        pass  # best-effort - a failed auto-provision here shouldn't break page load
                cmd_names = {
                    r["instance_id"]: r
                    for r in await db_rows(
                        "SELECT instance_id, start_name, stop_name, restart_name FROM amp_instance_commands WHERE guild_id=?",
                        (str(guild_id),),
                    )
                }
                for inst in amp_instances:
                    inst["label"] = _amp_state_label(inst["state"], _tr_tickets)
                    row = cmd_names.get(inst["id"])
                    inst["cmd_start"] = row["start_name"] if row else ""
                    inst["cmd_stop"] = row["stop_name"] if row else ""
                    inst["cmd_restart"] = row["restart_name"] if row else ""
                    # Same slug ensure_default_commands() above actually uses for real default
                    # command names - server_config.html used to recompute its own rough
                    # approximation inline (lower + replace spaces/underscores only) just for the
                    # placeholder text shown in an empty command-name field, which diverged from
                    # the real one for any name with other special characters (parentheses,
                    # exclamation marks, "#", ...) - e.g. "Space Engineers (EU)" showed
                    # "space-engineers-(eu)-start" as the example, which _valid_command_name()
                    # would then reject outright if typed in verbatim. One source of truth now.
                    inst["slug"] = amp_cog._slugify(inst.get("name") or inst.get("instance_name") or "")
            elif listing.get("connection_error"):
                # A real timeout/connect/login failure, not "this connection has no ADS layer" -
                # reported live as confusing (User: "wenn der nicht richtig die Seite lädt lande
                # ich da [bei dem einzelnen Fallback-Bild]") - the old code treated this exactly
                # like a standalone connection and fell through to _fetch_status() below, which
                # then ALSO tried its own live AMP call and typically failed the same way,
                # showing an unrelated single-connection card instead of the admin's actual
                # multi-instance setup. Skip that redundant second doomed call entirely here.
                amp_connection_error = listing["error"]
            else:
                amp_instances_error = listing["error"]
                amp_status = await amp_cog._fetch_status(amp_cfg)

    return templates.TemplateResponse("server_config.html", {
        **session(request), "request": request,
        "guild": {"id": str(guild.id), "name": guild.name,
                  "icon": str(guild.icon.url) if guild.icon else None},
        "cfg": cfg, "channels": channels, "roles": roles, "categories": categories,
        "token_set": token_set, "saved": saved,
        "active": f"server_{guild_id}",
        "guilds": await _guild_list(request),
        "tab": tab, "error": error, "success": success,
        "tab_label": _SERVER_CONFIG_TAB_LABELS.get(tab, _SERVER_CONFIG_TAB_LABELS["config"]),
        "rr_list": rr_list, "cmd_list": cmd_list,
        "leaderboard": lb, "warn_groups": warn_groups,
        "ticket_panels": ticket_panels, "ticket_list": ticket_list, "ga_list": ga_list,
        "embed_posts": embed_posts,
        "subs": subs, "twitch_configured": twitch_configured,
        "all_users": all_users, "server_perms": server_perms,
        "automod_presets": automod_presets,
        "leveling_channels": leveling_channels,
        "level_roles": level_roles,
        "level_rewards": level_rewards,
        "auto_kick_reminders": auto_kick_reminders,
        "auto_delete_entries": await db_rows(
            "SELECT * FROM auto_delete_channels WHERE guild_id=?", (str(guild_id),)
        ),
        "voice_channels": voice_channels,
        "tempvoice_configs": await db_rows(
            "SELECT * FROM temp_voice_config WHERE guild_id=?", (str(guild_id),)
        ),
        "amp_cfg": amp_cfg, "amp_status": amp_status, "amp_instances": amp_instances,
        "amp_instances_error": amp_instances_error, "amp_connection_error": amp_connection_error,
        "amp_raw_debug": amp_raw_debug,
        "toggleable_features": _TOGGLEABLE_FEATURES,
        "enabled_features": await _get_enabled_features(guild_id),
        "scheduled_messages": _scheduled_messages,
        "birthdays": _birthdays,
        "events_list": sorted(guild.scheduled_events, key=lambda e: e.start_time),
        "event_reminders": await _event_reminders_by_event(guild_id),
        "event_series": await _event_series_list(guild_id),
    })


# pane-config, pane-leveling, pane-automod and pane-birthday all post to the same
# /servers/{guild_id} route via separate <form>s, one per tab. Each form carries a hidden
# "tab" field so this route only ever writes the keys that tab actually owns — writing every
# key regardless of which form was submitted would silently blank out every OTHER tab's
# settings on every single save (e.g. saving Leveling would reset Auto-Mod/Welcome to empty).
_TAB_TEXT_KEYS = {
    "config": [
        "welcome_channel", "welcome_message", "leave_channel", "leave_message", "autorole",
        "welcome_card_circle_color", "welcome_card_text_color", "welcome_card_username_color",
    ],
    "leveling": [
        "level_channel", "leveling_voice_xp_per_min", "leveling_role_mode",
        "leveling_curve_quad", "leveling_curve_linear", "leveling_curve_base",
        "leveling_voice_curve_quad", "leveling_voice_curve_linear", "leveling_voice_curve_base",
    ],
    "automod": [
        "automod_spam_threshold", "automod_spam_window", "automod_timeout_minutes",
        "automod_banned_words", "automod_action", "automod_warn_message",
    ],
    "birthday": ["birthday_channel", "birthday_message"],
    # The reminder DMs themselves (offset + message, plural) are a separate list managed via
    # their own add/delete routes below, not a fixed set of form fields - only the required
    # role and the single final kick delay go through the generic per-tab save here.
    "autokick": ["auto_kick_role_id", "auto_kick_kick_hours"],
}
_TAB_CHECKBOX_KEYS = {
    "config": ["welcome_card_enabled"],
    "leveling": ["leveling_enabled", "leveling_voice_enabled"],
    "automod": ["automod_enabled", "automod_links"],
    "birthday": [],
    # auto_kick_enabled deliberately NOT here - it needs the previous saved value to detect an
    # off→on transition (see the dedicated handling in server_config_save below), the generic
    # loop below has no way to express that.
    "autokick": [],
}


@web.post("/servers/{guild_id}/features/save")
async def server_features_save(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    form = await request.form()
    selected = set(form.getlist("features")) & set(_TOGGLEABLE_FEATURES.keys())
    # Deliberately allowed to be an empty string (every checkbox unticked, hide all optional
    # tabs) - _get_enabled_features() only falls back to "show everything" when the key was
    # NEVER saved at all, not when it was explicitly saved empty.
    await set_guild_config(guild_id, "enabled_features", ",".join(sorted(selected)))
    return RedirectResponse(f"/servers/{guild_id}?tab=config&success=Gespeichert", status_code=302)


@web.post("/servers/{guild_id}")
async def server_config_save(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    tab = str(form.get("tab", "config"))
    if tab not in _TAB_TEXT_KEYS:
        tab = "config"

    # Channel-valued keys are validated against the guild's own channels before saving -
    # some are resolved later via a global bot.get_channel() (not guild-scoped), so an
    # unvalidated ID here could otherwise make the bot post into a channel in a different
    # guild served by the same token.
    channel_keys = ["welcome_channel", "leave_channel", "birthday_channel", "level_channel"]
    valid_channel_ids = {str(c.id) for c in guild.text_channels}
    for key in channel_keys:
        value = str(form.get(key, ""))
        if value and value not in valid_channel_ids:
            return RedirectResponse(
                f"/servers/{guild_id}?tab={tab}&error=Ungültiger+Kanal+({key})", status_code=302
            )

    # autorole went through the generic save loop below with no validation at all - unlike the
    # channel keys above, it isn't even guild-scoped-safe by construction (get_role() degrades
    # to a silent no-op for a wrong ID, but a non-numeric value saved via a raw POST would raise
    # an unhandled ValueError in welcome.py's on_member_join for every future join).
    role_keys = ["autorole", "auto_kick_role_id"]
    valid_role_ids = {str(ro.id) for ro in guild.roles if not ro.is_default()}
    for key in role_keys:
        value = str(form.get(key, ""))
        if value and value not in valid_role_ids:
            return RedirectResponse(
                f"/servers/{guild_id}?tab={tab}&error=Ungültige+Rolle+({key})", status_code=302
            )

    # (form key, min, max, error label)
    numeric_fields = [
        ("automod_spam_threshold", 2, 30, "Spam-Schwellenwert"),
        ("automod_spam_window", 1, 60, "Spam-Zeitfenster"),
        ("automod_timeout_minutes", 1, 40320, "Timeout-Dauer"),  # Discord's max timeout is 28 days
        ("leveling_voice_xp_per_min", 1, 100, "Voice-XP pro Minute"),
        # base must stay >= 1 - with quad=linear=base=0, xp_for_level(level) would always be 0
        # and level_from_xp() would loop forever on any non-negative xp.
        ("leveling_curve_quad", 0, 1000, "Level-Kurve (quadratisch)"),
        ("leveling_curve_linear", 0, 10000, "Level-Kurve (linear)"),
        ("leveling_curve_base", 1, 100000, "Level-Kurve (Basis-XP)"),
        ("leveling_voice_curve_quad", 0, 1000, "Voice-Level-Kurve (quadratisch)"),
        ("leveling_voice_curve_linear", 0, 10000, "Voice-Level-Kurve (linear)"),
        ("leveling_voice_curve_base", 1, 100000, "Voice-Level-Kurve (Basis-XP)"),
        # 720h = 30 days, same generous-but-bounded ceiling as automod_timeout_minutes above -
        # long enough for any realistic grace period, short enough to reject an obvious typo.
        ("auto_kick_kick_hours", 1, 720, "Kick-Frist (Auto-Kick)"),
    ]
    for field, lo, hi, label in numeric_fields:
        value = str(form.get(field, "")).strip()
        if value:
            try:
                if not (lo <= int(value) <= hi):
                    raise ValueError
            except ValueError:
                return RedirectResponse(
                    f"/servers/{guild_id}?tab={tab}&error=Ungültiger+Wert+({label})", status_code=302
                )

    if tab == "autokick" and form.get("auto_kick_enabled"):
        # Every OTHER required-together-with-"enabled" case in this route (channel_keys,
        # role_keys above) only rejects an INVALID value, not a genuinely EMPTY one - correct
        # for those, since an empty channel/role there just means "not using that optional
        # feature". Here an empty role/kick-hours with the checkbox ticked would instead
        # silently do nothing at all: cogs/auto_kick.py's _get_config() already fails safe and
        # no-ops without both, so nothing crashes, but the admin would see the checkbox checked
        # and quietly get no reminders or kicks ever, with no error anywhere telling them why -
        # reject up front instead, before anything gets saved. kick_hours is normally always
        # pre-filled by the template's own default and has no "clear it" affordance in the UI
        # (unlike the role dropdown's empty placeholder option), so this half is defense in
        # depth against a hand-crafted request more than something the rendered form itself
        # can trigger - kept for the same reason the role check exists, not because it's
        # equally reachable by accident.
        if not str(form.get("auto_kick_role_id", "")).strip():
            return RedirectResponse(
                f"/servers/{guild_id}?tab={tab}&error=Bitte+eine+Rolle+für+Auto-Kick+auswählen", status_code=302
            )
        if not str(form.get("auto_kick_kick_hours", "")).strip():
            return RedirectResponse(
                f"/servers/{guild_id}?tab={tab}&error=Bitte+eine+Kick-Frist+für+Auto-Kick+angeben", status_code=302
            )

    for key in _TAB_TEXT_KEYS[tab]:
        await set_guild_config(guild_id, key, str(form.get(key, "")))
    for key in _TAB_CHECKBOX_KEYS[tab]:
        await set_guild_config(guild_id, key, "1" if form.get(key) else "0")
    if tab == "leveling":
        # Multi-select, needs form.getlist() - can't go through the generic single-value loop above.
        leveling_channels = ",".join(c for c in form.getlist("leveling_channels") if c in valid_channel_ids)
        await set_guild_config(guild_id, "leveling_channels", leveling_channels)
    if tab == "autokick":
        # Only members who join AFTER this is turned on are ever subject to it (explicit
        # request - avoids sweeping up existing untagged members the instant this is enabled).
        # That means the "on" timestamp has to be tracked and only refreshed on a genuine
        # off→on transition, never on a save that just tweaks the role/kick delay while already
        # on - otherwise every settings tweak would silently exempt everyone who joined before
        # that particular save.
        was_enabled = await get_guild_config(guild_id, "auto_kick_enabled") == "1"
        now_enabled = bool(form.get("auto_kick_enabled"))
        if now_enabled and not was_enabled:
            await set_guild_config(
                guild_id, "auto_kick_enabled_at",
                datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )
        await set_guild_config(guild_id, "auto_kick_enabled", "1" if now_enabled else "0")
    return RedirectResponse(f"/servers/{guild_id}?tab={tab}&saved=true", status_code=303)


# ── Auto-Kick reminders ──────────────────────────────────────────────────────
# One or more DM reminders at admin-configured offsets after joining, leading up to the single
# kick delay saved via the generic tab form above - user-requested ("mach das so das man mehrer
# zeiten einstelen kann") after the first version only supported one fixed warning.

@web.post("/servers/{guild_id}/auto-kick/reminders/add")
async def auto_kick_reminder_add(request: Request, guild_id: int, hours: str = Form(...), message: str = Form(...)):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    message = message.strip()
    if not message:
        return RedirectResponse(f"/servers/{guild_id}?tab=autokick&error=Nachricht+erforderlich", status_code=302)
    # Discord's hard limit for a normal (non-embed) message is 2000 characters. Unchecked, a
    # too-long reminder would fail on every single send - and completely silently: cogs/
    # auto_kick.py's _remind_if_needed() catches discord.HTTPException with a bare `pass`
    # (deliberately, so a member with DMs closed doesn't get retried forever) and marks the
    # reminder as sent regardless of whether it actually went out, so a too-long message would
    # never surface anywhere, for any member, ever - same bug class already fixed for custom
    # commands' response text and giveaway prize text elsewhere in this project.
    #
    # Capped well under 2000, not just barely under it - {server} alone can grow by up to ~92
    # characters once substituted with a real (up to 100-char) server name, {user} a further
    # ~15 as a real mention. A first attempt at this cap used 1900, which still isn't safe: a
    # message using BOTH placeholders once each can grow by ~107, landing at ~2007 - over the
    # limit despite the "margin". 1850 leaves real headroom for that combination instead of
    # just barely missing it - same "leave a safety margin for variable substitution" principle
    # already applied to ticket panel descriptions elsewhere in this project, just computed
    # more carefully here after the first pass undercounted it.
    if len(message) > 1850:
        return RedirectResponse(f"/servers/{guild_id}?tab=autokick&error=Nachricht+zu+lang+(max.+1850+Zeichen)", status_code=302)
    try:
        hours_int = int(hours)
        if not (1 <= hours_int <= 720):
            raise ValueError
    except ValueError:
        return RedirectResponse(f"/servers/{guild_id}?tab=autokick&error=Ungültige+Stundenzahl", status_code=302)
    await db_exec(
        "INSERT INTO auto_kick_reminders (guild_id, hours, message) VALUES (?,?,?)",
        (str(guild_id), hours_int, message),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=autokick&success=Erinnerung+hinzugefügt", status_code=303)


@web.post("/servers/{guild_id}/auto-kick/reminders/delete/{reminder_id}")
async def auto_kick_reminder_delete(request: Request, guild_id: int, reminder_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    await db_exec(
        "DELETE FROM auto_kick_reminders WHERE id=? AND guild_id=?", (reminder_id, str(guild_id))
    )
    # auto_kick_reminders.id is never reused (AUTOINCREMENT), so leaving these rows behind
    # couldn't cause a future reminder to wrongly inherit "already sent" tracking - but they'd
    # otherwise just sit there forever with nothing left to reference, pure leftover data for
    # a reminder that no longer exists (user-requested cleanup, "daten reste loss werden").
    await db_exec(
        "DELETE FROM auto_kick_sent WHERE guild_id=? AND reminder_id=?", (str(guild_id), reminder_id)
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=autokick&success=Erinnerung+entfernt", status_code=303)


# ── Auto-Mod word-list presets ──────────────────────────────────────────────────

@web.post("/servers/{guild_id}/automod-presets/create")
async def automod_preset_create(request: Request, guild_id: int, label: str = Form(...), words: str = Form(...)):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    label = label.strip()
    words = words.strip()
    if not label or not words:
        return RedirectResponse(f"/servers/{guild_id}?tab=automod&error=Name+und+Wörter+erforderlich", status_code=302)
    await db_exec(
        "INSERT INTO automod_word_presets (guild_id, label, words) VALUES (?,?,?)",
        (str(guild_id), label, words),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=automod&success=Kategorie+erstellt", status_code=303)


@web.post("/servers/{guild_id}/automod-presets/edit/{preset_id}")
async def automod_preset_edit(request: Request, guild_id: int, preset_id: int, label: str = Form(...), words: str = Form(...)):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    label = label.strip()
    words = words.strip()
    if not label or not words:
        return RedirectResponse(f"/servers/{guild_id}?tab=automod&error=Name+und+Wörter+erforderlich", status_code=302)
    await db_exec(
        "UPDATE automod_word_presets SET label=?, words=? WHERE id=? AND guild_id=?",
        (label, words, preset_id, str(guild_id)),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=automod&success=Kategorie+aktualisiert", status_code=303)


@web.post("/servers/{guild_id}/automod-presets/delete/{preset_id}")
async def automod_preset_delete(request: Request, guild_id: int, preset_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    await db_exec(
        "DELETE FROM automod_word_presets WHERE id=? AND guild_id=?", (preset_id, str(guild_id))
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=automod&success=Kategorie+gelöscht", status_code=303)


# ── Level roles ──────────────────────────────────────────────────────────────

async def _retroactive_level_role_sync(guild_id: int, level_int: int):
    # A newly added level-role should also reach members who already qualify, not just show up
    # on their next level-up - otherwise the "catches up on skipped levels" guarantee only holds
    # going forward. Runs as a background task (see call site) so adding a role doesn't block the
    # dashboard on however many Discord API calls a big member list turns into.
    b = bot._bot_for_guild(guild_id)
    if not b:
        return
    cog = b.get_cog("Leveling")
    guild = b.get_guild(guild_id)
    if not cog or not guild:
        return
    rows = await db_rows(
        "SELECT user_id FROM levels WHERE guild_id=? AND (level>=? OR voice_level>=?)",
        (guild_id, level_int, level_int),
    )
    for row in rows:
        member = guild.get_member(row["user_id"])
        if member:
            await cog._sync_level_roles(member)


@web.post("/servers/{guild_id}/level-roles/add")
async def level_role_add(request: Request, guild_id: int, level: str = Form(...), role_id: str = Form(...)):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    valid_role_ids = {str(ro.id) for ro in guild.roles if not ro.is_default()}
    if role_id not in valid_role_ids:
        return RedirectResponse(f"/servers/{guild_id}?tab=leveling&error=Ungültige+Rolle", status_code=302)
    try:
        level_int = int(level)
        if not (1 <= level_int <= 1000):
            raise ValueError
    except ValueError:
        return RedirectResponse(f"/servers/{guild_id}?tab=leveling&error=Ungültiges+Level", status_code=302)
    # A bare `except Exception` around the INSERT used to stand in for "level already has a
    # role" (the UNIQUE(guild_id, level) constraint) - too broad, since it would misattribute
    # any other, unrelated DB failure as "already assigned" too. Checked explicitly instead.
    if await db_one("SELECT 1 FROM level_roles WHERE guild_id=? AND level=?", (str(guild_id), level_int)):
        return RedirectResponse(
            f"/servers/{guild_id}?tab=leveling&error=Für+dieses+Level+ist+schon+eine+Rolle+vergeben",
            status_code=302,
        )
    await db_exec(
        "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?,?,?)",
        (str(guild_id), level_int, role_id),
    )
    asyncio.create_task(_retroactive_level_role_sync(guild_id, level_int))
    return RedirectResponse(f"/servers/{guild_id}?tab=leveling&success=Level-Rolle+hinzugefügt", status_code=303)


@web.post("/servers/{guild_id}/level-roles/delete/{role_row_id}")
async def level_role_delete(request: Request, guild_id: int, role_row_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    await db_exec(
        "DELETE FROM level_roles WHERE id=? AND guild_id=?", (role_row_id, str(guild_id))
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=leveling&success=Level-Rolle+entfernt", status_code=303)


# ── Level rewards ────────────────────────────────────────────────────────────
# Free-text prizes (Discord Nitro, a game key, a subscription, ...) tied to a level - purely
# informational, the bot only announces them, fulfillment is always manual/off-platform.

@web.post("/servers/{guild_id}/level-rewards/add")
async def level_reward_add(request: Request, guild_id: int, level: str = Form(...), reward: str = Form(...)):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    reward = reward.strip()
    if not reward:
        return RedirectResponse(f"/servers/{guild_id}?tab=leveling&error=Belohnung+erforderlich", status_code=302)
    if len(reward) > 1000:
        # Goes straight into an embed field value in _announce_levelup() - Discord's hard limit
        # there is 1024 characters. That's already caught by that function's own try/except (it
        # would just log and silently skip the whole level-up announcement, not crash), but
        # rejecting it here up front matches the maxlength on the form field and gives the
        # admin an actual error instead of a level-up that silently never announces again.
        return RedirectResponse(f"/servers/{guild_id}?tab=leveling&error=Belohnung+zu+lang+(max.+1000+Zeichen)", status_code=302)
    try:
        level_int = int(level)
        if not (1 <= level_int <= 1000):
            raise ValueError
    except ValueError:
        return RedirectResponse(f"/servers/{guild_id}?tab=leveling&error=Ungültiges+Level", status_code=302)
    # Same fix as level_role_add above: an explicit existence check instead of a bare
    # `except Exception` standing in for the UNIQUE(guild_id, level) constraint, so an
    # unrelated DB failure can't get misreported as "already assigned".
    if await db_one("SELECT 1 FROM level_rewards WHERE guild_id=? AND level=?", (str(guild_id), level_int)):
        return RedirectResponse(
            f"/servers/{guild_id}?tab=leveling&error=Für+dieses+Level+ist+schon+eine+Belohnung+vergeben",
            status_code=302,
        )
    await db_exec(
        "INSERT INTO level_rewards (guild_id, level, reward) VALUES (?,?,?)",
        (str(guild_id), level_int, reward),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=leveling&success=Belohnung+hinzugefügt", status_code=303)


@web.post("/servers/{guild_id}/level-rewards/delete/{reward_row_id}")
async def level_reward_delete(request: Request, guild_id: int, reward_row_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    await db_exec(
        "DELETE FROM level_rewards WHERE id=? AND guild_id=?", (reward_row_id, str(guild_id))
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=leveling&success=Belohnung+entfernt", status_code=303)


# ── Reset a member's XP ──────────────────────────────────────────────────────
# Wipes the whole row (chat + voice XP/level, message/voice-minute counters) - unlike
# /setxp there's no way to reset just one track from the dashboard, matching how this is
# presented in the leaderboard table as one combined "remove this member" action.

@web.post("/servers/{guild_id}/levels/delete/{user_id}")
async def levels_delete(request: Request, guild_id: int, user_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/?error=Keine+Berechtigung", status_code=302)
    await db_exec(
        "DELETE FROM levels WHERE user_id=? AND guild_id=?", (user_id, guild_id)
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=leveling&success=XP+zurückgesetzt", status_code=303)


# ── Ticket Panels ────────────────────────────────────────────────────────────

def _parse_ticket_blocks(raw) -> list:
    """A ticket_panels.description/ticket_message value is either a legacy plain string
    (pre-dates the multi-embed "+" feature - treated as a single block) or a JSON array of
    block strings, each of which becomes its OWN Discord embed when sent ("es ist bewusst zwei
    einbettungen ... wenn ich bei den text + mache das es auch eine neuen einbettung ist" -
    explicit user request for "+" to add a genuinely separate embed, not just another line
    inside the same one). Always returns a list (possibly empty) - never raises on malformed
    JSON, a plain non-list value, or a list containing non-string items."""
    if not raw:
        return []
    try:
        data = _djson.loads(raw)
        if isinstance(data, list) and all(isinstance(b, str) for b in data):
            return [b for b in data if b.strip()]
    except (ValueError, TypeError):
        pass
    return [raw]


def _build_panel_embeds(name: str, emoji: str, description_raw) -> list:
    """One discord.Embed per block (see _parse_ticket_blocks) - only the first carries the
    panel's title/emoji, the rest are plain description-only cards. Capped at 10, Discord's own
    hard limit on embeds per message (also enforced at save time in tickets_panel_update, this
    is just defense in depth against stale/malformed data)."""
    blocks = _parse_ticket_blocks(description_raw) or ["Klicke unten um ein Ticket zu öffnen."]
    embeds = []
    for i, block in enumerate(blocks[:10]):
        e = discord.Embed(description=block, color=0x7C3AED)
        if i == 0:
            e.title = f"{emoji} {name}"
        embeds.append(e)
    return embeds


@web.post("/servers/{guild_id}/tickets/panels/create")
async def tickets_panel_create(request: Request, guild_id: int, name: str = Form(...)):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    name = name.strip()
    if not name:
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Name+erforderlich", status_code=302)
    if len(name) > 100:
        # The name ends up as (part of) a Discord embed title ("{emoji} {name}") when the
        # panel is published - Discord's hard limit there is 256 characters, and until now
        # nothing enforced any limit here at all. A too-long name wouldn't just look bad, it
        # would make /publish's channel.send() raise and (before this fix) crash the whole
        # request with an unhandled 500 instead of a friendly error.
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Name+zu+lang+(max.+100+Zeichen)", status_code=302)
    await db_exec(
        "INSERT INTO ticket_panels (guild_id, name, button_label, description, ticket_message, emoji) VALUES (?,?,?,?,?,?)",
        (guild_id, name, "Ticket öffnen",
         _djson.dumps(["Klicke unten um ein Ticket zu öffnen."]),
         _djson.dumps(["Beschreibe dein Anliegen und wir helfen dir so schnell wie möglich."]), "🎫"),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=tickets&success=Panel+erstellt", status_code=302)


@web.post("/servers/{guild_id}/tickets/panels/{panel_id}/update")
async def tickets_panel_update(request: Request, guild_id: int, panel_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    name = form.get("name", "")
    button_label = form.get("button_label", "Ticket öffnen")
    emoji = form.get("emoji", "🎫")
    support_role_id = form.get("support_role_id", "")
    category_id = form.get("category_id", "")
    archive_category_id = form.get("archive_category_id", "")
    # Each is a LIST of blocks now, one <textarea> per block in the form - "+" adds a genuinely
    # separate Discord embed, not just another line inside the same one ("es ist bewusst zwei
    # einbettungen ... wenn ich bei den text + mache das es auch eine neuen einbettung ist").
    # An earlier "+"-addable-LINES version (v1.14.57/59) turned out to mangle any already
    # richly formatted, multi-paragraph text pasted into a single block (every one of its own
    # newlines became a separate row) - each block here is its own free-form multi-line
    # textarea, shown/edited exactly as saved, only the block BOUNDARY is "+"-controlled.
    # ticket_message is independent of description (added right after, "das mann in den tiket
    # eine eigene nachricht verfassen kann") - previously the SAME description text was reused
    # verbatim inside every newly created ticket (cogs/tickets.py's _create_ticket), now it's
    # its own field so a long panel-advertisement text doesn't have to repeat inside the ticket.
    description_blocks = [b.strip() for b in form.getlist("description_block") if b.strip()]
    ticket_message_blocks = [b.strip() for b in form.getlist("ticket_message_block") if b.strip()]
    if support_role_id and support_role_id not in {str(ro.id) for ro in guild.roles}:
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Ungültige+Rolle", status_code=302)
    if category_id and category_id not in {str(c.id) for c in guild.categories}:
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Ungültige+Kategorie", status_code=302)
    if archive_category_id and archive_category_id not in {str(c.id) for c in guild.categories}:
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Ungültige+Archiv-Kategorie", status_code=302)
    if len(name.strip()) > 100:
        # Same reasoning as tickets_panel_create - ends up in the embed title.
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Name+zu+lang+(max.+100+Zeichen)", status_code=302)
    if len(button_label.strip()) > 80:
        # Discord's own hard limit for a button's label - exceeding it makes ch.send()/msg.edit()
        # raise, which (before this fix) would have crashed /publish's request with an
        # unhandled 500 instead of a friendly error.
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Button-Text+zu+lang+(max.+80+Zeichen)", status_code=302)
    # Discord's own hard cap on embeds per single message - a manually crafted POST could
    # otherwise submit more "+" blocks than the UI itself ever lets you add, which would make
    # every future channel.send(embeds=...) for this panel raise (caught, but with no
    # obvious cause for the admin - same reasoning as the per-block length checks below).
    if len(description_blocks) > 10:
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Zu+viele+Beschreibungs-Embeds+(max.+10)", status_code=302)
    if len(ticket_message_blocks) > 10:
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Zu+viele+Embeds+in+der+Ticket-Nachricht+(max.+10)", status_code=302)
    if any(len(b) > 3900 for b in description_blocks):
        # Each block becomes its OWN embed's description now - Discord's hard limit per embed
        # description is 4096 characters, kept at the same 3900-character cushion as before the
        # description/ticket_message split (this field carries no placeholder substitution).
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Ein+Beschreibungs-Embed+ist+zu+lang+(max.+3900+Zeichen)", status_code=302)
    if any(len(b) > 3900 for b in ticket_message_blocks):
        # Same per-embed 4096-character hard limit, cushioned to 3900 to leave room for
        # {user}/{server} placeholder substitution growth (cogs/tickets.py's
        # _fill_ticket_placeholders, applied per block at send time - can only ever GROW a
        # block, never shrink it). A too-long block wouldn't break /publish (that route doesn't
        # use this field at all), it would instead make channel.send() fail silently for every
        # future ticket creation from this panel - already caught by _create_ticket's own broad
        # try/except (cleanup + a generic "couldn't create ticket" message), but with no way for
        # the admin to tell WHY from that message alone. Rejecting it here is better than a
        # mystery failure at every ticket open attempt.
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Ein+Embed+in+der+Ticket-Nachricht+ist+zu+lang+(max.+3900+Zeichen)", status_code=302)
    panel_before = await db_one("SELECT * FROM ticket_panels WHERE id=? AND guild_id=?", (panel_id, guild_id))
    new_name = name.strip()
    new_label = button_label.strip() or "Ticket öffnen"
    new_emoji = emoji.strip() or "🎫"
    new_description = _djson.dumps(description_blocks)
    new_ticket_message = _djson.dumps(ticket_message_blocks)
    await db_exec(
        "UPDATE ticket_panels SET name=?, button_label=?, description=?, ticket_message=?, emoji=?, "
        "support_role_id=?, category_id=?, archive_category_id=? WHERE id=? AND guild_id=?",
        (new_name, new_label, new_description, new_ticket_message, new_emoji,
         support_role_id, category_id, archive_category_id, panel_id, guild_id),
    )
    # A published panel's button/embed lives on an already-sent Discord message - saving name/
    # button_label/emoji/description here only touched the DB row until now, so the dashboard
    # showed the new values as "saved" while the live message kept showing the stale ones. If
    # the panel is currently published, edit the live message in place to match.
    if panel_before and panel_before.get("status") == "published" and panel_before.get("channel_id") and panel_before.get("message_id"):
        b = bot._bot_for_guild(guild_id)
        if b:
            try:
                ch = b.get_channel(int(panel_before["channel_id"]))
                if ch:
                    msg = await ch.fetch_message(int(panel_before["message_id"]))
                    embeds = _build_panel_embeds(new_name, new_emoji, new_description)
                    view = _TicketView(panel_id, new_label, new_emoji)
                    await msg.edit(embeds=embeds, view=view)
                    b.add_view(view)
            except Exception:
                pass
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
    if not ch or ch.guild.id != guild_id:
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
    embeds = _build_panel_embeds(panel["name"], emoji, panel.get("description"))
    try:
        view = _TicketView(panel_id, label, emoji)
        msg = await ch.send(embeds=embeds, view=view)
    except Exception as e:
        # Nothing here was guarded before - an invalid emoji string (view construction itself
        # can raise), a name/label that's since grown past Discord's title/button-label limits,
        # or the bot simply missing "Embed Links"/"Send Messages" in the target channel would
        # all have crashed this request with an unhandled 500 instead of a normal error redirect.
        print(f"[Tickets] publish failed for panel {panel_id}: {e}")
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Veröffentlichen+fehlgeschlagen", status_code=302)
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
    # This only ever flipped the DB status - the live Discord message (with its still-fully-
    # working button) was never touched, so "deactivating" a panel here had zero effect on
    # what users actually saw/could click in Discord. Now deleted like publish/delete already do.
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
    if not ticket:
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Ticket+nicht+gefunden", status_code=302)
    b = bot._bot_for_guild(guild_id)
    if not b:
        # Without a live bot instance we can't tell whether the channel still exists, let
        # alone delete it - marking the ticket closed anyway would leave the channel orphaned
        # with no way to retry the deletion later (the dashboard ticket list only shows
        # status='open' rows), same failure mode already fixed for giveaway_end_web.
        return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Bot+nicht+online", status_code=302)
    ch = b.get_channel(ticket["channel_id"])
    if ch:
        guild_obj = b.get_guild(guild_id)
        panel = await db_one(
            "SELECT archive_category_id FROM ticket_panels WHERE id=?", (ticket["panel_id"],)
        ) if ticket.get("panel_id") else None
        # Same reasoning as the "bot not online" branch above: if the channel is still there and
        # we couldn't actually close it (e.g. missing permission right now), don't mark the
        # ticket closed - that would hide it from the open-tickets list with no way to retry.
        if not await _close_ticket_channel(ch, guild_obj, panel, "Ticket via Dashboard geschlossen"):
            return RedirectResponse(f"/servers/{guild_id}?tab=tickets&error=Ticket+konnte+nicht+geschlossen+werden", status_code=302)
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


# ── Embed Posts ──────────────────────────────────────────────────────────────
# User-requested ("ich will damit texte in schanels dort eintragen im bot ist es einfacher die
# zu bearbeiten also in dc selber deswegen sowas wo ich die chanels auswählen kann und der das
# dan einbettet") - a standalone rich-text/embed poster, independent of tickets/events/anything
# else: pick a channel, write one or more embed blocks (same "+"-adds-a-separate-embed model as
# ticket_panels' description/ticket_message, same JSON-array-of-blocks storage via
# _parse_ticket_blocks), the bot posts it - and unlike a manual Discord message, it stays
# editable from the dashboard afterward (the actual point: editing multi-line rich text in a
# browser textarea beats Discord's own message box, which has no native embed authoring at all).

def _build_freeform_embeds(content_raw, image_url: str = "", footer_text: str = "") -> list:
    """Like _build_panel_embeds, but with no forced title/emoji on the first embed - this
    feature has no "name" concept baked into the posted content itself (unlike a ticket panel,
    which always shows its configured name+emoji as a title), it's meant to stay fully
    freeform. Capped at 10 blocks, same Discord hard limit as everywhere else blocks are used.
    image/footer are per-POST, not per-block (confirmed by explicit user answer - Discord
    itself only supports them per individual embed, so they land on the LAST embed rather than
    needing one field per "+"-added block)."""
    blocks = _parse_ticket_blocks(content_raw) or [""]
    embeds = [discord.Embed(description=block, color=0x7C3AED) for block in blocks[:10]]
    if image_url:
        embeds[-1].set_image(url=image_url)
    if footer_text:
        embeds[-1].set_footer(text=footer_text)
    return embeds


@web.post("/servers/{guild_id}/embeds/create")
async def embed_post_create(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Server+nicht+gefunden", status_code=302)
    form = await request.form()
    name = form.get("name", "").strip()
    channel_id = form.get("channel_id", "")
    blocks = [b.strip() for b in form.getlist("content_block") if b.strip()]
    image_url = form.get("image_url", "").strip()
    footer_text = form.get("footer_text", "").strip()
    if not name:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Name+erforderlich", status_code=302)
    if len(name) > 100:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Name+zu+lang+(max.+100+Zeichen)", status_code=302)
    if channel_id not in {str(c.id) for c in guild.text_channels}:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Ungültiger+Kanal", status_code=302)
    if not blocks:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Mindestens+ein+Embed+erforderlich", status_code=302)
    if len(blocks) > 10:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Zu+viele+Embeds+(max.+10)", status_code=302)
    if any(len(b) > 3900 for b in blocks):
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Ein+Embed+ist+zu+lang+(max.+3900+Zeichen)", status_code=302)
    # Discord's per-embed 4096-char description limit (cushioned to 3900 above) is separate
    # from its OTHER hard limit: title+description+footer+field text summed across ALL embeds
    # in one message must stay under 6000 - easily reachable here since up to 10 blocks are
    # each allowed close to 3900 chars (10*3900 far exceeds 6000). Without this check, Discord
    # would reject the send() call outright and the admin would see a raw, confusing
    # "Discord-Fehler:" instead of a clear cause - checked with a safety margin (5900) for the
    # footer text that also counts toward the same combined total.
    if sum(len(b) for b in blocks) + len(footer_text) > 5900:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Alle+Embeds+zusammen+sind+zu+lang+(max.+5900+Zeichen+insgesamt)", status_code=302)
    if image_url and not image_url.startswith(("http://", "https://")):
        # Discord's API rejects a non-URL image value outright - caught here with a clear
        # cause instead of a raw "Discord-Fehler:" surfacing the API's own wording.
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Bild-URL+muss+mit+http(s)://+beginnen", status_code=302)
    if len(footer_text) > 2048:
        # Discord's own hard limit for embed footer text.
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Footer-Text+zu+lang+(max.+2048+Zeichen)", status_code=302)
    channel = guild.get_channel(int(channel_id))
    if not channel:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Kanal+nicht+gefunden", status_code=302)
    content = _djson.dumps(blocks)
    try:
        msg = await channel.send(embeds=_build_freeform_embeds(content, image_url, footer_text))
    except discord.HTTPException as e:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Discord-Fehler:+{e.text}", status_code=302)
    await db_exec(
        "INSERT INTO embed_posts (guild_id, name, channel_id, content, message_id, image_url, footer_text) "
        "VALUES (?,?,?,?,?,?,?)",
        (str(guild_id), name, channel_id, content, str(msg.id), image_url, footer_text),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=embeds&success=Gepostet", status_code=302)


@web.post("/servers/{guild_id}/embeds/{post_id}/update")
async def embed_post_update(request: Request, guild_id: int, post_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Server+nicht+gefunden", status_code=302)
    post = await db_one("SELECT * FROM embed_posts WHERE id=? AND guild_id=?", (post_id, guild_id))
    if not post:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Nicht+gefunden", status_code=302)
    form = await request.form()
    name = form.get("name", "").strip()
    channel_id = form.get("channel_id", "")
    blocks = [b.strip() for b in form.getlist("content_block") if b.strip()]
    image_url = form.get("image_url", "").strip()
    footer_text = form.get("footer_text", "").strip()
    if not name:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Name+erforderlich", status_code=302)
    if len(name) > 100:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Name+zu+lang+(max.+100+Zeichen)", status_code=302)
    if channel_id not in {str(c.id) for c in guild.text_channels}:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Ungültiger+Kanal", status_code=302)
    if not blocks:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Mindestens+ein+Embed+erforderlich", status_code=302)
    if len(blocks) > 10:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Zu+viele+Embeds+(max.+10)", status_code=302)
    if any(len(b) > 3900 for b in blocks):
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Ein+Embed+ist+zu+lang+(max.+3900+Zeichen)", status_code=302)
    # Same combined-total check as embed_post_create - see the comment there.
    if sum(len(b) for b in blocks) + len(footer_text) > 5900:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Alle+Embeds+zusammen+sind+zu+lang+(max.+5900+Zeichen+insgesamt)", status_code=302)
    if image_url and not image_url.startswith(("http://", "https://")):
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Bild-URL+muss+mit+http(s)://+beginnen", status_code=302)
    if len(footer_text) > 2048:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Footer-Text+zu+lang+(max.+2048+Zeichen)", status_code=302)
    content = _djson.dumps(blocks)
    embeds = _build_freeform_embeds(content, image_url, footer_text)
    new_message_id = post["message_id"]
    if channel_id != post["channel_id"]:
        # Moved to a different channel - an embed lives on a specific message in a specific
        # channel, there's no "move a message to another channel" API, so this deletes the old
        # one (best-effort, it may already be gone) and posts fresh in the new channel instead.
        old_ch = guild.get_channel(int(post["channel_id"])) if post["channel_id"] else None
        if old_ch and post["message_id"]:
            try:
                old_msg = await old_ch.fetch_message(int(post["message_id"]))
                await old_msg.delete()
            except Exception:
                pass
        new_ch = guild.get_channel(int(channel_id))
        if not new_ch:
            return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Kanal+nicht+gefunden", status_code=302)
        try:
            msg = await new_ch.send(embeds=embeds)
        except discord.HTTPException as e:
            return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Discord-Fehler:+{e.text}", status_code=302)
        new_message_id = str(msg.id)
    else:
        ch = guild.get_channel(int(channel_id)) if channel_id else None
        if not ch:
            return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Kanal+nicht+gefunden", status_code=302)
        if post["message_id"]:
            try:
                msg = await ch.fetch_message(int(post["message_id"]))
                await msg.edit(embeds=embeds)
            except discord.NotFound:
                # The live message was deleted directly in Discord - repost it fresh instead of
                # silently leaving the saved content with no actual message behind it.
                try:
                    msg = await ch.send(embeds=embeds)
                    new_message_id = str(msg.id)
                except discord.HTTPException as e:
                    return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Discord-Fehler:+{e.text}", status_code=302)
            except Exception as e:
                return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Discord-Fehler:+{e}", status_code=302)
        else:
            # No live message yet - e.g. a post restored from a backup (message_id is never
            # trusted across a restore, same as ticket_panels). Post it fresh instead of
            # silently saving the new content with no actual Discord message behind it.
            try:
                msg = await ch.send(embeds=embeds)
                new_message_id = str(msg.id)
            except discord.HTTPException as e:
                return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Discord-Fehler:+{e.text}", status_code=302)
    await db_exec(
        "UPDATE embed_posts SET name=?, channel_id=?, content=?, message_id=?, image_url=?, footer_text=? "
        "WHERE id=? AND guild_id=?",
        (name, channel_id, content, new_message_id, image_url, footer_text, post_id, guild_id),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=embeds&success=Gespeichert", status_code=302)


@web.post("/servers/{guild_id}/embeds/{post_id}/delete")
async def embed_post_delete(request: Request, guild_id: int, post_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    post = await db_one("SELECT * FROM embed_posts WHERE id=? AND guild_id=?", (post_id, guild_id))
    if post and post.get("message_id") and post.get("channel_id"):
        try:
            guild = bot.get_guild(guild_id)
            ch = guild.get_channel(int(post["channel_id"])) if guild else None
            if ch:
                msg = await ch.fetch_message(int(post["message_id"]))
                await msg.delete()
        except Exception:
            pass
    await db_exec("DELETE FROM embed_posts WHERE id=? AND guild_id=?", (post_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=embeds&success=Gelöscht", status_code=302)


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
    emoji = emoji.strip()
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Bot+nicht+verbunden", status_code=302)
    try:
        channel_id_i, message_id_i, role_id_i = int(channel_id), int(message_id), int(role_id)
    except (ValueError, TypeError):
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Ungültige+Eingabe", status_code=302)
    # Neither the target channel nor the role were ever checked against this guild's actual
    # channels/roles before - the same cross-guild validation gap fixed for practically every
    # other channel/role picker in the project.
    channel = guild.get_channel(channel_id_i)
    if not channel:
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Kanal+nicht+gefunden", status_code=302)
    role = guild.get_role(role_id_i)
    if not role:
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Rolle+nicht+gefunden", status_code=302)
    try:
        msg = await channel.fetch_message(message_id_i)
    except Exception:
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Nachricht+nicht+gefunden", status_code=302)
    try:
        # This route never actually placed the reaction on the message at all - it only wrote
        # a DB row. /reactionrole-add in Discord does this already; without it, a reaction role
        # configured via the dashboard has nothing for anyone to click in Discord at all, unless
        # someone happens to react with that exact emoji themselves first.
        await msg.add_reaction(emoji)
    except (discord.HTTPException, discord.NotFound):
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Ungültiger+Emoji", status_code=302)
    # Same de-dup fix as the Discord command: without this, adding a second mapping for the
    # same message+emoji (e.g. to change the granted role) would silently never take effect,
    # since _handle_reaction only ever reads the first matching row.
    existing = await db_one(
        "SELECT id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
        (guild_id, message_id_i, emoji),
    )
    if existing:
        await db_exec("UPDATE reaction_roles SET role_id=?, channel_id=? WHERE id=?",
                       (role_id_i, channel_id_i, existing["id"]))
    else:
        await db_exec(
            "INSERT INTO reaction_roles (guild_id,channel_id,message_id,emoji,role_id) VALUES (?,?,?,?,?)",
            (guild_id, channel_id_i, message_id_i, emoji, role_id_i),
        )
    return RedirectResponse(f"/servers/{guild_id}?tab=rr&success=Reaction+Role+hinzugefügt", status_code=302)


@web.post("/servers/{guild_id}/reaction_roles/{rr_id}/delete")
async def rr_delete(request: Request, guild_id: int, rr_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    row = await db_one("SELECT * FROM reaction_roles WHERE id=? AND guild_id=?", (rr_id, guild_id))
    if row:
        # Best-effort: remove the bot's own reaction too, otherwise the emoji stays on the
        # message looking just as clickable as before, but silently does nothing afterwards.
        guild = bot.get_guild(guild_id)
        channel = guild.get_channel(row["channel_id"]) if guild else None
        if channel:
            try:
                msg = await channel.fetch_message(row["message_id"])
                await msg.remove_reaction(row["emoji"], guild.me)
            except Exception:
                pass
    await db_exec("DELETE FROM reaction_roles WHERE id=? AND guild_id=?", (rr_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=rr&success=Reaction+Role+gelöscht", status_code=302)


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
    if not trigger:
        return RedirectResponse(f"/servers/{guild_id}?tab=commands&error=Trigger+darf+nicht+leer+sein", status_code=302)
    b = bot._bot_for_guild(guild_id)
    if b and trigger in {c.name for c in b.commands}:
        # Same reasoning as the /addcommand slash command: this cog's on_message and
        # discord.py's own classic-command dispatcher (command_prefix="!") both run
        # independently for every message - a trigger matching a real command's name
        # (currently only "geburtstag") would fire both, sending two unrelated responses.
        return RedirectResponse(f"/servers/{guild_id}?tab=commands&error=Reservierter+Befehlsname", status_code=302)
    if len(response) > 2000:
        # Discord's hard limit for a plain message - on_message sends this as-is when the
        # command is triggered, so anything longer would silently never work (now also
        # caught defensively there, but rejecting it here lets the admin fix it immediately).
        return RedirectResponse(f"/servers/{guild_id}?tab=commands&error=Antwort+zu+lang+(max.+2000+Zeichen)", status_code=302)
    # Same fix as the /addcommand slash command: a bare `except Exception` around the INSERT
    # used to stand in for "trigger already exists", which could just as easily swallow an
    # unrelated DB error and still report success. Atomic upsert instead.
    await db_exec(
        "INSERT INTO custom_commands (guild_id,trigger,response) VALUES (?,?,?) "
        "ON CONFLICT(guild_id,trigger) DO UPDATE SET response=excluded.response",
        (guild_id, trigger, response),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=commands&success=Command+gespeichert", status_code=302)


@web.post("/servers/{guild_id}/commands/{cmd_id}/delete")
async def cmd_delete(request: Request, guild_id: int, cmd_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM custom_commands WHERE id=? AND guild_id=?", (cmd_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=commands&success=Command+gelöscht", status_code=302)


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
    if winners < 1:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=giveaways&error=Anzahl+Gewinner+muss+mindestens+1+sein", status_code=302
        )
    if duration < 1:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=giveaways&error=Dauer+muss+mindestens+1+Minute+sein", status_code=302
        )
    if len(prize) > 240:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=giveaways&error=Preis+darf+max.+240+Zeichen+lang+sein", status_code=302
        )
    try:
        channel = bot.get_channel(int(channel_id))
    except (ValueError, TypeError):
        channel = None
    if not channel or channel.guild.id != guild_id:
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
    b = bot._bot_for_guild(guild_id)
    cog = b.cogs.get("Giveaways") if b else None
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
    g = await db_one("SELECT id FROM giveaways WHERE id=? AND guild_id=?", (gid, guild_id))
    if not g:
        return RedirectResponse(f"/servers/{guild_id}?tab=giveaways&error=Giveaway+nicht+gefunden", status_code=302)
    b = bot._bot_for_guild(guild_id)
    cog = b.cogs.get("Giveaways") if b else None
    if not cog:
        return RedirectResponse(f"/servers/{guild_id}?tab=giveaways&error=Bot+nicht+online", status_code=302)
    await cog._end_giveaway(gid)
    return RedirectResponse(f"/servers/{guild_id}?tab=giveaways", status_code=302)


@web.post("/servers/{guild_id}/giveaways/{gid}/reroll")
async def giveaway_reroll_web(request: Request, guild_id: int, gid: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    b = bot._bot_for_guild(guild_id)
    cog = b.cogs.get("Giveaways") if b else None
    if not cog:
        return RedirectResponse(f"/servers/{guild_id}?tab=giveaways&error=Bot+nicht+online", status_code=302)
    await db_exec("UPDATE giveaways SET ended=0 WHERE id=? AND guild_id=?", (gid, guild_id))
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
async def api_actions(request: Request):
    if r := admin_redirect(request):
        return JSONResponse({"error": "Keine Berechtigung"}, status_code=401)
    return await db_rows("SELECT * FROM mod_actions ORDER BY timestamp DESC LIMIT 100")


@web.get("/api/guilds")
async def api_guilds(request: Request):
    if r := admin_redirect(request):
        return JSONResponse({"error": "Keine Berechtigung"}, status_code=401)
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
