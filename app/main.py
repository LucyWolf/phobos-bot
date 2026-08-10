import asyncio
import secrets
from pathlib import Path
from typing import Optional

import bcrypt
import discord
import uvicorn
from discord.ext import commands
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

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


# ── Auth ──────────────────────────────────────────────────────────────────────

@web.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=302)
    only_default = await db_one("SELECT id FROM users WHERE username='admin'") and await db_one("SELECT COUNT(*) as c FROM users") == {"c": 1}
    return templates.TemplateResponse("login.html", {"request": request, "error": error, "default_creds": only_default, "version": VERSION})


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
    stats = {r["action"]: r["count"] for r in await db_rows("SELECT action, COUNT(*) as count FROM mod_actions GROUP BY action")}
    token_set = bool(await get_config("discord_token"))
    guilds = [{"id": str(g.id), "name": g.name, "members": g.member_count, "icon": str(g.icon.url) if g.icon else None} for g in bot.guilds]
    return templates.TemplateResponse("index.html", {
        **session(request), "request": request,
        "actions": actions, "stats": stats, "colors": ACTION_COLORS,
        "token_set": token_set, "guilds": guilds, "active": "dashboard",
    })


# ── Settings ──────────────────────────────────────────────────────────────────

@web.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False, error: str = "", success: str = ""):
    if r := auth_redirect(request): return r
    token = await get_config("discord_token")
    masked = ("•" * 40 + token[-6:]) if token else None
    token_set = bool(token)
    all_users = await db_rows("SELECT id, username, role, created_at FROM users ORDER BY created_at") if request.session.get("role") == "admin" else []
    return templates.TemplateResponse("settings.html", {
        **session(request), "request": request,
        "masked": masked, "saved": saved, "token_set": token_set,
        "users": all_users, "error": error, "success": success, "active": "settings",
    })


@web.post("/settings")
async def settings_save(request: Request, token: str = Form(...)):
    if r := auth_redirect(request): return r
    if token.strip():
        await set_config("discord_token", token.strip())
    return RedirectResponse("/settings?saved=true", status_code=303)


@web.post("/users/create")
async def users_create(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form(...)):
    if r := admin_redirect(request): return r
    if len(password) < 6:
        return RedirectResponse("/settings?error=Passwort+mindestens+6+Zeichen", status_code=302)
    try:
        await db_exec(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            (username.strip(), hash_pw(password), role),
        )
    except Exception:
        return RedirectResponse("/settings?error=Benutzername+bereits+vergeben", status_code=302)
    return RedirectResponse("/settings?success=Benutzer+erstellt", status_code=302)


@web.post("/users/delete/{user_id}")
async def users_delete(request: Request, user_id: int):
    if r := admin_redirect(request): return r
    if user_id == request.session.get("user_id"):
        return RedirectResponse("/settings?error=Du+kannst+dich+nicht+selbst+löschen", status_code=302)
    await db_exec("DELETE FROM users WHERE id=?", (user_id,))
    return RedirectResponse("/settings?success=Benutzer+gelöscht", status_code=302)


# ── Server Config ─────────────────────────────────────────────────────────────

@web.get("/servers/{guild_id}", response_class=HTMLResponse)
async def server_config(request: Request, guild_id: int, saved: bool = False):
    if r := auth_redirect(request): return r
    guild = bot.get_guild(guild_id)
    if not guild:
        return RedirectResponse("/", status_code=302)
    token_set = bool(await get_config("discord_token"))
    cfg = await get_all_guild_config(guild_id)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    roles = [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default()]
    categories = [{"id": str(c.id), "name": c.name} for c in guild.categories]
    return templates.TemplateResponse("server_config.html", {
        **session(request), "request": request,
        "guild": {"id": str(guild.id), "name": guild.name, "icon": str(guild.icon.url) if guild.icon else None},
        "cfg": cfg, "channels": channels, "roles": roles, "categories": categories,
        "token_set": token_set, "saved": saved, "active": "servers",
    })


@web.post("/servers/{guild_id}")
async def server_config_save(request: Request, guild_id: int):
    if r := auth_redirect(request): return r
    form = await request.form()
    keys = [
        "welcome_channel", "welcome_message", "leave_channel", "leave_message", "autorole",
        "log_channel",
        "leveling_enabled", "level_channel",
        "automod_enabled", "automod_spam_threshold", "automod_links", "automod_banned_words", "automod_action",
        "ticket_support_role", "ticket_category",
    ]
    for key in keys:
        val = form.get(key, "")
        if val:
            await set_guild_config(guild_id, key, str(val))
    return RedirectResponse(f"/servers/{guild_id}?saved=true", status_code=303)


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
