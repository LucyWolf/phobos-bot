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

# Wie viele Bildpunkte ein hochgeladenes Bild hoechstens haben darf, bevor Pillow abbricht.
# Ohne das gilt Pillows Standard, und der WARNT bei 89 Megapixeln bloss - abgebrochen wird
# erst beim Doppelten. Ein PNG, das 178 Megapixel ankuendigt, ist als Datei ein paar Kilobyte
# gross und belegt beim Entpacken ueber ein halbes Gigabyte Arbeitsspeicher. 50 Megapixel sind
# immer noch ein Bild von 7000 x 7000 Punkten - mehr braucht weder eine Willkommenskarte noch
# ein Discord-Anhang.
Image.MAX_IMAGE_PIXELS = 50_000_000

# Obergrenze fuer hochgeladene Bilder in Bytes. Sie landen base64-kodiert in guild_configs und
# damit in jedem Backup - ohne Grenze traegt eine einzige 200-MB-Datei jeden Export mit sich.
MAX_BILD_UPLOAD = 8 * 1024 * 1024

# Und fuer Backup-Dateien. Grosszuegig, weil ein Backup die eingebetteten Bilder base64-kodiert
# mitfuehrt - aber nicht unbegrenzt: Dashboard und Bot teilen sich einen Prozess, eine einzige
# zu grosse Datei nimmt also nicht nur die Weboberflaeche mit, sondern auch die Discord-Seite.
MAX_BACKUP_UPLOAD = 64 * 1024 * 1024

import aiohttp
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
from cogs.welcome import _make_card as _welcome_make_card, fill as _welcome_fill
from cogs.polls import (
    build_poll_embed as _build_poll_embed, PollView as _PollView,
    DEFAULT_BAR_COLOR as _DEFAULT_BAR_COLOR,
)
from cogs.ratings import (
    build_ratings_embed as _build_ratings_embed, RatingsListView as _RatingsListView,
    refresh_posted_list as _refresh_ratings_list,
)
from cogs.log_utils import log_bot_event as _log_bot_event, BOT_EVENT_CATEGORIES
from i18n import get_tr
import uvicorn
from discord.ext import commands
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
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
    role_rule_actions, normalize_reaction_emoji, parse_command_triggers,
    DEFAULT_BIRTHDAY_TRIGGERS, DEFAULT_BIRTHDAY_DELETE_WORDS,
    DEFAULT_BIRTHDAY_REPLY_SAVED, DEFAULT_BIRTHDAY_REPLY_DELETED,
    DEFAULT_BIRTHDAY_REPLY_ERROR, DEFAULT_TEMPVOICE_PANEL_TITLE,
    DEFAULT_TEMPVOICE_PANEL_TEXT, DEFAULT_TEMPVOICE_LABELS, parse_panel_labels,
    DEFAULT_VRC_NICKNAME_FORMAT, vrc_nickname, VRC_ACCOUNT_KEY,
    DEFAULT_VRC_PANEL_TITLE, DEFAULT_VRC_PANEL_TEXT, DEFAULT_VRC_PANEL_BUTTON,
    DEFAULT_VRC_INSTANCE_MESSAGE, DEFAULT_VRC_INSTANCE_BUTTON,
    DEFAULT_VRC_INSTANCE_CLOSED, DEFAULT_VRC_INSTANCE_TITLE,
    DEFAULT_VRC_INSTANCE_CLOSED_TITLE, DEFAULT_VRC_INSTANCE_COUNT_LABEL,
    DEFAULT_VRC_INSTANCE_FOOTER, DEFAULT_VRC_INSTANCE_LOCKED,
    DEFAULT_VRC_INSTANCE_LOCKED_TITLE,
    VRC_TOKEN_TTL_MINUTES, VRC_STATE_UNVERIFIED, VRC_STATE_PENDING, VRC_STATE_APPROVED,
    vrc_verify_code,
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


# How long a dashboard session cookie may live. Starlette's own default, stated here because
# the session table's cleanup has to agree with it - a row kept shorter than the cookie would
# sign people out early, longer would keep dead handles around forever.
SESSION_MAX_AGE = 14 * 24 * 60 * 60


def _looks_hashed(value: str) -> bool:
    """Ob dieser Wert aussieht wie ein gespeicherter Hash - 64 Hex-Zeichen.

    Klingt nach Kleinkram, ist aber der Punkt, an dem die ganze Massnahme sonst kippt: die
    Rueckfaelle unten akzeptieren waehrend der Umstellung auch noch den ROHEN Wert aus einer
    alten Zeile. Wer ein Backup liest, findet dort den Hash - und koennte ihn einfach als
    Token einreichen, woraufhin der Rueckfall ihn gegen genau dieselbe Zeile pruefen und
    durchwinken wuerde. Der eigene Test hat das aufgedeckt, bevor es je lief.

    Ein echtes Geheimnis aus secrets.token_urlsafe() ist Base64 und enthaelt praktisch immer
    Zeichen ausserhalb von [0-9a-f] oder hat eine andere Laenge; ein Treffer waere
    astronomisch unwahrscheinlich und kostet dann nur einen neuen Link.
    """
    value = value or ""
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())


def _token_pair(raw: str) -> tuple:
    """(Hash, Rohwert) fuer eine Abfrage mit "IN (?,?)" - der Rohwert wird unterdrueckt, wenn
    er wie ein Hash aussieht, damit der Umstellungs-Rueckfall nicht zum Einfallstor wird."""
    digest = _token_hash(raw)
    return (digest, digest if _looks_hashed(raw) else raw)


def _token_hash(raw: str) -> str:
    """Der Speicher-Wert fuer ein zufaellig erzeugtes Geheimnis, das nur VERGLICHEN wird.

    Betrifft drei Sorten: Passwort-Reset-Token, Einladungscodes und die Sitzungs-Handles.
    Keiner davon wird je zurueckgelesen - der Bot prueft nur, ob ein hereingereichter Wert
    dazu passt. Also gehoert er gehasht statt gespeichert, und damit ist "wer die Datenbank
    liest, uebernimmt Konten" fuer diese drei erledigt, ohne dass irgendwo ein Schluessel
    verwaltet oder verloren werden koennte.

    Ohne Salt und ohne Streckung, und das ist hier richtig: die Werte kommen aus
    secrets.token_urlsafe() mit 128 bis 256 Bit Zufall. Da gibt es nichts zu raten und keine
    Liste vorberechneter Hashes, gegen die ein Salt schuetzen muesste - anders als bei
    Passwoertern, die Menschen sich ausdenken und die deshalb weiterhin ueber bcrypt laufen.
    """
    import hashlib
    return hashlib.sha256((raw or "").encode()).hexdigest()


def _cookie_secure() -> bool:
    """Whether the session cookie gets the Secure flag (and HSTS gets sent).

    Off unless PHOBOS_COOKIE_SECURE says otherwise, and deliberately NOT guessed from the
    configured address. A Secure cookie is simply dropped by the browser over plain HTTP: guess
    this wrong in the "on" direction and every already-running installation locks its own
    admins out at the next restart, with nothing in the interface to explain why. An existing
    server must not need re-doing because of a security patch, so this one waits to be asked.

    Turn it on with one line in docker-compose once the dashboard is reached over HTTPS:
        environment:
          - PHOBOS_COOKIE_SECURE=1

    Decided once at startup, because Starlette's session middleware takes it at construction.
    """
    return os.environ.get("PHOBOS_COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes", "on")


COOKIE_SECURE = _cookie_secure()


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
    "cogs.auto_thread",
    "cogs.vrc_link",
    "cogs.temp_voice",
    "cogs.scheduler",
    "cogs.birthday",
    "cogs.amp",
    "cogs.auto_kick",
    "cogs.role_rules",
    "cogs.polls",
    "cogs.ratings",
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

        # Which guilds already got their copy of the global commands this process. on_ready
        # fires again after every gateway reconnect, and re-syncing every guild each time
        # would spend Discord's per-guild command budget on nothing.
        synced_guilds: set[int] = set()

        async def _sync_guild(guild: discord.Guild) -> None:
            """Publish the global commands to one guild, so they are usable immediately.

            A global sync alone is not enough in practice: Discord propagates global commands
            lazily and a newly added one stays invisible for up to an hour - which is exactly
            what a user hit here ("das klapt immernoch nicht", with /vrc-link missing from the
            command list). A guild-scoped sync takes effect at once.

            copy_global_to() MERGES into whatever guild commands the tree already holds, so
            the per-instance AMP commands are kept rather than replaced (checked against
            discord.py 2.3.2's own source, not assumed) - and cogs/amp.py copies the globals
            back in after it clears a guild, so whichever of the two runs last is fine.

            Failures are per guild on purpose: a server that invited the bot without the
            applications.commands scope answers 403 here, and that must not cost every OTHER
            server its commands.
            """
            if guild.id in synced_guilds:
                return
            try:
                instance.tree.copy_global_to(guild=guild)
                await instance.tree.sync(guild=guild)
                synced_guilds.add(guild.id)
            except discord.Forbidden:
                print(f"[Token-ID {token_id}] Keine Befehls-Rechte auf {guild.name} "
                      f"({guild.id}) - der Bot wurde ohne 'applications.commands' eingeladen.")
            except Exception as e:
                print(f"[Token-ID {token_id}] Befehls-Sync für Guild {guild.id} fehlgeschlagen: {e}")

        @instance.event
        async def on_ready():
            await instance.tree.sync()
            for guild in list(instance.guilds):
                await _sync_guild(guild)
            print(f"Phobos v{VERSION} online als {instance.user} [ID {token_id}]")

        @instance.event
        async def on_guild_join(guild: discord.Guild):
            """A server added after startup gets the same treatment - on_ready has long since
            run by then, so without this its members would wait out Discord's global
            propagation before any command of this bot worked for them."""
            await _sync_guild(guild)

        bot._bots[token_id] = instance
        login_failed = False
        try:
            async with instance:
                for cog in COGS:
                    try:
                        # Die Kooperations-Anfrage haengt am Bot statt im Cog: die Cogs
                        # importieren main.py bewusst nie (sie werden VON hier geladen, ein
                        # Rueckimport waere ein Kreis), brauchen aber dieselbe Pruefung auf
                        # oeffentliche Adressen wie die Weboberflaeche. Also durchgereicht.
                        instance.coop_ask = coop_frage_partner
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
    that would actually benefit from caching in the first place.

    Belt-and-suspenders update after a real incident ("der einladungs link war aufeinmal mit dem
    profil von mir drin und er hatte kein pw" - a moderator's browser, on a completely different
    device, landed straight in the ADMIN's already-logged-in session with no login prompt at
    all): every response here carries a Set-Cookie for the session, and per RFC 7234 a
    RFC-compliant shared cache must never store a response with Set-Cookie unless the response
    is explicitly marked cacheable - `no-store` alone already covers that, but plenty of real-
    world reverse-proxy/CDN cache configs don't correctly implement that nuance and cache
    anyway if told to via their own force-cache rules. Added `private` (explicitly forbids
    shared/proxy caches, not just browsers), `no-cache` (forces revalidation even where a cache
    insists on keeping a copy), and the legacy `Pragma`/`Expires` pair some older or oddly
    configured proxies still key off instead of Cache-Control. None of this can force a
    misconfigured proxy to behave - that's a server-side infra setting only the operator can
    fix (disable caching for this specific proxy host/domain) - but it closes every header-level
    loophole this app itself could still be leaving open."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


async def _current_session_epoch() -> str:
    """A global, admin-bumpable counter (config table) that every session carries a snapshot
    of at login time - SessionValidityMiddleware compares the two on each request, so bumping
    this instantly logs out every session everywhere (see /admin/logout-all), without needing
    to touch secret.key or restart the process. Requested after a live incident where a
    moderator's browser, on a different device, ended up inside the admin's already-logged-in
    session (most likely a caching reverse proxy replaying a cached Set-Cookie response) -
    rotating secret.key + restarting was the only way to kill every session at the time; this
    gives the admin an instant, in-dashboard equivalent for that specific emergency."""
    return await get_config("session_epoch") or "0"


# The public address the dashboard is actually being reached at, learned from logged-in
# requests. The invite link in the user administration builds itself from
# window.location.origin - whatever address the admin has open - and that is what people
# expect here too. The bot cannot do the same directly: it builds its links inside Discord,
# where there is no browser to ask. So the web half remembers the address and the bot reads
# it back. An explicitly configured base_url always wins over this.
#
# Only recorded from requests that carry a valid dashboard session: Host and X-Forwarded-Host
# are client-supplied, and a stranger hitting the public member page must not be able to
# decide what address everybody else's links point at.
_detected_base: str = ""


def _request_origin(request: Request) -> str:
    """scheme://host of THIS request, as the browser sees it - "" if it cannot be told.

    X-Forwarded-Proto/Host come first because this normally runs behind a reverse proxy, where
    the connection the app itself sees is plain http on an internal name. Only the first value
    of a comma-separated chain is used; the rest were added by whatever sat further out.
    """
    headers = request.headers
    proto = (headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower() \
        or (request.url.scheme or "").lower()
    host = (headers.get("x-forwarded-host") or headers.get("host") or "").split(",")[0].strip()
    if proto not in ("http", "https") or not host or "/" in host or " " in host:
        return ""
    return f"{proto}://{host}"


async def _remember_base_url(request: Request) -> None:
    """Store the dashboard's address, but only when it actually changed."""
    global _detected_base
    origin = _request_origin(request)
    if not origin or origin == _detected_base:
        return
    _detected_base = origin
    try:
        await set_config("detected_base_url", origin)
    except Exception as e:
        print(f"[base_url] konnte die erkannte Adresse nicht speichern: {e}")


async def link_base_url() -> str:
    """The address member-facing links are built on, without a trailing slash.

    A configured base_url wins; otherwise the address the dashboard was last opened at. Empty
    only before anybody has ever logged in on a fresh install.
    """
    base = (await get_config("base_url") or "").strip()
    if not base:
        base = (await get_config("detected_base_url") or "").strip()
    return base.rstrip("/")


async def _session_alive(sid: str) -> bool:
    """Ob dieses Sitzungs-Handle noch gilt - und stellt eine alte Zeile dabei still um.

    Gespeichert wird nur noch der Hash. Wer die Datenbankdatei erbeutet - ein Backup, ein
    Abzug - kann daraus kein gueltiges Handle mehr ablesen. Das zaehlt, weil der
    Sitzungsschluessel in derselben Ordnerstruktur liegt: mit beidem zusammen liesse sich
    sonst ein Cookie faelschen UND ein passendes Handle nachschlagen.

    Der Rueckfall auf den rohen Wert ist ausdruecklich KEINE dauerhafte Schwaeche, sondern die
    Umstellung: wer beim Update angemeldet war, hat eine Zeile im alten Format. Die wird beim
    naechsten Seitenaufruf auf den Hash umgeschrieben, statt die Sitzung wegzuwerfen - es soll
    niemand nach einem Update ploetzlich vor dem Login stehen. Nach einmal Durchlaufen gibt es
    keine alten Zeilen mehr.
    """
    digest = _token_hash(sid)
    if await db_one("SELECT sid FROM user_sessions WHERE sid=?", (digest,)):
        return True
    if _looks_hashed(sid):
        # Sieht der eingereichte Wert selbst wie ein gespeicherter Hash aus, ist er kein
        # Altbestand, sondern jemand, der ihn irgendwo abgelesen hat. Kein Rueckfall.
        return False
    alt = await db_one("SELECT sid FROM user_sessions WHERE sid=?", (sid,))
    if not alt:
        return False
    try:
        await db_exec("UPDATE user_sessions SET sid=? WHERE sid=?", (digest, sid))
    except Exception as e:
        # Schlaegt das Umschreiben fehl, bleibt die Zeile im alten Format stehen und wird beim
        # naechsten Aufruf erneut versucht. Die Sitzung darf daran nicht scheitern.
        print(f"[session] Umstellung eines alten Sitzungs-Handles fehlgeschlagen: {e}")
    return True


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Die Kopfzeilen, die jede Antwort tragen sollte.

    Absichtlich KEINE vollstaendige Content-Security-Policy: das Dashboard lebt von inline
    geschriebenem JavaScript und inline Styles, und eine Richtlinie ohne 'unsafe-inline' wuerde
    jede Seite auf einen Schlag funktionsunfaehig machen. Was hier steht, ist der Teil, der
    sofort wirkt und nichts kaputt macht - frame-ancestors deckt dasselbe ab wie
    X-Frame-Options und wird von neueren Browsern bevorzugt gelesen.

    HSTS nur bei gesicherten Cookies, also wenn die Installation ueber HTTPS laeuft: ueber
    einfaches HTTP ignorieren Browser die Zeile ohnehin, und sie versehentlich zu setzen waere
    die eine Kopfzeile, die man nicht mehr zurueknehmen kann.
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        # SAMEORIGIN, nicht DENY: das blockiert das Einbetten durch eine fremde Seite - also
        # den Clickjacking-Weg - laesst aber eine eigene Startseite auf demselben Host in
        # Ruhe. DENY haette so einen Aufbau ohne Vorwarnung kaputtgemacht, und eine
        # Sicherheitsverbesserung darf keinen laufenden Server zerlegen. Die
        # Mitglieder-Seiten setzen fuer sich weiterhin DENY; setdefault laesst das stehen.
        headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if COOKIE_SECURE:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response


class SessionValidityMiddleware(BaseHTTPMiddleware):
    """Re-checks role/active status from the DB on every request — otherwise a
    deactivated or demoted user keeps full access for the rest of their
    (up to 14 day) session cookie lifetime. Also enforces the global session_epoch (see
    _current_session_epoch) so an admin's "log everyone out" action takes effect immediately,
    on the very next request of every session - including the admin's own, once their own
    next request comes in (the request that triggers the bump itself has already passed this
    check earlier in the same dispatch chain, so it isn't cut off mid-action)."""
    async def dispatch(self, request: Request, call_next):
        try:
            uid = request.session.get("user_id")
        except Exception:
            uid = None
        if uid:
            row = await db_one("SELECT role, active FROM users WHERE id=?", (uid,))
            if not row or not row.get("active", 1):
                request.session.clear()
            elif request.session.get("session_epoch") != await _current_session_epoch():
                request.session.clear()
            elif row["role"] != request.session.get("role"):
                request.session["role"] = row["role"]
            if request.session.get("user_id"):
                # The handle issued at login has to still exist, or this cookie belongs to a
                # session somebody signed out of. Sessions from before this existed carry no
                # sid at all - those are accepted once and then quietly given one, so an
                # update does not throw everybody out; from their next login on they are
                # revocable like any other.
                sid = request.session.get("sid")
                if sid:
                    if not await _session_alive(sid):
                        request.session.clear()
                else:
                    try:
                        sid = secrets.token_urlsafe(24)
                        now = datetime.datetime.utcnow().isoformat()
                        await db_exec(
                            "INSERT INTO user_sessions (sid, user_id, created_at, last_seen) "
                            "VALUES (?,?,?,?)", (_token_hash(sid), uid, now, now))
                        request.session["sid"] = sid
                    except Exception as e:
                        print(f"[session] Nachrüsten einer Altsitzung fehlgeschlagen: {e}")
            if request.session.get("user_id"):
                # Re-read rather than reusing `uid`: the branches above clear the session for a
                # deactivated user or a stale epoch, and those requests must not count as a
                # logged-in sighting of this address.
                await _remember_base_url(request)
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
web.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="phobos_session",
                   max_age=SESSION_MAX_AGE, https_only=COOKIE_SECURE, same_site="lax")
web.add_middleware(SecurityHeadersMiddleware)
web.add_middleware(NoCacheMiddleware)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
def _ping_roles(guild) -> set:
    """Die Rollen-IDs, die auf diesem Server als Ping-Ziel taugen. @everyone bleibt aussen
    vor - die pingt ohnehin jeden, und genau davor sollen die Schalter schuetzen."""
    return {str(r.id) for r in guild.roles if not r.is_default()} if guild else set()


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
        "🎉": "bar-green", "🏆": "bar-green",
        "📤": "bar-red",   "🔨": "bar-red",   "🔇": "bar-red",   "🗑️": "bar-red",
        "🛡️": "bar-red",
        "✏️": "bar-yellow", "🔀": "bar-amber",
        "⏱️": "bar-amber",  "⚠️": "bar-amber",
        "🏷️": "bar-blue",   "🗳️": "bar-blue",  "🎫": "bar-blue", "📨": "bar-blue",
        "💎": "bar-pink",   "🎂": "bar-pink",
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


async def _sitzungen_beenden(user_id, ausser_sid: str = "") -> int:
    """Wirft alle angemeldeten Sitzungen dieses Kontos raus. Gibt zurueck, wie viele.

    Gehoert an jede Stelle, die ein Passwort setzt. Ein Passwortwechsel ist fast immer eine
    Reaktion: jemand fuerchtet, dass ein anderer mitliest. Genau dann muss die Sitzung dieses
    anderen enden - sonst aendert der Wechsel nur, womit man sich neu anmeldet, und der
    Eindringling bleibt sitzen, bis seine Sitzung von selbst verfaellt.

    `ausser_sid` laesst genau eine Sitzung stehen: wer sein eigenes Passwort im Profil aendert,
    soll nicht im selben Moment vor dem Login stehen. Beim Zuruecksetzen per Link und beim
    Setzen durch eine Administratorin bleibt nichts stehen.
    """
    try:
        if ausser_sid:
            behalten = _token_pair(ausser_sid)
            rows = await db_rows(
                "SELECT sid FROM user_sessions WHERE user_id=? AND sid NOT IN (?,?)",
                (user_id, *behalten))
            await db_exec(
                "DELETE FROM user_sessions WHERE user_id=? AND sid NOT IN (?,?)",
                (user_id, *behalten))
        else:
            rows = await db_rows("SELECT sid FROM user_sessions WHERE user_id=?", (user_id,))
            await db_exec("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        return len(rows)
    except Exception as e:
        print(f"[session] konnte die Sitzungen von {user_id} nicht beenden: {e}")
        return 0


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
    request.session["session_epoch"] = await _current_session_epoch()
    # A handle for THIS login, checked against user_sessions on every request. It is what
    # makes signing out mean something: the cookie alone cannot be taken back once it exists,
    # the row can. See the migration in database.py for the full reasoning.
    sid = secrets.token_urlsafe(24)
    now = datetime.datetime.utcnow().isoformat()
    request.session["sid"] = sid
    await db_exec("INSERT INTO user_sessions (sid, user_id, created_at, last_seen) "
                  "VALUES (?,?,?,?)", (_token_hash(sid), user["id"], now, now))
    # Sessions older than the cookie can possibly live are dead weight; clearing them here
    # costs one statement per login instead of a background task.
    try:
        cutoff = (datetime.datetime.utcnow()
                  - datetime.timedelta(seconds=SESSION_MAX_AGE)).isoformat()
        await db_exec("DELETE FROM user_sessions WHERE created_at < ?", (cutoff,))
    except Exception as e:
        print(f"[session] Aufräumen alter Sitzungen fehlgeschlagen: {e}")


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


# ── Bremse für Anmeldeversuche ───────────────────────────────────────────────
# Until now a password could be guessed as often as anybody liked; an external test walked
# through a wordlist at nine tries in two and a half seconds and was never once refused. The
# lockout that already existed applied only to the SECOND step (the 2FA code), which never
# comes into play while the password itself is still wrong.
#
# Counted per (address, username) pair rather than per username alone, on purpose: a lockout
# keyed on the username would hand anybody on the internet a way to lock the admin out of
# their own dashboard. A second, looser count per address stops one host from spraying many
# usernames instead.
#
# Honest about its limits: the address comes from X-Forwarded-For, which the client can put
# anything into. Somebody willing to rotate that header gets around this. It stops the attack
# that was actually demonstrated - and a proxy-level limit or fail2ban is the answer to the
# determined version, not application code.
_LOGIN_MAX_PER_USER = 5          # Fehlversuche je Adresse UND Benutzername
_LOGIN_MAX_PER_IP = 20           # Fehlversuche je Adresse über alle Benutzernamen
_LOGIN_LOCK_SECONDS = 15 * 60
_LOGIN_WINDOW_SECONDS = 15 * 60  # so lange zählt ein Fehlversuch mit
_LOGIN_TRACK_MAX = 5000          # darüber fliegt die älteste Hälfte raus
# key -> [Anzahl, erster Fehlversuch (monotonic), gesperrt bis (monotonic)]
_login_fails: dict[str, list] = {}

# Ein echter bcrypt-Hash, gegen den bei unbekanntem Benutzernamen geprueft wird, damit die
# Antwort genauso lange braucht. Einmal beim Start erzeugt statt fest eingetragen: ein
# eingebauter Hash waere in jeder Kopie dieses Projekts derselbe und damit ein verlaesslicher
# Anhaltspunkt, dass hier genau diese Software laeuft.
_DUMMY_PW_HASH = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt()).decode()


def _login_client(request: Request) -> str:
    """The address this attempt comes from, as far as it can be told behind a proxy."""
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if fwd:
        return fwd[:64]
    return (request.client.host if request.client else "?")[:64]


def _login_keys(request: Request, username: str) -> list:
    ip = _login_client(request)
    return [f"ip:{ip}", f"user:{ip}|{(username or '').strip().lower()[:64]}"]


def _login_locked_seconds(request: Request, username: str) -> int:
    """Seconds left on an active lockout for this attempt, or 0."""
    now = time.monotonic()
    worst = 0
    for key in _login_keys(request, username):
        entry = _login_fails.get(key)
        if entry and entry[2] > now:
            worst = max(worst, int(entry[2] - now))
    return worst


def _login_note_failure(request: Request, username: str) -> None:
    now = time.monotonic()
    if len(_login_fails) >= _LOGIN_TRACK_MAX:
        for stale, _ in sorted(_login_fails.items(), key=lambda kv: kv[1][1])[:_LOGIN_TRACK_MAX // 2]:
            _login_fails.pop(stale, None)
    for key, limit in zip(_login_keys(request, username),
                          (_LOGIN_MAX_PER_IP, _LOGIN_MAX_PER_USER)):
        entry = _login_fails.get(key)
        # A run of failures that has gone quiet for the whole window starts over - otherwise a
        # forgotten password months ago would still count against somebody today.
        if not entry or now - entry[1] > _LOGIN_WINDOW_SECONDS:
            entry = [0, now, 0.0]
        entry[0] += 1
        if entry[0] >= limit:
            entry[2] = now + _LOGIN_LOCK_SECONDS
            entry[0] = 0
            entry[1] = now
        _login_fails[key] = entry


def _login_note_success(request: Request, username: str) -> None:
    """A correct password clears that pair's count - but NOT the per-address one, so one
    working account cannot be used to keep guessing at the others from the same host."""
    _login_fails.pop(_login_keys(request, username)[1], None)


@web.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    locked = _login_locked_seconds(request, username)
    if locked:
        minutes = max(1, math.ceil(locked / 60))
        return RedirectResponse(
            f"/login?error=Zu+viele+Fehlversuche+–+bitte+in+{minutes}+Minute(n)+erneut+versuchen",
            status_code=302,
        )
    user = await db_one("SELECT * FROM users WHERE username=?", (username.strip(),))
    if not user:
        # Gegen ein unbekanntes Konto wird trotzdem geprueft. Ohne das lief bcrypt nur bei
        # existierenden Namen, und der Unterschied war messbar - ein externer Test las daraus
        # 227 ms gegen 14 ms ab und konnte so Benutzernamen erraten, ohne angemeldet zu sein.
        # Dieselbe Arbeit in beiden Faellen macht die Antwortzeit nichtssagend.
        verify_pw(password, _DUMMY_PW_HASH)
        _login_note_failure(request, username)
        return RedirectResponse("/login?error=Ungültige+Zugangsdaten", status_code=302)
    if not verify_pw(password, user["password_hash"]):
        _login_note_failure(request, username)
        return RedirectResponse("/login?error=Ungültige+Zugangsdaten", status_code=302)
    if not user.get("active", 1):
        # Counted too: a deactivated account is still a valid username, and leaving this path
        # free would keep a working oracle for "does this name exist" wide open.
        _login_note_failure(request, username)
        return RedirectResponse("/login?error=Dein+Konto+ist+deaktiviert", status_code=302)
    _login_note_success(request, username)
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
    """Signing out ends this login for good, not just in this browser.

    Clearing the session only rewrites the cookie of whoever is asking. Deleting the row is
    what makes a copy of that same cookie - taken from a shared machine, a backup, a proxy
    log - stop working at the same moment. Other devices of the same user keep their own
    sessions; each login has its own handle.
    """
    sid = request.session.get("sid")
    if sid:
        try:
            await db_exec("DELETE FROM user_sessions WHERE sid IN (?,?)", _token_pair(sid))
        except Exception as e:
            print(f"[session] Abmelden konnte die Sitzung nicht löschen: {e}")
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


def _safe_back(request: Request, default: str = "/") -> str:
    """Where to send somebody back to, taken from the Referer but never off this site.

    The Referer is whatever the browser was told to send, so an attacker can put their own
    address in it. Handing that straight to a redirect turned this route into an open
    redirect - and one that needs no login at all, which makes it a ready-made first hop for
    a phishing link that starts on a domain the victim trusts. Reported by an external test
    and confirmed here.

    Only a path on this same site survives: no scheme, no host, and no "//evil.example" - a
    leading double slash is a protocol-relative URL and leaves the site just as thoroughly as
    "https://" does.
    """
    ref = request.headers.get("referer", "") or ""
    try:
        parsed = urllib.parse.urlparse(ref)
    except ValueError:
        return default
    if parsed.scheme or parsed.netloc:
        # Absolute address: only allowed when it points back at the host this request came in
        # on, so a normal browser Referer keeps working behind a reverse proxy.
        host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
        host = host.split(",")[0].strip()
        if not host or parsed.netloc != host:
            return default
    path = parsed.path or "/"
    if not path.startswith("/") or path.startswith("//"):
        return default
    return path + (f"?{parsed.query}" if parsed.query else "")


@web.post("/settings/language")
async def set_language(request: Request, lang: str = Form("de")):
    if lang not in ("de", "en"):
        lang = "de"
    request.session["lang"] = lang
    uid = request.session.get("user_id")
    if uid:
        await db_exec("UPDATE users SET language=? WHERE id=?", (lang, uid))
    return RedirectResponse(_safe_back(request), status_code=302)


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
    weg = await _sitzungen_beenden(uid, request.session.get("sid", ""))
    hinweis = "Passwort+geändert"
    if weg:
        hinweis += f",+{weg}+andere+Anmeldung(en)+beendet"
    return RedirectResponse(f"/profile?success={hinweis}", status_code=302)


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
    "reaction_roles", "custom_commands", "auto_delete_channels", "vrc_links",
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
    # Role Rules, added at the same time the feature itself shipped this time (see the entries
    # above for what happens when this step gets forgotten).
    "role_rules",
    # Same gap as level_roles/amp_configs/embed_posts before them, found by diffing this list
    # against every table that actually carries a guild_id: the ⭐ Bewertungen items are pure
    # configuration (what can be rated) and were silently dropped by every backup since the
    # feature shipped. rating_votes stays out on purpose - those are members' answers, the
    # same "live event, not reusable configuration" line drawn at giveaways and polls.
    "rating_items",
    # Auto-Thread, added with the feature itself.
    "auto_thread_channels",
]

# Recurring 🗓️ Events are NOT in the list above even though they are configuration: their
# reminder templates (event_series_reminders) reference a series by its AUTOINCREMENT id, and a
# restore assigns fresh ids - the generic insert loop would leave every reminder pointing at
# whatever series happens to now hold its old id, on a different server. They get their own
# parent-then-children restore further down instead, which is also the only place that can
# clear last_discord_event_id (see there).

# Shared between the full-backup restore (/admin/backup/restore) and the per-server restore
# (/servers/{guild_id}/backup/restore) - was previously defined inline inside backup_restore()
# only, duplicating it for the new per-server path would have let the two drift out of sync.
def _rehome_role_rule(row: dict, new_guild_id: str) -> dict:
    """Point a restored CrossVerification rule's SELF-references at the guild it is being
    restored onto.

    The per-server restore replaces every row's guild_id with the target guild, but a role rule
    also carries the guild its ACTIONS apply to - in action_guild_id and in each block of
    `actions`. Those were restored verbatim, so a rule that acted on its own server ("wer hier
    Rolle A hat, bekommt hier Rolle B") came back still naming the server it was exported FROM:
    restoring a backup onto a second server then silently rewrote members' roles on the
    ORIGINAL one. Anything that pointed at a genuinely DIFFERENT server stays untouched - that
    is a deliberate cross-server link, not a self-reference, and rewriting it would destroy the
    very thing the rule was built for.
    """
    original_guild_id = str(row.get("guild_id") or "")
    if not original_guild_id or original_guild_id == new_guild_id:
        return row
    out = dict(row)
    if str(out.get("action_guild_id") or "") == original_guild_id:
        out["action_guild_id"] = new_guild_id
    try:
        blocks = _djson.loads(out.get("actions") or "[]")
    except (ValueError, TypeError):
        return out
    if not isinstance(blocks, list):
        return out
    changed = False
    for block in blocks:
        if isinstance(block, dict) and str(block.get("guild_id") or "") == original_guild_id:
            block["guild_id"] = new_guild_id
            changed = True
    if changed:
        out["actions"] = _djson.dumps(blocks)
    return out


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
    # The links themselves travel with a server backup: they are configuration in every sense
    # that matters here - a moderator approved each one by hand, and losing them means every
    # member has to ask again.
    # verified_at and the VRChat id travel along: the member proved ownership once, and a
    # server changing hands is no reason to make everybody paste a code onto their profile again.
    "vrc_links":
        "INSERT INTO vrc_links (guild_id,user_id,vrchat_name,vrc_user_id,status,requested_at,"
        "decided_at,decided_by,note,verified_at) "
        "VALUES (:guild_id,:user_id,:vrchat_name,:vrc_user_id,:status,:requested_at,"
        ":decided_at,:decided_by,:note,:verified_at) "
        "ON CONFLICT(guild_id,user_id) DO UPDATE SET vrchat_name=excluded.vrchat_name, "
        "vrc_user_id=excluded.vrc_user_id, status=excluded.status, verified_at=excluded.verified_at",
    "auto_thread_channels":
        "INSERT INTO auto_thread_channels (guild_id,channel_id,name_template,archive_minutes,skip_bots,require_attachment,starter_message) "
        "VALUES (:guild_id,:channel_id,:name_template,:archive_minutes,:skip_bots,:require_attachment,:starter_message) "
        "ON CONFLICT(guild_id,channel_id) DO UPDATE SET name_template=excluded.name_template, "
        "archive_minutes=excluded.archive_minutes, skip_bots=excluded.skip_bots, "
        "require_attachment=excluded.require_attachment, starter_message=excluded.starter_message",
    "temp_voice_config":
        "INSERT INTO temp_voice_config (guild_id,trigger_channel_id,category_id,name_template,user_limit,panel_enabled,panel_title,panel_text,panel_labels) VALUES (:guild_id,:trigger_channel_id,:category_id,:name_template,:user_limit,:panel_enabled,:panel_title,:panel_text,:panel_labels) ON CONFLICT(guild_id,trigger_channel_id) DO UPDATE SET category_id=excluded.category_id,name_template=excluded.name_template,user_limit=excluded.user_limit,panel_enabled=excluded.panel_enabled,panel_title=excluded.panel_title,panel_text=excluded.panel_text,panel_labels=excluded.panel_labels",
    "scheduled_messages":
        "INSERT OR IGNORE INTO scheduled_messages (guild_id,channel_id,message,send_at,sent) VALUES (:guild_id,:channel_id,:message,:send_at,:sent)",
    "notifications":
        "INSERT OR IGNORE INTO notifications (guild_id,platform,discord_channel_id,target,target_name,last_id,live,custom_message) VALUES (:guild_id,:platform,:discord_channel_id,:target,:target_name,:last_id,0,:custom_message)",
    "freestuff_channels":
        "INSERT INTO freestuff_channels (guild_id,channel_id,platforms,deal_max_price,deal_min_discount,deal_channel_id,deal_platforms,ping_role_id,ping_enabled,deal_ping_role_id,deal_ping_enabled) VALUES (:guild_id,:channel_id,:platforms,:deal_max_price,:deal_min_discount,:deal_channel_id,:deal_platforms,:ping_role_id,:ping_enabled,:deal_ping_role_id,:deal_ping_enabled) ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,platforms=excluded.platforms,deal_max_price=excluded.deal_max_price,deal_min_discount=excluded.deal_min_discount,deal_channel_id=excluded.deal_channel_id,deal_platforms=excluded.deal_platforms,ping_role_id=excluded.ping_role_id,ping_enabled=excluded.ping_enabled,deal_ping_role_id=excluded.deal_ping_role_id,deal_ping_enabled=excluded.deal_ping_enabled",
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
        "INSERT INTO embed_posts (guild_id,name,channel_id,content,image_url,footer_text,image_data,image_filename) "
        "VALUES (:guild_id,:name,:channel_id,:content,:image_url,:footer_text,:image_data,:image_filename)",
    # action_role_meta rides along deliberately: it is the ONLY thing that lets a restored rule
    # still mean something once its role ids no longer resolve - cogs/role_rules.py recreates
    # (or re-links by name) the action roles from this snapshot. Dropping it here would make a
    # restore look successful while leaving every rule permanently inert.
    # image_data (a base64 blob) rides along like it does for embed_posts - without it a
    # restored item loses its picture and there is no way to get it back from the file.
    "rating_items":
        "INSERT INTO rating_items (guild_id,label,url,recommended,created_at,image_url,image_data,image_filename) "
        "VALUES (:guild_id,:label,:url,:recommended,:created_at,:image_url,:image_data,:image_filename)",
    "role_rules":
        "INSERT INTO role_rules (guild_id,name,match_type,match_role_ids,action,action_guild_id,action_role_ids,action_role_meta,actions,priority,enabled) "
        "VALUES (:guild_id,:name,:match_type,:match_role_ids,:action,:action_guild_id,:action_role_ids,:action_role_meta,:actions,:priority,:enabled)",
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


async def _event_series_for_backup(guild_id: str | None) -> list[dict]:
    """Event series with their reminder templates nested inside each series.

    Nested rather than exported as a second flat table because event_series_reminders links to
    its series by AUTOINCREMENT id: a restore hands out fresh ids, so a flat list could only be
    reattached by guessing. See _restore_event_series() for the other half.
    """
    where, params = ("WHERE guild_id=?", (guild_id,)) if guild_id else ("", ())
    series = await db_rows(f"SELECT * FROM event_series {where}", params)
    for row in series:
        row["reminders"] = await db_rows(
            "SELECT offset_minutes, message FROM event_series_reminders WHERE series_id=?",
            (row["id"],),
        )
    return series


async def _restore_event_series(db, series_rows, guild_id_override: str | None) -> bool:
    """Insert each series, then its reminders under the id the insert just produced.

    last_discord_event_id is deliberately NOT restored: it names the Discord event object the
    SOURCE server created. Carried over verbatim, the scheduler would try to update an event
    on a server this installation may not even serve - the same trap a restored role rule's
    action_guild_id used to fall into (see _rehome_role_rule).
    """
    restored_any = False
    for row in series_rows or []:
        try:
            reminders = row.get("reminders") or []
            cur = await db.execute(
                "INSERT INTO event_series (guild_id, name, description, entity_type, channel_id, "
                "location, duration_minutes, announce_channel_id, notify_end, recurrence, "
                "next_start_at, last_discord_event_id, active, paused) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,'',?,?)",
                (guild_id_override or row.get("guild_id"), row.get("name"), row.get("description", ""),
                 row.get("entity_type"), row.get("channel_id", ""), row.get("location", ""),
                 row.get("duration_minutes"), row.get("announce_channel_id", ""),
                 row.get("notify_end", 0), row.get("recurrence"), row.get("next_start_at"),
                 row.get("active", 1), row.get("paused", 0)),
            )
            new_id = cur.lastrowid
            for rem in reminders:
                if not isinstance(rem, dict):
                    continue
                await db.execute(
                    "INSERT INTO event_series_reminders (series_id, offset_minutes, message) VALUES (?,?,?)",
                    (new_id, rem.get("offset_minutes"), rem.get("message", "")),
                )
            restored_any = True
        except Exception:
            # Per-row isolation, same as every other row in the restore loops.
            continue
    return restored_any


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
    data["event_series"] = await _event_series_for_backup(None)
    return data


async def _build_guild_backup(guild_id: int, exported_by: str, include_secrets: bool = False) -> dict:
    """Exports just one Discord server's own configuration - no dashboard users, tokens, or
    other guilds' data. Meant to be portable: a restore can target ANY guild the admin
    chooses, not just the one this was exported from, so guild_id is deliberately NOT baked
    into the export as anything other than informational metadata.

    Nothing in here is tied to the bot token the source server runs on, so the file can be
    restored into an entirely different installation - which is the point: handing one of
    several Discord servers over to someone else means handing them its settings.

    include_secrets=False (the default) blanks the AMP panel credentials - see below.
    """
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
    data["event_series"] = await _event_series_for_backup(gid_str)
    if not include_secrets:
        # The AMP panel's username/password are the one genuinely secret thing a server config
        # holds, and this export exists to be HANDED TO SOMEBODY ELSE. Blanked unless the admin
        # explicitly ticks the box - moving your own server between your own installations is
        # the only case where passing them along is what you want.
        for row in data.get("amp_configs", []):
            row["password"] = ""
            row["username"] = ""
    data["meta"]["includes_secrets"] = bool(include_secrets)
    return data


def _json_dl(data: dict, filename: str, password: str = "") -> Response:
    """Ein Backup zum Herunterladen - auf Wunsch mit Passwort verschlüsselt.

    Ohne Passwort passiert genau das, was schon immer passiert ist: eine lesbare JSON-Datei.
    Das bleibt der Standard, damit vorhandene Abläufe und Lesezeichen weiterlaufen.

    Mit Passwort verlässt die Datei den Server unlesbar. Das ist der eine Ort, an dem der Bot
    etwas gegen ein abhandengekommenes Backup tun kann: auf der Maschine selbst muss er seine
    Zugangsdaten im Klartext zurückbekommen, in der Kopie nicht. Vergisst jemand das Passwort,
    ist nur diese Datei verloren - auf dem Server bleibt alles, wie es war.
    """
    if password:
        from backup_crypto import encrypt
        content = encrypt(data, password)
        filename = filename.replace(".json", ".enc.json")
    else:
        content = _djson.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _backup_payload(raw: bytes, password: str) -> dict:
    """Den Inhalt einer hochgeladenen Backup-Datei holen, verschlüsselt oder nicht.

    Eine Datei von früher wird unverändert wie bisher gelesen - erkannt wird nur, was sich
    ausdrücklich als verschlüsseltes Phobos-Backup ausweist. Wirft ValueError mit einem Text,
    der dem Menschen davor sagt, was los ist.
    """
    from backup_crypto import is_encrypted, decrypt, BackupCryptoError
    if is_encrypted(raw):
        try:
            return decrypt(raw, password)
        except BackupCryptoError as e:
            raise ValueError(str(e))
    data = _djson.loads(raw)
    if not isinstance(data, dict):
        # Gültiges JSON, das kein Objekt ist (eine nackte Liste, Zahl, null ...) - json.loads()
        # nimmt das an, aber der Aufrufer greift gleich darauf zu wie auf ein Wörterbuch.
        raise ValueError("not a JSON object")
    return data


@web.get("/backup/export")
async def backup_export_own_get(request: Request):
    """Der alte Weg ohne Passwort - bleibt, damit Lesezeichen und Abläufe weiterlaufen."""
    return await backup_export_own(request, "")


@web.post("/backup/export")
async def backup_export_own(request: Request, password: str = Form("")):
    if r := auth_redirect(request): return r
    uid = request.session.get("user_id")
    uname = request.session.get("username", "user")
    data = await _build_user_backup(uid, uname)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    return _json_dl(data, f"backup_{uname}_{ts}.json", password)


@web.get("/admin/backup/user/{user_id}")
async def backup_export_user_get(request: Request, user_id: int):
    return await backup_export_user(request, user_id, "")


@web.post("/admin/backup/user/{user_id}")
async def backup_export_user(request: Request, user_id: int, password: str = Form("")):
    if r := admin_redirect(request): return r
    by = request.session.get("username", "admin")
    data = await _build_user_backup(user_id, by)
    if not data:
        return RedirectResponse("/users?error=Benutzer+nicht+gefunden", status_code=302)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    uname = data["meta"]["username"]
    return _json_dl(data, f"backup_{uname}_{ts}.json", password)


@web.get("/admin/backup/all")
async def backup_export_all_get(request: Request):
    return await backup_export_all(request, "")


@web.post("/admin/backup/all")
async def backup_export_all(request: Request, password: str = Form("")):
    if r := admin_redirect(request): return r
    by = request.session.get("username", "admin")
    data = await _build_full_backup(by)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    return _json_dl(data, f"backup_full_{ts}.json", password)


@web.post("/admin/backup/restore")
async def backup_restore(request: Request, backup_file: UploadFile = File(...),
                         password: str = Form("")):
    if r := admin_redirect(request): return r
    try:
        raw = await backup_file.read()
        if len(raw) > MAX_BACKUP_UPLOAD:
            raise ValueError(f"Backup-Datei zu groß (max. {MAX_BACKUP_UPLOAD // (1024*1024)} MB)")
        data = await _backup_payload(raw, password)
    except ValueError as e:
        # Beim verschlüsselten Backup sagt der Text, was los ist - falsches Passwort oder
        # veränderte Datei. Bei einer kaputten Klartext-Datei die bisherige Meldung.
        # Ein Fehler, den der Mensch davor beheben kann, bekommt seinen Grund gesagt -
        # falsches Passwort oder veraenderte Datei. Alles andere bleibt bei der bisherigen
        # Meldung. Kein erneutes raise: das hier IST schon der Fehlerzweig, ein raise daraus
        # faengt das except darunter nicht mehr und landete als Serverfehler beim Nutzer.
        grund = str(e)
        if grund == "not a JSON object":
            return RedirectResponse("/users?error=Ungültige+Backup-Datei+(kein+gültiges+JSON)",
                                    status_code=302)
        return RedirectResponse(f"/users?error={urllib.parse.quote_plus(grund[:160])}",
                                status_code=302)
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
                    # Exactly the same trap as ticket_message above, for CrossVerification's
                    # role snapshot: a backup taken before action_role_meta existed has no such
                    # key, and the named-parameter INSERT would raise on the missing parameter -
                    # dropping the ENTIRE rule, not just the snapshot. An empty snapshot only
                    # costs the auto-create ability until the rule is saved once through the
                    # dashboard (which refreshes it); losing the rule outright costs everything.
                    if tbl == "role_rules":
                        # Same trap for both columns a pre-existing backup cannot know about.
                        row = {"action_role_meta": "", "actions": "", **row}
                    # Ditto for the VRC-Link columns: a backup taken before the ownership check
                    # existed has neither key, and the named-parameter INSERT would drop the
                    # whole link rather than just the missing field.
                    if tbl == "vrc_links":
                        row = {"vrc_user_id": "", "verified_at": "", **row}
                    if tbl == "freestuff_channels":
                        row = {"ping_role_id": "", "ping_enabled": 1,
                               "deal_ping_role_id": "", "deal_ping_enabled": 1, **row}
                    if tbl == "notifications":
                        row = {"ping_role_id": "", "ping_enabled": 1, **row}
                    if tbl == "temp_voice_config":
                        row = {"panel_enabled": 0, "panel_title": "", "panel_text": "",
                               "panel_labels": "", **row}
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

        # Same dedicated parent-then-children restore as the per-server path, but keeping each
        # series' own guild_id - a full backup restores an entire installation, it does not
        # move anything onto a different server.
        if await _restore_event_series(db, data.get("event_series"), None):
            restored.append("Events")

        await db.commit()

    # auto_delete_channels rows written above bypass the AutoDelete cog's in-memory
    # self._configs cache - without this, a restored config would silently stay inactive
    # until the next bot reconnect (same reload the save/edit/delete routes already trigger).
    if "auto_delete_channels" in data:
        await _reload_auto_delete()
    if "auto_thread_channels" in data:
        # Same reason as the auto_delete reload right above: rows written straight into the
        # table bypass the cog's in-memory config, which would otherwise only pick them up on
        # the next bot restart.
        await _reload_auto_thread()

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
async def server_backup_export_get(request: Request, guild_id: int, include_secrets: str = ""):
    return await server_backup_export(request, guild_id, include_secrets, "")


@web.post("/servers/{guild_id}/backup")
async def server_backup_export(request: Request, guild_id: int,
                               include_secrets: str = Form(""), password: str = Form("")):
    if r := admin_redirect(request): return r
    by = request.session.get("username", "admin")
    data = await _build_guild_backup(guild_id, by, include_secrets == "1")
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    guild = bot.get_guild(guild_id)
    # Sanitized for use in a filename - a guild name can contain characters (/, quotes, emoji)
    # that would be awkward or invalid in one, unlike the guild_id fallback which is already
    # filename-safe on its own.
    name_part = re.sub(r"[^\w\-]+", "_", guild.name).strip("_") if guild else str(guild_id)
    return _json_dl(data, f"backup_server_{name_part or guild_id}_{ts}.json", password)


@web.post("/servers/{guild_id}/backup/restore")
async def server_backup_restore(request: Request, guild_id: int,
                                backup_file: UploadFile = File(...),
                                password: str = Form("")):
    if r := admin_redirect(request): return r
    try:
        raw = await backup_file.read()
        if len(raw) > MAX_BACKUP_UPLOAD:
            raise ValueError(f"Backup-Datei zu groß (max. {MAX_BACKUP_UPLOAD // (1024*1024)} MB)")
        data = await _backup_payload(raw, password)
    except ValueError as e:
        # Siehe backup_restore(): kein raise aus dem Fehlerzweig heraus.
        grund = str(e)
        if grund == "not a JSON object":
            return RedirectResponse(
                f"/servers/{guild_id}?tab=config&error=Ungültige+Backup-Datei+(kein+gültiges+JSON)",
                status_code=302)
        return RedirectResponse(
            f"/servers/{guild_id}?tab=config&error={urllib.parse.quote_plus(grund[:160])}",
            status_code=302)
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
                    if tbl == "role_rules":
                        # Same fallback as the full-backup path for older backups.
                        merged = {"action_role_meta": "", "actions": "", **merged}
                        # Self-references have to be rehomed BEFORE guild_id is lost - see
                        # _rehome_role_rule(); `row` still carries the exported guild id.
                        #
                        # These three lines sat one block further down, under the
                        # temp_voice_config branch, so they never ran for the table they were
                        # written for: a per-server restore left every self-referencing rule
                        # still naming the server it was exported FROM. Restoring a backup onto
                        # a second server then rewrote members' roles on the ORIGINAL one -
                        # precisely the failure _rehome_role_rule() exists to prevent, and
                        # precisely the situation this backup feature was asked for ("wenn man
                        # einen von 10 discord server einen anderen übergeben will").
                        merged = _rehome_role_rule({**merged, "guild_id": row.get("guild_id")}, gid_str)
                        merged["guild_id"] = gid_str
                    if tbl == "temp_voice_config":
                        merged = {"panel_enabled": 0, "panel_title": "", "panel_text": "",
                                  "panel_labels": "", **merged}
                    if tbl == "vrc_links":
                        # Same older-backup fallback as the full-backup path above.
                        merged = {"vrc_user_id": "", "verified_at": "", **merged}
                    if tbl == "freestuff_channels":
                        merged = {"ping_role_id": "", "ping_enabled": 1,
                                  "deal_ping_role_id": "", "deal_ping_enabled": 1, **merged}
                    if tbl == "notifications":
                        merged = {"ping_role_id": "", "ping_enabled": 1, **merged}
                    await db.execute(sql, merged)
                except Exception:
                    pass
            if rows:
                restored.append(tbl.replace("_", " ").title())
            if tbl == "automod_word_presets" and rows:
                restored_presets = True
            if tbl == "amp_instance_commands" and rows:
                restored_amp_cmds = True

        # Recurring events keep their own restore: their reminder templates hang off an
        # autoincrement id that only exists once the series row has been inserted.
        # gid_str, not the exported guild id: this restore path deliberately re-homes every
        # row onto the guild in the URL, exactly like the generic loop above does.
        if await _restore_event_series(db, data.get("event_series"), gid_str):
            restored.append("Events")

        await db.commit()

    if "auto_delete_channels" in data:
        await _reload_auto_delete()
    if "auto_thread_channels" in data:
        # Same reason as the auto_delete reload right above: rows written straight into the
        # table bypass the cog's in-memory config, which would otherwise only pick them up on
        # the next bot restart.
        await _reload_auto_thread()
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
            (_token_hash(token), user["id"], expires),
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
        "SELECT user_id FROM password_reset_tokens WHERE token IN (?,?) AND expires_at > ?",
        # Der gehashte Wert zuerst, der rohe als Rueckfall: ein Link, der beim Update schon
        # unterwegs war, soll weiter funktionieren. Solche Zeilen sind nach einer Stunde
        # ohnehin weg, danach greift nur noch der Hash.
        (*_token_pair(token), datetime.datetime.utcnow().isoformat()),
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
        "SELECT user_id FROM password_reset_tokens WHERE token IN (?,?) AND expires_at > ?",
        # Der gehashte Wert zuerst, der rohe als Rueckfall: ein Link, der beim Update schon
        # unterwegs war, soll weiter funktionieren. Solche Zeilen sind nach einer Stunde
        # ohnehin weg, danach greift nur noch der Hash.
        (*_token_pair(token), datetime.datetime.utcnow().isoformat()),
    )
    if not row:
        return RedirectResponse("/login?error=Link+ungültig+oder+abgelaufen", status_code=302)
    await db_exec("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(password), row["user_id"]))
    await _sitzungen_beenden(row["user_id"])
    await db_exec("DELETE FROM password_reset_tokens WHERE token IN (?,?)", _token_pair(token))
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
async def users_role(request: Request, user_id: int, role: str = Form(...), next: str = Form("/users")):
    if r := admin_redirect(request): return r
    dest = next if (next == "/users" or next.startswith("/servers/")) else "/users"
    sep = "&" if "?" in dest else "?"
    if role not in ("admin", "moderator"):
        return RedirectResponse(f"{dest}{sep}error=Ungültige+Rolle", status_code=302)
    if role == "moderator":
        other_admins = await db_one(
            "SELECT COUNT(*) as c FROM users WHERE role='admin' AND id!=?", (user_id,)
        )
        if not other_admins or other_admins.get("c", 0) == 0:
            return RedirectResponse(f"{dest}{sep}error=Letzter+Admin+kann+nicht+herabgestuft+werden", status_code=302)
    await db_exec("UPDATE users SET role=? WHERE id=?", (role, user_id))
    return RedirectResponse(f"{dest}{sep}success=Rolle+geändert", status_code=302)


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
    weg = await _sitzungen_beenden(user_id)
    hinweis = "Passwort+geändert"
    if weg:
        hinweis += f",+{weg}+Anmeldung(en)+beendet"
    return RedirectResponse(f"/users?success={hinweis}", status_code=302)


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


def _cgroup_ram() -> tuple[int, int | None] | None:
    """Return (used_bytes, limit_bytes) from THIS container's own cgroup memory accounting, or
    None if the cgroup files aren't readable at all (not running in a container, or some other
    reason). limit_bytes is None when the container has no memory limit configured (cgroup v2's
    "max" / v1's near-2**63 no-limit sentinel) - used_bytes is still returned in that case,
    since cgroups track actual usage independently of whether a cap is set. Confirmed live: a
    container with no configured memory limit (`docker inspect` showing HostConfig.Memory=0)
    still has a perfectly readable, meaningful memory.current - discarding it just because
    there's no memory.max to divide it by (the previous behavior here) meant get_system_stats()
    fell all the way back to psutil's HOST-wide numbers, which look identical across every
    container running on the same machine regardless of each one's actual own footprint."""
    NO_LIMIT = 2 ** 62
    # cgroups v2 (modern Docker / systemd)
    try:
        raw_limit = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        used = int(Path("/sys/fs/cgroup/memory.current").read_text().strip())
        limit = None if raw_limit == "max" else int(raw_limit)
        if limit is None or 0 < limit < NO_LIMIT:
            return used, limit
    except Exception:
        pass
    # cgroups v1 (older Docker)
    try:
        limit = int(Path("/sys/fs/cgroup/memory/memory.limit_in_bytes").read_text().strip())
        used  = int(Path("/sys/fs/cgroup/memory/memory.usage_in_bytes").read_text().strip())
        if 0 < limit < NO_LIMIT:
            return used, limit
        if limit >= NO_LIMIT:
            return used, None
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
            used, limit = cg
            ram_used = used // (1024 ** 2)
            if limit is not None:
                ram_total = limit // (1024 ** 2)
                ram_pct   = round(used / limit * 100, 1)
            else:
                # No memory limit configured for this container - the host's total is the
                # practical ceiling, but ram_used stays THIS container's own actual usage
                # (not the host's aggregate, which would look identical for every container
                # on the same machine regardless of what each one is actually doing).
                vm = psutil.virtual_memory()
                ram_total = vm.total // (1024 ** 2)
                ram_pct   = round(used / vm.total * 100, 1) if vm.total else 0
        else:
            vm = psutil.virtual_memory()
            ram_used  = vm.used  // (1024 ** 2)
            ram_total = vm.total // (1024 ** 2)
            # vm.percent and vm.used use different internal definitions of "used" memory
            # (percent factors in reclaimable cache/buffers differently) - they can disagree
            # by a percentage point or more on a real host, looking inconsistent side by side
            # on the same card. Deriving the percentage from the exact same used/total shown
            # here keeps the bar and the numbers in agreement.
            ram_pct   = round(vm.used / vm.total * 100, 1) if vm.total else 0
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
        "user_allowed_tabs": await _viewer_allowed_tabs(request, guild_id) if guild_id else None,
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
    except (discord.HTTPException, OSError) as e:
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
    await db_exec("INSERT INTO invite_codes (code, expires_at) VALUES (?, ?)",
                  (_token_hash(code), expires_at))
    return JSONResponse({"code": code, "expires_at": expires_at})


@web.post("/admin/invite/revoke")
async def admin_invite_revoke(request: Request):
    if r := admin_redirect(request): return r
    await db_exec("DELETE FROM invite_codes WHERE used=0")
    return JSONResponse({"ok": True})


@web.post("/admin/logout-all")
async def admin_logout_all(request: Request):
    """User-requested ("mach führ den admin ein all logaut buton unter benutzer") after a live
    incident where a moderator's session ended up pointing at the admin's own account - see
    _current_session_epoch. Bumping the global epoch signs out every OTHER session on its next
    request; this clicking admin's own session is cleared explicitly right here instead of
    relying on that same indirect mechanism - a real browser follows the redirect below
    immediately, so leaving it to "their next request" would have them bounce through /users
    for a single unseen instant before landing on /login anyway (confirmed live: the automatic
    redirect-follow already IS that next request) - explicit is clearer than relying on that
    coincidence, and redirecting straight to /login here (with the success message) avoids the
    pointless bounce through a page they can no longer see."""
    if r := admin_redirect(request): return r
    await set_config("session_epoch", secrets.token_urlsafe(8))
    request.session.clear()
    return RedirectResponse("/login?success=Alle+angemeldeten+Sitzungen+wurden+beendet+–+bitte+erneut+einloggen", status_code=302)


@web.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, code: str = "", error: str = ""):
    if not code:
        return RedirectResponse("/login", status_code=302)
    inv = await db_one("SELECT * FROM invite_codes WHERE code IN (?,?) AND used=0",
                       _token_pair(code))
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
    inv = await db_one("SELECT * FROM invite_codes WHERE code IN (?,?) AND used=0",
                       _token_pair(code))
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
    await db_exec("UPDATE invite_codes SET used=1 WHERE code IN (?,?)", _token_pair(code))
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


_GITHUB_REPO_URL = "https://github.com/LucyWolf/phobos-bot"


@web.get("/settings/report", response_class=HTMLResponse)
async def report_page(request: Request):
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r
    lang = request.session.get("lang", "de")
    tr = get_tr(lang)
    body_template = (
        f"**{tr['report_body_question']}**\n\n\n"
        "---\n"
        f"{tr['report_body_auto_attached']}\n"
        f"- {tr['report_body_version_label']}: v{VERSION}\n"
        f"- {tr['report_body_platform_label']}: {_os_display_string()}\n"
    )
    return templates.TemplateResponse("settings_report.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request),
        # Without this the sidebar's "no bot token yet" warning fired on this page: the
        # template reads token_set, an absent one is undefined, and undefined is falsy - so
        # opening "Melden" turned Einstellungen red on an installation that has a token.
        "token_set": await _token_configured(),
        "active": "report",
        "github_repo_url": _GITHUB_REPO_URL,
        "github_signup_url": "https://github.com/signup",
        "body_template": body_template,
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
    user_allowed_tabs = await _viewer_allowed_tabs(request, guild_id)
    if user_allowed_tabs is not None and "freestuff" not in user_allowed_tabs:
        return _redirect_no_access(guild_id, user_allowed_tabs)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    cfg = await db_one("SELECT * FROM freestuff_channels WHERE guild_id=?", (guild_id,))
    return templates.TemplateResponse("freestuff.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request), "token_set": token_set,
        "active": f"server_{guild_id}",
        "guild_id": guild_id, "guild_name": guild.name,
        "channels": channels, "cfg": cfg,
        # Fuer die Ping-Auswahl - @everyone bleibt draussen, siehe _ping_roles().
        "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default()],
        "success": success, "error": error,
        "enabled_features": await _get_enabled_features(guild_id),
        "user_allowed_tabs": user_allowed_tabs,
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
    ping_role_id: str = Form(""),
    deal_ping_role_id: str = Form(""),
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
    # Rollen gegen die des Servers pruefen, wie ueberall sonst - eine erfundene ID wuerde sonst
    # gespeichert und spaeter stumm ins Leere zeigen.
    _b = bot._bot_for_guild(int(guild_id)) if str(guild_id).isdigit() else None
    _g = _b.get_guild(int(guild_id)) if _b else None
    _gueltig = {str(r.id) for r in _g.roles if not r.is_default()} if _g else set()
    for _rid in (ping_role_id, deal_ping_role_id):
        if _rid.strip() and _rid.strip() not in _gueltig:
            return RedirectResponse(
                f"/servers/{guild_id}/freestuff?error=Ungültige+Rolle", status_code=302)
    await db_exec(
        """INSERT INTO freestuff_channels
               (guild_id, channel_id, platforms, deal_max_price, deal_min_discount, deal_channel_id,
                deal_platforms, ping_role_id, ping_enabled, deal_ping_role_id, deal_ping_enabled)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(guild_id) DO UPDATE SET
               channel_id=excluded.channel_id,
               platforms=excluded.platforms,
               deal_max_price=excluded.deal_max_price,
               deal_min_discount=excluded.deal_min_discount,
               deal_channel_id=excluded.deal_channel_id,
               deal_platforms=excluded.deal_platforms,
               ping_role_id=excluded.ping_role_id,
               ping_enabled=excluded.ping_enabled,
               deal_ping_role_id=excluded.deal_ping_role_id,
               deal_ping_enabled=excluded.deal_ping_enabled""",
        (guild_id, channel_id, plat_str, max_price, min_disc, deal_ch, deal_plat_str,
         ping_role_id.strip(), 1, deal_ping_role_id.strip(), 1),
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
async def auto_delete_save(
    request: Request, guild_id: str, channel_id: str = Form(""), delay_seconds: str = Form(""),
    include_bot_messages: str = Form(""),
):
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
    include_bot_int = 1 if include_bot_messages else 0
    await db_exec(
        "INSERT INTO auto_delete_channels (guild_id, channel_id, delay_seconds, include_bot_messages) VALUES (?,?,?,?) "
        "ON CONFLICT(guild_id, channel_id) DO UPDATE SET delay_seconds=excluded.delay_seconds, "
        "include_bot_messages=excluded.include_bot_messages",
        (guild_id, channel_id, delay_int, include_bot_int),
    )
    await _reload_auto_delete()
    return RedirectResponse(f"/servers/{guild_id}?tab=autodelete&success=Gespeichert", status_code=302)

@web.post("/servers/{guild_id}/auto-delete/edit/{entry_id}")
async def auto_delete_edit(
    request: Request, guild_id: str, entry_id: int, channel_id: str = Form(""), delay_seconds: str = Form(""),
    include_bot_messages: str = Form(""),
):
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
    include_bot_int = 1 if include_bot_messages else 0
    try:
        await db_exec(
            "UPDATE auto_delete_channels SET channel_id=?, delay_seconds=?, include_bot_messages=? "
            "WHERE id=? AND guild_id=?",
            (channel_id, delay_int, include_bot_int, entry_id, guild_id),
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


# ── VRC-Link ──────────────────────────────────────────────────────────────────
# A member gets a personal link, opens a page of their own, proves the VRChat account is
# theirs by putting a short code into their VRChat status message, and a moderator (optionally) waves it
# through. The member-facing pages below are the only ones in this file that are reachable
# WITHOUT a dashboard login: the people using them are Discord members, not administrators.
# The token in the URL is what stands in for a login, and it is scoped to exactly one member
# on exactly one server and expires within the hour - see cogs/vrc_link.py for the rest.

async def _vrc_apply(guild_id: int, user_id: str, vrchat_name: str, revoke: bool = False) -> None:
    """Run the cog's own apply/revoke against the bot instance that serves this guild, so the
    dashboard and the slash commands can never end up doing two different things."""
    try:
        b = bot._bot_for_guild(guild_id)
        guild = b.get_guild(guild_id) if b else None
        member = guild.get_member(int(user_id)) if guild and str(user_id).isdigit() else None
        if not member:
            return
        from cogs.vrc_link import apply_link, revoke_link, sync_vrc_roles
        if revoke:
            await revoke_link(b, guild, member)
            return
        await apply_link(b, guild, member, vrchat_name)
        # "sobald der account verlinkt wurde": the VRChat roles this member's Discord roles
        # earn them are pushed the moment the link takes effect, not only on the next
        # interval - and an interval is optional on top of this, not a replacement for it.
        link = await db_one("SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
                            (str(guild_id), str(user_id)))
        if link:
            await sync_vrc_roles(guild, member, link)
    except Exception as e:
        print(f"[vrc_link] dashboard apply failed for {user_id} in {guild_id}: {e}")


@web.get("/settings/vrchat", response_class=HTMLResponse)
async def vrchat_settings_page(request: Request, error: str = "", success: str = ""):
    """The installation-wide VRChat bot account, alongside the other global settings.

    Not in a server's own tab: the bot signs in as ONE account for everything it does, so
    asking for it per server would mean typing the same credentials again and again - and
    VRChat counting each one as another login. Same arrangement as the Streaming-API page,
    which holds the Twitch apps that every server's settings then draw on.
    """
    if r := auth_redirect(request): return r
    if r := admin_redirect(request): return r
    account = await db_one("SELECT * FROM vrc_accounts WHERE guild_id=?", (VRC_ACCOUNT_KEY,))
    if account:
        # Password and session cookies stay on the server - the page only needs to know that
        # an account is stored, plus whoever it turned out to be.
        for _k in ("password", "totp_secret", "auth_cookie", "two_factor_cookie"):
            account[_k] = ""
    return templates.TemplateResponse("vrchat_settings.html", {
        **session(request), "request": request,
        "guilds": await _guild_list(request),
        "token_set": await _token_configured(),
        "active": "vrchat",
        "vrc_account": account,
        "error": error, "success": success,
    })


@web.post("/settings/vrchat/save")
async def vrc_account_save(request: Request):
    """Store the VRChat bot account and immediately try to sign in with it.

    Testing right here rather than offering a separate button: credentials that are only
    checked the first time something needs them fail hours later, in a background task, where
    the person who typed them is no longer looking.
    """
    # Admin-only rather than per-server: this one account serves the whole installation, so a
    # moderator of a single server must not be able to point it somewhere else - or read the
    # result of trying.
    if r := admin_redirect(request): return r
    form = await request.form()
    username = (form.get("vrc_username") or "").strip()
    password = (form.get("vrc_password") or "").strip()
    # The 2FA secret is deliberately not asked for any more - the form offers the one-time code
    # only. Anything a previous version stored is left alone in the row but no longer used, so
    # the behaviour here does not depend on what happens to be sitting in that column.
    # Written into the row as-is, which also clears anything an older version stored there.
    # Leaving a stale secret lying in the database when nothing reads it any more would be
    # keeping a credential around for no reason at all.
    totp = ""
    # Typed in for this one login. Never written to the database - it is valid for about thirty
    # seconds, so keeping it would be storing nothing useful.
    one_time = (form.get("vrc_code") or "").strip().replace(" ", "")
    existing = await db_one("SELECT * FROM vrc_accounts WHERE guild_id=?", (VRC_ACCOUNT_KEY,))
    # An empty password field means "leave it alone" - the form never renders the stored one
    # back into the page, so clearing the box would otherwise wipe the password every time
    # somebody corrects a typo in the username.
    if not password and existing:
        password = existing["password"]
    if not username or not password:
        return RedirectResponse(
            f"/settings/vrchat?error=Benutzername+und+Passwort+erforderlich",
            status_code=302)

    from vrchat import login as vrc_login, VRChatError
    # The cached session is only reusable while the username is unchanged; pointing the entry
    # at a different account has to start a real login.
    same_account = bool(existing and existing["username"] == username)
    try:
        result = await vrc_login(
            username, password, totp,
            auth_cookie=existing["auth_cookie"] if same_account else "",
            two_factor_cookie=existing["two_factor_cookie"] if same_account else "",
            one_time_code=one_time,
        )
    except VRChatError as e:
        await db_exec(
            "INSERT INTO vrc_accounts (guild_id, username, password, totp_secret, last_check, last_error) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET username=excluded.username, "
            "password=excluded.password, totp_secret=excluded.totp_secret, "
            "last_check=excluded.last_check, last_error=excluded.last_error",
            (VRC_ACCOUNT_KEY, username, password, totp,
             datetime.datetime.utcnow().isoformat(), str(e)[:500]),
        )
        return RedirectResponse(
            f"/settings/vrchat?error={urllib.parse.quote_plus(str(e))}",
            status_code=302)
    except Exception as e:
        # A network failure, a DNS hiccup, VRChat handing back something unparseable - none of
        # it should surface as a 500 on a page the admin is mid-way through filling in.
        print(f"[vrchat] unexpected error during login as {username!r}: {e!r}")
        return RedirectResponse(
            f"/settings/vrchat?error=VRChat+war+nicht+erreichbar",
            status_code=302)

    user = result["user"]
    await db_exec(
        "INSERT INTO vrc_accounts (guild_id, username, password, totp_secret, auth_cookie, "
        "two_factor_cookie, vrc_user_id, vrc_display_name, last_check, last_error) "
        "VALUES (?,?,?,?,?,?,?,?,?,'') ON CONFLICT(guild_id) DO UPDATE SET "
        "username=excluded.username, password=excluded.password, totp_secret=excluded.totp_secret, "
        "auth_cookie=excluded.auth_cookie, two_factor_cookie=excluded.two_factor_cookie, "
        "vrc_user_id=excluded.vrc_user_id, vrc_display_name=excluded.vrc_display_name, "
        "last_check=excluded.last_check, last_error=''",
        (VRC_ACCOUNT_KEY, username, password, totp, result["auth_cookie"],
         result["two_factor_cookie"], str(user.get("id") or ""),
         str(user.get("displayName") or ""), datetime.datetime.utcnow().isoformat()),
    )
    who = urllib.parse.quote_plus(str(user.get("displayName") or username))
    # The session now always rests on VRChat's twoFactorAuth cookie, which expires after roughly
    # a month. Said every time, because a connection that quietly stops working in four weeks
    # with nobody knowing why is the worst way for this to end.
    msg = (f"Verbunden+als+{who}"
           "+—+in+etwa+einem+Monat+ist+erneut+ein+Code+nötig")
    return RedirectResponse(f"/settings/vrchat?success={msg}", status_code=303)


@web.post("/settings/vrchat/delete")
async def vrc_account_delete(request: Request):
    # Admin-only for the same reason as saving it - see there.
    if r := admin_redirect(request): return r
    await db_exec("DELETE FROM vrc_accounts WHERE guild_id=?", (VRC_ACCOUNT_KEY,))
    return RedirectResponse("/settings/vrchat?success=VRChat-Konto+entfernt", status_code=303)


@web.post("/servers/{guild_id}/vrc/decide/{link_id}")
async def vrc_decide(request: Request, guild_id: int, link_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    action = form.get("action", "")
    row = await db_one("SELECT * FROM vrc_links WHERE id=? AND guild_id=?", (link_id, str(guild_id)))
    if not row:
        return RedirectResponse(f"/servers/{guild_id}?tab=vrclink&error=Nicht+gefunden", status_code=302)
    who = request.session.get("username", "admin")
    now = datetime.datetime.utcnow().isoformat()
    if action == "approve":
        await db_exec(
            "UPDATE vrc_links SET status='approved', decided_at=?, decided_by=? WHERE id=?",
            (now, who, link_id))
        await _vrc_apply(guild_id, row["user_id"], row["vrchat_name"])
        msg = "Freigegeben"
    elif action == "revoke":
        # Back to pending rather than deleted: the member keeps their entry and the moderator
        # keeps the history of who asked for what, which a delete would throw away.
        await db_exec(
            "UPDATE vrc_links SET status='pending', decided_at=?, decided_by=? WHERE id=?",
            (now, who, link_id))
        await _vrc_apply(guild_id, row["user_id"], row["vrchat_name"], revoke=True)
        msg = "Freigabe+zurückgenommen"
    elif action == "delete":
        # Reihenfolge wie beim Selbst-Loesen: zuruecknehmen, solange die Zeile noch da ist.
        if row["status"] == "approved":
            await _vrc_apply(guild_id, row["user_id"], row["vrchat_name"], revoke=True)
        await db_exec("DELETE FROM vrc_links WHERE id=?", (link_id,))
        msg = "Eintrag+gelöscht"
    else:
        return RedirectResponse(f"/servers/{guild_id}?tab=vrclink&error=Unbekannte+Aktion", status_code=302)
    return RedirectResponse(f"/servers/{guild_id}?tab=vrclink&success={msg}", status_code=303)


@web.post("/servers/{guild_id}/vrc/refresh")
async def vrc_refresh(request: Request, guild_id: int):
    """Re-apply role and nickname to every approved link - the "Bulk actions" of the service
    this was modelled on, for when the nickname format changed after people already linked."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    rows = await db_rows(
        "SELECT * FROM vrc_links WHERE guild_id=? AND status='approved'", (str(guild_id),))
    done = 0
    umbenannt = 0
    for row in rows:
        # Das VRChat-Profil WIRKLICH neu lesen. Vorher hat dieser Knopf nur Rolle und
        # Spitznamen aus dem gespeicherten Namen neu gesetzt - wer sich bei VRChat umbenannt
        # hatte, behielt hier also ewig den alten Namen, obwohl genau dieser Knopf laut
        # Beschreibung der Weg dafuer ist. Kostet eine Anfrage je Mitglied; deshalb sitzt er
        # hinter einem Knopf und auf keiner Zeitschaltuhr.
        neuer_name = row["vrchat_name"]
        if row["vrc_user_id"]:
            from cogs.vrc_link import fetch_profile, profile_fields
            state, user = await fetch_profile(row["vrc_user_id"])
            if state == "ok" and user:
                fields = profile_fields(user)
                neuer_name = fields["vrchat_name"] or row["vrchat_name"]
                try:
                    await db_exec(
                        "UPDATE vrc_links SET vrchat_name=?, vrc_trust=?, vrc_age_verified=?, "
                        "vrc_supporter=?, vrc_avatar=? WHERE id=?",
                        (neuer_name, fields["vrc_trust"], fields["vrc_age_verified"],
                         fields["vrc_supporter"], fields["vrc_avatar"], row["id"]),
                    )
                    if neuer_name != row["vrchat_name"]:
                        umbenannt += 1
                except Exception as e:
                    # Der neue Name kann mit einer anderen Verknuepfung auf diesem Server
                    # kollidieren - dann gewinnt der eindeutige Index, und dieses eine
                    # Mitglied bleibt, wie es war. Der Rest laeuft weiter.
                    print(f"[vrc_link] Auffrischen von {row['id']} fehlgeschlagen: {e}")
                    neuer_name = row["vrchat_name"]
        # Sequential on purpose: each iteration is one or two Discord edits, and firing a few
        # hundred of them at once is how a bot earns a rate limit that stalls everything else
        # it is doing. discord.py serialises per route anyway, so this only looks slower.
        #
        # The group is re-read here too, which is one VRChat request per member. That is a lot,
        # and it is why this sits behind a button an admin presses deliberately rather than on
        # any timer - "refresh everything" is exactly when somebody wants the group state to be
        # current, and no_op when no group is configured.
        await _vrc_sync_group(guild_id, row)
        await _vrc_apply(guild_id, row["user_id"], neuer_name)
        done += 1
    hinweis = f"{done}+Verknüpfung(en)+aufgefrischt"
    if umbenannt:
        hinweis += f",+davon+{umbenannt}+mit+neuem+VRChat-Namen"
    return RedirectResponse(f"/servers/{guild_id}?tab=vrclink&success={hinweis}",
                            status_code=303)


@web.post("/servers/{guild_id}/vrc/panel")
async def vrc_panel_post(request: Request, guild_id: int):
    """Post the link panel into the configured channel.

    A button on a message is what makes this feature reachable at all: a slash command only
    appears once Discord has propagated it, which takes up to an hour globally and is exactly
    what made the first version look broken. A posted message works the instant it exists.
    """
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    channel_id = await get_guild_config(guild_id, "vrc_panel_channel") or ""
    b = bot._bot_for_guild(guild_id)
    guild = b.get_guild(guild_id) if b else None
    channel = guild.get_channel(int(channel_id)) if guild and str(channel_id).isdigit() else None
    if not guild or not isinstance(channel, discord.TextChannel):
        return RedirectResponse(
            f"/servers/{guild_id}?tab=vrclink&error=Bitte+zuerst+einen+Textkanal+auswählen+und+speichern",
            status_code=303)
    try:
        from cogs.vrc_link import post_panel
        await post_panel(b, guild, channel)
    except discord.Forbidden:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=vrclink&error=Dem+Bot+fehlt+die+Berechtigung+in+diesem+Kanal",
            status_code=303)
    except Exception as e:
        print(f"[vrc_link] panel post failed in {guild_id}: {e}")
        return RedirectResponse(
            f"/servers/{guild_id}?tab=vrclink&error={urllib.parse.quote_plus(str(e)[:120])}",
            status_code=303)
    return RedirectResponse(
        f"/servers/{guild_id}?tab=vrclink&success=Panel+gepostet", status_code=303)


@web.post("/servers/{guild_id}/vrc/probe")
async def vrc_probe(request: Request, guild_id: int, vrchat_name: str = Form("")):
    """Show an admin exactly what VRChat hands back for one name.

    Built because the ownership check kept reporting the code as missing while it was
    plainly visible on the profile, and there was no way to tell the two possible causes apart
    from the outside: the text has not reached VRChat's API yet, or the bot never receives that
    field at all. The same question applies to the 18+ badge, which VRChat has shipped under
    more than one name and may not expose for other people's accounts.

    So this answers it with facts instead of guesses: which fields came back, how long the text
    is, whether the age flag is there. Admin-level and read-only - it stores nothing.
    """
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return JSONResponse({"error": "Kein Zugriff"}, status_code=403)
    name = " ".join((vrchat_name or "").split())[:MAX_VRCHAT_NAME_WEB]
    if not name:
        return JSONResponse({"error": "Bitte einen VRChat-Namen eingeben."})
    from cogs.vrc_link import resolve_vrchat, profile_text, PROFILE_TEXT_FIELDS
    try:
        state, user = await resolve_vrchat(name)
    except Exception as e:
        return JSONResponse({"error": f"Abfrage fehlgeschlagen: {str(e)[:200]}"})
    if state == "not_found":
        return JSONResponse({"error": f"VRChat kennt kein Konto namens „{name}“."})
    if state != "ok":
        return JSONResponse({"error": "VRChat ist nicht erreichbar oder kein Konto verbunden."})
    from vrchat import trust_rank, is_age_verified, is_supporter
    text = profile_text(user)
    return JSONResponse({
        "name": str(user.get("displayName") or ""),
        "id": str(user.get("id") or ""),
        "trust": trust_rank(user),
        "age": bool(is_age_verified(user)),
        # The three spellings is_age_verified() looks at, reported separately - "no 18+" means
        # something very different when NONE of them came back than when one came back false.
        "age_fields": {k: user.get(k) for k in ("ageVerified", "ageVerificationStatus")
                       if k in user},
        "age_tag": "system_age_verified" in set(user.get("tags") or []),
        "supporter": bool(is_supporter(user)),
        # Which of the fields the ownership check reads actually arrived, and what is in them.
        "text_fields": {k: (user.get(k) if isinstance(user.get(k), str) else None)
                        for k in PROFILE_TEXT_FIELDS},
        "text": text[:600],
        "text_len": len(text),
        "fields": sorted(user.keys())[:80],
    })


async def _vrc_group_and_bot(guild_id: int) -> dict:
    """The configured group, plus where the BOT account itself stands with it.

    The bot cannot be granted a single group permission until it is a member, so this is the
    first thing an operator needs to see - and it was previously nowhere on the page.
    """
    group_id = (await get_guild_config(guild_id, "vrc_group_id") or "").strip()
    if not group_id:
        return {"error": "Für diesen Server ist keine Gruppen-ID eingetragen."}
    account = await db_one("SELECT * FROM vrc_accounts WHERE guild_id=?", (VRC_ACCOUNT_KEY,))
    if not account or not account["vrc_user_id"]:
        return {"error": "Es ist kein VRChat-Bot-Konto verbunden."}
    from cogs.vrc_link import vrc_session
    session = await vrc_session()
    if not session:
        return {"error": "Die VRChat-Anmeldung des Bot-Kontos funktioniert gerade nicht."}
    from vrchat import get_group, group_member, GROUP_STATUS_LABELS
    out = {"group_id": group_id, "bot_name": account["vrc_display_name"] or account["username"]}
    try:
        group = await get_group(group_id, session["auth_cookie"], session["two_factor_cookie"])
    except Exception as e:
        # A group the bot cannot see is the normal answer for "not a member yet", not a
        # breakdown - so the name stays unknown and the membership check below still runs.
        group = None
        out["group_note"] = str(e)[:200]
    if group:
        out["group_name"] = str(group.get("name") or "")
        out["group_members"] = group.get("memberCount")
    try:
        member = await group_member(group_id, account["vrc_user_id"],
                                    session["auth_cookie"], session["two_factor_cookie"])
    except Exception as e:
        return {**out, "error": str(e)[:200]}
    status = "member" if member else "inactive"
    if isinstance(member, dict) and member.get("membershipStatus"):
        status = str(member["membershipStatus"])
    out["bot_status"] = status
    out["bot_status_text"] = GROUP_STATUS_LABELS.get(status, status)
    out["bot_is_member"] = status == "member"
    return out


@web.post("/servers/{guild_id}/vrc/group/check")
async def vrc_group_check(request: Request, guild_id: int):
    """Read-only: is the bot account in this group, and what is the group called."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return JSONResponse({"error": "Kein Zugriff"}, status_code=403)
    try:
        return JSONResponse(await _vrc_group_and_bot(guild_id))
    except Exception as e:
        print(f"[vrc_link] group check for guild {guild_id} failed: {e}")
        return JSONResponse({"error": str(e)[:200]})


@web.post("/servers/{guild_id}/vrc/group/roles")
async def vrc_group_roles(request: Request, guild_id: int):
    """The group's own roles, for the mapping dropdown. Read-only."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return JSONResponse({"error": "Kein Zugriff"}, status_code=403)
    group_id = (await get_guild_config(guild_id, "vrc_group_id") or "").strip()
    if not group_id:
        return JSONResponse({"error": "Für diesen Server ist keine Gruppen-ID eingetragen."})
    from cogs.vrc_link import vrc_session
    session = await vrc_session()
    if not session:
        return JSONResponse({"error": "Die VRChat-Anmeldung des Bot-Kontos funktioniert gerade nicht."})
    from vrchat import get_group_roles
    try:
        roles = await get_group_roles(group_id, session["auth_cookie"],
                                      session["two_factor_cookie"])
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]})
    return JSONResponse({"roles": roles})


@web.post("/servers/{guild_id}/vrc/instances/check")
async def vrc_instances_check(request: Request, guild_id: int):
    """Look for open group instances right now and announce whatever is new.

    The same routine the timer runs, on a button - so an admin can see it work instead of
    waiting out an interval to find out whether the channel and permissions are right.
    """
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return JSONResponse({"error": "Kein Zugriff"}, status_code=403)
    group_id = (await get_guild_config(guild_id, "vrc_group_id") or "").strip()
    if not group_id:
        return JSONResponse({"error": "Für diesen Server ist keine Gruppen-ID eingetragen."})
    b = bot._bot_for_guild(guild_id)
    guild = b.get_guild(guild_id) if b else None
    if not guild:
        return JSONResponse({"error": "Der Bot ist auf diesem Server gerade nicht erreichbar."})
    from cogs.vrc_link import vrc_session, announce_instances
    session = await vrc_session()
    if not session:
        return JSONResponse({"error": "Die VRChat-Anmeldung des Bot-Kontos funktioniert gerade nicht."})
    from vrchat import get_group_instances_raw, _parse_group_instances
    try:
        # Roh holen und selbst auswerten, damit die Antwort BEIDE Zahlen kennt: was VRChat
        # geschickt hat und was davon lesbar war. "Er sieht die Instanz nicht" und "er sieht
        # die Leute nicht" sehen sonst gleich aus, sind aber zwei verschiedene Probleme.
        roh = await get_group_instances_raw(group_id, session["auth_cookie"],
                                            session["two_factor_cookie"])
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]})
    instances = _parse_group_instances(roh)
    posted = 0
    if (await get_guild_config(guild_id, "vrc_instance_channel") or "").strip().isdigit():
        posted = await announce_instances(b, guild)
    return JSONResponse({
        "geliefert": len(roh) if isinstance(roh, list) else 0,
        "open": [{"world": i["world_name"] or "(ohne Namen)", "count": i["count"]}
                 for i in instances],
        "posted": posted,
    })


def _kurzfassung(wert, tiefe: int = 0):
    """Ein Wert so, dass ein Mensch ihn lesen kann, ohne dass eine Seite explodiert.

    Zahlen, Wahrheitswerte und kurze Texte kommen unveraendert; laengere Texte werden
    gekuerzt; verschachtelte Objekte zeigen ihre Schluessel statt ihres ganzen Inhalts. Es
    geht darum zu sehen, WELCHE Felder es gibt und was ungefaehr drinsteht - nicht darum,
    eine Antwort vollstaendig abzudrucken.
    """
    if isinstance(wert, str):
        return wert if len(wert) <= 120 else wert[:117] + "…"
    if isinstance(wert, (int, float, bool)) or wert is None:
        return wert
    if isinstance(wert, dict):
        if tiefe >= 1:
            return f"{{…{len(wert)} Felder: {', '.join(sorted(wert)[:8])}}}"
        return {k: _kurzfassung(v, tiefe + 1) for k, v in sorted(wert.items())}
    if isinstance(wert, list):
        if not wert:
            return []
        return [_kurzfassung(x, tiefe + 1) for x in wert[:5]] + \
               ([f"… und {len(wert) - 5} weitere"] if len(wert) > 5 else [])
    return str(wert)[:120]


@web.post("/servers/{guild_id}/vrc/instances/raw")
async def vrc_instances_raw(request: Request, guild_id: int):
    """Zeigt unveraendert, was VRChat fuer die offenen Instanzen dieser Gruppe liefert.

    Gebaut, weil zwei Fragen offen sind, die sich nicht nachlesen lassen: ob eine Instanz
    einen selbst vergebenen Namen mitbringt, und ob VRChat die drei Zustaende unterscheidet -
    offen, geschlossen (keiner kommt mehr rein, die Drinnen bleiben) und beendet. Die
    Schnittstelle ist nicht dokumentiert; was in einer Antwort steht, sieht man nur nach.

    Zusaetzlich wird fuer die erste Instanz die EINZELANSICHT geholt: Gruppenliste und
    Einzelansicht liefern erfahrungsgemaess nicht dasselbe, und ein Zustandsfeld steht eher
    dort. Nur fuer die erste, damit die Prüfhilfe nicht selbst zur Anfragenschleuder wird.

    Liest nur, speichert nichts.
    """
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return JSONResponse({"error": "Kein Zugriff"}, status_code=403)
    group_id = (await get_guild_config(guild_id, "vrc_group_id") or "").strip()
    if not group_id:
        return JSONResponse({"error": "Für diesen Server ist keine Gruppen-ID eingetragen."})
    from cogs.vrc_link import vrc_session
    session = await vrc_session()
    if not session:
        return JSONResponse({"error": "Die VRChat-Anmeldung des Bot-Kontos funktioniert gerade nicht."})
    from vrchat import get_group_instances_raw, get_instance
    try:
        roh = await get_group_instances_raw(group_id, session["auth_cookie"],
                                            session["two_factor_cookie"])
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]})
    if not isinstance(roh, list):
        return JSONResponse({"error": "VRChat antwortete nicht mit einer Liste."})

    eintraege = []
    for entry in roh[:10]:
        if isinstance(entry, dict):
            eintraege.append({"felder": sorted(entry.keys()),
                              "inhalt": _kurzfassung(entry)})
    einzeln = None
    ort = ""
    for entry in roh:
        if isinstance(entry, dict):
            ort = str(entry.get("location") or "")
            if not ort:
                w = entry.get("world") if isinstance(entry.get("world"), dict) else {}
                wid, iid = str(w.get("id") or ""), str(entry.get("instanceId") or "")
                ort = f"{wid}:{iid}" if wid and iid else ""
            if ort:
                break
    if ort:
        try:
            details = await get_instance(ort, session["auth_cookie"],
                                         session["two_factor_cookie"])
            if details:
                einzeln = {"ort": ort, "felder": sorted(details.keys()),
                           "inhalt": _kurzfassung(details)}
        except Exception as e:
            einzeln = {"ort": ort, "fehler": str(e)[:200]}
    return JSONResponse({"anzahl": len(roh), "instanzen": eintraege, "einzelansicht": einzeln})


# ── Debug-Bericht ────────────────────────────────────────────────────────────────
# Gebaut auf Zuruf ("kannst du ein debug machen dann teste ich das direkt, ich will gerne
# sehen was der alles melden kann"). Anders als "Rohdaten anzeigen" kuerzt hier nichts auf
# eine Feldliste zusammen: der Bericht ist ein Text zum Kopieren, der in EINEM Durchlauf
# alles sammelt, was der Bot ueber VRChat erfahren kann - Konto, Gruppe, Rollen, jede offene
# Instanz roh und ausgewertet, dazu der eigene gespeicherte Stand und die Einstellungen.
# Damit laesst sich von aussen beantworten, was sich nicht nachlesen laesst: wie VRChat einen
# selbst vergebenen Instanznamen nennt und ob ueberhaupt ein Feld den Zwischenzustand
# "geschlossen" verraet.

# Feldnamen, die nach Zustand, Name oder Zugang klingen. Nur zum Hervorheben - der ganze
# Baum steht ohnehin darunter, das hier spart nur das Suchen.
_DEBUG_SPUR = ("clos", "hard", "end", "activ", "shut", "lock", "queue", "full", "capacit",
               "name", "displayname", "type", "access", "public", "invite", "strict",
               "count", "occupan", "user", "age", "role", "owner", "created", "region",
               "canrequest", "hidden", "secure", "permanent", "tag")


def _flach(wert, pfad: str = "", raus: list | None = None) -> list:
    """Macht aus einer verschachtelten Antwort flache "pfad = wert"-Paare.

    Listen werden bei 8 Eintraegen gekappt, lange Texte bei 200 Zeichen: der Bericht soll
    vollstaendig genug sein, um Feldnamen zu finden, und kurz genug, um ihn zu verschicken.
    """
    raus = [] if raus is None else raus
    if isinstance(wert, dict):
        if not wert:
            raus.append((pfad or ".", "{}"))
        for k in sorted(wert):
            _flach(wert[k], f"{pfad}.{k}" if pfad else str(k), raus)
    elif isinstance(wert, list):
        if not wert:
            raus.append((pfad or ".", "[]"))
        for i, v in enumerate(wert[:8]):
            _flach(v, f"{pfad}[{i}]", raus)
        if len(wert) > 8:
            raus.append((f"{pfad}[…]", f"und {len(wert) - 8} weitere"))
    else:
        text = wert if isinstance(wert, (int, float, bool)) or wert is None else str(wert)
        text = str(text)
        raus.append((pfad or ".", text if len(text) <= 200 else text[:197] + "…"))
    return raus


def _baum(wert, einzug: str = "  ") -> list:
    """Der flache Baum als Textzeilen."""
    return [f"{einzug}{p} = {w}" for p, w in _flach(wert)]


def _auffaellig(wert) -> list:
    """Die Zeilen daraus, deren Feldname nach einem Zustands- oder Namensfeld klingt."""
    treffer = []
    for p, w in _flach(wert):
        letzte = p.split(".")[-1].split("[")[0].lower()
        if any(s in letzte for s in _DEBUG_SPUR):
            treffer.append(f"  {p} = {w}")
    return treffer


@web.post("/servers/{guild_id}/vrc/debug")
async def vrc_debug(request: Request, guild_id: int):
    """Sammelt in einem Rutsch alles, was der Bot ueber die VRChat-Seite sagen kann.

    Kostet je nach Lage etwa fuenf bis zehn VRChat-Anfragen - deswegen ein Knopf und keine
    Schleife. Liest nur, schreibt nichts, und laesst Passwoerter, Geheimnisse und Kekse
    draussen. Jeder Abschnitt faengt seine Fehler selbst ab: faellt einer aus, steht das
    drin und der Rest wird trotzdem fertig.
    """
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return JSONResponse({"error": "Kein Zugriff"}, status_code=403)

    b = bot._bot_for_guild(guild_id)
    guild = b.get_guild(guild_id) if b else None
    z = []
    z.append("═══ Phobos VRC-Debug ═══")
    z.append(f"Erzeugt: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC · Phobos v{VERSION}")
    z.append(f"Server:  {(guild.name if guild else '(Bot nicht auf dem Server)')} [{guild_id}]")
    z.append("")

    cfg = await get_all_guild_config(guild_id)
    group_id = (cfg.get("vrc_group_id") or "").strip()

    # ── 1. Einstellungen ─────────────────────────────────────────────────────
    z.append("── 1. Einstellungen (vrc_*) ──")
    geheim = ("pass", "secret", "token", "cookie")
    vrc_keys = sorted(k for k in cfg if k.startswith("vrc_"))
    if not vrc_keys:
        z.append("  (nichts eingetragen)")
    for k in vrc_keys:
        v = cfg.get(k) or ""
        if any(g in k.lower() for g in geheim):
            v = "(nicht angezeigt)" if v else ""
        if len(v) > 200:
            v = v[:197] + "…"
        z.append(f"  {k} = {v}")
    z.append("")

    # ── 2. Bot-Konto ─────────────────────────────────────────────────────────
    z.append("── 2. VRChat-Konto des Bots ──")
    from cogs.vrc_link import vrc_session, VRC_ACCOUNT_KEY
    konto = await db_one("SELECT * FROM vrc_accounts WHERE guild_id=?", (VRC_ACCOUNT_KEY,))
    if not konto or not konto["username"]:
        z.append("  Kein VRChat-Konto hinterlegt - ab hier geht nichts weiter.")
        return JSONResponse({"report": "\n".join(z)})
    z.append(f"  Benutzername:   {konto['username']}")
    z.append(f"  VRChat-ID:      {konto['vrc_user_id'] or '(unbekannt)'}")
    z.append(f"  Anzeigename:    {konto['vrc_display_name'] or '(unbekannt)'}")
    z.append(f"  2FA-Geheimnis:  {'hinterlegt' if konto['totp_secret'] else 'nein'}")
    z.append(f"  Sitzungs-Keks:  {'vorhanden' if konto['auth_cookie'] else 'nein'}")
    z.append(f"  Letzte Prüfung: {konto['last_check'] or '-'}")
    z.append(f"  Letzter Fehler: {konto['last_error'] or '-'}")
    session = await vrc_session()
    if not session:
        z.append("  → Anmeldung klappt gerade NICHT. Ohne sie bleibt der Rest leer.")
        return JSONResponse({"report": "\n".join(z)})
    z.append("  → Anmeldung steht.")
    z.append("")

    import vrchat as V

    # ── 3. Gruppe ────────────────────────────────────────────────────────────
    z.append("── 3. Gruppe ──")
    if not group_id:
        z.append("  Keine Gruppen-ID eingetragen - Abschnitte 3 bis 6 entfallen.")
        return JSONResponse({"report": "\n".join(z)})
    z.append(f"  Gruppen-ID: {group_id}")
    try:
        gruppe = await V.get_group(group_id, session["auth_cookie"], session["two_factor_cookie"])
        if not gruppe:
            z.append("  VRChat kennt diese Gruppe nicht (oder der Bot darf sie nicht sehen).")
        else:
            z.extend(_baum(gruppe))
    except Exception as e:
        z.append(f"  Fehler: {str(e)[:300]}")
    z.append("")

    # ── 4. Rollen der Gruppe ─────────────────────────────────────────────────
    z.append("── 4. Rollen der Gruppe ──")
    try:
        rollen = await V.get_group_roles(group_id, session["auth_cookie"],
                                         session["two_factor_cookie"])
        if not rollen:
            z.append("  Keine Rollen gelesen. Meist fehlt dem Bot-Konto das Recht dazu.")
        for ro in rollen[:25]:
            z.append(f"  • {ro.get('name', '?')}  [{ro.get('id', '?')}]"
                     f"{'  (Verwaltung)' if ro.get('isManagementRole') else ''}")
    except Exception as e:
        z.append(f"  Fehler: {str(e)[:300]}")
    zuord = await db_rows("SELECT * FROM vrc_role_map WHERE guild_id=?", (str(guild_id),))
    z.append(f"  Hinterlegte Zuordnungen Discord → VRChat: {len(zuord)}")
    for zz in zuord[:25]:
        rolle = guild.get_role(int(zz["discord_role_id"])) if guild and str(zz["discord_role_id"]).isdigit() else None
        z.append(f"    {(rolle.name if rolle else zz['discord_role_id'])} → "
                 f"{zz['vrc_role_name'] or zz['vrc_role_id']}")
    z.append("")

    # ── 5. Offene Instanzen ──────────────────────────────────────────────────
    z.append("── 5. Instanzen, wie die Gruppenliste sie liefert ──")
    roh = []
    try:
        roh = await V.get_group_instances_raw(group_id, session["auth_cookie"],
                                              session["two_factor_cookie"])
    except Exception as e:
        z.append(f"  Fehler: {str(e)[:300]}")
    if not isinstance(roh, list):
        z.append(f"  VRChat antwortete nicht mit einer Liste, sondern mit {type(roh).__name__}.")
        roh = []
    z.append(f"  VRChat liefert {len(roh)} Eintrag/Einträge.")
    for n, eintrag in enumerate(roh[:5], 1):
        z.append("")
        z.append(f"  ┌─ Eintrag {n} ─ vollständig ─")
        z.extend("  " + line for line in _baum(eintrag))
    if len(roh) > 5:
        z.append(f"  … und {len(roh) - 5} weitere Einträge, hier nicht abgedruckt.")
    z.append("")

    z.append("── 5b. Was der Bot daraus macht ──")
    try:
        gelesen = V._parse_group_instances(roh)
        if not gelesen:
            z.append("  Nichts lesbar. Wenn oben Einträge stehen, heißen die Felder anders "
                     "als erwartet - genau das steht dann in Abschnitt 5.")
        for i in gelesen:
            z.append(f"  • Welt: {i.get('world_name') or '(ohne Namen)'}")
            z.append(f"    Ort:  {i.get('location')}")
            z.append(f"    Drin: {i.get('count')}")
            z.append(f"    Link: {V.launch_url(i.get('location') or '')}")
    except Exception as e:
        z.append(f"  Fehler beim Auswerten: {str(e)[:300]}")
    z.append("")

    # ── 6. Einzelansicht ─────────────────────────────────────────────────────
    z.append("── 6. Einzelansicht je Instanz (eigene Anfrage, oft mehr Felder) ──")
    orte = [str(i.get("location") or "") for i in (V._parse_group_instances(roh) or [])]
    orte = [o for o in orte if o][:3]
    if not orte:
        z.append("  Kein Ort bekannt, also nichts abzufragen.")
    for ort in orte:
        z.append("")
        z.append(f"  ┌─ {ort} ─")
        try:
            det = await V.get_instance(ort, session["auth_cookie"], session["two_factor_cookie"])
            if not det:
                z.append("    VRChat gibt dazu nichts zurück (Instanz schon vorbei?).")
            else:
                z.extend("  " + line for line in _baum(det))
                from vrchat import instance_state
                lage = instance_state(det)
                z.append("    ── so liest der Bot das ──")
                z.append(f"    Zustand: {'GESCHLOSSEN seit ' + lage['closed_at'] if lage['closed_at'] else 'offen'}"
                         f" · hart: {lage['hard_close']}")
                z.append(f"    Eigener Name: {lage['name'] or '(keiner, nur die Instanznummer)'}")
                z.append(f"    Drin: {lage['count']}")
                spur = _auffaellig(det)
                if spur:
                    z.append("    ── davon interessant für Zustand/Name ──")
                    z.extend("  " + s for s in spur)
        except Exception as e:
            z.append(f"    Fehler: {str(e)[:300]}")
    z.append("")

    # ── 7. Eigener Stand ─────────────────────────────────────────────────────
    z.append("── 7. Was der Bot selbst gespeichert hat ──")
    eigene = await db_rows("SELECT * FROM vrc_instances WHERE guild_id=? ORDER BY id DESC "
                           "LIMIT 15", (str(guild_id),))
    if not eigene:
        z.append("  Noch keine Instanz vermerkt.")
    for e in eigene:
        z.append(f"  • {e['location']}")
        z.append(f"    Welt {e['world_name'] or '-'} · Nachricht {e['message_id'] or '-'} · "
                 f"zuletzt {e['last_count'] if e['last_count'] is not None else '-'} drin")
        z.append(f"    zuerst gesehen {e['first_seen'] or '-'} · beendet {e['closed_at'] or '-'}")
    z.append("")

    # ── 8. Verknüpfte Mitglieder ─────────────────────────────────────────────
    z.append("── 8. Verknüpfte Mitglieder (Zahlen, keine Namen) ──")
    try:
        links = await db_rows("SELECT * FROM vrc_links WHERE guild_id=?", (str(guild_id),))
        z.append(f"  Verknüpft: {len(links)}")
        z.append(f"  davon bestätigt: {sum(1 for l in links if l['verified_at'])}")
        z.append(f"  davon 18+ bei VRChat: {sum(1 for l in links if l['vrc_age_verified'])}")
        z.append(f"  davon in der Gruppe: {sum(1 for l in links if l['vrc_group_member'])}")
    except Exception as e:
        z.append(f"  Fehler: {str(e)[:300]}")

    bericht = "\n".join(z)
    if len(bericht) > 120000:
        bericht = bericht[:120000] + "\n… hier abgeschnitten."
    return JSONResponse({"report": bericht})


@web.post("/servers/{guild_id}/vrc/rolemap/add")
async def vrc_rolemap_add(request: Request, guild_id: int, discord_role_id: str = Form(""),
                          vrc_role_id: str = Form(""), vrc_role_name: str = Form("")):
    """Add one "Discord role → VRChat group role" pair."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    b = bot._bot_for_guild(guild_id)
    guild = b.get_guild(guild_id) if b else None
    valid = {str(ro.id) for ro in guild.roles if not ro.is_default()} if guild else set()
    if discord_role_id not in valid:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=vrclink&error=Ungültige+Discord-Rolle", status_code=303)
    vrc_role_id = (vrc_role_id or "").strip()[:64]
    if not vrc_role_id:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=vrclink&error=Bitte+eine+VRChat-Rolle+wählen",
            status_code=303)
    try:
        await db_exec(
            "INSERT OR IGNORE INTO vrc_role_map (guild_id, discord_role_id, vrc_role_id, "
            "vrc_role_name, created_at) VALUES (?,?,?,?,?)",
            (str(guild_id), discord_role_id, vrc_role_id, (vrc_role_name or "").strip()[:100],
             datetime.datetime.utcnow().isoformat()),
        )
    except Exception as e:
        print(f"[vrc_link] could not store the role mapping for {guild_id}: {e}")
        return RedirectResponse(
            f"/servers/{guild_id}?tab=vrclink&error=Zuordnung+konnte+nicht+gespeichert+werden",
            status_code=303)
    weg = await _vrc_sync_rolemap(guild_id)
    hinweis = "Zuordnung+gespeichert"
    if weg:
        hinweis += f",+bei+{weg}+Mitglied(ern)+angewendet"
    return RedirectResponse(f"/servers/{guild_id}?tab=vrclink&success={hinweis}", status_code=303)


@web.post("/servers/{guild_id}/vrc/rolemap/delete/{map_id}")
async def vrc_rolemap_delete(request: Request, guild_id: int, map_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    # guild_id in the WHERE as well as the id: without it, a moderator of one server could
    # delete another server's mapping by guessing a number.
    await db_exec("DELETE FROM vrc_role_map WHERE id=? AND guild_id=?", (map_id, str(guild_id)))
    weg = await _vrc_sync_rolemap(guild_id)
    hinweis = "Zuordnung+entfernt"
    if weg:
        hinweis += f",+bei+{weg}+Mitglied(ern)+nachgezogen"
    return RedirectResponse(f"/servers/{guild_id}?tab=vrclink&success={hinweis}", status_code=303)


async def _vrc_sync_rolemap(guild_id: int) -> int:
    """Zieht die VRChat-Rollen aller bestaetigten Mitglieder nach. Gibt zurueck, bei wie vielen.

    Gebraucht, wenn sich die ZUORDNUNG aendert statt der Discord-Rollen. Fuer Rollenwechsel
    gibt es den Listener im Cog; eine geloeschte Zuordnung loest den aber nicht aus - die
    Betroffenen behielten ihre VRChat-Rolle, bis sich zufaellig etwas anderes an ihnen
    aenderte. Ein Admin, der eine Zuordnung wegnimmt, meint damit die Rechte.

    Kostet je betroffenem Mitglied eine VRChat-Anfrage und sonst nichts: sync_vrc_roles()
    vergleicht gegen den gemerkten Stand und ruft nur an, wo sich wirklich etwas unterscheidet.
    """
    b = bot._bot_for_guild(guild_id)
    guild = b.get_guild(guild_id) if b else None
    if not guild:
        return 0
    from cogs.vrc_link import sync_vrc_roles
    rows = await db_rows(
        "SELECT * FROM vrc_links WHERE guild_id=? AND status='approved' AND vrc_group_member=1",
        (str(guild_id),))
    betroffen = 0
    for row in rows:
        member = guild.get_member(int(row["user_id"])) if str(row["user_id"]).isdigit() else None
        if not member:
            continue
        try:
            if await sync_vrc_roles(guild, member, row):
                betroffen += 1
        except Exception as e:
            print(f"[vrc_link] Nachziehen fuer {row['user_id']} in {guild_id}: {e}")
    return betroffen


@web.post("/servers/{guild_id}/vrc/group/join")
async def vrc_group_join(request: Request, guild_id: int):
    """Have the bot account join the configured group.

    An open group takes it straight away; a request-based one answers "requested" and the
    group's own staff decide. Either way this saves an operator from signing in to vrchat.com
    as the bot account, two-factor and all, to press one button.
    """
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return JSONResponse({"error": "Kein Zugriff"}, status_code=403)
    group_id = (await get_guild_config(guild_id, "vrc_group_id") or "").strip()
    if not group_id:
        return JSONResponse({"error": "Für diesen Server ist keine Gruppen-ID eingetragen."})
    from cogs.vrc_link import vrc_session
    session = await vrc_session()
    if not session:
        return JSONResponse({"error": "Die VRChat-Anmeldung des Bot-Kontos funktioniert gerade nicht."})
    from vrchat import join_group, GROUP_STATUS_LABELS
    try:
        status = await join_group(group_id, session["auth_cookie"], session["two_factor_cookie"])
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]})
    return JSONResponse({
        "bot_status": status,
        "bot_status_text": GROUP_STATUS_LABELS.get(status, status),
        "bot_is_member": status == "member",
    })


# ── VRC-Link: the member's own page ───────────────────────────────────────────
# Everything below is reachable WITHOUT a dashboard login. That is the point: these pages are
# for Discord members, who have no account here and never will. A token is the whole
# credential, which is why it names exactly one member on exactly one server, expires within
# the hour, and is the only thing any of these routes will act on - none of them take a user
# or guild id from the request.
#
# The token is carried in the FORM, not in the address - and these pages set no cookie of any
# kind, by request ("ich wil keine cookies"). That leaves exactly one place where it is visible:
# the link handed out in Discord, because a link cannot carry anything else. From the first
# page onwards every action is a POST with the token in the body, where no proxy log, no
# browser history, no Referer header and no screenshot of an address bar ever sees it. Even the
# language switch is a POST for that reason.
#
# Worth being plain about what that does NOT achieve: the entry link itself still appears once
# in the access log and the history, for as long as it is valid. Without a cookie there is no
# way around that - a reload is a GET, and a GET can only carry state in its address. Exactly
# the same exposure the invite link and the password-reset link in this project already have.
#
# CSRF: a form on someone else's site cannot supply the token, since there is no cookie the
# browser would attach on its own. The token IS the proof, and only the member has it.

# How long to wait between two VRChat lookups for the same visitor. Every one of them is a
# request to an interface that rate-limits hard and whose operator bans accounts for hammering
# it - and all three routes that reach VRChat are behind this, not just the obvious one. In
# memory rather than in the table on purpose: losing it on a restart costs nothing, and this is
# a politeness brake, not a security boundary.
_VRC_CHECK_COOLDOWN = 8.0
_vrc_last_check: dict[str, float] = {}
# Above this many remembered visitors the oldest half is dropped. Without it the dict grows by
# one entry per handed-out link and never shrinks - slow, but it never stops either.
_VRC_CHECK_MAX = 2000


def _vrc_throttled(token: str) -> bool:
    """True when this visitor asked for a VRChat lookup too recently. Records the attempt."""
    now = time.monotonic()
    last = _vrc_last_check.get(token, 0.0)
    if now - last < _VRC_CHECK_COOLDOWN:
        return True
    if len(_vrc_last_check) >= _VRC_CHECK_MAX:
        for stale, _ in sorted(_vrc_last_check.items(), key=lambda kv: kv[1])[:_VRC_CHECK_MAX // 2]:
            _vrc_last_check.pop(stale, None)
    _vrc_last_check[token] = now
    return False


def _vrc_harden(response, request: Request):
    """Headers every member-facing page carries.

    no-referrer so the address never travels to anywhere the member clicks on from here;
    no-store so a shared or borrowed browser does not hand the next person a cached copy of
    somebody's linking page; DENY so the page cannot be framed into a look-alike.
    """
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["X-Frame-Options"] = "DENY"
    return response

# VRChat display names are at most 32 characters; anything longer is not a name, it is a
# paste accident. The cog states the same limit for its own use - written out here rather
# than imported because every cog import in this file is deliberately done inside the
# function that needs it, and a constant read at module scope would undo that.
MAX_VRCHAT_NAME_WEB = 32

# How long a sent group invite counts as "already on its way". Long enough that somebody who
# wanders off and comes back does not trigger a second one, short enough that an invite which
# genuinely went missing can be asked for again within the hour.
VRC_INVITE_COOLDOWN = 30 * 60


async def _vrc_fresh_code() -> str:
    """An ownership code that no other open claim is currently using.

    Two people must never be handed the same code ("jeder bekommt einen anderen code dann zum
    eingeben der darf nicht der selbe sein"). Random already makes that vanishingly unlikely -
    six characters out of twenty-seven is roughly 387 million - but "unlikely" is not the same
    as "cannot", and the check costs one indexed lookup. Falls back to the last drawn code
    after a few tries rather than looping forever: at that point the database is the problem,
    and refusing the member their link would help nobody.
    """
    code = vrc_verify_code()
    for _ in range(5):
        try:
            clash = await db_one("SELECT id FROM vrc_links WHERE verify_code=?", (code,))
        except Exception as e:
            print(f"[vrc_link] could not check the code for collisions: {e}")
            return code
        if not clash:
            return code
        code = vrc_verify_code()
    return code


async def _vrc_token_row(token: str):
    """The token's row, or None when it is unknown, expired - or the server has switched the
    feature off in the meantime.

    Die Abschalt-Pruefung sitzt genau hier, weil jede der sechs oeffentlichen Routen ueber
    diese Funktion geht. Vorher stand sie nur dort, wo der Link AUSGEGEBEN wird: schaltete ein
    Admin VRC-Link ab, konnten alle, die kurz vorher einen Link bekommen hatten, munter
    weitermachen - Konto verknuepfen, Rolle und Spitzname kassieren, Gruppeneinladungen
    anfordern. Ein abgeschalteter Schalter muss sofort wirken, nicht erst wenn der letzte
    ausgegebene Link abgelaufen ist.
    """
    row = await db_one("SELECT * FROM vrc_link_tokens WHERE token=?", (token,))
    if not row:
        return None
    try:
        if datetime.datetime.fromisoformat(row["expires_at"]) < datetime.datetime.utcnow():
            return None
    except ValueError:
        return None
    if not str(row["guild_id"]).isdigit():
        return None
    if (await get_guild_config(int(row["guild_id"]), "vrc_enabled") or "0") != "1":
        return None
    return row


def _vrc_public_lang(request: Request, lang: str = "") -> str:
    """Which language the member's page speaks.

    An explicit ?lang= wins, otherwise the browser's own preference decides. There is no
    session here to remember a choice in - these pages have no login by design - so the page
    carries the parameter through its own links instead.
    """
    if lang in ("de", "en"):
        return lang
    accept = (request.headers.get("accept-language") or "").lower()
    # German is this project's default everywhere else, so only a browser that clearly asks
    # for English before German gets English.
    for part in accept.split(","):
        code = part.split(";")[0].strip()[:2]
        if code == "en":
            return "en"
        if code == "de":
            return "de"
    return "de"


async def _vrc_page(request: Request, row, lang: str,
                    error: str = "", success: str = "", status_code: int = 200):
    """Render the member's page from scratch, whatever just happened to them.

    `row` is the token row this visitor proved they hold, or None. Every route below ends here
    rather than redirecting, so an error keeps the member on the step they were on with their
    own words still on screen - a redirect would throw away the name they just typed and make
    them start over.
    """
    tr = get_tr(lang)
    if not row:
        # One page for all three ways of getting here - a link that was already opened once, an
        # hour that has passed, a browser that refuses cookies. The member cannot tell them
        # apart and does not need to: the answer is the same in every case, get a fresh link.
        return _vrc_harden(templates.TemplateResponse("vrc_link_public.html", {
            "request": request, "tr": tr, "lang": lang,
            "expired": True, "guild": None, "member": None, "link": None,
            "error": "", "success": "",
        }, status_code=410), request)

    guild = bot.get_guild(int(row["guild_id"])) if str(row["guild_id"]).isdigit() else None
    member = guild.get_member(int(row["user_id"])) if guild and str(row["user_id"]).isdigit() else None
    link = await db_one("SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
                        (row["guild_id"], row["user_id"]))
    cfg = await get_all_guild_config(int(row["guild_id"])) if str(row["guild_id"]).isdigit() else {}
    role = None
    if guild and str(cfg.get("vrc_linked_role") or "").isdigit():
        role = guild.get_role(int(cfg["vrc_linked_role"]))
    nick_preview = ""
    if link and member:
        nick_preview = vrc_nickname(cfg.get("vrc_nickname_format") or DEFAULT_VRC_NICKNAME_FORMAT,
                                    link["vrchat_name"], member.name)
    return _vrc_harden(templates.TemplateResponse("vrc_link_public.html", {
        "request": request, "tr": tr, "lang": lang, "expired": False,
        # Handed to the page so every form can carry it in its BODY. Never built into a link:
        # that would put it back into the address bar, the proxy log and the browser history,
        # which is the whole point of doing it this way.
        "token": row["token"],
        # So the page can show how long this door stays open, and close itself when the time
        # is up instead of letting somebody type into a form that will be refused.
        "expires_at": row["expires_at"],
        "guild": guild, "member": member, "link": link,
        "guild_name": guild.name if guild else f"#{row['guild_id']}",
        "guild_icon": guild.icon.url if guild and guild.icon else "",
        "member_name": member.display_name if member else "",
        "member_handle": member.name if member else "",
        "member_avatar": member.display_avatar.url if member else "",
        "role_name": role.name if role else "",
        # Gruppenzustand: nur zeigen, wenn der Server überhaupt eine Gruppe eingetragen hat.
        "group_on": bool((cfg.get("vrc_group_id") or "").strip()),
        "group_member": bool(link and link["vrc_group_member"]),
        "group_invited": bool(link and link["vrc_group_invited"]),
        "group_can_invite": cfg.get("vrc_group_invite") == "1",
        "nick_preview": nick_preview if cfg.get("vrc_nickname_enabled") == "1" else "",
        "needs_approval": cfg.get("vrc_auto_approve") != "1",
        "error": error, "success": success,
    }, status_code=status_code), request)


async def _vrc_visitor(token: str):
    """The token row this visitor supplied in their form, or None.

    Every POST below carries it in the body rather than the address - see the note above the
    route block for why, and for what that does and does not buy.
    """
    return await _vrc_token_row(token) if token else None


@web.get("/vrc/{token}", response_class=HTMLResponse)
async def vrc_public_open(request: Request, token: str, lang: str = ""):
    """The link handed out in Discord, and the only place the token is ever visible.

    Rendered directly rather than redirected: with no cookie there is nothing to carry the
    member across a redirect, so the page is served here and every form on it takes the token
    along in its body from then on. Reloading this address keeps working for the hour the link
    is valid, which is the whole reason it is not spent on first sight.
    """
    lang = _vrc_public_lang(request, lang)
    return await _vrc_page(request, await _vrc_token_row(token), lang)


@web.post("/vrc/lang", response_class=HTMLResponse)
async def vrc_public_lang_switch(request: Request, t: str = Form(""), lang: str = Form("")):
    """Switching language is a POST for one reason only: a link would put the token back into
    the address bar, which is exactly what this arrangement exists to avoid."""
    lang = _vrc_public_lang(request, lang)
    return await _vrc_page(request, await _vrc_visitor(t), lang)


@web.post("/vrc/name", response_class=HTMLResponse)
async def vrc_public_name(request: Request, lang: str = Form(""), t: str = Form(""),
                          vrchat_name: str = Form("")):
    """Step one: the member states a VRChat name, and it gets looked up for real."""
    lang = _vrc_public_lang(request, lang)
    tr = get_tr(lang)
    row = await _vrc_visitor(t)
    if not row:
        return await _vrc_page(request, None, lang)

    name = " ".join((vrchat_name or "").split())[:MAX_VRCHAT_NAME_WEB]
    if not name:
        return await _vrc_page(request, row, lang, error=tr["vrcp_err_empty"])
    # Behind the same brake as the other two: this route is the one that costs TWO VRChat
    # requests per press, so leaving it unthrottled while guarding the cheaper ones would have
    # been protecting the wrong door.
    if _vrc_throttled(t):
        return await _vrc_page(request, row, lang, error=tr["vrcp_err_toofast"])

    from cogs.vrc_link import resolve_vrchat, profile_fields
    state, user = await resolve_vrchat(name)
    if state == "not_found":
        return await _vrc_page(request, row, lang,
                               error=tr["vrcp_err_notfound"].replace("{name}", name))
    if state != "ok":
        return await _vrc_page(request, row, lang, error=tr["vrcp_err_unavailable"])

    fields = profile_fields(user)
    name = fields["vrchat_name"] or name

    # One VRChat account per server, the other half of "one VRChat profile per Discord
    # profile". Matched on the VRChat id as well as the name: somebody who renames themselves
    # on VRChat must not be able to claim their own account a second time under the new name.
    taken = await db_one(
        "SELECT user_id FROM vrc_links WHERE guild_id=? AND user_id!=? "
        "AND (LOWER(vrchat_name)=LOWER(?) OR (vrc_user_id!='' AND vrc_user_id=?))",
        (row["guild_id"], row["user_id"], name, fields["vrc_user_id"]),
    )
    if taken:
        return await _vrc_page(request, row, lang,
                               error=tr["vrcp_err_taken"].replace("{name}", name))

    existing = await db_one("SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
                            (row["guild_id"], row["user_id"]))

    # Whether the member has to prove the account is theirs with a code in their VRChat status.
    # A switch rather than a law, and on by default: without it "linking" means nothing more
    # than that somebody typed a name, and a member could wear the nickname and role of
    # anybody they can spell. A server that only wants the plain job - read the VRChat name
    # and the 18+ badge, carry the name over to Discord - can turn it off and have exactly
    # that, and the moderator approval below is then what stands between a claim and a role.
    require_proof = (await get_guild_config(int(row["guild_id"]), "vrc_require_ownership")
                     or "1") != "0"
    auto = (await get_guild_config(int(row["guild_id"]), "vrc_auto_approve") or "0") == "1"
    if require_proof:
        new_status = VRC_STATE_UNVERIFIED
        # An unfinished claim for the SAME account keeps the code it was given. The member has
        # likely already pasted it into VRChat by the time they land back here, and handing out
        # a fresh one would silently invalidate what they just did.
        if existing and existing["status"] == VRC_STATE_UNVERIFIED \
                and existing["vrc_user_id"] == fields["vrc_user_id"] and existing["verify_code"]:
            code = existing["verify_code"]
        else:
            code = await _vrc_fresh_code()
        decided_at = decided_by = ""
    else:
        new_status = VRC_STATE_APPROVED if auto else VRC_STATE_PENDING
        code = ""
        decided_at = datetime.datetime.utcnow().isoformat() if auto else ""
        decided_by = "Ohne Eigentumsnachweis" if auto else ""

    now = datetime.datetime.utcnow().isoformat()
    try:
        if existing:
            # Ist es ein ANDERES VRChat-Konto als bisher, gilt nichts mehr von dem, was ueber
            # das alte bekannt war. Der gemerkte Rollenstand gehoerte dem alten Konto: bliebe
            # er stehen, haelt sync_vrc_roles() "Soll == Ist" fuer erfuellt und gibt dem neuen
            # Konto nie eine Rolle. Ebenso der Einladungs-Merker - sonst wartet jemand auf
            # eine Einladung, die an ein fremdes Konto ging.
            wechsel = (existing["vrc_user_id"] or "") != fields["vrc_user_id"]
            await db_exec(
                "UPDATE vrc_links SET vrchat_name=?, vrc_user_id=?, vrc_trust=?, "
                "vrc_age_verified=?, vrc_supporter=?, vrc_avatar=?, status=?, verify_code=?, "
                "verified_at='', requested_at=?, decided_at=?, decided_by=?"
                + (", vrc_group_member=0, vrc_group_roles='[]', vrc_roles_synced='', "
                   "vrc_group_invited='', vrc_group_checked=''" if wechsel else "")
                + " WHERE id=?",
                (name, fields["vrc_user_id"], fields["vrc_trust"], fields["vrc_age_verified"],
                 fields["vrc_supporter"], fields["vrc_avatar"], new_status, code,
                 now, decided_at, decided_by, existing["id"]),
            )
            if existing["status"] == VRC_STATE_APPROVED:
                # They had a confirmed link and are now claiming a different account. Whatever
                # the old one earned them has to go before the new one is even a candidate.
                await _vrc_apply(int(row["guild_id"]), row["user_id"],
                                 existing["vrchat_name"], revoke=True)
        else:
            await db_exec(
                "INSERT INTO vrc_links (guild_id, user_id, vrchat_name, vrc_user_id, vrc_trust, "
                "vrc_age_verified, vrc_supporter, vrc_avatar, status, verify_code, requested_at, "
                "decided_at, decided_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["guild_id"], row["user_id"], name, fields["vrc_user_id"],
                 fields["vrc_trust"], fields["vrc_age_verified"], fields["vrc_supporter"],
                 fields["vrc_avatar"], new_status, code, now, decided_at, decided_by),
            )
    except Exception as e:
        # Both unique indexes on this table can still reject the write even though the checks
        # above passed: two people can claim the same name in the same instant, and the
        # database is the only place that can settle that.
        print(f"[vrc_link] storing claim for {row['user_id']} in {row['guild_id']} failed: {e}")
        return await _vrc_page(request, row, lang,
                               error=tr["vrcp_err_taken"].replace("{name}", name))
    # Whether they are already in the VRChat group is part of knowing WHO this is, so it is
    # settled the moment the link exists - not only later, on the confirmation step. With the
    # ownership proof switched off there IS no confirmation step, and the group would
    # otherwise stay unknown until somebody happened to press "refresh".
    stored = await db_one("SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
                          (row["guild_id"], row["user_id"]))
    await _vrc_sync_group(int(row["guild_id"]), stored)

    if new_status == VRC_STATE_APPROVED:
        # Nothing left to confirm - the role and the nickname are due right now.
        await _vrc_apply(int(row["guild_id"]), row["user_id"], name)
        return await _vrc_page(request, row, lang, success=tr["vrcp_ok_verified"])
    if new_status == VRC_STATE_PENDING:
        return await _vrc_page(request, row, lang, success=tr["vrcp_ok_pending"])
    return await _vrc_page(request, row, lang)


@web.post("/vrc/verify", response_class=HTMLResponse)
async def vrc_public_verify(request: Request, lang: str = Form(""), t: str = Form("")):
    """Step two: read the VRChat profile back and look for the code the member was given."""
    lang = _vrc_public_lang(request, lang)
    tr = get_tr(lang)
    row = await _vrc_visitor(t)
    if not row:
        return await _vrc_page(request, None, lang)
    link = await db_one("SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
                        (row["guild_id"], row["user_id"]))
    if not link or link["status"] != VRC_STATE_UNVERIFIED:
        return await _vrc_page(request, row, lang)
    if _vrc_throttled(t):
        return await _vrc_page(request, row, lang, error=tr["vrcp_err_toofast"])

    from cogs.vrc_link import fetch_profile, code_present, profile_fields, profile_text
    state, user = await fetch_profile(link["vrc_user_id"])
    if state == "not_found":
        return await _vrc_page(request, row, lang, error=tr["vrcp_err_gone"])
    if state != "ok":
        return await _vrc_page(request, row, lang, error=tr["vrcp_err_unavailable"])
    if not code_present(user, link["verify_code"]):
        # "It is not there" without saying what WAS there is the kind of answer that costs an
        # evening - reported as exactly that ("der sagt immer nur dass der code nicht drin
        # ist", with a screenshot showing the code plainly in the profile). So the member is
        # shown what the bot actually read back, which separates the two causes that look
        # identical from the outside: the text has not reached VRChat's API yet, or the bot
        # cannot see that field at all.
        seen = profile_text(user).strip()
        if seen:
            extra = tr["vrcp_err_nocode_saw"].replace("{seen}", seen[:300])
        else:
            extra = tr["vrcp_err_nocode_empty"]
        print(f"[vrc_link] code {link['verify_code']} not found for {link['vrc_user_id']} - "
              f"profile text was {seen[:300]!r}")
        return await _vrc_page(request, row, lang,
                               error=tr["vrcp_err_nocode"] + " " + extra)

    fields = profile_fields(user)
    approved = (await get_guild_config(int(row["guild_id"]), "vrc_auto_approve") or "0") == "1"
    new_status = VRC_STATE_APPROVED if approved else VRC_STATE_PENDING
    now = datetime.datetime.utcnow().isoformat()
    await db_exec(
        "UPDATE vrc_links SET vrchat_name=?, vrc_trust=?, vrc_age_verified=?, vrc_supporter=?, "
        "vrc_avatar=?, status=?, verified_at=?, verify_code='', decided_at=?, decided_by=? "
        "WHERE id=?",
        (fields["vrchat_name"] or link["vrchat_name"], fields["vrc_trust"],
         fields["vrc_age_verified"], fields["vrc_supporter"], fields["vrc_avatar"],
         new_status, now, now if approved else "", "VRChat-Bestätigung" if approved else "",
         link["id"]),
    )
    # One more VRChat request while the member is already waiting - the only moment it is
    # honest to spend one, and it saves them a second round trip to see their group state.
    await _vrc_sync_group(int(row["guild_id"]), link)
    if approved:
        await _vrc_apply(int(row["guild_id"]), row["user_id"],
                         fields["vrchat_name"] or link["vrchat_name"])
    return await _vrc_page(request, row, lang,
                           success=tr["vrcp_ok_verified"] if approved else tr["vrcp_ok_pending"])


@web.post("/vrc/refresh", response_class=HTMLResponse)
async def vrc_public_refresh(request: Request, lang: str = Form(""), t: str = Form("")):
    """Re-read the VRChat profile of a confirmed link - picks up a rename and the badges."""
    lang = _vrc_public_lang(request, lang)
    tr = get_tr(lang)
    row = await _vrc_visitor(t)
    if not row:
        return await _vrc_page(request, None, lang)
    link = await db_one("SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
                        (row["guild_id"], row["user_id"]))
    if not link or not link["vrc_user_id"]:
        return await _vrc_page(request, row, lang)
    if _vrc_throttled(t):
        return await _vrc_page(request, row, lang, error=tr["vrcp_err_toofast"])

    from cogs.vrc_link import fetch_profile, profile_fields
    state, user = await fetch_profile(link["vrc_user_id"])
    if state == "not_found":
        return await _vrc_page(request, row, lang, error=tr["vrcp_err_gone"])
    if state != "ok":
        return await _vrc_page(request, row, lang, error=tr["vrcp_err_unavailable"])
    fields = profile_fields(user)
    name = fields["vrchat_name"] or link["vrchat_name"]
    try:
        await db_exec(
            "UPDATE vrc_links SET vrchat_name=?, vrc_trust=?, vrc_age_verified=?, "
            "vrc_supporter=?, vrc_avatar=? WHERE id=?",
            (name, fields["vrc_trust"], fields["vrc_age_verified"], fields["vrc_supporter"],
             fields["vrc_avatar"], link["id"]),
        )
    except Exception as e:
        # The new name can collide with somebody else's link on this server - the unique index
        # is what stops two members wearing the same linked nickname, and it has to win here
        # too. Everything else about the link stays as it was.
        print(f"[vrc_link] refresh of link {link['id']} failed: {e}")
        return await _vrc_page(request, row, lang,
                               error=tr["vrcp_err_taken"].replace("{name}", name))
    await _vrc_sync_group(int(row["guild_id"]), link)
    if link["status"] == VRC_STATE_APPROVED:
        await _vrc_apply(int(row["guild_id"]), row["user_id"], name)
    return await _vrc_page(request, row, lang, success=tr["vrcp_ok_refreshed"])


async def _vrc_sync_group(guild_id: int, link) -> None:
    """Re-read whether this member is in the server's VRChat group and write it down.

    Called only where a person is already waiting on a VRChat request anyway - confirming a
    link, refreshing their own page - never on a timer. An unreachable group leaves the stored
    flag exactly as it was: reading an outage as "not a member" would strip the group role off
    everybody the first time VRChat hiccups.
    """
    group_id = (await get_guild_config(guild_id, "vrc_group_id") or "").strip()
    if not group_id or not link or not link["vrc_user_id"]:
        return
    from cogs.vrc_link import group_membership
    state, is_member = await group_membership(group_id, link["vrc_user_id"])
    if state != "ok":
        return
    try:
        # Wer nicht (mehr) in der Gruppe ist, hat dort auch keine Rollen mehr - VRChat nimmt
        # sie mit der Mitgliedschaft weg. Der gemerkte Stand muss deshalb mitgeleert werden,
        # sonst haelt sync_vrc_roles() beim Wiedereintritt "Soll == Ist" fuer erfuellt und
        # vergibt nie wieder etwas. Genau der Fall: austreten, wieder beitreten, Rollen weg.
        await db_exec(
            "UPDATE vrc_links SET vrc_group_member=?, vrc_group_checked=?"
            + ("" if is_member else ", vrc_group_roles='[]'")
            + " WHERE id=?",
            (1 if is_member else 0, datetime.datetime.utcnow().isoformat(), link["id"]),
        )
    except Exception as e:
        print(f"[vrc_link] could not store group membership for link {link['id']}: {e}")


@web.post("/vrc/invite", response_class=HTMLResponse)
async def vrc_public_invite(request: Request, lang: str = Form(""), t: str = Form("")):
    """Ask the bot to send this member a group invite.

    Only offered once the link is confirmed: an invite is a real action on VRChat's side, and
    handing one out on nothing but a typed name would let anybody pull a stranger's account
    into the group.
    """
    lang = _vrc_public_lang(request, lang)
    tr = get_tr(lang)
    row = await _vrc_visitor(t)
    if not row:
        return await _vrc_page(request, None, lang)
    link = await db_one("SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
                        (row["guild_id"], row["user_id"]))
    if not link or link["status"] != VRC_STATE_APPROVED or not link["vrc_user_id"]:
        return await _vrc_page(request, row, lang, error=tr["vrcp_invite_not_yet"])
    guild_id = int(row["guild_id"])
    group_id = (await get_guild_config(guild_id, "vrc_group_id") or "").strip()
    if not group_id or (await get_guild_config(guild_id, "vrc_group_invite") or "0") != "1":
        return await _vrc_page(request, row, lang, error=tr["vrcp_invite_off"])
    if link["vrc_group_member"]:
        return await _vrc_page(request, row, lang, success=tr["vrcp_group_yes"])
    # An invite already on its way is not a reason to send another one. The eight-second brake
    # below only stops an impatient double-click; somebody coming back ten minutes later would
    # otherwise fire a second, third and fourth invite at VRChat for the same person - and
    # repeated writes are exactly the pattern that gets a bot account flagged.
    if link["vrc_group_invited"]:
        try:
            sent_at = datetime.datetime.fromisoformat(link["vrc_group_invited"])
            fresh = (datetime.datetime.utcnow() - sent_at).total_seconds() < VRC_INVITE_COOLDOWN
        except ValueError:
            fresh = False
        if fresh:
            return await _vrc_page(request, row, lang, success=tr["vrcp_group_invited"])
    if _vrc_throttled(t):
        return await _vrc_page(request, row, lang, error=tr["vrcp_err_toofast"])

    from cogs.vrc_link import send_group_invite
    state, detail = await send_group_invite(group_id, link["vrc_user_id"])
    if state == "error":
        # Passed through rather than flattened into "it failed": the two things that actually
        # go wrong here - the bot account lacking the group's invite permission, and VRChat
        # rate-limiting - need different responses from whoever reads it.
        return await _vrc_page(request, row, lang,
                               error=tr["vrcp_invite_failed"] + " " + detail)
    try:
        await db_exec("UPDATE vrc_links SET vrc_group_invited=? WHERE id=?",
                      (datetime.datetime.utcnow().isoformat(), link["id"]))
    except Exception as e:
        print(f"[vrc_link] could not note the group invite for link {link['id']}: {e}")
    if state == "already":
        # VRChat meldet "bereits eingeladen" und "ist schon Mitglied" beide als dasselbe
        # "already" - welches von beiden, sagt nur ein Blick in die Mitgliederliste. Ohne den
        # blieb der Merker auf "kein Mitglied" stehen: die Gruppenrolle auf Discord kam nie,
        # obwohl der Betreffende laengst drin war. Kostet eine Anfrage, und nur in diesem
        # seltenen Zweig.
        await _vrc_sync_group(guild_id, link)
    return await _vrc_page(request, row, lang,
                           success=tr["vrcp_invite_sent"] if state == "sent"
                           else tr["vrcp_invite_already"])


@web.post("/vrc/unlink", response_class=HTMLResponse)
async def vrc_public_unlink(request: Request, lang: str = Form(""), t: str = Form("")):
    lang = _vrc_public_lang(request, lang)
    tr = get_tr(lang)
    row = await _vrc_visitor(t)
    if not row:
        return await _vrc_page(request, None, lang)
    link = await db_one("SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
                        (row["guild_id"], row["user_id"]))
    if not link:
        return await _vrc_page(request, row, lang)
    # Erst zuruecknehmen, DANN loeschen - nicht umgekehrt. revoke_link() schlaegt die Zeile
    # noch einmal nach, um die auf VRChat-Seite vergebenen Gruppenrollen abzunehmen; war sie
    # da schon geloescht, fand es nichts mehr und die Rollen blieben dem Mitglied erhalten.
    # Wer sich loesen liess, behielt also genau die Rechte, um die es ging.
    if link["status"] == VRC_STATE_APPROVED:
        await _vrc_apply(int(row["guild_id"]), row["user_id"], link["vrchat_name"], revoke=True)
    await db_exec("DELETE FROM vrc_links WHERE id=?", (link["id"],))
    return await _vrc_page(request, row, lang, success=tr["vrcp_ok_unlinked"])


# ── Kooperationen zwischen zwei Phobos-Installationen ─────────────────────────
# Zwei Communities arbeiten zusammen, jede betreibt ihren eigenen Bot. Wer drueben schon
# geprueft wurde, soll hier nicht noch einmal durch dieselbe Pruefung. Genau dafuer ist das
# hier - und fuer nichts sonst: uebertragen wird eine einzige Antwort, ja oder nein, zu einer
# einzigen Discord-ID. Keine Mitgliederlisten, keine Namen, keine Rollen.

# Wie oft ein Partner fragen darf, bevor gebremst wird. Ohne Bremse waere die Schnittstelle
# ein Werkzeug, um reihenweise Discord-IDs durchzuprobieren - "ist dieser Mensch bei euch?"
# ist fuer sich genommen schon eine Auskunft.
_COOP_MAX_PER_MINUTE = 60
_coop_anfragen: dict = {}


def _coop_gebremst(schluessel_hash: str) -> bool:
    """True, wenn dieser Partner sein Minutenkontingent ausgeschoepft hat."""
    jetzt = time.monotonic()
    fenster = _coop_anfragen.setdefault(schluessel_hash, [])
    while fenster and jetzt - fenster[0] > 60:
        fenster.pop(0)
    if len(fenster) >= _COOP_MAX_PER_MINUTE:
        return True
    fenster.append(jetzt)
    if len(_coop_anfragen) > 500:
        for k in [k for k, v in _coop_anfragen.items() if not v or jetzt - v[-1] > 300]:
            _coop_anfragen.pop(k, None)
    return False


@web.post("/coop/check")
async def coop_check(request: Request):
    """Beantwortet einem Partner, ob eine Discord-ID hier als geprueft gilt.

    Die einzige Route dieses Bereichs ohne Anmeldung - sie gehoert keinem Menschen, sondern
    der anderen Installation. Ausgewiesen wird sie durch den Kooperations-Schluessel, den
    diese Seite selbst erzeugt hat und jederzeit zuruecknehmen kann.

    Die Antwort ist absichtlich duenn: {"verified": true|false}. Kein Name, keine Rollen,
    kein Hinweis darauf, ob die Person hier ueberhaupt Mitglied ist - ein Nein bedeutet
    "nicht geprueft" und sonst nichts. Wer den Schluessel hat, soll Verifizierungen
    anerkennen koennen, nicht die Mitgliederliste abtasten.
    """
    form = await request.form()
    schluessel = (form.get("key") or "").strip()
    user_id = (form.get("user_id") or "").strip()
    if not schluessel or not user_id.isdigit():
        return JSONResponse({"verified": False}, status_code=400)

    digest = _token_hash(schluessel)
    if _coop_gebremst(digest):
        return JSONResponse({"verified": False, "error": "too many requests"}, status_code=429)

    row = await db_one(
        "SELECT * FROM coop_partners WHERE key_in_hash=? AND enabled=1", (digest,))
    if not row:
        # Derselbe Wortlaut wie bei einer abgelehnten Person: ein falscher Schluessel darf
        # sich nicht von "kenne ich nicht" unterscheiden lassen.
        return JSONResponse({"verified": False}, status_code=403)

    geteilt = {r for r in (row["share_role_ids"] or "").split(",") if r.strip()}
    if not geteilt:
        return JSONResponse({"verified": False})

    b = bot._bot_for_guild(int(row["guild_id"])) if str(row["guild_id"]).isdigit() else None
    guild = b.get_guild(int(row["guild_id"])) if b else None
    member = guild.get_member(int(user_id)) if guild else None
    verifiziert = bool(member and {str(r.id) for r in member.roles} & geteilt)

    try:
        await db_exec("UPDATE coop_partners SET last_in=? WHERE id=?",
                      (datetime.datetime.utcnow().isoformat(), row["id"]))
    except Exception as e:
        print(f"[coop] konnte den Zeitstempel nicht setzen: {e}")
    return JSONResponse({"verified": verifiziert})


async def coop_frage_partner(row, user_id) -> bool:
    """Fragt EINEN Partner, ob diese Discord-ID bei ihm geprueft ist.

    Gibt nur bei einem klaren Ja True zurueck. Jeder andere Ausgang - Netz weg, Schluessel
    zurueckgezogen, Partner gerade neu gestartet - ist ein Nein: eine Rolle zu vergeben, weil
    eine Anfrage unklar ausging, waere genau das Gegenteil dessen, wofuer die Pruefung da ist.
    """
    ziel = (row["base_url"] or "").strip().rstrip("/")
    schluessel = (row["key_out"] or "").strip()
    if not ziel or not schluessel:
        return False
    if not _is_public_http_url(ziel):
        # Dieselbe Schranke wie beim Umfrage-Vorschaubild: der Server steht im Netz und
        # erreicht Dinge, die die fragende Person nie erreichen wuerde.
        print(f"[coop] Adresse {ziel[:60]} ist keine oeffentliche - Anfrage unterbleibt")
        return False
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as sitzung:
            async with sitzung.post(f"{ziel}/coop/check",
                                    data={"key": schluessel, "user_id": str(user_id)}) as antwort:
                if antwort.status != 200:
                    return False
                daten = await antwort.json(content_type=None)
    except Exception as e:
        print(f"[coop] Anfrage an {ziel[:60]} fehlgeschlagen: {e}")
        return False
    return bool(isinstance(daten, dict) and daten.get("verified") is True)


def _coop_rollen(form, feld: str, guild) -> str:
    """Die angekreuzten Rollen als Liste, gegen die echten Rollen des Servers geprueft."""
    echte = {str(r.id) for r in guild.roles if not r.is_default()} if guild else set()
    return ",".join(r for r in form.getlist(feld) if r in echte)


@web.post("/servers/{guild_id}/coop/add")
async def coop_add(request: Request, guild_id: int):
    """Legt eine Kooperation an und erzeugt den Schluessel, mit dem der Partner hier fragen darf.

    Der Schluessel wird EINMAL angezeigt und nur gehasht gespeichert - wie ein Passwort. Er
    wandert dafuer durch die Sitzung und nicht durch die Adresszeile: dort stuende er im
    Verlauf, im Proxy-Log und in jedem Referer.
    """
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    b = bot._bot_for_guild(guild_id)
    guild = b.get_guild(guild_id) if b else None
    form = await request.form()
    name = " ".join((form.get("name") or "").split())[:80] or "Partner"
    base_url = (form.get("base_url") or "").strip().rstrip("/")[:300]
    key_out = (form.get("key_out") or "").strip()[:200]
    if base_url and not base_url.startswith(("http://", "https://")):
        return RedirectResponse(
            f"/servers/{guild_id}?tab=rolerules&error=Die+Partner-Adresse+muss+mit+http+beginnen",
            status_code=302)
    schluessel = secrets.token_urlsafe(32)
    try:
        await db_exec(
            "INSERT INTO coop_partners (guild_id, name, share_role_ids, key_in_hash, base_url, "
            "key_out, grant_role_ids, enabled, created_at, note) VALUES (?,?,?,?,?,?,?,1,?,?)",
            (str(guild_id), name, _coop_rollen(form, "share_role_ids", guild),
             _token_hash(schluessel), base_url, key_out,
             _coop_rollen(form, "grant_role_ids", guild),
             datetime.datetime.utcnow().isoformat(), (form.get("note") or "").strip()[:300]),
        )
    except Exception as e:
        print(f"[coop] anlegen fehlgeschlagen: {e}")
        return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&error=Konnte+nicht+angelegt+werden",
                                status_code=302)
    request.session["coop_new_key"] = schluessel
    request.session["coop_new_name"] = name
    return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&success=Kooperation+angelegt",
                            status_code=302)


@web.post("/servers/{guild_id}/coop/{coop_id}/save")
async def coop_save(request: Request, guild_id: int, coop_id: int):
    """Aendert eine bestehende Kooperation - ohne den Schluessel anzufassen."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    b = bot._bot_for_guild(guild_id)
    guild = b.get_guild(guild_id) if b else None
    form = await request.form()
    base_url = (form.get("base_url") or "").strip().rstrip("/")[:300]
    if base_url and not base_url.startswith(("http://", "https://")):
        return RedirectResponse(
            f"/servers/{guild_id}?tab=rolerules&error=Die+Partner-Adresse+muss+mit+http+beginnen",
            status_code=302)
    # guild_id in der Bedingung, nicht nur die id: sonst liesse sich die Kooperation eines
    # fremden Servers durch Raten der Nummer aendern.
    await db_exec(
        "UPDATE coop_partners SET name=?, share_role_ids=?, base_url=?, key_out=?, "
        "grant_role_ids=?, enabled=?, note=? WHERE id=? AND guild_id=?",
        (" ".join((form.get("name") or "").split())[:80] or "Partner",
         _coop_rollen(form, "share_role_ids", guild), base_url,
         (form.get("key_out") or "").strip()[:200],
         _coop_rollen(form, "grant_role_ids", guild),
         1 if form.get("enabled") else 0, (form.get("note") or "").strip()[:300],
         coop_id, str(guild_id)),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&success=Gespeichert", status_code=302)


@web.post("/servers/{guild_id}/coop/{coop_id}/newkey")
async def coop_newkey(request: Request, guild_id: int, coop_id: int):
    """Zieht den alten Schluessel zurueck und gibt einen neuen aus.

    Der alte ist damit sofort wertlos - genau das, was man braucht, wenn eine Kooperation
    endet oder der Schluessel in falsche Haende geraten ist.
    """
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    row = await db_one("SELECT name FROM coop_partners WHERE id=? AND guild_id=?",
                       (coop_id, str(guild_id)))
    if not row:
        return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&error=Nicht+gefunden",
                                status_code=302)
    schluessel = secrets.token_urlsafe(32)
    await db_exec("UPDATE coop_partners SET key_in_hash=? WHERE id=? AND guild_id=?",
                  (_token_hash(schluessel), coop_id, str(guild_id)))
    request.session["coop_new_key"] = schluessel
    request.session["coop_new_name"] = row["name"]
    return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&success=Neuer+Schlüssel+erzeugt",
                            status_code=302)


@web.post("/servers/{guild_id}/coop/{coop_id}/delete")
async def coop_delete(request: Request, guild_id: int, coop_id: int):
    """Beendet eine Kooperation. Vergebene Rollen bleiben - die gehoeren den Mitgliedern."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM coop_partners WHERE id=? AND guild_id=?", (coop_id, str(guild_id)))
    return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&success=Kooperation+beendet",
                            status_code=302)


@web.post("/servers/{guild_id}/coop/{coop_id}/test")
async def coop_test(request: Request, guild_id: int, coop_id: int, user_id: str = Form("")):
    """Fragt den Partner testweise nach einer Discord-ID und zeigt, was zurueckkommt.

    Gebaut, weil sich sonst nur an einem echten Beitritt zeigt, ob Adresse und Schluessel
    stimmen - und dann zur falschen Zeit.
    """
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return JSONResponse({"error": "Kein Zugriff"}, status_code=403)
    row = await db_one("SELECT * FROM coop_partners WHERE id=? AND guild_id=?",
                       (coop_id, str(guild_id)))
    if not row:
        return JSONResponse({"error": "Nicht gefunden"}, status_code=404)
    if not (row["base_url"] or "").strip():
        return JSONResponse({"error": "Für diese Kooperation ist keine Partner-Adresse eingetragen."})
    ziel = (user_id or "").strip() or str(request.session.get("user_id") or "")
    if not ziel.isdigit():
        return JSONResponse({"error": "Bitte eine Discord-ID angeben."})
    verifiziert = await coop_frage_partner(row, ziel)
    return JSONResponse({"verified": bool(verifiziert), "user_id": ziel})


# ── Auto-Thread ───────────────────────────────────────────────────────────────
# One thread per message in the configured channels - see cogs/auto_thread.py.

# Mirrors ALLOWED_ARCHIVE_MINUTES in cogs/auto_thread.py. Duplicated as a literal rather than
# imported because main.py never imports from a cog at module level (the cogs are loaded as
# extensions, and one of them importing main.py back would be circular) - the cog re-validates
# the stored value anyway, so the two can't silently drift into accepting different things.
_AUTO_THREAD_ARCHIVE_MINUTES = (60, 1440, 4320, 10080)


async def _reload_auto_thread():
    for b in bot._bots.values():
        cog = b.cogs.get("AutoThread")
        if cog:
            await cog.reload()


def _auto_thread_form(guild, channel_id: str, name_template: str, archive_minutes: str,
                      starter_message: str) -> tuple[tuple | None, str | None]:
    """Shared validation for auto-thread/save and .../edit - returns (values, None) or
    (None, error), same convention as _role_rule_form_data."""
    if not guild or channel_id not in {str(c.id) for c in guild.text_channels}:
        return None, "Ungültiger+Kanal"
    try:
        archive = int(archive_minutes)
    except (ValueError, TypeError):
        return None, "Ungültige+Archivierungsdauer"
    if archive not in _AUTO_THREAD_ARCHIVE_MINUTES:
        return None, "Ungültige+Archivierungsdauer"
    template = (name_template or "").strip()[:100] or "{user}"
    return (template, archive, (starter_message or "").strip()[:1500]), None


@web.post("/servers/{guild_id}/auto-thread/save")
async def auto_thread_save(
    request: Request, guild_id: str, channel_id: str = Form(""),
    name_template: str = Form(""), archive_minutes: str = Form("1440"),
    skip_bots: str = Form(""), require_attachment: str = Form(""),
    starter_message: str = Form(""),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(int(guild_id))
    values, error = _auto_thread_form(guild, channel_id, name_template, archive_minutes, starter_message)
    if error:
        return RedirectResponse(f"/servers/{guild_id}?tab=autothread&error={error}", status_code=302)
    template, archive, starter = values
    await db_exec(
        "INSERT INTO auto_thread_channels (guild_id, channel_id, name_template, archive_minutes, "
        "skip_bots, require_attachment, starter_message) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(guild_id, channel_id) DO UPDATE SET name_template=excluded.name_template, "
        "archive_minutes=excluded.archive_minutes, skip_bots=excluded.skip_bots, "
        "require_attachment=excluded.require_attachment, starter_message=excluded.starter_message",
        (guild_id, channel_id, template, archive, 1 if skip_bots else 0,
         1 if require_attachment else 0, starter),
    )
    await _reload_auto_thread()
    return RedirectResponse(f"/servers/{guild_id}?tab=autothread&success=Gespeichert", status_code=303)


@web.post("/servers/{guild_id}/auto-thread/edit/{entry_id}")
async def auto_thread_edit(
    request: Request, guild_id: str, entry_id: int, channel_id: str = Form(""),
    name_template: str = Form(""), archive_minutes: str = Form("1440"),
    skip_bots: str = Form(""), require_attachment: str = Form(""),
    starter_message: str = Form(""),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(int(guild_id))
    values, error = _auto_thread_form(guild, channel_id, name_template, archive_minutes, starter_message)
    if error:
        return RedirectResponse(f"/servers/{guild_id}?tab=autothread&error={error}", status_code=302)
    template, archive, starter = values
    # Moving an entry onto a channel that already has one would hit the UNIQUE constraint -
    # reported as its own message instead of a generic failure, same as auto_delete_edit.
    try:
        await db_exec(
            "UPDATE auto_thread_channels SET channel_id=?, name_template=?, archive_minutes=?, "
            "skip_bots=?, require_attachment=?, starter_message=? WHERE id=? AND guild_id=?",
            (channel_id, template, archive, 1 if skip_bots else 0,
             1 if require_attachment else 0, starter, entry_id, guild_id),
        )
    except Exception:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=autothread&error=Für+diesen+Kanal+existiert+schon+ein+Eintrag",
            status_code=302,
        )
    await _reload_auto_thread()
    return RedirectResponse(f"/servers/{guild_id}?tab=autothread&success=Gespeichert", status_code=303)


@web.post("/servers/{guild_id}/auto-thread/delete/{entry_id}")
async def auto_thread_remove(request: Request, guild_id: str, entry_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id): return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM auto_thread_channels WHERE id=? AND guild_id=?", (entry_id, guild_id))
    await _reload_auto_thread()
    return RedirectResponse(f"/servers/{guild_id}?tab=autothread&success=Gelöscht", status_code=303)


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
    except (discord.HTTPException, OSError) as e:
        # Same three-part fix already established for Embed-Nachrichten's identical pattern:
        # OSError caught alongside HTTPException (discord.py 2.3.2's http.py re-raises a real
        # network failure unwrapped on Linux, this project's actual runtime), _discord_error_text()
        # used instead of a bare e.text (OSError has no .text attribute, which would otherwise
        # itself raise AttributeError for that case), and urllib.parse.quote() so a &/%/+ in the
        # message (e.g. Discord quoting back a rejected URL with a query string) can't get cut
        # off or garbled by the redirect query string parser.
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Discord-Fehler:+{urllib.parse.quote(_discord_error_text(e))}", status_code=302)

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
    except (discord.HTTPException, OSError) as e:
        # Same three-part fix already established for Embed-Nachrichten's identical pattern:
        # OSError caught alongside HTTPException (discord.py 2.3.2's http.py re-raises a real
        # network failure unwrapped on Linux, this project's actual runtime), _discord_error_text()
        # used instead of a bare e.text (OSError has no .text attribute, which would otherwise
        # itself raise AttributeError for that case), and urllib.parse.quote() so a &/%/+ in the
        # message (e.g. Discord quoting back a rejected URL with a query string) can't get cut
        # off or garbled by the redirect query string parser.
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Discord-Fehler:+{urllib.parse.quote(_discord_error_text(e))}", status_code=302)

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
    except (discord.HTTPException, OSError) as e:
        # Same three-part fix already established for Embed-Nachrichten's identical pattern:
        # OSError caught alongside HTTPException (discord.py 2.3.2's http.py re-raises a real
        # network failure unwrapped on Linux, this project's actual runtime), _discord_error_text()
        # used instead of a bare e.text (OSError has no .text attribute, which would otherwise
        # itself raise AttributeError for that case), and urllib.parse.quote() so a &/%/+ in the
        # message (e.g. Discord quoting back a rejected URL with a query string) can't get cut
        # off or garbled by the redirect query string parser.
        return RedirectResponse(f"/servers/{guild_id}?tab=events&error=Discord-Fehler:+{urllib.parse.quote(_discord_error_text(e))}", status_code=302)
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


@web.post("/servers/{guild_id}/events/series/pause/{series_id}")
async def events_series_pause(request: Request, guild_id: int, series_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    # Flips paused 0<->1 - cogs/scheduler.py's _check_recurring skips paused series entirely
    # (no new occurrence gets created), but next_start_at itself is left untouched: resuming an
    # already-overdue series creates its next occurrence on the very next 5-minute tick instead
    # of silently skipping whatever was missed while paused, same catch-up behavior already
    # used elsewhere in this project (giveaways/polls resuming after the bot was offline).
    await db_exec(
        "UPDATE event_series SET paused = 1 - paused WHERE id=? AND guild_id=?",
        (series_id, str(guild_id)),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=events&success=Aktualisiert", status_code=302)


# ── Temp Voice ────────────────────────────────────────────────────────────────

def _tempvoice_panel_fields(form) -> tuple:
    """The panel fields, shared by tempvoice/add and .../edit so the two can't drift."""
    # One JSON object rather than six columns - see database.py's migration note. A caption
    # left exactly as the default is not stored at all, so a later change to the German
    # wording still reaches every server that never touched its own.
    labels = {}
    for key, default in DEFAULT_TEMPVOICE_LABELS.items():
        value = (form.get(f"label_{key}") or "").strip()[:80]
        if value and value != default:
            labels[key] = value
    return (
        1 if form.get("panel_enabled") else 0,
        (form.get("panel_title") or "").strip()[:256],   # Discord's embed title limit
        (form.get("panel_text") or "").strip()[:4000],   # Discord's embed description limit
        _djson.dumps(labels) if labels else "",
    )


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
    # INSERT OR REPLACE used to quietly overwrite an existing trigger: entering a channel that
    # already had a configuration threw away its settings - a hand-written panel text included -
    # and still answered "Gespeichert". The edit route has always refused the same collision
    # with a clear message; this one now does too, and points at the entry that already exists.
    existing = await db_one(
        "SELECT id FROM temp_voice_config WHERE guild_id=? AND trigger_channel_id=?",
        (guild_id, trigger),
    )
    if existing:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=tempvoice&error=Für+diesen+Kanal+existiert+schon+ein+Trigger+"
            f"—+bearbeite+ihn+über+das+Zahnrad", status_code=302)
    panel_enabled, panel_title, panel_text, panel_labels = _tempvoice_panel_fields(form)
    await db_exec(
        "INSERT INTO temp_voice_config (guild_id, trigger_channel_id, category_id, "
        "name_template, user_limit, panel_enabled, panel_title, panel_text, panel_labels) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (guild_id, trigger, category, name_tpl, user_limit, panel_enabled, panel_title,
         panel_text, panel_labels),
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
        panel_enabled, panel_title, panel_text, panel_labels = _tempvoice_panel_fields(form)
        await db_exec(
            "UPDATE temp_voice_config SET trigger_channel_id=?, category_id=?, name_template=?, "
            "user_limit=?, panel_enabled=?, panel_title=?, panel_text=?, panel_labels=? "
            "WHERE id=? AND guild_id=?",
            (trigger, category, name_tpl, user_limit, panel_enabled, panel_title, panel_text,
             panel_labels, config_id, guild_id),
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
    user_allowed_tabs = await _viewer_allowed_tabs(request, guild_id)
    if user_allowed_tabs is not None and "notifications" not in user_allowed_tabs:
        return _redirect_no_access(guild_id, user_allowed_tabs)
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
        # Fuer die Ping-Auswahl - @everyone bleibt draussen, siehe _ping_roles().
        "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default()],
        "twitch_apis": twitch_apis,
        "current_api_id": current_api_id,
        "api_unresolved": api_unresolved,
        "twitch_configured": bool(twitch_apis),
        "success": success, "error": error,
        "enabled_features": await _get_enabled_features(guild_id),
        "user_allowed_tabs": user_allowed_tabs,
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
    ping_role_id: str = Form(""),
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
        "INSERT INTO notifications (guild_id,platform,discord_channel_id,target,target_name,"
        "custom_message,ping_role_id,ping_enabled) VALUES (?,?,?,?,?,?,?,?)",
        (guild_id, platform, discord_channel_id, target.lower() if platform == "twitch" else target,
         target_name.strip(), custom_message.strip(),
         ping_role_id.strip() if ping_role_id.strip() in _ping_roles(guild) else "",
         1),
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
    ping_role_id: str = Form(""),
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
            "UPDATE notifications SET discord_channel_id=?, target=?, target_name=?, custom_message=?, "
            "ping_role_id=?, ping_enabled=?, live=0, last_id='' WHERE id=? AND guild_id=?",
            (discord_channel_id, target_norm, target_name.strip(), custom_message.strip(),
             ping_role_id.strip() if ping_role_id.strip() in _ping_roles(guild) else "",
             1, nid, guild_id),
        )
    else:
        await db_exec(
            "UPDATE notifications SET discord_channel_id=?, target=?, target_name=?, custom_message=?, "
            "ping_role_id=?, ping_enabled=? WHERE id=? AND guild_id=?",
            (discord_channel_id, target_norm, target_name.strip(), custom_message.strip(),
             ping_role_id.strip() if ping_role_id.strip() in _ping_roles(guild) else "",
             1, nid, guild_id),
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
# Matches the 9 bullet points already documented in the Log page's info box
# (log_info_item_member/_roles/_bans/_delete/_bulk/_edit/_voice/_channel/_boost) - one
# category per bullet, tagged by cogs/logging_cog.py on every write. Always-on (no per-server
# switch), unlike BOT_EVENT_CATEGORIES below.
NATIVE_LOG_CATEGORIES = ("member", "roles", "bans", "delete", "bulk", "edit", "voice", "channel", "boost")
# The per-user display filter (checkboxes on the Log page) covers both the always-on native
# Discord-event categories AND the opt-in bot-action categories (cogs/log_utils.py) with the
# exact same mechanism - a viewer doesn't need to care which of the two a category belongs to
# when deciding what to look at.
# The individual events inside a category, for the ones that log more than one thing. A
# category not listed here logs exactly one kind of event, so splitting it would just be the
# same checkbox twice. Keys match the `sub` that cogs/logging_cog.py passes to _log(), and the
# stored form is "<category>.<sub>" - switching off a whole category still covers all of its
# sub-entries, so the two levels never contradict each other.
LOG_SUBCATEGORIES = {
    "member":  ("join", "leave"),
    "roles":   ("change", "nick", "timeout"),
    "bans":    ("ban", "unban"),
    "voice":   ("join", "leave", "move"),
    "channel": ("create", "delete", "rename"),
}

LOG_CATEGORIES = NATIVE_LOG_CATEGORIES + BOT_EVENT_CATEGORIES


@web.get("/servers/{guild_id}/log", response_class=HTMLResponse)
async def server_log_page(request: Request, guild_id: str, success: str = "", error: str = "",
                           limit: Optional[int] = None,
                           categories: Optional[List[str]] = Query(None)):
    if r := auth_redirect(request): return r
    token_set = await _token_configured()
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    user_allowed_tabs = await _viewer_allowed_tabs(request, guild_id)
    if user_allowed_tabs is not None and "log" not in user_allowed_tabs:
        return _redirect_no_access(guild_id, user_allowed_tabs)
    uid = request.session.get("user_id")
    if limit is not None and limit in LOG_LIMIT_OPTIONS:
        if uid:
            await db_exec("UPDATE users SET log_limit=? WHERE id=?", (limit, uid))
    else:
        user_row = await db_one("SELECT log_limit FROM users WHERE id=?", (uid,)) if uid else None
        limit = (user_row or {}).get("log_limit") or 200
    if limit not in LOG_LIMIT_OPTIONS:
        limit = 200

    if categories is not None:
        # Filter checkboxes were just submitted - normalize "every box checked" (or "none
        # checked", equally meaningless as an actual restriction) back to the stored
        # "show everything" empty value, same normalization already used for the
        # per-moderator tab-restriction save route.
        valid = [c for c in categories if c in LOG_CATEGORIES]
        log_categories_value = "" if (not valid or len(valid) == len(LOG_CATEGORIES)) else ",".join(valid)
        if uid:
            await db_exec("UPDATE users SET log_categories=? WHERE id=?", (log_categories_value, uid))
    else:
        user_row = await db_one("SELECT log_categories FROM users WHERE id=?", (uid,)) if uid else None
        log_categories_value = (user_row or {}).get("log_categories") or ""
    active_log_categories = [c for c in log_categories_value.split(",") if c] or list(LOG_CATEGORIES)

    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    log_channel = await get_guild_config(int(guild_id), "log_channel") or ""
    _log_disabled = {
        x.strip() for x in
        (await get_guild_config(int(guild_id), "log_events_disabled") or "").split(",") if x.strip()
    }
    exclude_raw = await get_guild_config(int(guild_id), "log_exclude_channels") or ""
    log_exclude_channels = [c.strip() for c in exclude_raw.split(",") if c.strip()]
    bot_events_raw = await get_guild_config(int(guild_id), "log_bot_events") or ""
    active_bot_events = [c.strip() for c in bot_events_raw.split(",") if c.strip()]
    if log_categories_value:
        # Rows written before this feature existed (or by a future, not-yet-known category)
        # carry an empty category - always shown regardless of the filter, so switching the
        # filter on for the first time never makes older history disappear.
        placeholders = ",".join("?" for _ in active_log_categories)
        logs = await db_rows(
            f"""SELECT icon, title, description, created_at FROM server_logs
                WHERE guild_id=? AND (category='' OR category IN ({placeholders}))
                ORDER BY id DESC LIMIT ?""",
            (guild_id, *active_log_categories, limit),
        )
    else:
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
        "native_log_categories": NATIVE_LOG_CATEGORIES,
        "log_subcategories": LOG_SUBCATEGORIES,
        "enabled_native_categories": [c for c in NATIVE_LOG_CATEGORIES if c not in _log_disabled],
        # Every sub-entry that is NOT in the disabled list. A category the server has never
        # touched has nothing stored at all, so all of its sub-entries come back enabled -
        # which is what "all on by default" has to mean here too.
        "enabled_log_subcategories": [
            f"{cat}.{sub}" for cat, subs in LOG_SUBCATEGORIES.items() for sub in subs
            if f"{cat}.{sub}" not in _log_disabled
        ],
        "log_exclude_channels": log_exclude_channels,
        "logs": logs, "success": success, "error": error,
        "log_limit": limit, "log_limit_options": LOG_LIMIT_OPTIONS,
        "log_categories": LOG_CATEGORIES, "active_log_categories": active_log_categories,
        "bot_event_categories": BOT_EVENT_CATEGORIES, "active_bot_events": active_bot_events,
        "enabled_features": await _get_enabled_features(guild_id),
        "user_allowed_tabs": user_allowed_tabs,
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
    bot_events = ",".join(c for c in form.getlist("log_bot_events") if c in BOT_EVENT_CATEGORIES)
    # Stored as what is switched OFF, not what is on: an empty value then still means "all
    # nine native event types", which is what every server that never opened this setting has.
    # Storing the enabled set instead would silence the whole log for all of them at once.
    enabled_native = {c for c in form.getlist("log_events") if c in NATIVE_LOG_CATEGORIES}
    enabled_subs = set(form.getlist("log_events_sub"))
    disabled = [c for c in NATIVE_LOG_CATEGORIES if c not in enabled_native]
    # Sub-entries are only recorded for categories that are still ON: inside a switched-off
    # category they would be redundant, and writing them anyway means silently re-enabling
    # them later when the category is switched back on is no longer possible.
    for cat, subs in LOG_SUBCATEGORIES.items():
        if cat not in enabled_native:
            continue
        disabled += [f"{cat}.{sub}" for sub in subs if f"{cat}.{sub}" not in enabled_subs]
    events_disabled = ",".join(disabled)

    from database import set_guild_config
    await set_guild_config(int(guild_id), "log_channel", log_channel)
    await set_guild_config(int(guild_id), "log_exclude_channels", exclude_channels)
    await set_guild_config(int(guild_id), "log_bot_events", bot_events)
    await set_guild_config(int(guild_id), "log_events_disabled", events_disabled)
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
    "config": "⚙️ Config", "welcome": "👋 Willkommen", "automod": "🛡️ Spam-Schutz",
    "leveling": "🏆 Leveling",
    "rr": "🎭 Reaction Roles", "commands": "📢 Commands", "tickets": "🎫 Tickets",
    "giveaways": "🎉 Giveaways", "warnings": "⚠️ Warnungen", "users": "👥 Nutzer",
    "tempvoice": "🔊 Temp-Voice", "scheduled": "📅 Geplant", "events": "🗓️ Events",
    "birthday": "🎂 Geburtstage", "autodelete": "🗑️ Auto-Delete",
    "autothread": "🧵 Auto-Thread", "vrclink": "🔗 VRC-Link",
    "amp": "🎮 Gameserver", "autokick": "🚪 Auto-Kick", "embeds": "📨 Embed-Nachrichten",
    "rolerules": "🔗 CrossVerification", "polls": "🗳️ Umfragen", "ratings": "⭐ Bewertungen",
}

# Features an admin can hide from THIS server's own sidebar (for everyone alike) to cut down on
# clutter for servers that only use a handful of them - "config" (base settings), "users"
# (access control) and "botdesign" (bot identity) are deliberately left out of THIS server-wide
# list and stay permanently visible here, since they're structural/administrative rather than a
# feature someone would opt in or out of for the whole server. Hiding a tab here only removes
# its sidebar link - a bookmarked or manually-typed URL to it still works, this is about
# decluttering navigation, not gating access (that's what user_guild_permissions/admin-only
# routes already handle separately). "config" specifically CAN still be hidden on a PER-
# MODERATOR basis though - see _MODERATOR_RESTRICTABLE_TABS just below, a separate, narrower
# restriction that only ever affects one already-granted moderator at a time, never the server
# as a whole.
_TOGGLEABLE_FEATURES = {
    "welcome": "👋 Willkommen",
    "automod": "🛡️ Spam-Schutz", "leveling": "🏆 Leveling", "rr": "🎭 Reaction Roles",
    "commands": "📢 Commands", "tickets": "🎫 Tickets", "giveaways": "🎉 Giveaways",
    "warnings": "⚠️ Warnungen", "tempvoice": "🔊 Temp-Voice", "scheduled": "📅 Geplant",
    "events": "🗓️ Events", "birthday": "🎂 Geburtstage", "autodelete": "🗑️ Auto-Delete",
    "autothread": "🧵 Auto-Thread", "vrclink": "🔗 VRC-Link",
    "amp": "🎮 Gameserver", "notifications": "🟣 Streaming", "freestuff": "🎁 Free Stuff",
    "log": "📋 Log", "autokick": "🚪 Auto-Kick", "embeds": "📨 Embed-Nachrichten",
    "rolerules": "🔗 CrossVerification", "polls": "🗳️ Umfragen", "ratings": "⭐ Bewertungen",
}

# User-requested ("ich will den das der mod auch nur das sieht was weigegeben ist ... also
# komplete ausblendung") - unlike _TOGGLEABLE_FEATURES above (server-wide declutter, config/
# users/botdesign deliberately excluded and always visible), the per-moderator restriction on
# the "👥 Nutzer" tab DOES let an admin hide "⚙️ Config" for a specific moderator - that tab's
# own content (feature-toggle + backup/restore) is already admin-only in the template regardless
# of this, so restricting it here is pure sidebar declutter, never a new access boundary. "users"/
# "botdesign" stay out of this superset too: their content is likewise already fully admin-gated
# (a restricted moderator visiting either just sees an empty/admin-only state), so hiding their
# links wouldn't add anything a determined narrowing-down admin actually needs.
_MODERATOR_RESTRICTABLE_TABS = {**_TOGGLEABLE_FEATURES, "config": "⚙️ Config"}


def _restriction_fallback_url(guild_id, user_allowed_tabs: Optional[set]) -> str:
    """Where to bounce a moderator away from a tab they don't have - never straight back to
    'config' if THAT is also one of their blocked tabs (would otherwise redirect right back
    into the same enforcement check, config -> config -> ...). Picks their own 'config' first
    if they still have it (keeps the familiar landing spot for everyone else), else the first
    tab they DO have. `user_allowed_tabs` is only ever empty for a row that was never actually
    restricted (see _user_guild_allowed_tabs - an all-unchecked save also normalizes to
    unrestricted), so a restricted moderator always has at least one tab left to land on."""
    if user_allowed_tabs:
        tab = "config" if "config" in user_allowed_tabs else sorted(user_allowed_tabs)[0]
        return f"/servers/{guild_id}?tab={tab}"
    return "/servers"


def _redirect_no_access(guild_id, user_allowed_tabs: Optional[set]) -> RedirectResponse:
    base = _restriction_fallback_url(guild_id, user_allowed_tabs)
    sep = "&" if "?" in base else "?"
    return RedirectResponse(f"{base}{sep}error=Kein+Zugriff+auf+diesen+Bereich", status_code=302)


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


# User-requested ("es wäre schön wenn mann den moderatoren nur zu bestimmte rechte geben kann
# mansche brauchen nur umfragen oder tikets") - a per-moderator, per-server restriction on top
# of the existing user_guild_permissions grant (that one is all-or-nothing: has access to this
# server's whole dashboard, or none at all). Deliberately the OPPOSITE default of
# `enabled_features` above: an empty/unset `allowed_tabs` here means UNRESTRICTED (every tab the
# server itself has enabled) rather than "nothing" - so a moderator already granted access today
# keeps working exactly as before until an admin explicitly narrows them down on the "👥 Nutzer"
# tab. Admins are never subject to this (checked by the caller, not in here) - this only ever
# narrows what an already-granted MODERATOR can reach, never grants anything beyond what
# user_guild_permissions/_guild_access already allow.
async def _user_guild_allowed_tabs(user_id, guild_id) -> Optional[set]:
    row = await db_one(
        "SELECT allowed_tabs FROM user_guild_permissions WHERE user_id=? AND guild_id=?",
        (user_id, str(guild_id)),
    )
    if not row or not row.get("allowed_tabs"):
        return None  # no row (e.g. token-based access) or never restricted = unrestricted
    return {t for t in row["allowed_tabs"].split(",") if t}


async def _viewer_allowed_tabs(request: Request, guild_id) -> Optional[set]:
    """None = unrestricted (admin, or a moderator never narrowed down) - the same "no
    restriction" meaning used throughout this feature and by _server_subnav.html's own
    `enabled_features is none` check it's meant to sit alongside."""
    if request.session.get("role") == "admin":
        return None
    return await _user_guild_allowed_tabs(request.session.get("user_id"), guild_id)


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

    # A restricted moderator ("nur umfragen oder tikets") gets bounced off any tab outside their
    # own allowed set - "users"/"botdesign" stay reachable regardless (their content is already
    # fully admin-gated in the template either way), but "config" CAN be hidden per moderator
    # too (_MODERATOR_RESTRICTABLE_TABS) since the user explicitly asked for it to be fully
    # hideable, not just its content admin-gated. An admin is never subject to this at all.
    user_allowed_tabs = await _viewer_allowed_tabs(request, guild_id)
    if user_allowed_tabs is not None and tab in _MODERATOR_RESTRICTABLE_TABS and tab not in user_allowed_tabs:
        return _redirect_no_access(guild_id, user_allowed_tabs)

    token_set = await _token_configured()
    cfg = await get_all_guild_config(guild_id)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    voice_channels = [{"id": str(c.id), "name": c.name} for c in guild.voice_channels]
    # Embed-Nachrichten-only channel picker (text channels + forums) - deliberately kept
    # separate from the plain `channels` list used everywhere else on this page (tickets,
    # auto-delete, scheduled messages, ...), none of which can meaningfully target a forum.
    embed_channels = (
        [{"id": str(c.id), "name": c.name, "is_forum": False, "tags": [], "require_tag": False}
         for c in guild.text_channels]
        + [{"id": str(c.id), "name": c.name, "is_forum": True, "require_tag": c.flags.require_tag,
            # A custom (server-uploaded) tag emoji str()s to raw Discord markup like
            # "<:pog:123...>" - rendering that literally in the tag picker would show that
            # exact ugly text next to the tag name instead of an actual emoji, since HTML has
            # no idea what that syntax means. emoji_url (PartialEmoji.url, Discord's own CDN
            # link for custom emoji, empty for a plain unicode one) lets the template show a
            # real <img> for a custom emoji instead - a unicode emoji has no url and keeps
            # rendering directly via the plain "emoji" text field, unicode already displays
            # correctly on its own.
            "tags": [{"id": str(t.id), "name": t.name,
                      "emoji": str(t.emoji) if t.emoji and not t.emoji.is_custom_emoji() else "",
                      "emoji_url": t.emoji.url if t.emoji and t.emoji.is_custom_emoji() else ""}
                     for t in c.available_tags]}
           for c in guild.forums]
    )
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
        # A custom server emoji is stored in its canonical "<:name:id>" form (see
        # normalize_reaction_emoji) - printed as-is the Emoji column shows that raw markup
        # instead of an emoji, which is unreadable exactly where the admin needs to tell one
        # row from another. Resolved to the CDN image Discord serves for it; a plain unicode
        # emoji has no id and keeps being printed as text.
        _m = re.fullmatch(r"<(a?):([A-Za-z0-9_]+):(\d+)>", rr["emoji"] or "")
        rr["emoji_image"] = (
            f"https://cdn.discordapp.com/emojis/{_m.group(3)}.{'gif' if _m.group(1) else 'png'}"
            if _m else None
        )
        rr["emoji_name"] = _m.group(2) if _m else None

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
        ep["applied_tags_list"] = [t for t in (ep.get("applied_tags") or "").split(",") if t]
        # image_data can be a sizeable base64 blob - the template only ever needs to know
        # WHETHER an uploaded image exists (via image_filename) and fetches the actual bytes
        # through its own dedicated /embeds/{id}/image route when previewing it, never
        # straight out of this context.
        ep.pop("image_data", None)

    # VRC-Link
    _vrc_role_map_rows = await db_rows(
        "SELECT * FROM vrc_role_map WHERE guild_id=? ORDER BY id", (str(guild_id),))
    _role_names = {str(ro.id): ro.name for ro in guild.roles}
    for _rm in _vrc_role_map_rows:
        # A Discord role that has since been deleted still has a mapping pointing at it -
        # shown as its bare id rather than silently dropped, so an admin can see and remove it.
        _rm["discord_role_name"] = _role_names.get(_rm["discord_role_id"], "")
    _vrc_account = await db_one("SELECT * FROM vrc_accounts WHERE guild_id=?", (VRC_ACCOUNT_KEY,))
    if _vrc_account:
        # The password and the session cookies never leave the server - the page only needs to
        # know THAT an account is stored, plus whoever it turned out to be.
        for _k in ("password", "totp_secret", "auth_cookie", "two_factor_cookie"):
            _vrc_account[_k] = ""
    _vrc_links = await db_rows(
        "SELECT * FROM vrc_links WHERE guild_id=? ORDER BY status DESC, requested_at ASC",
        (str(guild_id),),
    )
    for _vl in _vrc_links:
        _m = guild.get_member(int(_vl["user_id"])) if str(_vl["user_id"]).isdigit() else None
        _vl["member_name"] = _m.display_name if _m else f"#{_vl['user_id']}"
        _vl["in_guild"] = _m is not None
        # What the nickname WOULD become, so an admin can see the effect of the format before
        # queueing it onto 200 people.
        _vl["preview"] = vrc_nickname(
            cfg.get("vrc_nickname_format") or DEFAULT_VRC_NICKNAME_FORMAT,
            _vl["vrchat_name"], _m.name if _m else "")

    # Temp Voice
    _tempvoice_configs = await db_rows(
        "SELECT * FROM temp_voice_config WHERE guild_id=?", (str(guild_id),)
    )
    for _tv in _tempvoice_configs:
        # The captions that are actually in effect, not the raw JSON: an untouched field has
        # nothing stored, and the form needs the German default to show in it.
        _tv["labels"] = parse_panel_labels(_tv.get("panel_labels") or "")

    # Role Rules
    role_rules = await db_rows(
        "SELECT * FROM role_rules WHERE guild_id=? ORDER BY priority ASC, id ASC", (str(guild_id),)
    )
    _all_guild_roles = [{"id": str(ro.id), "name": ro.name} for ro in guild.roles if not ro.is_default()]
    _role_names_by_id = {ro["id"]: ro["name"] for ro in _all_guild_roles}
    role_rule_target_guilds = await _role_rule_target_guilds(request, guild_id)
    role_rule_target_roles = {}
    for tg in role_rule_target_guilds:
        tg_obj = bot.get_guild(int(tg["id"]))
        role_rule_target_roles[tg["id"]] = (
            [{"id": str(ro.id), "name": ro.name} for ro in tg_obj.roles if not ro.is_default()]
            if tg_obj else []
        )
    for rr in role_rules:
        match_ids = [i for i in (rr.get("match_role_ids") or "").split(",") if i]
        rr["match_role_ids_list"] = match_ids
        rr["match_role_names"] = [_role_names_by_id.get(i, "?") for i in match_ids]
        action_ids = [i for i in (rr.get("action_role_ids") or "").split(",") if i]
        rr["action_role_ids_list"] = action_ids
        # Resolved via the unrestricted bot.get_guild() (same as action_guild_name below), not
        # the permission-filtered role_rule_target_roles dict used for the form's checkboxes -
        # a rule's target could be a guild the CURRENT viewer no longer has dashboard access to
        # (e.g. a moderator whose access was narrowed after another admin created the rule),
        # which would otherwise show every role name as "?" despite the rule itself resolving
        # and running just fine in the cog.
        tg_obj = bot.get_guild(int(rr["action_guild_id"]))
        rr["action_guild_name"] = tg_obj.name if tg_obj else "?"
        target_names_by_id = (
            {str(ro.id): ro.name for ro in tg_obj.roles if not ro.is_default()} if tg_obj else {}
        )
        rr["action_role_names"] = [target_names_by_id.get(i, "?") for i in action_ids]
        # Every action block of the rule, resolved for display and for re-populating the edit
        # form. A rule saved before multi-action existed comes back from role_rule_actions() as
        # a single block built from the legacy columns, so this list is never empty and the
        # template needs no special case for "old rule".
        rr["action_blocks"] = []
        for block in role_rule_actions(rr):
            b_guild = bot.get_guild(int(block["guild_id"])) if block["guild_id"].isdigit() else None
            b_names = (
                {str(ro.id): ro.name for ro in b_guild.roles if not ro.is_default()} if b_guild else {}
            )
            rr["action_blocks"].append({
                "action": block["action"],
                "guild_id": block["guild_id"],
                "guild_name": b_guild.name if b_guild else "?",
                "is_cross": block["guild_id"] != str(guild_id),
                "role_ids": block["role_ids"],
                "role_names": [b_names.get(i, "?") for i in block["role_ids"]],
            })
        # Flat "add:guild:id,id|remove:guild:id" encoding for the client-side test sandbox -
        # deliberately not JSON, matching the existing data-* convention documented at the
        # hidden .rr-rule-data block in the template (the js/jsraw filters only take scalars).
        rr["actions_encoded"] = "|".join(
            f"{b['action']}:{b['guild_id']}:{','.join(b['role_ids'])}" for b in rr["action_blocks"]
        )
    role_rules_interval = await get_guild_config(guild_id, "role_rules_interval_minutes") or "0"
    # Absent = on, mirroring the cog's own default - see role_rule_save_autocreate().
    role_rules_autocreate = (await get_guild_config(guild_id, "role_rules_autocreate") or "1") != "0"
    # Debug trace straight from the cog's own in-memory ring buffer (cogs/role_rules.py's
    # self._debug_log) - shown on the dashboard itself instead of requiring a docker exec/logs
    # round-trip for every troubleshooting attempt. Filtered to lines that mention THIS guild's
    # id (covers on_member_update/rule-match lines logged under it, AND lines where it's the
    # printed TARGET of a cross-server action from elsewhere) or any guild this tab's own rules
    # target, so an admin sees the full chain without wading through unrelated servers' entries.
    role_rules_debug_log = []
    _rr_guild_bot = bot._bot_for_guild(guild_id)
    _rr_cog = _rr_guild_bot.get_cog("RoleRules") if _rr_guild_bot else None
    # Distinguish "cog genuinely has nothing to show yet" from "the cog isn't even loaded on
    # the bot instance connected to this guild" (e.g. a startup error in cogs/role_rules.py) -
    # the latter would otherwise look identical to "no events yet" and send an admin chasing
    # the wrong problem.
    role_rules_cog_missing = _rr_cog is None
    if _rr_cog:
        # Built from every action BLOCK's target, not from the action_guild_id column: that
        # column only mirrors the FIRST block, so for a rule like "gib Rolle A auf Server Z UND
        # nimm Rolle B auf Server Y" the whole of Server Y's trace was filtered out of this
        # view - exactly the lines an admin opens the debug box to read when the second action
        # is the one not working.
        _rr_relevant_ids = {str(guild_id)} | {
            b["guild_id"] for rr in role_rules for b in rr["action_blocks"]
        }
        role_rules_debug_log = [
            line for line in reversed(_rr_cog._debug_log)
            if any(gid in line for gid in _rr_relevant_ids)
        ][:100]

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

    # Active polls
    poll_list = await db_rows(
        "SELECT p.*, (SELECT COUNT(*) FROM poll_votes v WHERE v.poll_id=p.id) AS vote_count "
        "FROM polls p WHERE p.guild_id=? AND p.ended=0 ORDER BY p.created_at DESC", (str(guild_id),)
    )
    for p in poll_list:
        ch = guild.get_channel(int(p["channel_id"])) if p["channel_id"] else None
        p["channel_name"] = f"#{ch.name}" if ch else "?"
        p["options"] = await db_rows(
            "SELECT * FROM poll_options WHERE poll_id=? ORDER BY option_index", (p["id"],)
        )

    # Rating list ("die maps oder seiten in eine liste eintragen") - recommended items first
    # (manual admin flag), then everything else sorted by average rating.
    rating_list = await db_rows(
        "SELECT i.*, "
        "(SELECT COUNT(*) FROM rating_votes v WHERE v.item_id=i.id) AS vote_count, "
        "(SELECT AVG(stars) FROM rating_votes v WHERE v.item_id=i.id) AS avg_stars "
        "FROM rating_items i WHERE i.guild_id=? "
        "ORDER BY i.recommended DESC, avg_stars DESC, i.label COLLATE NOCASE",
        (str(guild_id),),
    )
    # "die bewerungen möchte ich auch in dc posten können ... ich muss dafür ein text chanel
    # anbinden können" - the persistent posted-list channel, if one's configured/posted yet.
    ratings_channel_id = await get_guild_config(guild_id, "ratings_channel_id") or ""
    ratings_posted = bool(await get_guild_config(guild_id, "ratings_message_id"))

    # Notifications
    subs = await db_rows(
        "SELECT * FROM notifications WHERE guild_id=? ORDER BY platform, target_name", (str(guild_id),)
    )
    twitch_configured = bool(await db_rows("SELECT 1 FROM twitch_apis LIMIT 1"))

    # Dashboard users & server access
    all_users = await db_rows("SELECT id, username, role FROM users ORDER BY role DESC, username")
    perm_rows = await db_rows(
        "SELECT user_id, allowed_tabs FROM user_guild_permissions WHERE guild_id=?", (str(guild_id),)
    )
    server_perms = {p["user_id"] for p in perm_rows}
    # Per-granted-moderator tab restriction, for the "👥 Nutzer" tab's own checklist - a user_id
    # NOT in this dict (or an empty set) means unrestricted, matching _viewer_allowed_tabs' own
    # "none/empty = no restriction" convention used for enforcement above.
    server_user_allowed_tabs = {
        p["user_id"]: {t for t in (p["allowed_tabs"] or "").split(",") if t} for p in perm_rows
    }
    server_admin_count = sum(1 for u in all_users if u["role"] == "admin")

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

    _coops = await db_rows(
        "SELECT * FROM coop_partners WHERE guild_id=? ORDER BY id", (str(guild_id),))
    _coop_key_einmal = request.session.pop("coop_new_key", "")
    _coop_name_einmal = request.session.pop("coop_new_name", "")
    return templates.TemplateResponse("server_config.html", {
        **session(request), "request": request,
        "guild": {"id": str(guild.id), "name": guild.name,
                  "icon": str(guild.icon.url) if guild.icon else None},
        "cfg": cfg, "channels": channels, "embed_channels": embed_channels,
        "role_rules": role_rules, "all_guild_roles": _all_guild_roles,
        # Kooperationen mit fremden Installationen - eigener Abschnitt, eigene Tabelle, die
        # bestehenden Regeln oben bleiben davon unberuehrt.
        "coops": _coops,
        # Ein frisch erzeugter Schluessel wird genau einmal gezeigt und dabei aus der Sitzung
        # genommen: gespeichert ist nur sein Hash, ein zweites Mal gibt es ihn nicht.
        "coop_new_key": _coop_key_einmal, "coop_new_name": _coop_name_einmal,
        "role_rule_target_guilds": role_rule_target_guilds,
        "role_rule_target_roles": role_rule_target_roles,
        "role_rules_interval": role_rules_interval,
        "role_rules_autocreate": role_rules_autocreate,
        "role_rules_debug_log": role_rules_debug_log,
        "role_rules_cog_missing": role_rules_cog_missing,
        "roles": roles, "categories": categories,
        "token_set": token_set, "saved": saved,
        "active": f"server_{guild_id}",
        "guilds": await _guild_list(request),
        "tab": tab, "error": error, "success": success,
        "tab_label": _SERVER_CONFIG_TAB_LABELS.get(tab, _SERVER_CONFIG_TAB_LABELS["config"]),
        "rr_list": rr_list, "cmd_list": cmd_list,
        "leaderboard": lb, "warn_groups": warn_groups,
        "ticket_panels": ticket_panels, "ticket_list": ticket_list, "ga_list": ga_list,
        "poll_list": poll_list,
        "rating_list": rating_list, "ratings_channel_id": ratings_channel_id,
        "ratings_posted": ratings_posted,
        "embed_posts": embed_posts,
        "subs": subs, "twitch_configured": twitch_configured,
        "all_users": all_users, "server_perms": server_perms,
        "server_user_allowed_tabs": server_user_allowed_tabs,
        "server_admin_count": server_admin_count,
        "automod_presets": automod_presets,
        "leveling_channels": leveling_channels,
        "level_roles": level_roles,
        "level_rewards": level_rewards,
        "auto_kick_reminders": auto_kick_reminders,
        "auto_thread_entries": await db_rows(
            "SELECT * FROM auto_thread_channels WHERE guild_id=? ORDER BY id ASC", (str(guild_id),)
        ),
        "auto_delete_entries": await db_rows(
            "SELECT * FROM auto_delete_channels WHERE guild_id=?", (str(guild_id),)
        ),
        "voice_channels": voice_channels,
        "tempvoice_configs": _tempvoice_configs,
        "vrc_links": _vrc_links,
        "vrc_pending_count": sum(1 for v in _vrc_links if v["status"] != "approved"),
        "vrc_account": _vrc_account,
        # Everything else in the tab hangs off a working account, so the template only shows
        # it once there is one - settings that provably cannot do anything yet are noise.
        "vrc_connected": bool(_vrc_account and _vrc_account["vrc_user_id"]),
        "vrc_nickname_default": DEFAULT_VRC_NICKNAME_FORMAT,
        # Without a public address the bot cannot build a member link at all, so the tab says
        # so plainly instead of letting an admin post a panel whose button answers with an
        # error. Normally it is simply the address this dashboard is open at - see
        # link_base_url() - so this is only ever empty on a brand-new install.
        "vrc_link_base": await link_base_url(),
        "vrc_panel_title_default": DEFAULT_VRC_PANEL_TITLE,
        "vrc_panel_text_default": DEFAULT_VRC_PANEL_TEXT,
        "vrc_panel_button_default": DEFAULT_VRC_PANEL_BUTTON,
        # Only show the group column when this server actually uses a group - an extra column
        # of dashes tells nobody anything.
        "vrc_group_on": bool((cfg.get("vrc_group_id") or "").strip()),
        "vrc_role_map": _vrc_role_map_rows,
        "vrc_instance_default": DEFAULT_VRC_INSTANCE_MESSAGE,
        "vrc_instance_button_default": DEFAULT_VRC_INSTANCE_BUTTON,
        "vrc_instance_closed_default": DEFAULT_VRC_INSTANCE_CLOSED,
        "vrc_instance_title_default": DEFAULT_VRC_INSTANCE_TITLE,
        "vrc_instance_closed_title_default": DEFAULT_VRC_INSTANCE_CLOSED_TITLE,
        "vrc_instance_count_default": DEFAULT_VRC_INSTANCE_COUNT_LABEL,
        "vrc_instance_footer_default": DEFAULT_VRC_INSTANCE_FOOTER,
        "vrc_instance_locked_default": DEFAULT_VRC_INSTANCE_LOCKED,
        "vrc_instance_locked_title_default": DEFAULT_VRC_INSTANCE_LOCKED_TITLE,
        # Names for the live example under the format field. A real linked pair if there is
        # one - seeing the format applied to somebody who is actually on the server says more
        # than a made-up name - otherwise a stand-in, so the example is never empty.
        "vrc_example_vrchat": next((v["vrchat_name"] for v in _vrc_links if v["status"] == "approved"),
                                   "AlexInVR"),
        "vrc_example_discord": next((v["member_name"] for v in _vrc_links if v["status"] == "approved"),
                                    "alex"),
        "amp_cfg": amp_cfg, "amp_status": amp_status, "amp_instances": amp_instances,
        "amp_instances_error": amp_instances_error, "amp_connection_error": amp_connection_error,
        "amp_raw_debug": amp_raw_debug,
        "welcome_overlay_presets": _WELCOME_OVERLAY_PRESETS,
        "toggleable_features": _TOGGLEABLE_FEATURES,
        "moderator_restrictable_tabs": _MODERATOR_RESTRICTABLE_TABS,
        "enabled_features": await _get_enabled_features(guild_id),
        "user_allowed_tabs": user_allowed_tabs,
        "scheduled_messages": _scheduled_messages,
        "birthdays": _birthdays,
        # The words that ACTUALLY take effect after parsing, not the raw string - shown back
        # on the tab so an admin can see at a glance what their input turned into (an empty
        # setting falls back to the defaults, which would otherwise be invisible).
        "birthday_triggers": parse_command_triggers(
            cfg.get("birthday_commands") or "", DEFAULT_BIRTHDAY_TRIGGERS),
        "birthday_delete_words": parse_command_triggers(
            cfg.get("birthday_delete_words") or "", DEFAULT_BIRTHDAY_DELETE_WORDS),
        # Defaults handed to the template so an empty field can show the text that is actually
        # being sent, rather than an empty box next to a bot that clearly answers something.
        "tempvoice_panel_defaults": {
            "title": DEFAULT_TEMPVOICE_PANEL_TITLE,
            "text": DEFAULT_TEMPVOICE_PANEL_TEXT,
            "labels": DEFAULT_TEMPVOICE_LABELS,
        },
        "birthday_reply_defaults": {
            "saved": DEFAULT_BIRTHDAY_REPLY_SAVED,
            "deleted": DEFAULT_BIRTHDAY_REPLY_DELETED,
            "error": DEFAULT_BIRTHDAY_REPLY_ERROR,
        },
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
    # Config itself owns no text fields anymore - the welcome/leave/autorole/card settings
    # moved to their own "welcome" tab (see below), leaving config with only the always-visible
    # feature-toggle and server-backup cards which don't go through this per-tab save loop at
    # all. The key still has to exist (server_config_save() indexes into it unconditionally).
    "config": [],
    "welcome": [
        "welcome_channel", "welcome_message", "leave_channel", "leave_message", "autorole",
        "welcome_card_circle_color", "welcome_card_text_color", "welcome_card_username_color",
        "welcome_card_heading_text", "welcome_card_subtitle_text",
        "welcome_card_avatar_shape", "welcome_card_avatar_position", "welcome_ping_role",
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
    "vrclink": ["vrc_linked_role", "vrc_nickname_format", "vrc_panel_channel",
                "vrc_panel_title", "vrc_panel_text", "vrc_panel_button", "vrc_dm_text",
                "vrc_group_id", "vrc_group_role", "vrc_link_minutes",
                "vrc_role_sync_minutes", "vrc_instance_channel", "vrc_instance_role",
                "vrc_instance_message", "vrc_instance_minutes", "vrc_instance_button",
                "vrc_instance_closed_message", "vrc_instance_delete_after",
                "vrc_instance_title", "vrc_instance_closed_title",
                "vrc_instance_count_label", "vrc_instance_footer",
                "vrc_instance_locked_title", "vrc_instance_locked_message"],
    "birthday": ["birthday_channel", "birthday_message", "birthday_commands",
                 "birthday_delete_words", "birthday_reply_saved",
                 "birthday_reply_deleted", "birthday_reply_error"],
    # The reminder DMs themselves (offset + message, plural) are a separate list managed via
    # their own add/delete routes below, not a fixed set of form fields - only the required
    # role and the single final kick delay go through the generic per-tab save here.
    "autokick": ["auto_kick_role_id", "auto_kick_kick_hours"],
}
_TAB_CHECKBOX_KEYS = {
    "config": [],
    "welcome": ["welcome_card_enabled"],
    "leveling": ["leveling_enabled", "leveling_voice_enabled"],
    "automod": ["automod_enabled", "automod_links"],
    "birthday": [],
    # vrc_require_ownership defaults to ON when absent, so an existing server keeps the
    # proof it already had - see the read in vrc_public_name().
    "vrclink": ["vrc_enabled", "vrc_nickname_enabled", "vrc_auto_approve", "vrc_dm_on_join",
                "vrc_require_ownership", "vrc_group_invite", "vrc_instance_cleanup",
                "vrc_instance_live_count", "vrc_instance_detail"],
    # auto_kick_enabled deliberately NOT here - it needs the previous saved value to detect an
    # off→on transition (see the dedicated handling in server_config_save below), the generic
    # loop below has no way to express that.
    "autokick": [],
}


@web.post("/servers/{guild_id}/features/save")
async def server_features_save(request: Request, guild_id: int):
    # Server-WIDE setting, same for every viewer of this server - the template already hides
    # this card's form from anyone but an admin, but the route itself must refuse it too
    # ("der mod kann die sachen die bei nutzer aus sind wieder an machen" - confirmed live: a
    # granted moderator could POST here directly and rewrite it, even fully restricted via
    # their own allowed_tabs, since that's a separate, per-viewer check this route never made).
    if r := admin_redirect(request): return r
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
    raw_tab = str(form.get("tab", "config"))
    tab = raw_tab if raw_tab in _TAB_TEXT_KEYS else "config"

    # Dieselbe Sperre wie beim ANZEIGEN des Reiters, mit derselben Liste, damit die Namen
    # nicht auseinanderlaufen koennen. Bisher galt sie nur fuer GET: ein eingeschraenkter
    # Moderator konnte den Reiter nicht sehen, aber sehr wohl hineinschreiben, indem er das
    # Formular selbst abschickte.
    #
    # Geprueft werden BEIDE Namen: der abgeschickte - das ist der eigentliche Weg vorbei - und
    # der, unter dem am Ende wirklich geschrieben wird. Nur sieben Reiter haben ueberhaupt
    # eigene Textfelder, alle anderen fallen hier auf "config" zurueck; ohne den zweiten Blick
    # schriebe ein auf "Umfragen" beschraenkter Moderator ueber genau diesen Rueckfall die
    # Grundeinstellungen des Servers, die ihm verwehrt sind.
    #
    # Wer nie eingeschraenkt wurde - jeder Admin und jeder normale Moderator - laeuft komplett
    # daran vorbei: _viewer_allowed_tabs() liefert dann None, und nichts an diesem Verhalten
    # aendert sich fuer bestehende Installationen.
    user_allowed_tabs = await _viewer_allowed_tabs(request, guild_id)
    if user_allowed_tabs is not None:
        for _name in (raw_tab, tab):
            if _name in _MODERATOR_RESTRICTABLE_TABS and _name not in user_allowed_tabs:
                return _redirect_no_access(guild_id, user_allowed_tabs)

    # Channel-valued keys are validated against the guild's own channels before saving -
    # some are resolved later via a global bot.get_channel() (not guild-scoped), so an
    # unvalidated ID here could otherwise make the bot post into a channel in a different
    # guild served by the same token.
    channel_keys = ["welcome_channel", "leave_channel", "birthday_channel", "level_channel",
                    "vrc_panel_channel", "vrc_instance_channel"]
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
    role_keys = ["autorole", "auto_kick_role_id", "vrc_linked_role", "vrc_group_role",
                 "vrc_instance_role", "welcome_ping_role"]
    valid_role_ids = {str(ro.id) for ro in guild.roles if not ro.is_default()}
    for key in role_keys:
        value = str(form.get(key, ""))
        if value and value not in valid_role_ids:
            return RedirectResponse(
                f"/servers/{guild_id}?tab={tab}&error=Ungültige+Rolle+({key})", status_code=302
            )

    # A VRChat group id is checked for shape before it is stored - a typo here would otherwise
    # only surface later as "the bot cannot see this group", which points at the wrong thing.
    _group_id = str(form.get("vrc_group_id", "")).strip()
    if _group_id:
        from vrchat import looks_like_group_id
        if not looks_like_group_id(_group_id):
            return RedirectResponse(
                f"/servers/{guild_id}?tab={tab}&error=Gruppen-ID+muss+mit+grp_+beginnen",
                status_code=302)

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
        # How long a member's personal VRC-Link page stays open. One minute is enough for
        # somebody who is already standing at the keyboard; a day is the sensible ceiling for
        # a link that is, after all, the whole credential.
        ("vrc_link_minutes", 1, 1440, "Gültigkeit des VRC-Link-Links"),
        # 0 = nur beim Verknüpfen, sonst der Abstand zwischen zwei Rollen-Abgleichen.
        ("vrc_role_sync_minutes", 0, 1440, "Abgleich der VRChat-Rollen (Minuten)"),
        # 0 = aus. Eine Anfrage je Server und Durchlauf, deshalb sind kurze Abstände hier
        # vertretbar - anders als bei allem, was pro Mitglied fragt.
        ("vrc_instance_minutes", 0, 1440, "Instanz-Prüfung (Minuten)"),
        ("vrc_instance_delete_after", 0, 1440, "Meldung löschen nach (Minuten)"),
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

    # The welcome card canvas is only 800px wide - an unbounded heading/subtitle would run
    # visibly off the edge, so both get a hard length cap here (mirroring numeric_fields'
    # pattern above, just for string length instead of numeric range). This only bounds the RAW
    # template, though - {server}/{user}/{count} can still expand a compliant 60/80-char template
    # well past the canvas width once substituted (a guild name alone can be up to 100 chars), so
    # cogs/welcome.py's _make_card() additionally fits the SUBSTITUTED text to the actual pixel
    # budget at render time (_fit_text()) as the real backstop - this cap is just an early,
    # cheap rejection of an obviously-too-long template, not the only thing preventing overflow.
    text_length_fields = [
        ("welcome_card_heading_text", 60, "Überschrift-Text"),
        ("welcome_card_subtitle_text", 80, "Untertitel-Text"),
    ]
    for field, max_len, label in text_length_fields:
        if len(str(form.get(field, ""))) > max_len:
            return RedirectResponse(
                f"/servers/{guild_id}?tab={tab}&error=Zu+langer+Wert+({label})", status_code=302
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
    if tab == "welcome":
        # File uploads can't go through the generic text-key loop above (form.get() would
        # return the UploadFile object itself, not a string) - handled separately here, only
        # reachable on the welcome tab's form which is the only one with enctype=multipart/
        # form-data. Same "leave untouched unless a new file is uploaded, explicit checkbox to
        # actually clear it" convention as the SMTP password field and the embed image feature.
        if form.get("remove_welcome_card_bg"):
            await set_guild_config(guild_id, "welcome_card_bg_image", "")
        else:
            try:
                new_bg = await _read_welcome_bg_upload(form.get("welcome_card_bg_image"))
            except ValueError as e:
                return RedirectResponse(f"/servers/{guild_id}?tab={tab}&error={e}", status_code=302)
            if new_bg is not None:
                await set_guild_config(guild_id, "welcome_card_bg_image", new_bg)
        try:
            new_overlay = await _read_welcome_overlay_upload(form.get("welcome_card_overlay_image"))
        except ValueError as e:
            return RedirectResponse(f"/servers/{guild_id}?tab={tab}&error={e}", status_code=302)
        if new_overlay is not None:
            # A freshly uploaded file always wins over the preset dropdown, same precedence as
            # the background image - and replaces whatever preset was active before, if any.
            await set_guild_config(guild_id, "welcome_card_overlay_image", new_overlay)
            await set_guild_config(guild_id, "welcome_card_overlay_preset", "")
        else:
            explicit, image_b64, marker = await _resolve_welcome_overlay_choice(
                str(form.get("welcome_card_overlay_choice", ""))
            )
            if explicit:
                await set_guild_config(guild_id, "welcome_card_overlay_image", image_b64)
                await set_guild_config(guild_id, "welcome_card_overlay_preset", marker)
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
    close_button_label = form.get("close_button_label", "Ticket schließen")
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
    if len(close_button_label.strip()) > 80:
        # Same Discord button-label limit as above, for the in-ticket close button.
        return RedirectResponse(
            f"/servers/{guild_id}?tab=tickets&error=Schließen-Button-Text+zu+lang+(max.+80+Zeichen)", status_code=302
        )
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
    new_close_label = close_button_label.strip() or "Ticket schließen"
    new_emoji = emoji.strip() or "🎫"
    new_description = _djson.dumps(description_blocks)
    new_ticket_message = _djson.dumps(ticket_message_blocks)
    await db_exec(
        "UPDATE ticket_panels SET name=?, button_label=?, close_button_label=?, description=?, ticket_message=?, emoji=?, "
        "support_role_id=?, category_id=?, archive_category_id=? WHERE id=? AND guild_id=?",
        (new_name, new_label, new_close_label, new_description, new_ticket_message, new_emoji,
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
    await _log_bot_event(
        bot, guild_id, "🔒", "Ticket geschlossen", "ticket",
        plain=f"#{ch.name} · über Dashboard" if ch else "über Dashboard",
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

def _build_freeform_embeds(content_raw, image_url: str = "", footer_text: str = "", image_filename: str = "") -> list:
    """Like _build_panel_embeds, but with no forced title/emoji on the first embed - this
    feature has no "name" concept baked into the posted content itself (unlike a ticket panel,
    which always shows its configured name+emoji as a title), it's meant to stay fully
    freeform. Capped at 10 blocks, same Discord hard limit as everywhere else blocks are used.
    image/footer are per-POST, not per-block (confirmed by explicit user answer - Discord
    itself only supports them per individual embed, so they land on the LAST embed rather than
    needing one field per "+"-added block). image_filename (set only when the image came from
    an upload, not a pasted URL) takes precedence over image_url and points the embed at
    "attachment://<filename>" instead - the caller is responsible for actually attaching a
    matching discord.File with that same filename, see _embed_post_files()."""
    blocks = _parse_ticket_blocks(content_raw) or [""]
    embeds = [discord.Embed(description=block, color=0x7C3AED) for block in blocks[:10]]
    if image_filename:
        embeds[-1].set_image(url=f"attachment://{image_filename}")
    elif image_url:
        embeds[-1].set_image(url=image_url)
    if footer_text:
        embeds[-1].set_footer(text=footer_text)
    return embeds


# No app-level size cap by design (explicit user request: "mach die grenze weg mach nur eine
# warung hin ab wann dc sich dan beschwert und es nicht klapen könnte") - Discord itself is the
# real, sole size enforcement (its actual limit varies by the target guild's boost level, from
# 10 MB up to 500 MB), surfaced to the admin via the existing discord.HTTPException handler in
# embed_post_create/_update if a given upload turns out to be too big for that specific server.
# The dashboard hint text next to the file field spells this out instead of guessing a number.
# (Referenced below as "the module-level comment above" from _read_embed_image_upload's
# docstring - kept distinct from the unrelated format-mapping comment right underneath.)

# Discord's embed `set_image()` only ever actually RENDERS these four formats - anything else
# (bmp, tiff, ico, ...) Pillow can perfectly well open/verify() as a real, undamaged image, but
# posting it would produce a broken, non-rendering embed image with no error anywhere to explain
# why. Keyed by Pillow's own Image.format string (set by whichever plugin actually decoded the
# file), NOT the filename extension the browser happened to send - a renamed/extension-less file
# must not be trusted to describe its own real content.
_PIL_FORMAT_TO_EXT = {"PNG": "png", "JPEG": "jpg", "GIF": "gif", "WEBP": "webp"}


async def _read_embed_image_upload(image_file):
    """Validates and reads an uploaded embed image (User-requested: "mus das eine bild url
    sein kanst du nicht beides machen eins reinladen und die url" - upload as an alternative
    to pasting a URL). Returns (base64_data, filename) if a real file was provided, or
    (None, None) if the field was empty/no file was chosen - callers treat that the same as
    "no upload happened". Raises ValueError(message) with a dashboard-ready error string on an
    invalid upload (not a real image, or a real image format Discord's embeds don't render -
    see _PIL_FORMAT_TO_EXT above), same pattern as every other validation error in this feature.
    No size check here - see the module-level comment above.
    Deliberately does NOT re-encode the image through Pillow before storing it - only opens it
    to confirm it's a real, undamaged image. Re-encoding would strip an animated GIF down to
    its first frame and flatten PNG transparency, both real losses for something meant to be
    posted as-is to Discord."""
    if not image_file or not getattr(image_file, "filename", ""):
        return None, None
    data = await image_file.read()
    if not data:
        return None, None
    if len(data) > MAX_BILD_UPLOAD:
        raise ValueError(f"Bild zu groß (max. {MAX_BILD_UPLOAD // (1024*1024)} MB)")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        real_format = img.format or ""
    except Exception:
        raise ValueError("Ungültiges Bildformat")
    ext = _PIL_FORMAT_TO_EXT.get(real_format)
    if not ext:
        raise ValueError("Ungültiges Bildformat")
    return base64.b64encode(data).decode("ascii"), f"image.{ext}"


def _embed_post_files(image_data_b64: str, image_filename: str) -> list:
    """Rebuilds the discord.File attachment list from the stored base64 image, if any - called
    fresh on every send/edit rather than trusting Discord to have kept a prior attachment
    around, so switching between an uploaded image / a URL / no image at all always ends up in
    the exact state just saved, deterministically."""
    if not image_data_b64 or not image_filename:
        return []
    try:
        raw = base64.b64decode(image_data_b64)
    except Exception:
        return []
    return [discord.File(io.BytesIO(raw), filename=image_filename)]


# Open Graph / Twitter Card image auto-fetch for poll options ("kannst du aus den link das bild
# raus nehmen automatich" - user explicitly picked automatic-on-save over a manual fetch
# button). A <meta> tag's property/content attributes can appear in either order
# (<meta property="og:image" content="...">  vs  <meta content="..." property="og:image">), so
# _META_TAG_RE first isolates each whole tag and then _OG_PROP_RE/_CONTENT_RE search WITHIN that
# tag's text independently of attribute order, rather than trying to match both in one fixed
# sequence. No HTML-parser dependency added for this - a full DOM isn't needed just to read a
# handful of <head> meta tags.
_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_OG_PROP_RE = re.compile(
    r'(?:property|name)\s*=\s*["\'](og:image(?::secure_url)?|twitter:image(?::src)?)["\']',
    re.IGNORECASE,
)
_CONTENT_RE = re.compile(r'content\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)
_OG_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=8)
# NOT 500 KB as the "meta tags live in <head>" reasoning would suggest - verified live against
# youtube.com, whose og:image tag sits past byte 700,000 (a huge inline state blob comes before
# it in the actual markup) - a smaller cap would silently miss a very common real link target.
# Still bounded rather than unlimited, caps worst-case time/memory for a huge/malicious response.
_OG_FETCH_MAX_BYTES = 2_000_000


def _extract_og_image(html: str, base_url: str) -> str:
    best_og, best_twitter = "", ""
    for tag in _META_TAG_RE.findall(html):
        prop_m = _OG_PROP_RE.search(tag)
        if not prop_m:
            continue
        content_m = _CONTENT_RE.search(tag)
        if not content_m or not content_m.group(1).strip():
            continue
        url = urllib.parse.urljoin(base_url, content_m.group(1).strip())
        prop_name = prop_m.group(1).lower()
        if prop_name.startswith("og:image") and not best_og:
            best_og = url
        elif prop_name.startswith("twitter:image") and not best_twitter:
            best_twitter = url
    return best_og or best_twitter


def _extract_image_candidates(html: str, base_url: str) -> list:
    """Every distinct Open Graph/Twitter Card image URL declared in the page (not just the
    single best guess _extract_og_image makes) - a page can legitimately declare more than one
    (og:image plus a separately-cropped twitter:image, or even multiple og:image tags for a
    gallery), and the automatic best-guess used at save time isn't always the one an admin
    actually wants ("mach mal andere Varianten rein so das mann sich das selber ausuchen kann").
    Kept in document order, deduplicated, capped at a small number - this is a manual picker
    for a human to glance at, not an exhaustive image scrape of the whole page."""
    seen, candidates = [], []
    for tag in _META_TAG_RE.findall(html):
        prop_m = _OG_PROP_RE.search(tag)
        if not prop_m:
            continue
        content_m = _CONTENT_RE.search(tag)
        if not content_m or not content_m.group(1).strip():
            continue
        url = urllib.parse.urljoin(base_url, content_m.group(1).strip())[:500]
        # Anfuehrungszeichen, spitze Klammern und Leerraum gehoeren in keine Bild-Adresse -
        # echte sind an diesen Stellen prozentkodiert. Ungeprueft kaeme so etwas hier durch:
        #   <meta property="og:image" content='https://x/y.png" onerror="...'>
        # Die Adresse beginnt mit https://, besteht die Pruefung unten also, und landete im
        # Dashboard in einem src="..." - ein fremder Server haette damit Code im Browser
        # desjenigen ausgefuehrt, der seinen Link in eine Umfrage einfuegt.
        if any(z in url for z in '"\'<>`\\') or any(z.isspace() for z in url):
            continue
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.append(url)
            candidates.append(url)
        if len(candidates) >= 6:
            break
    return candidates


def _is_public_http_url(url: str) -> bool:
    """Whether this address is safe for the server itself to fetch.

    The poll preview lets anyone with a dashboard login hand the server a URL to open. Without
    this, that URL could just as well be http://127.0.0.1:8080 or a cloud provider's metadata
    service - the server sits inside the network, so it can reach things the person asking
    never could. Reported by an external test, and correct.

    Only http(s) to a name that resolves entirely to public addresses passes. Every name the
    host resolves to is checked, not just the first: a name that answers with one public and
    one loopback address would otherwise slip through on the public one.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    import ipaddress
    import socket as _sock
    try:
        infos = _sock.getaddrinfo(parsed.hostname, parsed.port or
                                  (443 if parsed.scheme == "https" else 80),
                                  proto=_sock.IPPROTO_TCP)
    except Exception:
        # Unresolvable is not reachable either, so refusing costs nothing and keeps this from
        # becoming a way to ask the server what does and does not resolve inside the network.
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


async def _fetch_html_for_og(url: str) -> str:
    """Shared HTTP fetch behind both the single-best-guess auto-save lookup and the live
    preview button's multi-candidate list - one network call either way, never raises, returns
    "" on ANY failure (timeout, connection error, non-HTML response) so a flaky/slow site never
    breaks saving the poll or the preview button, only leaves that option's image empty."""
    # Checked here rather than at each caller, so no future caller can forget it.
    if not await asyncio.get_running_loop().run_in_executor(None, _is_public_http_url, url):
        return ""
    try:
        async with aiohttp.ClientSession(timeout=_OG_FETCH_TIMEOUT) as session:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; PhobosBot/1.0; +poll-preview)"}
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return ""
                if "html" not in resp.headers.get("Content-Type", "").lower():
                    return ""
                chunks, total = [], 0
                async for chunk in resp.content.iter_chunked(8192):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= _OG_FETCH_MAX_BYTES:
                        break
                return b"".join(chunks).decode("utf-8", errors="ignore")
    except Exception:
        return ""


async def _fetch_og_image(url: str) -> str:
    """Best-effort single-best-guess image for a poll option's link, used automatically on
    save when the option has a link but no image of its own."""
    html = await _fetch_html_for_og(url)
    if not html:
        return ""
    image_url = _extract_og_image(html, url)
    if image_url and image_url.startswith(("http://", "https://")):
        return image_url[:500]
    return ""


async def _fetch_og_image_candidates(url: str) -> list:
    """Every candidate image for the live "🔍" preview button's picker - see
    _extract_image_candidates for why this can return more than one."""
    html = await _fetch_html_for_og(url)
    if not html:
        return []
    return _extract_image_candidates(html, url)


async def _resolve_poll_option_image(
    image_url: str, has_upload: bool, upload_data: str, upload_filename: str,
    link_url: str, remove_checked: bool, existing_row,
) -> tuple:
    """Single source of truth for what a poll option's image ends up being, shared by
    poll_create_web (always existing_row=None, remove_checked=False) and poll_edit_web - so the
    two routes can never drift on this precedence. Mirrors embed_post_update's established
    "blank field on a normal re-submit means unchanged, not removed" convention (a file input
    can never be pre-filled, so an empty upload field must not be read as removal either) with
    ONE new case added: an option that has no image at all yet but does have a link gets an
    auto-fetch attempt. Returns (image_url, image_data_b64, image_filename)."""
    if remove_checked:
        return "", "", ""
    if has_upload:
        return "", upload_data or "", upload_filename or ""
    if image_url:
        return image_url, "", ""
    if existing_row and (existing_row.get("image_data") or existing_row.get("image_url")):
        return (
            existing_row.get("image_url") or "",
            existing_row.get("image_data") or "",
            existing_row.get("image_filename") or "",
        )
    if link_url:
        fetched = await _fetch_og_image(link_url)
        return fetched, "", ""
    return "", "", ""


def _clamp_poll_image_width(raw_width: str) -> int:
    """Sanitizes the submitted custom-width field to a safe pixel range (50-2000) - defends
    against a manipulated raw POST as much as it validates real input; a value outside this
    range is silently clamped rather than rejecting the whole save, since it's a minor cosmetic
    knob, not something worth failing the entire poll save over."""
    try:
        w = int(raw_width)
    except (TypeError, ValueError):
        return 0
    if w <= 0:
        return 0
    return max(50, min(2000, w))


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clamp_poll_bar_color(raw_color: str) -> str:
    """Sanitizes the poll bar-color picker's submitted value - a real <input type="color"> always
    submits a strict lowercase #rrggbb per the HTML5 spec, so this is mainly defense against a
    manipulated raw POST rather than something a normal browser submission would ever trip."""
    if raw_color and _HEX_COLOR_RE.match(raw_color):
        return raw_color
    return _DEFAULT_BAR_COLOR


_POLL_IMAGE_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=8)
_POLL_IMAGE_FETCH_MAX_BYTES = 8_000_000


async def _fetch_image_bytes(url: str) -> bytes:
    """Downloads a poll option's image so it can be resized (see _resize_image_bytes) instead
    of just referencing the external URL directly - only needed for the 'custom' width size
    mode, where the whole point is that Discord must receive an already-correctly-sized
    attachment rather than the original, whatever-size image. Never raises: any failure
    (timeout, non-200, non-image response, oversized body) yields b"", and the caller falls
    back to leaving the image as a plain URL at its original size rather than losing it."""
    try:
        async with aiohttp.ClientSession(timeout=_POLL_IMAGE_FETCH_TIMEOUT) as session:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; PhobosBot/1.0; +poll-image)"}
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return b""
                chunks, total = [], 0
                async for chunk in resp.content.iter_chunked(8192):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > _POLL_IMAGE_FETCH_MAX_BYTES:
                        return b""
                return b"".join(chunks)
    except Exception:
        return b""


def _resize_image_bytes(data: bytes, target_width: int) -> tuple:
    """Resizes raw image bytes to exactly target_width pixels wide (aspect ratio preserved,
    LANCZOS resampling) and re-encodes as PNG - the actual mechanism behind the 'custom' poll
    option image size: Discord renders an attached image at its real pixel dimensions (not
    stretched to fill the embed), so shrinking the file itself is the only way to get a size
    between the fixed ~80px thumbnail and the full-width large image. Keeps RGBA if the source
    has transparency, RGB otherwise. Returns (resized_bytes, "") on success, ("", error) on
    failure (not a real image, corrupt data) - caller decides the fallback, same "return instead
    of raise" convention as the rest of this file's image helpers.
    Deliberately does NOT try to preserve GIF animation - a resized frame is always a static
    PNG, an acceptable trade-off for a feature whose whole point is an exact pixel size."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    except Exception:
        return "", "Ungültiges Bildformat"
    if img.width <= 0:
        return "", "Ungültiges Bildformat"
    target_height = max(1, round(img.height * (target_width / img.width)))
    img = img.resize((target_width, target_height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), ""


async def _apply_poll_option_custom_width(image_url: str, image_data_b64: str, image_filename: str,
                                            target_width: int, index: int) -> tuple:
    """Second pass after _resolve_poll_option_image(): if a target width was given, turns
    whatever image the option ended up with (an uploaded/kept attachment, or a plain URL -
    typed, auto-fetched, or picked from the link preview gallery) into a resized attachment at
    exactly that width, since Discord can only render an image at an arbitrary size via a real
    attachment's actual pixel dimensions, never via a URL alone. Used to be gated behind a
    'large'/'small'/'custom' size picker - removed on explicit request ("ich wil die gröse nur
    nuch mit px machen nix andeeres") once cogs/polls.py stopped needing that distinction for
    where the poll's progress bar goes (build_poll_embed() now only cares whether an option HAS
    an image at all, not what size it is) - a width of 0 (nothing entered) just means "leave
    the image at whatever size it already is", same effective behavior as the old 'large' mode.
    A download/resize failure falls back to the image exactly as _resolve_poll_option_image left
    it (still a working URL or attachment, just not resized) rather than losing the image
    entirely - same "never let an image feature break the rest of saving" principle as
    _fetch_og_image returning "" on failure instead of raising."""
    if target_width <= 0:
        return image_url, image_data_b64, image_filename
    if image_data_b64:
        try:
            raw = base64.b64decode(image_data_b64)
        except Exception:
            return image_url, image_data_b64, image_filename
    elif image_url:
        raw = await _fetch_image_bytes(image_url)
        if not raw:
            return image_url, image_data_b64, image_filename
    else:
        return image_url, image_data_b64, image_filename
    resized, err = _resize_image_bytes(raw, target_width)
    if err:
        return image_url, image_data_b64, image_filename
    return "", base64.b64encode(resized).decode("ascii"), f"opt{index}_custom.png"


async def _read_welcome_bg_upload(upload_file, max_dim: int = 1600) -> str | None:
    """Validates and reads an uploaded welcome-card background image. Unlike
    _read_embed_image_upload above, this ALWAYS re-encodes to PNG and downscales if needed -
    the upload here is only ever used as compositing input for a freshly-generated 800x280 card
    image on every future join, never forwarded to Discord in its original form, so there's no
    reason to preserve animation/original resolution and every reason to keep the stored value
    small (it lives in guild_configs as base64 TEXT, dumped wholesale into every backup export).
    Returns a base64 PNG string, or None if no file was submitted (the "leave the existing value
    untouched" case - same convention as the SMTP password field and the embed image feature).
    Raises ValueError(message) on an invalid upload, same pattern as _read_embed_image_upload."""
    if not upload_file or not getattr(upload_file, "filename", ""):
        return None
    data = await upload_file.read()
    if not data:
        return None
    if len(data) > MAX_BILD_UPLOAD:
        raise ValueError(f"Bild+zu+groß+(max.+{MAX_BILD_UPLOAD // (1024*1024)}+MB)")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGB")
    except Exception:
        raise ValueError("Ungültiges+Bildformat")
    if img.width > max_dim or img.height > max_dim:
        scale = max_dim / max(img.width, img.height)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def _read_welcome_overlay_upload(upload_file, max_dim: int = 1600) -> str | None:
    """Validates and reads an uploaded welcome-card OVERLAY image - a separate function from
    _read_welcome_bg_upload() above rather than a shared one with a flag, same "different
    requirements deserve their own clearly-named function" precedent that already separates
    _read_embed_image_upload() from _read_welcome_bg_upload(). The one thing that actually
    differs: this converts to RGBA, not RGB, so the overlay keeps its transparency - the whole
    point of an overlay (e.g. a "shattered glass" crack texture) is to sit on top of the
    finished card with see-through areas, which _read_welcome_bg_upload's RGB conversion would
    destroy. Same downscale-to-1600px-max and base64 PNG return convention otherwise."""
    if not upload_file or not getattr(upload_file, "filename", ""):
        return None
    data = await upload_file.read()
    if not data:
        return None
    if len(data) > MAX_BILD_UPLOAD:
        raise ValueError(f"Bild+zu+groß+(max.+{MAX_BILD_UPLOAD // (1024*1024)}+MB)")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGBA")
    except Exception:
        raise ValueError("Ungültiges+Bildformat")
    if img.width > max_dim or img.height > max_dim:
        scale = max_dim / max(img.width, img.height)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _embed_channel_is_valid(guild, channel_id: str) -> bool:
    """Whether channel_id is a real text channel OR forum channel of this guild - the two
    target types Embed-Nachrichten supports posting to."""
    return channel_id in {str(c.id) for c in guild.text_channels} | {str(c.id) for c in guild.forums}


def _resolve_forum_tags(forum, tag_ids: list) -> list:
    """Looks up the actual discord.ForumTag objects a forum post should carry, from the ids
    submitted by the dashboard form - create_thread()/Thread.edit() both want real ForumTag
    objects, not bare ids. Silently drops any id that no longer matches one of the forum's
    currently available tags (e.g. an admin deleted that tag in Discord after this post was
    last saved) rather than erroring - same "don't fail on stale references" spirit as the
    rest of this feature."""
    wanted = set(tag_ids)
    return [t for t in forum.available_tags if str(t.id) in wanted]


async def _post_embed_content(channel, name: str, embeds: list, files: list, applied_tags: list | None = None):
    """Sends embed content to a target that's either a normal text channel (plain
    channel.send) or a forum channel. A forum has no "send a message" concept - posting there
    always means creating a new thread ("post"), which requires a title (Discord's own forum
    thread name limit is 100 chars, matching the name field's existing max length here, so no
    separate truncation surprises the admin) and, if the forum is configured to require one,
    at least one tag (ForumChannel.flags.require_tag - callers validate this before calling
    here, since it needs a dashboard-friendly error message rather than a raw Discord
    rejection). Returns (message_id, thread_id) as strings - thread_id is '' for a text
    channel. Raises discord.HTTPException on failure exactly like channel.send() would, so
    every existing caller's error handling keeps working unchanged."""
    if isinstance(channel, discord.ForumChannel):
        result = await channel.create_thread(
            name=name[:100], embeds=embeds, files=files, applied_tags=applied_tags or [],
        )
        return str(result.message.id), str(result.thread.id)
    msg = await channel.send(embeds=embeds, files=files)
    return str(msg.id), ""


async def _fetch_embed_thread(guild, thread_id: int):
    """Resolves a forum post's thread, trying the guild's cache first and falling back to a
    live fetch (archived threads in particular tend to fall out of cache) - raises
    discord.NotFound if the thread is genuinely gone, same as fetch_message() would for a
    regular message, so callers can keep using one shared except-branch for both post types."""
    thread = guild.get_thread(thread_id)
    if thread is not None:
        return thread
    return await guild.fetch_channel(thread_id)


async def _fetch_embed_starter_message(thread):
    """A forum post's editable content lives on its thread's starter message, not on the
    thread object itself (Thread.edit() only touches thread metadata like name/archived/locked,
    never content/embeds/attachments) - starter_message is cache-dependent, fetching by the
    thread's own id (a forum thread's id IS its starter message's id in Discord's data model)
    is the reliable fallback."""
    return thread.starter_message or await thread.fetch_message(thread.id)


def _discord_error_text(e: Exception) -> str:
    """Human-readable text for an exception raised by a Discord send/edit call - discord.py's
    HTTPException carries the actual API error message on .text, but a genuine network-level
    failure (DNS/connection-reset/refused) surfaces as a bare OSError instead: confirmed by
    reading discord.py 2.3.2's own http.py, whose request() retry loop only retries a caught
    OSError on macOS/Windows-specific errno codes (54/10054) and re-raises it unwrapped
    otherwise - on Linux (this project's actual runtime) that's every realistic connection
    failure. OSError has no .text attribute, so building the message via e.text unconditionally
    would itself raise AttributeError for that case - str(e) covers it instead."""
    return getattr(e, "text", None) or str(e)


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
    image_file = form.get("image_file")
    has_upload = bool(image_file and getattr(image_file, "filename", ""))
    if not name:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Name+erforderlich", status_code=302)
    if len(name) > 100:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Name+zu+lang+(max.+100+Zeichen)", status_code=302)
    if not _embed_channel_is_valid(guild, channel_id):
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
    if image_url and has_upload:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Bitte+nur+Bild-URL+ODER+Datei+hochladen,+nicht+beides", status_code=302)
    if image_url and not image_url.startswith(("http://", "https://")):
        # Discord's API rejects a non-URL image value outright - caught here with a clear
        # cause instead of a raw "Discord-Fehler:" surfacing the API's own wording.
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Bild-URL+muss+mit+http(s)://+beginnen", status_code=302)
    if len(footer_text) > 2048:
        # Discord's own hard limit for embed footer text.
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Footer-Text+zu+lang+(max.+2048+Zeichen)", status_code=302)
    try:
        image_data_b64, image_filename = await _read_embed_image_upload(image_file)
    except ValueError as msg:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error={urllib.parse.quote(str(msg))}", status_code=302)
    channel = guild.get_channel(int(channel_id))
    if not channel:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Kanal+nicht+gefunden", status_code=302)
    is_forum = isinstance(channel, discord.ForumChannel)
    tag_ids = form.getlist("tag_ids") if is_forum else []
    applied_tags = _resolve_forum_tags(channel, tag_ids) if is_forum else []
    if is_forum and channel.flags.require_tag and not applied_tags:
        # Caught here with a clear cause instead of letting create_thread() fail with a raw
        # Discord rejection - found live ("der sagt das der tag fehlt ich kan keinen
        # eintragen"): this forum requires at least one tag on every new post.
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Dieses+Forum+erfordert+mindestens+einen+Tag", status_code=302)
    if is_forum and len(applied_tags) > 5:
        # Same "catch it here with a clear cause" spirit as the require_tag check just above,
        # for the OTHER end of the same limit - discord.py's own Thread.edit() docstring states
        # it outright ("There can only be up to 5 tags applied to a thread") but never actually
        # enforces it client-side, so selecting more than 5 from a forum that happens to offer
        # more than 5 tags would otherwise only surface as a raw, confusing Discord API
        # rejection at create_thread() time instead of a clear dashboard message.
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Maximal+5+Tags+pro+Forum-Beitrag+erlaubt", status_code=302)
    content = _djson.dumps(blocks)
    embeds = _build_freeform_embeds(content, image_url, footer_text, image_filename or "")
    files = _embed_post_files(image_data_b64 or "", image_filename or "")
    try:
        new_message_id, new_thread_id = await _post_embed_content(channel, name, embeds, files, applied_tags)
    except (discord.HTTPException, OSError) as e:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Discord-Fehler:+{urllib.parse.quote(_discord_error_text(e))}", status_code=302)
    await db_exec(
        "INSERT INTO embed_posts (guild_id, name, channel_id, content, message_id, image_url, footer_text, image_data, image_filename, thread_id, applied_tags) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (str(guild_id), name, channel_id, content, new_message_id, image_url, footer_text,
         image_data_b64 or "", image_filename or "", new_thread_id, ",".join(str(t.id) for t in applied_tags)),
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
    image_file = form.get("image_file")
    has_upload = bool(image_file and getattr(image_file, "filename", ""))
    remove_image = form.get("remove_image") == "1"
    if not name:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Name+erforderlich", status_code=302)
    if len(name) > 100:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Name+zu+lang+(max.+100+Zeichen)", status_code=302)
    if not _embed_channel_is_valid(guild, channel_id):
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
    if image_url and has_upload:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Bitte+nur+Bild-URL+ODER+Datei+hochladen,+nicht+beides", status_code=302)
    # Unlike the file input, the URL field IS pre-filled with the post's current image_url - so
    # a "remove_image" checkbox submitted alongside that SAME unchanged value just means the
    # admin ticked the box without also touching the URL text (the far more common case, since
    # there's no reason to manually clear a field you're already asking to remove) and
    # remove_image should win exactly as before. Only a genuinely NEW/different URL typed in
    # alongside it is an actual conflict worth rejecting - same "reject an ambiguous combo
    # instead of silently picking one" spirit as the check just above, which would otherwise
    # have that new image silently discarded by remove_image with no indication why.
    if remove_image and (has_upload or (image_url and image_url != (post.get("image_url") or ""))):
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Entweder+Bild+entfernen+ODER+ein+neues+Bild+angeben,+nicht+beides", status_code=302)
    if image_url and not image_url.startswith(("http://", "https://")):
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Bild-URL+muss+mit+http(s)://+beginnen", status_code=302)
    if len(footer_text) > 2048:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Footer-Text+zu+lang+(max.+2048+Zeichen)", status_code=302)
    target_channel = guild.get_channel(int(channel_id))
    if not target_channel:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Kanal+nicht+gefunden", status_code=302)
    is_forum = isinstance(target_channel, discord.ForumChannel)
    tag_ids = form.getlist("tag_ids") if is_forum else []
    applied_tags = _resolve_forum_tags(target_channel, tag_ids) if is_forum else []
    if is_forum and target_channel.flags.require_tag and not applied_tags:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Dieses+Forum+erfordert+mindestens+einen+Tag", status_code=302)
    if is_forum and len(applied_tags) > 5:
        # Same as the identical check in embed_post_create - see the comment there.
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Maximal+5+Tags+pro+Forum-Beitrag+erlaubt", status_code=302)
    try:
        new_image_data_b64, new_image_filename = await _read_embed_image_upload(image_file)
    except ValueError as msg:
        return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error={urllib.parse.quote(str(msg))}", status_code=302)
    # A file input can never be pre-filled with "the image already on this post" (browsers
    # don't allow that, for security reasons) - so an empty file field on a normal re-submit
    # must NOT be read as "remove the image", or every text-only edit would silently wipe out
    # a previously uploaded image. Same "leave blank to keep the existing value" convention
    # already used for e.g. the SMTP password field. Removal instead needs the explicit
    # "🗑 Bild entfernen" checkbox (edit form only, nothing to remove yet when creating).
    if remove_image:
        final_image_url, final_image_data, final_image_filename = "", "", ""
    elif has_upload:
        final_image_url, final_image_data, final_image_filename = "", new_image_data_b64 or "", new_image_filename or ""
    elif image_url:
        final_image_url, final_image_data, final_image_filename = image_url, "", ""
    else:
        final_image_url = post.get("image_url") or ""
        final_image_data = post.get("image_data") or ""
        final_image_filename = post.get("image_filename") or ""
    content = _djson.dumps(blocks)
    embeds = _build_freeform_embeds(content, final_image_url, footer_text, final_image_filename)
    files = _embed_post_files(final_image_data, final_image_filename)
    new_message_id = post["message_id"]
    new_thread_id = post.get("thread_id") or ""
    if channel_id != post["channel_id"]:
        # Moved to a different channel/forum - an embed post lives on a specific message (or,
        # for a forum, a specific thread) in a specific channel, there's no "move to another
        # channel" API for either, so this deletes the old one (best-effort, it may already be
        # gone) and posts fresh in the new target instead.
        old_ch = guild.get_channel(int(post["channel_id"])) if post["channel_id"] else None
        try:
            if post.get("thread_id"):
                old_thread = await _fetch_embed_thread(guild, int(post["thread_id"]))
                await old_thread.delete()
            elif old_ch and post["message_id"]:
                old_msg = await old_ch.fetch_message(int(post["message_id"]))
                await old_msg.delete()
        except Exception:
            pass
        new_ch = target_channel
        try:
            new_message_id, new_thread_id = await _post_embed_content(new_ch, name, embeds, files, applied_tags)
        except (discord.HTTPException, OSError) as e:
            return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Discord-Fehler:+{urllib.parse.quote(_discord_error_text(e))}", status_code=302)
    else:
        ch = target_channel
        if post.get("thread_id"):
            try:
                thread = await _fetch_embed_thread(guild, int(post["thread_id"]))
                starter = await _fetch_embed_starter_message(thread)
                await starter.edit(embeds=embeds, attachments=files)
                # The forum post's title is the thread's own name, and its applied tags are
                # also thread-level metadata - both separate from the message content, kept in
                # sync with what the admin just edited here. Requires "Manage Threads", same
                # permission the bot already needs to have created the thread in the first
                # place. Tags always passed explicitly (even as []) for the same reason
                # attachments are - otherwise a removed tag would just silently stick around.
                thread_updates = {}
                if thread.name != name[:100]:
                    thread_updates["name"] = name[:100]
                if {t.id for t in thread.applied_tags} != {t.id for t in applied_tags}:
                    thread_updates["applied_tags"] = applied_tags
                if thread_updates:
                    await thread.edit(**thread_updates)
            except discord.NotFound:
                # The thread or its starter message was deleted directly in Discord - repost a
                # fresh thread instead of silently leaving the saved content with nothing live.
                try:
                    new_message_id, new_thread_id = await _post_embed_content(ch, name, embeds, files, applied_tags)
                except (discord.HTTPException, OSError) as e:
                    return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Discord-Fehler:+{urllib.parse.quote(_discord_error_text(e))}", status_code=302)
            except Exception as e:
                return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Discord-Fehler:+{urllib.parse.quote(str(e))}", status_code=302)
        elif post["message_id"]:
            try:
                msg = await ch.fetch_message(int(post["message_id"]))
                # attachments is always passed explicitly (even as []) rather than left out -
                # otherwise Discord would keep whatever attachment the message already had,
                # which breaks the moment an admin switches away from an uploaded image (to a
                # URL, or removes it) since the stale attachment would just sit there unused.
                await msg.edit(embeds=embeds, attachments=files)
            except discord.NotFound:
                # The live message was deleted directly in Discord - repost it fresh instead of
                # silently leaving the saved content with no actual message behind it.
                try:
                    new_message_id, new_thread_id = await _post_embed_content(ch, name, embeds, files, applied_tags)
                except (discord.HTTPException, OSError) as e:
                    return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Discord-Fehler:+{urllib.parse.quote(_discord_error_text(e))}", status_code=302)
            except Exception as e:
                return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Discord-Fehler:+{urllib.parse.quote(str(e))}", status_code=302)
        else:
            # No live message/thread yet - e.g. a post restored from a backup (message_id/
            # thread_id are never trusted across a restore, same as ticket_panels). Post it
            # fresh instead of silently saving the new content with nothing live behind it.
            try:
                new_message_id, new_thread_id = await _post_embed_content(ch, name, embeds, files, applied_tags)
            except (discord.HTTPException, OSError) as e:
                return RedirectResponse(f"/servers/{guild_id}?tab=embeds&error=Discord-Fehler:+{urllib.parse.quote(_discord_error_text(e))}", status_code=302)
    await db_exec(
        "UPDATE embed_posts SET name=?, channel_id=?, content=?, message_id=?, image_url=?, footer_text=?, image_data=?, image_filename=?, thread_id=?, applied_tags=? "
        "WHERE id=? AND guild_id=?",
        (name, channel_id, content, new_message_id, final_image_url, footer_text,
         final_image_data, final_image_filename, new_thread_id,
         ",".join(str(t.id) for t in applied_tags), post_id, guild_id),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=embeds&success=Gespeichert", status_code=302)


@web.post("/servers/{guild_id}/embeds/{post_id}/delete")
async def embed_post_delete(request: Request, guild_id: int, post_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    post = await db_one("SELECT * FROM embed_posts WHERE id=? AND guild_id=?", (post_id, guild_id))
    if post:
        try:
            guild = bot.get_guild(guild_id)
            if guild and post.get("thread_id"):
                # A forum post's live content IS the thread - deleting just the starter message
                # isn't a thing Discord distinguishes from deleting the whole thread anyway, so
                # go straight for the thread itself.
                thread = await _fetch_embed_thread(guild, int(post["thread_id"]))
                await thread.delete()
            elif guild and post.get("message_id") and post.get("channel_id"):
                ch = guild.get_channel(int(post["channel_id"]))
                if ch:
                    msg = await ch.fetch_message(int(post["message_id"]))
                    await msg.delete()
        except Exception:
            pass
    await db_exec("DELETE FROM embed_posts WHERE id=? AND guild_id=?", (post_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=embeds&success=Gelöscht", status_code=302)


_EMBED_IMAGE_MEDIA_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp",
}


@web.get("/servers/{guild_id}/embeds/{post_id}/image")
async def embed_post_image(request: Request, guild_id: int, post_id: int):
    """Serves an uploaded embed image for the dashboard's OWN edit-form preview only - never
    used as the actual Discord embed URL (that goes via a real message attachment instead, see
    _embed_post_files()). Same auth/guild-access gate as every other route here, so this never
    needs to be reachable from outside the dashboard."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    post = await db_one(
        "SELECT image_data, image_filename FROM embed_posts WHERE id=? AND guild_id=?",
        (post_id, guild_id),
    )
    if not post or not post.get("image_data"):
        raise HTTPException(status_code=404)
    try:
        raw = base64.b64decode(post["image_data"])
    except Exception:
        raise HTTPException(status_code=404)
    ext = (post.get("image_filename") or "").rsplit(".", 1)[-1].lower()
    media_type = _EMBED_IMAGE_MEDIA_TYPES.get(ext, "application/octet-stream")
    return Response(content=raw, media_type=media_type)


@web.get("/servers/{guild_id}/welcome-card/bg-image")
async def welcome_card_bg_image(request: Request, guild_id: int):
    """Serves the stored welcome-card background image for the dashboard's own preview <img> -
    same admin-preview-only pattern as embed_post_image() above, never used as anything Discord
    itself sees (the background is composited server-side into the generated card PNG)."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    bg_b64 = await get_guild_config(guild_id, "welcome_card_bg_image")
    if not bg_b64:
        raise HTTPException(status_code=404)
    try:
        raw = base64.b64decode(bg_b64)
    except Exception:
        raise HTTPException(status_code=404)
    return Response(content=raw, media_type="image/png")


# Built-in overlay presets shipped with the bot itself (app/assets/), so admins have something
# to pick from a menu instead of needing to source their own transparent overlay image first -
# user request: "am besten mach da im bot ein menü teil dafür für vorgefertigte sachen wo die
# leute sich da was einfach auswählen können". Keyed by a short, fixed id (never taken from
# request input) so the serving/apply routes below can validate against this dict instead of
# trusting an arbitrary filename - adding a future preset is just one more dict entry plus its
# image file, nothing else needs to change. The one shipped preset was provided by the user for
# this exact purpose (confirmed they hold the rights to redistribute it here).
_ASSETS_DIR = Path(__file__).parent / "assets"
_WELCOME_OVERLAY_PRESETS = {
    "shattered_glass": {"label": "Zersprungenes Glas", "file": "welcome_card_overlay_example.png"},
    "hearts": {"label": "Herzen", "file": "welcome_card_overlay_hearts.png"},
    "pub": {"label": "Kneipe", "file": "welcome_card_overlay_pub.png"},
    "tropical": {"label": "Sommer/Tropisch", "file": "welcome_card_overlay_tropical.png"},
}


async def _resolve_welcome_overlay_choice(choice: str):
    """Resolves the welcome_card_overlay_choice <select> value - shared by server_config_save()
    (actually saving it) and welcome_card_preview() (showing it live before saving) so both stay
    in sync automatically. Returns (explicit, image_b64, preset_marker):
    - choice == "none" -> (True, "", "") - the admin explicitly chose "no overlay".
    - choice is a known preset id -> (True, <base64 PNG>, choice) - reads the bundled file
      (already pre-processed at <=1600px RGBA, see the asset's own generation), no need to run
      it back through _read_welcome_overlay_upload().
    - choice is empty/unrecognized (the placeholder option, or nothing submitted) -> (False,
      None, None) - "no explicit choice was made this submission", caller should fall through to
      whatever else already determines the overlay (a freshly uploaded file, or the guild's
      currently saved value) rather than overwriting it."""
    if choice == "none":
        return True, "", ""
    preset = _WELCOME_OVERLAY_PRESETS.get(choice)
    if preset:
        try:
            raw = (_ASSETS_DIR / preset["file"]).read_bytes()
        except OSError:
            return True, "", ""  # bundled file missing somehow - fail safe to "no overlay"
        return True, base64.b64encode(raw).decode("ascii"), choice
    return False, None, None


class _PreviewAvatar:
    """Stands in for discord.Member.display_avatar - only the one call _make_card() actually
    makes (.replace(format=, size=) then str(...)) needs to work, always resolving to Discord's
    own public default-avatar CDN asset. No real member lookup, no privacy question."""
    def replace(self, format=None, size=None):
        return self

    def __str__(self):
        return "https://cdn.discordapp.com/embed/avatars/0.png"


class _PreviewMember:
    """A minimal stand-in for discord.Member, used only by welcome_card_preview() below so the
    dashboard's live preview can call the exact same _make_card()/fill() the bot uses for a real
    join, without an actual member ever joining. Exposes only the handful of attributes those
    two functions touch - display_avatar/display_name for the card itself, guild.member_count
    so the default "Mitglied #X" subtitle looks realistic even before anything is typed in. No
    .mention attribute - the preview always calls fill(..., plain_mention=True) since card text
    never uses a real Discord mention (see fill()'s own docstring), so nothing here ever reads
    .mention in the first place."""
    def __init__(self, guild):
        self.display_name = "Preview User"
        self.guild = guild
        self.display_avatar = _PreviewAvatar()

    def __str__(self):
        return "Preview User"


@web.post("/servers/{guild_id}/welcome-card/preview")
async def welcome_card_preview(request: Request, guild_id: int):
    """Live preview for the welcome card - renders whatever is CURRENTLY in the dashboard form
    (not yet saved) using the exact same _make_card() the bot calls on a real join, so the
    preview can never visually drift from the real thing. Pure read/render, no guild_configs
    write - safe to call on every debounced keystroke from the frontend."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404)
    form = await request.form()

    # Mirrors server_config_save()'s background-image precedence exactly, just without writing
    # anything: a file picked in THIS request wins, then an explicit removal checkbox, else
    # whatever is already saved for this guild. An invalid upload falls back silently instead of
    # erroring - a live preview shouldn't interrupt someone mid-edit with a failed request.
    try:
        new_bg = await _read_welcome_bg_upload(form.get("welcome_card_bg_image"))
    except ValueError:
        new_bg = None
    if form.get("remove_welcome_card_bg"):
        bg_image_b64 = None
    elif new_bg is not None:
        bg_image_b64 = new_bg
    else:
        bg_image_b64 = await get_guild_config(guild_id, "welcome_card_bg_image")

    # Same precedence for the overlay image, extended with the preset dropdown: a freshly
    # uploaded file wins, then an explicit dropdown choice (see _resolve_welcome_overlay_choice),
    # else whatever is already saved for this guild.
    try:
        new_overlay = await _read_welcome_overlay_upload(form.get("welcome_card_overlay_image"))
    except ValueError:
        new_overlay = None
    if new_overlay is not None:
        overlay_image_b64 = new_overlay
    else:
        explicit, choice_image_b64, _marker = await _resolve_welcome_overlay_choice(
            str(form.get("welcome_card_overlay_choice", ""))
        )
        if explicit:
            overlay_image_b64 = choice_image_b64
        else:
            overlay_image_b64 = await get_guild_config(guild_id, "welcome_card_overlay_image")

    member = _PreviewMember(guild)
    heading_raw = str(form.get("welcome_card_heading_text", ""))
    subtitle_raw = str(form.get("welcome_card_subtitle_text", ""))
    heading_text = _welcome_fill(heading_raw, member, plain_mention=True) if heading_raw else None
    subtitle_text = _welcome_fill(subtitle_raw, member, plain_mention=True) if subtitle_raw else None

    try:
        buf = await _welcome_make_card(
            member,
            str(form.get("welcome_card_circle_color") or "#5865F2"),
            str(form.get("welcome_card_text_color") or "#FFFFFF"),
            str(form.get("welcome_card_username_color") or "#FFDA85"),
            bg_image_b64=bg_image_b64,
            heading_text=heading_text,
            subtitle_text=subtitle_text,
            avatar_shape=str(form.get("welcome_card_avatar_shape") or ""),
            avatar_position=str(form.get("welcome_card_avatar_position") or ""),
            overlay_image_b64=overlay_image_b64,
        )
    except Exception:
        raise HTTPException(status_code=500)
    return Response(content=buf.getvalue(), media_type="image/png")


# ── Role Rules ──────────────────────────────────────────────────────────────
# "IF a member has/lacks certain roles, THEN add/remove roles", live-evaluated by
# cogs/role_rules.py. An action can target a different guild for cross-server sync, but only
# one served by the SAME bot token as the source guild - see _role_rule_target_guilds() and the
# module docstring of cogs/role_rules.py for why that's the only reachable case at evaluation
# time, and why the dropdown below therefore never offers anything else in the first place.

async def _role_rule_target_guilds(request: Request, guild_id: int) -> list:
    guild_bot = bot._bot_for_guild(guild_id)
    if not guild_bot:
        return []
    same_token_ids = {g.id for g in guild_bot.guilds}
    return [g for g in await _guild_list(request) if int(g["id"]) in same_token_ids]


# Upper bound on action blocks per rule - purely a guard against a replayed/hand-crafted
# request submitting thousands of action_idx values, each costing a guild+role validation pass.
# Far above anything the "+ UND.." button is realistically used for.
MAX_RULE_ACTIONS = 25


def _role_rule_match_type_valid(v: str) -> bool:
    return v in ("any", "all", "none")


async def _role_rule_form_data(request: Request, guild: discord.Guild, form) -> tuple[dict | None, str | None]:
    """Shared validation for role-rules/add and .../edit - returns (row_dict, None) on success
    or (None, error_message) on the first validation failure, same "fail with a clear message
    instead of a silent fallback" convention as level_role_add."""
    name = form.get("name", "").strip()[:100]
    match_type = form.get("match_type", "any")
    if not _role_rule_match_type_valid(match_type):
        return None, "Ungültige+Bedingung"
    valid_role_ids = {str(ro.id) for ro in guild.roles if not ro.is_default()}
    # dict.fromkeys(...) dedupes while keeping first-seen order - a normal checkbox list can
    # never submit the same value twice on its own, but a hand-crafted/replayed request could,
    # and without this a duplicate id lands in the stored comma-list verbatim: harmless for
    # _matches()'s own set-based evaluation (which dedupes implicitly), but the dashboard's
    # read-only summary row builds its role-name list from a plain list comprehension over the
    # same string, so a stored "500,500" visibly renders as "@Member, @Member" twice.
    match_role_ids = list(dict.fromkeys(r for r in form.getlist("match_role_ids") if r in valid_role_ids))
    if not match_role_ids:
        return None, "Mindestens+eine+Bedingungs-Rolle+erforderlich"
    # One rule carries a LIST of action blocks ("gib Rolle A" UND "nimm Rolle B"), each with
    # its own action, target server and roles - the form submits one hidden action_idx per
    # block plus that block's own suffixed fields, so a block deleted in the browser simply
    # stops submitting anything and needs no separate bookkeeping.
    allowed_targets = {g["id"] for g in await _role_rule_target_guilds(request, guild.id)}
    block_indices = list(dict.fromkeys(form.getlist("action_idx")))
    if not block_indices:
        return None, "Mindestens+eine+Aktion+erforderlich"
    if len(block_indices) > MAX_RULE_ACTIONS:
        # Rejected, not silently truncated: quietly dropping the blocks past the limit would
        # save a rule that does LESS than what the form showed, and the redirect would still
        # say "saved" - the one outcome an admin has no way to notice.
        return None, f"Höchstens+{MAX_RULE_ACTIONS}+Aktionen+pro+Regel"
    actions = []
    for idx in block_indices:
        action = form.get(f"action_{idx}", "add")
        if action not in ("add", "remove"):
            return None, "Ungültige+Aktion"
        action_guild_id = form.get(f"action_guild_id_{idx}", "")
        if action_guild_id not in allowed_targets:
            return None, "Ungültiger+Zielserver"
        target_guild = bot.get_guild(int(action_guild_id))
        if not target_guild:
            return None, "Zielserver+nicht+gefunden"
        valid_action_role_ids = {str(ro.id) for ro in target_guild.roles if not ro.is_default()}
        action_role_ids = list(dict.fromkeys(
            r for r in form.getlist(f"action_role_ids_{idx}") if r in valid_action_role_ids))
        if not action_role_ids:
            return None, "Mindestens+eine+Aktions-Rolle+je+Aktion+erforderlich"
        # Snapshot of what each picked role looks like RIGHT NOW, so cogs/role_rules.py can
        # recreate it on the target guild if it gets deleted later (a bare id resolves to
        # nothing once the role is gone - no name to recreate it under). Taken here rather than
        # in the cog because this is the only moment the role is guaranteed to still exist: the
        # ids above were just validated against target_guild.roles. Refreshed on every save, so
        # renaming a role in Discord and re-saving the rule updates the snapshot too.
        _t_roles = {str(ro.id): ro for ro in target_guild.roles}
        actions.append({
            "action": action,
            "guild_id": action_guild_id,
            "role_ids": action_role_ids,
            "meta": {
                rid: {
                    "name": _t_roles[rid].name,
                    "color": _t_roles[rid].colour.value,
                    "hoist": _t_roles[rid].hoist,
                    "mentionable": _t_roles[rid].mentionable,
                }
                for rid in action_role_ids if rid in _t_roles
            },
        })
    # The legacy single-action columns mirror the FIRST block - see database.py's migration
    # note for why they are kept written rather than retired.
    _first = actions[0]
    action, action_guild_id = _first["action"], _first["guild_id"]
    action_role_ids = _first["role_ids"]
    action_role_meta = _djson.dumps(_first["meta"])
    try:
        priority = int(form.get("priority", "100"))
        if not (1 <= priority <= 1000):
            raise ValueError
    except ValueError:
        return None, "Ungültige+Priorität+(1-1000)"
    enabled = 1 if form.get("enabled") == "1" else 0
    return {
        "name": name, "match_type": match_type, "match_role_ids": ",".join(match_role_ids),
        "action": action, "action_guild_id": action_guild_id,
        "action_role_ids": ",".join(action_role_ids), "action_role_meta": action_role_meta,
        "actions": _djson.dumps(actions), "priority": priority, "enabled": enabled,
    }, None


@web.post("/servers/{guild_id}/role-rules/add")
async def role_rule_add(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    data, error = await _role_rule_form_data(request, guild, form)
    if error:
        return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&error={error}", status_code=302)
    await db_exec(
        "INSERT INTO role_rules (guild_id,name,match_type,match_role_ids,action,action_guild_id,action_role_ids,action_role_meta,actions,priority,enabled) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (str(guild_id), data["name"], data["match_type"], data["match_role_ids"], data["action"],
         data["action_guild_id"], data["action_role_ids"], data["action_role_meta"],
         data["actions"], data["priority"], data["enabled"]),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&success=Regel+hinzugefügt", status_code=303)


@web.post("/servers/{guild_id}/role-rules/edit/{rule_id}")
async def role_rule_edit(request: Request, guild_id: int, rule_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    data, error = await _role_rule_form_data(request, guild, form)
    if error:
        return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&error={error}", status_code=302)
    await db_exec(
        "UPDATE role_rules SET name=?, match_type=?, match_role_ids=?, action=?, action_guild_id=?, "
        "action_role_ids=?, action_role_meta=?, actions=?, priority=?, enabled=? WHERE id=? AND guild_id=?",
        (data["name"], data["match_type"], data["match_role_ids"], data["action"],
         data["action_guild_id"], data["action_role_ids"], data["action_role_meta"],
         data["actions"], data["priority"], data["enabled"], rule_id, str(guild_id)),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&success=Regel+gespeichert", status_code=303)


@web.post("/servers/{guild_id}/role-rules/delete/{rule_id}")
async def role_rule_delete(request: Request, guild_id: int, rule_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec("DELETE FROM role_rules WHERE id=? AND guild_id=?", (rule_id, str(guild_id)))
    return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&success=Regel+entfernt", status_code=303)


@web.post("/servers/{guild_id}/role-rules/toggle/{rule_id}")
async def role_rule_toggle(request: Request, guild_id: int, rule_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    await db_exec(
        "UPDATE role_rules SET enabled = 1 - enabled WHERE id=? AND guild_id=?",
        (rule_id, str(guild_id)),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&success=Aktualisiert", status_code=303)


@web.post("/servers/{guild_id}/role-rules/save-interval")
async def role_rule_save_interval(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    try:
        interval = int(form.get("interval_minutes", "0"))
        if not (0 <= interval <= 1440):
            raise ValueError
    except ValueError:
        return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&error=Ungültiges+Intervall+(0-1440)", status_code=302)
    await set_guild_config(guild_id, "role_rules_interval_minutes", str(interval))
    return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&success=Intervall+gespeichert", status_code=303)


@web.post("/servers/{guild_id}/role-rules/save-autocreate")
async def role_rule_save_autocreate(request: Request, guild_id: int):
    """Whether cogs/role_rules.py may recreate an action role that no longer exists on the
    target server. Stored as "1"/"0" with an ABSENT key meaning on - the behaviour was
    user-requested as what the feature should simply do, so an install that never touches this
    switch gets it, and only an explicit opt-out writes "0"."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    await set_guild_config(guild_id, "role_rules_autocreate",
                           "1" if form.get("autocreate") == "1" else "0")
    return RedirectResponse(f"/servers/{guild_id}?tab=rolerules&success=Gespeichert", status_code=303)


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


@web.post("/servers/{guild_id}/users/{user_id}/tabs")
async def server_user_tabs_save(request: Request, guild_id: int, user_id: int):
    """User-requested ("manche brauchen nur umfragen oder tikets") - narrows an ALREADY-granted
    moderator down to only some of this server's tabs, without touching whether they have
    access to the server at all (that stays user_guild_permissions' own grant/revoke above)."""
    if r := admin_redirect(request): return r
    row = await db_one(
        "SELECT 1 FROM user_guild_permissions WHERE user_id=? AND guild_id=?", (user_id, str(guild_id))
    )
    if not row:
        return RedirectResponse(f"/servers/{guild_id}?tab=users&error=Kein+Zugriff+gewährt", status_code=302)
    form = await request.form()
    submitted = {t for t in form.getlist("tabs") if t in _MODERATOR_RESTRICTABLE_TABS}
    # Every toggleable tab checked is equivalent to no restriction at all - stored as an empty
    # string so it reads the exact same way as "never restricted" everywhere else (an admin who
    # later ADDS a brand-new feature tab shouldn't have it silently stay blocked for a moderator
    # who was simply granted "everything" back when fewer tabs existed).
    allowed_tabs = "" if submitted == set(_MODERATOR_RESTRICTABLE_TABS.keys()) else ",".join(sorted(submitted))
    await db_exec(
        "UPDATE user_guild_permissions SET allowed_tabs=? WHERE user_id=? AND guild_id=?",
        (allowed_tabs, user_id, str(guild_id)),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=users&success=Rechte+gespeichert", status_code=302)


# ── Reaction Roles ────────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/reaction_roles/add")
async def rr_add(request: Request, guild_id: int):
    """Adds ONE OR MORE emoji->role mappings to the same message in one go.

    User-requested ("waere cool und einfacher wenn man mehrere reactionroles auf einmal
    hinzufuegen kann anstatt immer nur eine.... das wird naemlich dann sehr schnell
    unuebersichtlich") - a role-picker message typically carries a dozen mappings, and the
    channel and message id are identical for every one of them. The form therefore asks for
    those once and submits a parallel list of emoji/role pairs: the channel lookup, the role
    validation and - the expensive part - the message fetch happen ONCE for the whole batch
    instead of once per mapping.
    """
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    channel_id = form.get("channel_id", "")
    message_id = form.get("message_id", "")
    # Parallel lists rather than indexed field names: a row always submits BOTH its text input
    # and its select (an untouched one as empty strings), and a row deleted in the browser
    # submits neither - so the two lists can only ever line up.
    emojis = form.getlist("emoji")
    role_ids = form.getlist("role_id")
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Bot+nicht+verbunden", status_code=302)
    try:
        channel_id_i, message_id_i = int(channel_id), int(message_id)
    except (ValueError, TypeError):
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Ungültige+Eingabe", status_code=302)
    # Neither the target channel nor the role were ever checked against this guild's actual
    # channels/roles before - the same cross-guild validation gap fixed for practically every
    # other channel/role picker in the project.
    channel = guild.get_channel(channel_id_i)
    if not channel:
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Kanal+nicht+gefunden", status_code=302)

    # Everything is validated BEFORE the first reaction is placed: a batch that turns out to be
    # half-wrong would otherwise leave some reactions already sitting on the message in Discord
    # with nothing in the database behind them, and no hint which ones.
    pairs = []
    seen_emojis = set()
    for raw_emoji, raw_role in zip(emojis, role_ids):
        # Normalized before anything else looks at it - see normalize_reaction_emoji() for why
        # a custom emoji stored in a looser spelling produces a reaction that is placed,
        # looks clickable, and silently never grants a role.
        one_emoji, one_role = normalize_reaction_emoji(raw_emoji), raw_role.strip()
        if not one_emoji and not one_role:
            continue  # an empty row the admin added and never filled in
        if not one_emoji or not one_role:
            return RedirectResponse(
                f"/servers/{guild_id}?tab=rr&error=Jede+Zeile+braucht+Emoji+UND+Rolle", status_code=302)
        if one_emoji in seen_emojis:
            # Discord allows one reaction per emoji per message, so two rows with the same
            # emoji cannot both work - the second would just overwrite the first. Rejected
            # instead of silently dropping one of the two roles the admin picked.
            return RedirectResponse(
                f"/servers/{guild_id}?tab=rr&error=Emoji+"
                f"{urllib.parse.quote_plus(one_emoji)}+doppelt+vergeben", status_code=302)
        seen_emojis.add(one_emoji)
        try:
            role_id_i = int(one_role)
        except (ValueError, TypeError):
            return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Ungültige+Eingabe", status_code=302)
        if not guild.get_role(role_id_i):
            return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Rolle+nicht+gefunden", status_code=302)
        pairs.append((one_emoji, role_id_i))
    if not pairs:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=rr&error=Mindestens+eine+Zuordnung+erforderlich", status_code=302)
    try:
        msg = await channel.fetch_message(message_id_i)
    except Exception:
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Nachricht+nicht+gefunden", status_code=302)

    # Roles the bot provably cannot hand out: either it lacks "Manage Roles" entirely, or the
    # role sits at or above its own top role in the hierarchy. Both fail only at CLICK time,
    # deep inside the gateway handler, where the sole trace is a console line nobody watching
    # the dashboard will ever see. Reported here instead - but the rows are still saved rather
    # than rejected: fixing the role order in Discord afterwards makes them work as configured,
    # and refusing the save would just mean typing everything in again later.
    me = guild.me

    added, failed, blocked = 0, [], []
    for one_emoji, role_id_i in pairs:
        try:
            # This route never actually placed the reaction on the message at all - it only
            # wrote a DB row. /reactionrole-add in Discord does this already; without it, a
            # reaction role configured via the dashboard has nothing for anyone to click in
            # Discord at all, unless someone happens to react with that exact emoji first.
            await msg.add_reaction(one_emoji)
        except (discord.HTTPException, discord.NotFound):
            # One unusable emoji must not discard the rest of the batch - collected and named
            # in the result message instead, so the admin knows exactly which one to fix.
            failed.append(one_emoji)
            continue
        # Same de-dup fix as the Discord command: without this, adding a second mapping for the
        # same message+emoji (e.g. to change the granted role) would silently never take
        # effect, since _handle_reaction only ever reads the first matching row.
        existing = await db_one(
            "SELECT id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
            (guild_id, message_id_i, one_emoji),
        )
        if existing:
            await db_exec("UPDATE reaction_roles SET role_id=?, channel_id=? WHERE id=?",
                           (role_id_i, channel_id_i, existing["id"]))
        else:
            await db_exec(
                "INSERT INTO reaction_roles (guild_id,channel_id,message_id,emoji,role_id) VALUES (?,?,?,?,?)",
                (guild_id, channel_id_i, message_id_i, one_emoji, role_id_i),
            )
        added += 1
        # Only checked for mappings that actually made it in: warning about a role whose
        # reaction Discord just rejected would point at the wrong problem entirely.
        role_obj = guild.get_role(role_id_i)
        if me is not None and role_obj is not None and (
                not me.guild_permissions.manage_roles or role_obj >= me.top_role):
            blocked.append(role_obj.name)
    if failed:
        note = urllib.parse.quote_plus(" ".join(failed))
        if not added:
            return RedirectResponse(
                f"/servers/{guild_id}?tab=rr&error=Ungültiger+Emoji:+{note}", status_code=302)
        msg = f"{added}+hinzugefügt,+ungültiger+Emoji:+{note}"
        if blocked:
            msg += ("+—+ACHTUNG:+der+Bot+kann+diese+Rolle(n)+nicht+vergeben:+"
                    + urllib.parse.quote_plus(", ".join(dict.fromkeys(blocked))))
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&success={msg}", status_code=302)
    label = "Reaction+Role" if added == 1 else "Reaction+Roles"
    msg = f"{added}+{label}+hinzugefügt"
    if blocked:
        names = urllib.parse.quote_plus(", ".join(dict.fromkeys(blocked)))
        msg += f"+—+ACHTUNG:+der+Bot+kann+diese+Rolle(n)+nicht+vergeben:+{names}+(Rolle+in+Discord+über+die+Bot-Rolle+ziehen+bzw.+„Rollen+verwalten“+geben)"
    return RedirectResponse(f"/servers/{guild_id}?tab=rr&success={msg}", status_code=302)


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
                # guild.me can be None when the bot's own member object is not in the cache,
                # and remove_reaction(emoji, None) then raises inside this best-effort block -
                # the reaction silently stays on the message, still looking clickable. The
                # per-guild bot's own user works just as well as the target here.
                await msg.remove_reaction(row["emoji"], guild.me or bot._bot_for_guild(guild_id).user)
            except Exception:
                pass
    await db_exec("DELETE FROM reaction_roles WHERE id=? AND guild_id=?", (rr_id, guild_id))
    return RedirectResponse(f"/servers/{guild_id}?tab=rr&success=Reaction+Role+gelöscht", status_code=302)


@web.post("/servers/{guild_id}/reaction_roles/{rr_id}/edit")
async def rr_edit(
    request: Request, guild_id: int, rr_id: int,
    channel_id: str = Form(...), message_id: str = Form(...),
    emoji: str = Form(...), role_id: str = Form(...),
):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    row = await db_one("SELECT * FROM reaction_roles WHERE id=? AND guild_id=?", (rr_id, guild_id))
    if not row:
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Nicht+gefunden", status_code=302)
    emoji = normalize_reaction_emoji(emoji)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Bot+nicht+verbunden", status_code=302)
    try:
        channel_id_i, message_id_i, role_id_i = int(channel_id), int(message_id), int(role_id)
    except (ValueError, TypeError):
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Ungültige+Eingabe", status_code=302)
    channel = guild.get_channel(channel_id_i)
    if not channel:
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Kanal+nicht+gefunden", status_code=302)
    role = guild.get_role(role_id_i)
    if not role:
        return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Rolle+nicht+gefunden", status_code=302)

    target_changed = (channel_id_i, message_id_i, emoji) != (row["channel_id"], row["message_id"], row["emoji"])
    if target_changed:
        # Editing into a combo another row already owns would leave two DB rows for the same
        # message+emoji, only one of which _handle_reaction ever reads - reject instead of
        # silently shadowing it.
        conflict = await db_one(
            "SELECT id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=? AND id!=?",
            (guild_id, message_id_i, emoji, rr_id),
        )
        if conflict:
            return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Kombination+existiert+bereits", status_code=302)
        try:
            new_msg = await channel.fetch_message(message_id_i)
        except Exception:
            return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Nachricht+nicht+gefunden", status_code=302)
        try:
            await new_msg.add_reaction(emoji)
        except (discord.HTTPException, discord.NotFound):
            return RedirectResponse(f"/servers/{guild_id}?tab=rr&error=Ungültiger+Emoji", status_code=302)
        # Best-effort: remove the reaction from the OLD message/emoji so it doesn't keep looking
        # clickable there while silently doing nothing anymore.
        old_channel = guild.get_channel(row["channel_id"])
        if old_channel:
            try:
                old_msg = await old_channel.fetch_message(row["message_id"])
                # Same guild.me fallback as in rr_delete.
                await old_msg.remove_reaction(row["emoji"], guild.me or bot._bot_for_guild(guild_id).user)
            except Exception:
                pass

    await db_exec(
        "UPDATE reaction_roles SET channel_id=?, message_id=?, emoji=?, role_id=? WHERE id=? AND guild_id=?",
        (channel_id_i, message_id_i, emoji, role_id_i, rr_id, guild_id),
    )
    return RedirectResponse(f"/servers/{guild_id}?tab=rr&success=Reaction+Role+aktualisiert", status_code=302)


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
    # Same addition as in the /addcommand slash command: the birthday command left
    # b.commands when it became per-guild configurable, so it has to be checked separately.
    birthday_words = parse_command_triggers(
        await get_guild_config(guild_id, "birthday_commands") or "", DEFAULT_BIRTHDAY_TRIGGERS)
    if (b and trigger in {c.name for c in b.commands}) or trigger in birthday_words:
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
    await _log_bot_event(
        bot, guild_id, "🎉", "Giveaway gestartet", "giveaway",
        plain=f"{prize} · #{channel.name} · {winners} Gewinner",
    )

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


# ── Polls ─────────────────────────────────────────────────────────────────────

@web.post("/servers/{guild_id}/polls/create")
async def poll_create_web(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    # Manual form parsing (not typed Form(...) params) since this route also needs a file
    # upload + form.getlist() for the variable option count - same style as embed_post_create,
    # which has the identical "image URL or upload" field.
    form = await request.form()
    channel_id = form.get("channel_id", "")
    question = form.get("question", "").strip()
    # Per-option label/image-url/image-file/link fields are submitted as four PARALLEL lists
    # (one dashboard row per option, always all four slots present even when empty since
    # they're plain text/url/file inputs) - zipped together BEFORE filtering so a row's image/
    # link never end up misaligned with a different row's label. A row only survives if it has
    # a non-empty LABEL (a picture with no button text makes no sense); its image/link may be
    # empty or absent.
    raw_labels = form.getlist("option")
    raw_images = form.getlist("option_image")
    raw_image_files = form.getlist("option_image_file")
    raw_links = form.getlist("option_link")
    raw_widths = form.getlist("option_image_width")
    raw_images += [""] * (len(raw_labels) - len(raw_images))
    raw_image_files += [None] * (len(raw_labels) - len(raw_image_files))
    raw_links += [""] * (len(raw_labels) - len(raw_links))
    raw_widths += [""] * (len(raw_labels) - len(raw_widths))
    options = [
        (lbl.strip(), img.strip(), img_file, link.strip(), _clamp_poll_image_width(width))
        for lbl, img, img_file, link, width in zip(raw_labels, raw_images, raw_image_files, raw_links, raw_widths)
        if lbl.strip()
    ]
    multiple = bool(form.get("multiple_choice", ""))
    show_started = bool(form.get("show_started", ""))
    show_ranking = bool(form.get("show_ranking", ""))
    bar_color = _clamp_poll_bar_color(form.get("bar_color", ""))
    try:
        duration_minutes = int(form.get("duration_minutes") or 0)
    except (ValueError, TypeError):
        duration_minutes = 0
    starts_at_raw = form.get("starts_at", "").strip()
    end_mode = form.get("end_mode", "duration")
    if end_mode not in ("duration", "fixed"):
        end_mode = "duration"
    ends_at_fixed_raw = form.get("ends_at_fixed", "").strip()

    if len(options) < 2:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Mindestens+2+Optionen+nötig", status_code=302)
    if len(options) > 25:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Maximal+25+Optionen+erlaubt", status_code=302)
    if len({o[0].casefold() for o in options}) != len(options):
        # Case-insensitive on purpose - "dwad" and "Dwad" as two separate buttons would look just
        # as duplicated/confusing to a voter as two literal "dwad"s (the reported bug: three
        # buttons all reading "dwad", no way to tell which is which - screenshot showed a real
        # poll in exactly this state).
        return RedirectResponse(
            f"/servers/{guild_id}?tab=polls&error=Optionen+müssen+unterschiedliche+Namen+haben", status_code=302
        )
    if len(question) > 200:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Frage+zu+lang+(max.+200+Zeichen)", status_code=302)
    if duration_minutes < 0 or duration_minutes > 10080:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Ungültige+Dauer", status_code=302)

    # Optional scheduled start ("ich will angeben können wann die anfängt") + a toggle between
    # a relative duration or a fixed absolute end datetime ("entweder dauer oder mit datum unt
    # uhrzeit"). Both raw datetime-local values are interpreted in the viewer's own dashboard
    # timezone (same _aware()/_request_tz pattern events_create uses) and then converted to a
    # NAIVE UTC isoformat string for storage - matching cogs/polls.py's own existing convention
    # for ends_at (built from datetime.utcnow(), compared against datetime.utcnow() again in
    # _schedule/_start_poll), not the separate Europe/Berlin-normalized convention scheduled
    # messages/events use elsewhere in this file.
    tz = _request_tz.get()
    now_utc = datetime.datetime.utcnow()
    starts_at_store = ""
    starts_dt_utc = None
    if starts_at_raw:
        try:
            starts_dt = _aware(datetime.datetime.fromisoformat(starts_at_raw), tz)
        except ValueError:
            return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Ungültiger+Startzeitpunkt", status_code=302)
        starts_dt_utc = starts_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        if starts_dt_utc <= now_utc:
            return RedirectResponse(
                f"/servers/{guild_id}?tab=polls&error=Startzeitpunkt+muss+in+der+Zukunft+liegen", status_code=302
            )
        starts_at_store = starts_dt_utc.isoformat()

    ends_at_fixed_store = ""
    if end_mode == "fixed":
        if not ends_at_fixed_raw:
            return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Enddatum+erforderlich", status_code=302)
        try:
            ends_dt = _aware(datetime.datetime.fromisoformat(ends_at_fixed_raw), tz)
        except ValueError:
            return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Ungültiges+Enddatum", status_code=302)
        ends_dt_utc = ends_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        reference_utc = starts_dt_utc if starts_dt_utc is not None else now_utc
        if ends_dt_utc <= reference_utc:
            return RedirectResponse(
                f"/servers/{guild_id}?tab=polls&error=Enddatum+muss+nach+dem+Start+liegen", status_code=302
            )
        ends_at_fixed_store = ends_dt_utc.isoformat()

    for lbl, img, img_file, link, width in options:
        opt_has_upload = bool(img_file and getattr(img_file, "filename", ""))
        if opt_has_upload and img:
            return RedirectResponse(
                f"/servers/{guild_id}?tab=polls&error=Option+({urllib.parse.quote(lbl)}):+Entweder+Bild-URL+ODER+Datei,+nicht+beides",
                status_code=302,
            )
        if img and not img.startswith(("http://", "https://")):
            return RedirectResponse(
                f"/servers/{guild_id}?tab=polls&error=Options-Bild-URL+({urllib.parse.quote(lbl)})+muss+mit+http(s)://+beginnen",
                status_code=302,
            )
        if link and not link.startswith(("http://", "https://")):
            return RedirectResponse(
                f"/servers/{guild_id}?tab=polls&error=Options-Link+({urllib.parse.quote(lbl)})+muss+mit+http(s)://+beginnen",
                status_code=302,
            )
    try:
        channel = bot.get_channel(int(channel_id))
    except (ValueError, TypeError):
        channel = None
    if not channel or channel.guild.id != guild_id:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Kanal+nicht+gefunden", status_code=302)
    try:
        # Read all per-option uploads up front (before anything gets written to the DB) so a
        # single bad option image rejects the whole request cleanly, same as every other
        # validation above - not a partially-created poll with only some images accepted.
        # Each attachment filename must be made unique (_read_embed_image_upload always
        # returns a generic "image.<ext>") since Discord requires distinct filenames once more
        # than one file rides on the same message - prefixed by option index.
        option_uploads = []
        for i, (lbl, img, img_file, link, width) in enumerate(options):
            opt_data_b64, opt_filename = await _read_embed_image_upload(img_file)
            if opt_filename:
                opt_filename = f"opt{i}_{opt_filename}"
            option_uploads.append((opt_data_b64 or "", opt_filename or ""))
    except ValueError as msg:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error={urllib.parse.quote(str(msg))}", status_code=302)
    # No poll-wide image anymore ("bild zwei brauchen wir glaube ich nicht mehr" - removed once
    # every option got its own auto-fetched image, making one shared banner image redundant).
    # polls.image_url/image_data/image_filename stay in the schema (never dropped, same
    # convention as every other retired column in this project) purely so an ALREADY-existing
    # poll from before this change keeps rendering whatever image it already had - there's just
    # no more way to set/change one through either form now.
    final_image_url, final_image_data, final_image_filename = "", "", ""
    # An option with a link but no image/upload of its own gets an automatic Open Graph
    # preview-image lookup (user explicitly picked "automatic on save" over a manual fetch
    # button) - resolved for every option CONCURRENTLY via gather() rather than one at a time,
    # so up to 25 options each doing a real network fetch adds only ~one fetch's worth of
    # latency to this request instead of their sum. existing_row=None/remove_checked=False
    # always apply here (a brand-new poll has nothing to keep or remove yet) - see
    # _resolve_poll_option_image's docstring for the full precedence shared with editing.
    resolved_options = await asyncio.gather(*[
        _resolve_poll_option_image(img, bool(opt_filename), opt_data_b64, opt_filename, link, False, None)
        for (lbl, img, img_file, link, width), (opt_data_b64, opt_filename) in zip(options, option_uploads)
    ])
    # Second pass: an option with a width set gets its resolved image downloaded/resized to
    # that exact pixel width (see _apply_poll_option_custom_width) - kept as its own gather()
    # rather than folded into the one above so a resize failure can never affect the already-
    # correct precedence result of the first pass.
    resolved_options = await asyncio.gather(*[
        _apply_poll_option_custom_width(url, data, filename, width, i)
        for i, ((lbl, img, img_file, link, width), (url, data, filename)) in enumerate(zip(options, resolved_options))
    ])

    created_at = datetime.datetime.utcnow().isoformat()
    duration_minutes_store = duration_minutes if end_mode == "duration" else 0
    if end_mode == "fixed":
        # A fixed absolute end datetime doesn't depend on when the poll actually starts, so it
        # can be resolved right away regardless of whether starts_at_store is set.
        ends_at = ends_at_fixed_store
    elif not starts_at_store:
        # Immediate start + duration mode: resolve relative to "now" same as before this
        # feature existed.
        ends_at = (
            (datetime.datetime.utcnow() + datetime.timedelta(minutes=duration_minutes)).isoformat()
            if duration_minutes > 0 else ""
        )
    else:
        # Scheduled start + duration mode: the real start moment is still in the future, so the
        # duration can't be resolved into an absolute ends_at yet - _start_poll does that once
        # the poll actually goes live, using duration_minutes_store.
        ends_at = ""

    pid = await db_insert(
        "INSERT INTO polls (guild_id,channel_id,question,multiple_choice,ends_at,created_by,"
        "image_url,image_data,image_filename,bar_color,starts_at,duration_minutes,show_started,show_ranking) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(guild_id), str(channel.id), question, int(multiple), ends_at, request.session.get("user_id") or 0,
         final_image_url, final_image_data, final_image_filename, bar_color, starts_at_store,
         duration_minutes_store, int(show_started), int(show_ranking)),
    )
    for i, (label, opt_image, opt_image_file, opt_link, opt_width) in enumerate(options):
        opt_final_url, opt_final_data, opt_final_filename = resolved_options[i]
        await db_exec(
            "INSERT INTO poll_options (poll_id,option_index,label,image_url,link_url,image_data,image_filename,image_size,image_width) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            # image_size is a retired column (never dropped, see database.py's schema comment) -
            # 'custom' is written unconditionally now that px width is the only sizing mechanism,
            # kept only so an already-restored backup row still has SOMETHING recognizable there.
            (pid, i, label[:80], opt_final_url[:500], opt_link[:500], opt_final_data, opt_final_filename, "custom", opt_width),
        )

    if starts_at_store:
        # Scheduled poll - don't post anything now, cogs.polls.Polls._start_poll() does the
        # actual channel.send()/embed-build/duration-resolution when the moment arrives (or on
        # the next bot restart, if it was already due - see cog_load()'s pending-start resume).
        b = bot._bot_for_guild(guild_id)
        cog = b.cogs.get("Polls") if b else None
        if cog:
            poll_row = await db_one("SELECT * FROM polls WHERE id=?", (pid,))
            cog._schedule_start(poll_row)
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&success=Umfrage+geplant", status_code=302)

    # An option's own uploaded picture is NOT separately attached here - _build_poll_embed's
    # chart_files is now the complete, authoritative attachment list (the one combined image
    # holding every option's own picture/bar, see cogs/polls.py's _render_combined_poll_image) -
    # attaching an option's raw upload again here as well would create a stray, UNREFERENCED
    # duplicate attachment (Discord shows an attachment nobody's embed points to as its own
    # extra inline image at the bottom of the message).
    files = _embed_post_files(final_image_data, final_image_filename)
    opt_rows = await db_rows("SELECT * FROM poll_options WHERE poll_id=? ORDER BY option_index", (pid,))
    embeds, chart_files = _build_poll_embed(
        question, multiple, opt_rows, {}, image_url=final_image_url, image_filename=final_image_filename,
        ends_at=ends_at, created_at=created_at, bar_color=bar_color, show_started=show_started,
        show_ranking=show_ranking,
    )
    files.extend(chart_files)
    view = _PollView(pid, opt_rows)
    try:
        msg = await channel.send(embeds=embeds, view=view, files=files)
    except (discord.HTTPException, OSError):
        await db_exec("DELETE FROM polls WHERE id=?", (pid,))
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Umfrage+konnte+nicht+gepostet+werden", status_code=302)
    await db_exec("UPDATE polls SET message_id=? WHERE id=?", (str(msg.id), pid))
    await _log_bot_event(
        bot, guild_id, "🗳️", "Umfrage gepostet", "poll",
        plain=f"{question} · #{channel.name} · {len(opt_rows)} Optionen",
    )
    if ends_at:
        b = bot._bot_for_guild(guild_id)
        cog = b.cogs.get("Polls") if b else None
        if cog:
            poll_row = await db_one("SELECT * FROM polls WHERE id=?", (pid,))
            cog._schedule(poll_row)
    return RedirectResponse(f"/servers/{guild_id}?tab=polls&success=Umfrage+gestartet", status_code=302)


@web.post("/servers/{guild_id}/polls/{poll_id}/end")
async def poll_end_web(request: Request, guild_id: int, poll_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    poll = await db_one("SELECT id FROM polls WHERE id=? AND guild_id=?", (poll_id, str(guild_id)))
    if not poll:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Umfrage+nicht+gefunden", status_code=302)
    b = bot._bot_for_guild(guild_id)
    cog = b.cogs.get("Polls") if b else None
    if not cog:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Bot+nicht+online", status_code=302)
    await cog._end_poll(poll_id)
    return RedirectResponse(f"/servers/{guild_id}?tab=polls", status_code=302)


@web.post("/servers/{guild_id}/polls/{poll_id}/delete")
async def poll_delete_web(request: Request, guild_id: int, poll_id: int):
    """Distinct from /end - ending keeps the poll's message around with its final results and
    just stops further votes (build_poll_embed(ended=True) + view=None, see _end_poll), while
    this removes the poll entirely: the live Discord message too (best-effort, same "channel/
    message/bot-offline could all be gone already" tolerance as poll_edit_web's live-edit
    block), not just the dashboard row - user-requested explicitly ("wenn ich das lösche dann
    will ich auch das es in dc auch gelöscht wirt")."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    poll = await db_one("SELECT * FROM polls WHERE id=? AND guild_id=?", (poll_id, str(guild_id)))
    if not poll:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Umfrage+nicht+gefunden", status_code=302)
    if poll["message_id"]:
        # The whole block - including the int(channel_id) conversion, not just the actual
        # network calls - is inside this one try/except: a malformed channel_id (DB corruption
        # or manual tampering, channel_id is always a validated str(channel.id) under normal
        # operation) would otherwise raise OUTSIDE any handler and crash this whole route with
        # an unhandled 500, even though the DB rows get deleted just fine below regardless of
        # whether this Discord-side cleanup succeeds.
        try:
            channel = bot.get_channel(int(poll["channel_id"])) if poll["channel_id"] else None
            if channel:
                msg = await channel.fetch_message(int(poll["message_id"]))
                await msg.delete()
        except Exception:
            # Already deleted directly in Discord, channel gone, or bot offline for this
            # guild's token - the dashboard/DB side of the delete below must not depend on
            # this succeeding, same best-effort principle as every other live-message
            # touch-point in this file.
            pass
    await db_exec("DELETE FROM poll_votes WHERE poll_id=?", (poll_id,))
    await db_exec("DELETE FROM poll_options WHERE poll_id=?", (poll_id,))
    await db_exec("DELETE FROM polls WHERE id=?", (poll_id,))
    return RedirectResponse(f"/servers/{guild_id}?tab=polls&success=Umfrage+gelöscht", status_code=302)


@web.post("/servers/{guild_id}/polls/preview-link-image")
async def poll_preview_link_image(request: Request, guild_id: int):
    """Live, save-nothing Open Graph image lookup for the create/edit forms' automatic
    background preview (schedulePollPreviewAutoFetch/pollPreviewAutoFetch, fires ~600ms after
    a link field stops changing) - the manual "🔍" button that used to trigger this on demand
    was removed in v1.15.41 once the automatic fetch made it redundant, this route stayed as
    its sole remaining caller. Returns EVERY candidate image found (see
    _extract_image_candidates), the frontend just uses the first one for the live preview - the
    single best-guess the automatic fetch ON SAVE uses (_resolve_poll_option_image/
    _fetch_og_image) is a separate, independent code path that never calls this route. Same
    access level as creating or ending a poll - no poll_id binding needed since this also runs
    on the create form, before any poll exists yet."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return JSONResponse({"image_urls": []}, status_code=403)
    form = await request.form()
    url = form.get("url", "").strip()
    if not url.startswith(("http://", "https://")):
        return JSONResponse({"image_urls": []})
    image_urls = await _fetch_og_image_candidates(url)
    return JSONResponse({"image_urls": image_urls})


@web.get("/servers/{guild_id}/polls/{poll_id}/option/{option_id}/image")
async def poll_option_image_web(request: Request, guild_id: int, poll_id: int, option_id: int):
    """Serves a single option's uploaded image for the dashboard's OWN edit-form preview only -
    never the actual Discord embed URL (that goes via a real message attachment, see
    _embed_post_files()). poll_id is checked in the WHERE clause too, not just option_id, so an
    option belonging to a DIFFERENT poll (even one in the same guild) can never be served here."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    row = await db_one(
        "SELECT o.image_data, o.image_filename FROM poll_options o "
        "JOIN polls p ON p.id=o.poll_id WHERE o.id=? AND o.poll_id=? AND p.guild_id=?",
        (option_id, poll_id, str(guild_id)),
    )
    if not row or not row.get("image_data"):
        raise HTTPException(status_code=404)
    try:
        raw = base64.b64decode(row["image_data"])
    except Exception:
        raise HTTPException(status_code=404)
    ext = (row.get("image_filename") or "").rsplit(".", 1)[-1].lower()
    media_type = _EMBED_IMAGE_MEDIA_TYPES.get(ext, "application/octet-stream")
    return Response(content=raw, media_type=media_type)


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@web.post("/servers/{guild_id}/polls/{poll_id}/edit")
async def poll_edit_web(request: Request, guild_id: int, poll_id: int):
    """Full edit (question, multiple-choice, every option's label/image/link, add/remove
    options) - user explicitly chose the unrestricted "edit everything, regardless of vote
    count" option over a votes==0-only or images/links-only alternative. Channel, the auto-end
    duration, and the poll-wide image are deliberately NOT editable here - the poll-wide image
    field was removed from both forms entirely (see poll_create_web's comment), the other two
    were never in scope of the request that led to this route ("Frage, Optionen, Bilder/Links")."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    poll = await db_one("SELECT * FROM polls WHERE id=? AND guild_id=?", (poll_id, str(guild_id)))
    if not poll:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Umfrage+nicht+gefunden", status_code=302)
    existing_options = await db_rows("SELECT * FROM poll_options WHERE poll_id=? ORDER BY option_index", (poll_id,))
    existing_by_id = {o["id"]: o for o in existing_options}

    form = await request.form()
    question = form.get("question", "").strip()
    # Same four-parallel-lists shape as poll_create_web, plus two more: option_id (empty for an
    # option newly added during THIS edit) and option_remove_image - a checkbox list whose
    # VALUE is the option's id rather than a fixed "1", the standard trick for knowing which of
    # several same-named checkboxes were actually checked (form.getlist() on a checkbox field
    # only ever returns the checked ones, with nothing to say which row each came from unless
    # the value itself identifies it).
    raw_ids = form.getlist("option_id")
    raw_labels = form.getlist("option")
    raw_images = form.getlist("option_image")
    raw_image_files = form.getlist("option_image_file")
    raw_links = form.getlist("option_link")
    raw_widths = form.getlist("option_image_width")
    removed_image_ids = set(form.getlist("option_remove_image"))
    raw_ids += [""] * (len(raw_labels) - len(raw_ids))
    raw_images += [""] * (len(raw_labels) - len(raw_images))
    raw_image_files += [None] * (len(raw_labels) - len(raw_image_files))
    raw_links += [""] * (len(raw_labels) - len(raw_links))
    raw_widths += [""] * (len(raw_labels) - len(raw_widths))
    options = [
        (_safe_int(oid), lbl.strip(), img.strip(), img_file, link.strip(), _clamp_poll_image_width(width))
        for oid, lbl, img, img_file, link, width in zip(raw_ids, raw_labels, raw_images, raw_image_files, raw_links, raw_widths)
        if lbl.strip()
    ]
    multiple = bool(form.get("multiple_choice", ""))
    show_started = bool(form.get("show_started", ""))
    show_ranking = bool(form.get("show_ranking", ""))
    bar_color = _clamp_poll_bar_color(form.get("bar_color", ""))

    if len(options) < 2:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Mindestens+2+Optionen+nötig", status_code=302)
    if len(options) > 25:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Maximal+25+Optionen+erlaubt", status_code=302)
    if len({o[1].casefold() for o in options}) != len(options):
        # Same case-insensitive dedup as poll_create_web - see its own comment for why.
        return RedirectResponse(
            f"/servers/{guild_id}?tab=polls&error=Optionen+müssen+unterschiedliche+Namen+haben", status_code=302
        )
    if len(question) > 200:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error=Frage+zu+lang+(max.+200+Zeichen)", status_code=302)
    for oid, lbl, img, img_file, link, width in options:
        opt_has_upload = bool(img_file and getattr(img_file, "filename", ""))
        if opt_has_upload and img:
            return RedirectResponse(
                f"/servers/{guild_id}?tab=polls&error=Option+({urllib.parse.quote(lbl)}):+Entweder+Bild-URL+ODER+Datei,+nicht+beides",
                status_code=302,
            )
        if img and not img.startswith(("http://", "https://")):
            return RedirectResponse(
                f"/servers/{guild_id}?tab=polls&error=Options-Bild-URL+({urllib.parse.quote(lbl)})+muss+mit+http(s)://+beginnen",
                status_code=302,
            )
        if link and not link.startswith(("http://", "https://")):
            return RedirectResponse(
                f"/servers/{guild_id}?tab=polls&error=Options-Link+({urllib.parse.quote(lbl)})+muss+mit+http(s)://+beginnen",
                status_code=302,
            )

    try:
        option_uploads = []
        for i, (oid, lbl, img, img_file, link, width) in enumerate(options):
            opt_data_b64, opt_filename = await _read_embed_image_upload(img_file)
            if opt_filename:
                opt_filename = f"opt{i}_{opt_filename}"
            option_uploads.append((opt_data_b64 or "", opt_filename or ""))
    except ValueError as msg:
        return RedirectResponse(f"/servers/{guild_id}?tab=polls&error={urllib.parse.quote(str(msg))}", status_code=302)

    # No poll-wide image field in either form anymore (see poll_create_web's identical
    # comment) - editing just leaves whatever an already-existing poll happened to have
    # untouched, there's no more input to change it from.
    final_image_url = poll.get("image_url") or ""
    final_image_data = poll.get("image_data") or ""
    final_image_filename = poll.get("image_filename") or ""

    resolved_options = await asyncio.gather(*[
        _resolve_poll_option_image(
            img, bool(opt_filename), opt_data_b64, opt_filename, link,
            str(oid) in removed_image_ids if oid is not None else False,
            existing_by_id.get(oid) if oid is not None else None,
        )
        for (oid, lbl, img, img_file, link, width), (opt_data_b64, opt_filename) in zip(options, option_uploads)
    ])
    # Same second pass as poll_create_web: only actually resizes anything for an option with a
    # width set, everything else passes through unchanged.
    resolved_options = await asyncio.gather(*[
        _apply_poll_option_custom_width(url, data, filename, width, i)
        for i, ((oid, lbl, img, img_file, link, width), (url, data, filename)) in enumerate(zip(options, resolved_options))
    ])

    submitted_ids = {oid for oid, *_ in options if oid is not None}
    # An option the admin removed from the edit form entirely (its whole row deleted client-
    # side) never gets submitted at all - anything left in existing_by_id afterward was dropped
    # on purpose. Its votes are removed right along with it; a vote for an option that no
    # longer exists wouldn't mean anything.
    for removed_id in set(existing_by_id.keys()) - submitted_ids:
        await db_exec("DELETE FROM poll_options WHERE id=?", (removed_id,))
        await db_exec("DELETE FROM poll_votes WHERE poll_id=? AND option_id=?", (poll_id, removed_id))

    for i, (oid, label, opt_image, opt_image_file, opt_link, opt_width) in enumerate(options):
        opt_final_url, opt_final_data, opt_final_filename = resolved_options[i]
        # image_size is a retired column (never dropped, see database.py's schema comment) -
        # 'custom' is written unconditionally now that px width is the only sizing mechanism.
        if oid is not None and oid in existing_by_id:
            await db_exec(
                "UPDATE poll_options SET option_index=?, label=?, image_url=?, link_url=?, image_data=?, image_filename=?, image_size=?, image_width=? WHERE id=?",
                (i, label[:80], opt_final_url[:500], opt_link[:500], opt_final_data, opt_final_filename, "custom", opt_width, oid),
            )
        else:
            await db_exec(
                "INSERT INTO poll_options (poll_id,option_index,label,image_url,link_url,image_data,image_filename,image_size,image_width) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (poll_id, i, label[:80], opt_final_url[:500], opt_link[:500], opt_final_data, opt_final_filename, "custom", opt_width),
            )

    # Deliberately not cleaned up: if multiple_choice is switched off while a user already has
    # more than one vote recorded from when it was on, those extra votes just stay - only
    # nudges the displayed total vote count slightly, never a crash or a wrong option tally.
    await db_exec(
        "UPDATE polls SET question=?, multiple_choice=?, image_url=?, image_data=?, image_filename=?, bar_color=?, show_started=?, show_ranking=? WHERE id=?",
        (question, int(multiple), final_image_url, final_image_data, final_image_filename, bar_color, int(show_started), int(show_ranking), poll_id),
    )

    opt_rows = await db_rows("SELECT * FROM poll_options WHERE poll_id=? ORDER BY option_index", (poll_id,))
    vote_rows = await db_rows("SELECT option_id, COUNT(*) c FROM poll_votes WHERE poll_id=? GROUP BY option_id", (poll_id,))
    counts = {r["option_id"]: r["c"] for r in vote_rows}
    embeds, chart_files = _build_poll_embed(
        question, multiple, opt_rows, counts, ended=bool(poll["ended"]),
        image_url=final_image_url, image_filename=final_image_filename,
        ends_at=poll.get("ends_at") or "", created_at=poll.get("created_at") or "", bar_color=bar_color,
        show_started=show_started, show_ranking=show_ranking,
    )
    # An option's own uploaded picture is NOT separately attached here - chart_files is now the
    # complete, authoritative attachment list (the one combined image holding every option's
    # own picture/bar, see cogs/polls.py's _render_combined_poll_image) - attaching an option's
    # raw upload again here as well would create a stray, UNREFERENCED duplicate attachment (see
    # _build_poll_embed's docstring).
    files = _embed_post_files(final_image_data, final_image_filename)
    files.extend(chart_files)
    # The int(channel_id) conversion sits INSIDE this try/except too, not just the network
    # calls after it - the DB save above already succeeded regardless of what happens here (a
    # malformed channel_id, DB corruption or manual tampering since it's always a validated
    # str(channel.id) under normal operation, would otherwise crash this whole route with an
    # unhandled 500 AFTER the save already went through - directly contradicting this block's
    # own "best-effort, doesn't matter if it fails" comment below).
    try:
        channel = bot.get_channel(int(poll["channel_id"])) if poll["channel_id"] else None
        if channel and poll["message_id"]:
            msg = await channel.fetch_message(int(poll["message_id"]))
            # Buttons can change (an option was renamed/added/removed) so, unlike a plain vote,
            # view= is passed explicitly here rather than omitted - same reasoning as
            # attachments= below. None for an already-ended poll keeps its buttons removed.
            view = None if poll["ended"] else _PollView(poll_id, opt_rows)
            # attachments= always passed explicitly (even as []), never left out - otherwise
            # Discord keeps whatever attachment the message already had, which breaks the
            # moment an image is swapped/removed during this edit (same reasoning as
            # embed_post_update's identical attachments= usage above).
            await msg.edit(embeds=embeds, view=view, attachments=files)
    except Exception:
        # Best-effort - the DB save above already succeeded regardless of whether the live
        # Discord message could still be found/edited (channel or message deleted, bot
        # offline for this guild's token, etc.).
        pass
    return RedirectResponse(f"/servers/{guild_id}?tab=polls&success=Umfrage+aktualisiert", status_code=302)


# ── Ratings ───────────────────────────────────────────────────────────────────
# Admin-curated catalog (maps/sites/games/...) managed entirely here on the dashboard - the
# Discord-facing half (/bewerten, /bewertungen) lives in cogs/ratings.py. See that module's own
# docstring for why this is a separate feature from polls rather than a poll variant.

@web.post("/servers/{guild_id}/ratings/add")
async def rating_item_add(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    label = form.get("label", "").strip()
    url = form.get("url", "").strip()
    image_url = form.get("image_url", "").strip()
    if not label:
        return RedirectResponse(f"/servers/{guild_id}?tab=ratings&error=Name+erforderlich", status_code=302)
    if len(label) > 100:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=ratings&error=Name+zu+lang+(max.+100+Zeichen)", status_code=302
        )
    if url and not url.startswith(("http://", "https://")):
        return RedirectResponse(f"/servers/{guild_id}?tab=ratings&error=Ungültige+URL", status_code=302)
    try:
        upload_data, upload_filename = await _read_embed_image_upload(form.get("image_file"))
    except ValueError as msg:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=ratings&error={urllib.parse.quote(str(msg))}", status_code=302
        )
    if upload_data and image_url:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=ratings&error=Entweder+Bild-URL+ODER+Datei,+nicht+beides", status_code=302
        )
    if image_url and not image_url.startswith(("http://", "https://")):
        return RedirectResponse(f"/servers/{guild_id}?tab=ratings&error=Ungültige+Bild-URL", status_code=302)
    final_image_url = "" if upload_data else image_url
    await db_exec(
        "INSERT INTO rating_items (guild_id,label,url,image_url,image_data,image_filename) VALUES (?,?,?,?,?,?)",
        (str(guild_id), label, url[:500], final_image_url, upload_data or "", upload_filename or ""),
    )
    await _refresh_ratings_list(bot, guild_id)
    return RedirectResponse(f"/servers/{guild_id}?tab=ratings&success=Eintrag+hinzugefügt", status_code=302)


@web.post("/servers/{guild_id}/ratings/edit/{item_id}")
async def rating_item_edit(request: Request, guild_id: int, item_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    item = await db_one("SELECT * FROM rating_items WHERE id=? AND guild_id=?", (item_id, str(guild_id)))
    if not item:
        return RedirectResponse(f"/servers/{guild_id}?tab=ratings&error=Eintrag+nicht+gefunden", status_code=302)
    form = await request.form()
    label = form.get("label", "").strip()
    url = form.get("url", "").strip()
    image_url = form.get("image_url", "").strip()
    remove_image = bool(form.get("remove_image", ""))
    recommended = bool(form.get("recommended", ""))
    if not label:
        return RedirectResponse(f"/servers/{guild_id}?tab=ratings&error=Name+erforderlich", status_code=302)
    if len(label) > 100:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=ratings&error=Name+zu+lang+(max.+100+Zeichen)", status_code=302
        )
    if url and not url.startswith(("http://", "https://")):
        return RedirectResponse(f"/servers/{guild_id}?tab=ratings&error=Ungültige+URL", status_code=302)
    try:
        upload_data, upload_filename = await _read_embed_image_upload(form.get("image_file"))
    except ValueError as msg:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=ratings&error={urllib.parse.quote(str(msg))}", status_code=302
        )
    if upload_data and image_url:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=ratings&error=Entweder+Bild-URL+ODER+Datei,+nicht+beides", status_code=302
        )
    if image_url and not image_url.startswith(("http://", "https://")):
        return RedirectResponse(f"/servers/{guild_id}?tab=ratings&error=Ungültige+Bild-URL", status_code=302)
    # Same "leave a blank field alone on a normal re-submit, only an explicit checkbox actually
    # removes it" precedent as embed_post_update's own image handling - a file input can never
    # be pre-filled, so an empty image_file/image_url on this edit must mean "keep the existing
    # picture", not "delete it".
    if remove_image:
        final_image_url, final_image_data, final_image_filename = "", "", ""
    elif upload_data:
        final_image_url, final_image_data, final_image_filename = "", upload_data, upload_filename
    elif image_url:
        final_image_url, final_image_data, final_image_filename = image_url, "", ""
    else:
        final_image_url = item.get("image_url") or ""
        final_image_data = item.get("image_data") or ""
        final_image_filename = item.get("image_filename") or ""
    await db_exec(
        "UPDATE rating_items SET label=?, url=?, recommended=?, image_url=?, image_data=?, image_filename=? WHERE id=?",
        (label, url[:500], int(recommended), final_image_url, final_image_data, final_image_filename, item_id),
    )
    await _refresh_ratings_list(bot, guild_id)
    return RedirectResponse(f"/servers/{guild_id}?tab=ratings&success=Eintrag+gespeichert", status_code=302)


@web.post("/servers/{guild_id}/ratings/delete/{item_id}")
async def rating_item_delete(request: Request, guild_id: int, item_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    # poll_votes-style cascade: an item's ratings have no meaning once the item itself is gone,
    # deleted explicitly here rather than left as orphaned rows (rating_votes has no FK/CASCADE
    # of its own, same convention as every other comma-list/child-row relationship in this app).
    await db_exec("DELETE FROM rating_votes WHERE item_id IN (SELECT id FROM rating_items WHERE id=? AND guild_id=?)",
                  (item_id, str(guild_id)))
    await db_exec("DELETE FROM rating_items WHERE id=? AND guild_id=?", (item_id, str(guild_id)))
    await _refresh_ratings_list(bot, guild_id)
    return RedirectResponse(f"/servers/{guild_id}?tab=ratings&success=Eintrag+gelöscht", status_code=302)


@web.post("/servers/{guild_id}/ratings/post")
async def rating_list_post(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse("/servers", status_code=302)
    form = await request.form()
    channel_id = form.get("channel_id", "").strip()
    if not channel_id or channel_id not in {str(c.id) for c in guild.text_channels}:
        return RedirectResponse(f"/servers/{guild_id}?tab=ratings&error=Ungültiger+Kanal", status_code=302)
    # Read the PREVIOUS channel/message BEFORE overwriting ratings_channel_id below - reading
    # them after would always see the just-written NEW channel_id, making the "did the channel
    # actually change" check below permanently true and skipping the fresh-post path even on a
    # real channel switch.
    old_channel_id = await get_guild_config(guild_id, "ratings_channel_id")
    old_message_id = await get_guild_config(guild_id, "ratings_message_id")
    await set_guild_config(guild_id, "ratings_channel_id", channel_id)
    items = await db_rows(
        "SELECT i.*, "
        "(SELECT COUNT(*) FROM rating_votes v WHERE v.item_id=i.id) AS vote_count, "
        "(SELECT AVG(stars) FROM rating_votes v WHERE v.item_id=i.id) AS avg_stars "
        "FROM rating_items i WHERE i.guild_id=? "
        "ORDER BY i.recommended DESC, avg_stars DESC, i.label COLLATE NOCASE",
        (str(guild_id),),
    )
    embed, chart_files = await _build_ratings_embed(guild_id)
    view = _RatingsListView(items)
    b = bot._bot_for_guild(guild_id)
    try:
        # Same "edit the existing message in place unless the channel changed or it's gone"
        # precedent as tickets_panel_update's own live-message handling above - a channel switch
        # just means the OLD post is orphaned where it sits (not deleted automatically, an admin
        # who moves the list to a different channel likely wants the old one either way, exactly
        # like ticket panels behave on the same kind of channel change).
        msg = None
        if old_message_id and old_channel_id == channel_id:
            old_channel = b.get_channel(int(channel_id)) if b else None
            if old_channel:
                try:
                    msg = await old_channel.fetch_message(int(old_message_id))
                except discord.NotFound:
                    msg = None
        if msg:
            await msg.edit(embed=embed, view=view, attachments=chart_files)
        else:
            channel = b.get_channel(int(channel_id)) if b else None
            if not channel:
                return RedirectResponse(f"/servers/{guild_id}?tab=ratings&error=Bot+nicht+online", status_code=302)
            msg = await channel.send(embed=embed, view=view, files=chart_files)
        if b:
            b.add_view(view)
    except Exception as e:
        return RedirectResponse(
            f"/servers/{guild_id}?tab=ratings&error=Discord-Fehler:+{urllib.parse.quote(str(e))}", status_code=302
        )
    await set_guild_config(guild_id, "ratings_message_id", str(msg.id))
    return RedirectResponse(f"/servers/{guild_id}?tab=ratings&success=Liste+gepostet", status_code=302)


@web.get("/servers/{guild_id}/ratings/{item_id}/image")
async def rating_item_image_web(request: Request, guild_id: int, item_id: int):
    """Serves an uploaded rating item's image for the dashboard's OWN edit-form preview only -
    never the actual Discord embed URL (that goes via a real message attachment, see
    build_ratings_embed's chart_files). Same pattern as poll_option_image_web above."""
    if r := auth_redirect(request): return r
    if not await _guild_access(request, guild_id):
        return RedirectResponse("/servers", status_code=302)
    row = await db_one(
        "SELECT image_data, image_filename FROM rating_items WHERE id=? AND guild_id=?",
        (item_id, str(guild_id)),
    )
    if not row or not row.get("image_data"):
        raise HTTPException(status_code=404)
    try:
        raw = base64.b64decode(row["image_data"])
    except Exception:
        raise HTTPException(status_code=404)
    ext = (row.get("image_filename") or "").rsplit(".", 1)[-1].lower()
    media_type = _EMBED_IMAGE_MEDIA_TYPES.get(ext, "application/octet-stream")
    return Response(content=raw, media_type=media_type)


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
