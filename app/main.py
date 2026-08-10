import asyncio
import datetime
from pathlib import Path

import aiosqlite
import discord
import uvicorn
from discord import app_commands
from discord.ext import commands
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

DB_PATH = Path("/app/data/phobos.db")

# ── Database ──────────────────────────────────────────────────────────────────

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mod_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                target_name TEXT NOT NULL,
                moderator_id INTEGER NOT NULL,
                moderator_name TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.commit()


async def get_config(key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else None


async def set_config(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


async def db_rows(query: str, params: tuple = ()):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(query, params)
            return [dict(r) for r in await cur.fetchall()]
    except Exception:
        return []


async def log_action(action, target, moderator, guild_id, reason=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO mod_actions (action,target_id,target_name,moderator_id,moderator_name,guild_id,reason) VALUES (?,?,?,?,?,?,?)",
            (action, target.id, str(target), moderator.id, str(moderator), guild_id, reason),
        )
        await db.commit()


# ── Discord Bot ───────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Phobos online als {bot.user}")


@bot.tree.command(name="kick", description="Ein Mitglied kicken")
@app_commands.default_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund angegeben"):
    await member.kick(reason=reason)
    await log_action("kick", member, interaction.user, interaction.guild_id, reason)
    await interaction.response.send_message(f"{member.mention} wurde gekickt. Grund: {reason}", ephemeral=True)


@bot.tree.command(name="ban", description="Ein Mitglied bannen")
@app_commands.default_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund angegeben"):
    await member.ban(reason=reason)
    await log_action("ban", member, interaction.user, interaction.guild_id, reason)
    await interaction.response.send_message(f"{member.mention} wurde gebannt. Grund: {reason}", ephemeral=True)


@bot.tree.command(name="unban", description="User anhand ID entbannen")
@app_commands.default_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str, reason: str = "Kein Grund angegeben"):
    user = await bot.fetch_user(int(user_id))
    await interaction.guild.unban(user, reason=reason)
    await log_action("unban", user, interaction.user, interaction.guild_id, reason)
    await interaction.response.send_message(f"{user} wurde entbannt.", ephemeral=True)


@bot.tree.command(name="timeout", description="Mitglied für X Minuten timen")
@app_commands.default_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Kein Grund angegeben"):
    until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
    await member.timeout(until, reason=reason)
    await log_action("timeout", member, interaction.user, interaction.guild_id, reason)
    await interaction.response.send_message(f"{member.mention} für {minutes} Min. getimeouted.", ephemeral=True)


@bot.tree.command(name="warn", description="Mitglied verwarnen")
@app_commands.default_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO warnings (user_id, guild_id, moderator_id, reason) VALUES (?,?,?,?)",
            (member.id, interaction.guild_id, interaction.user.id, reason),
        )
        await db.commit()
    await log_action("warn", member, interaction.user, interaction.guild_id, reason)
    await interaction.response.send_message(f"{member.mention} verwarnt. Grund: {reason}", ephemeral=True)


@bot.tree.command(name="warnings", description="Verwarnungen eines Mitglieds anzeigen")
@app_commands.default_permissions(moderate_members=True)
async def warnings(interaction: discord.Interaction, member: discord.Member):
    rows = await db_rows(
        "SELECT * FROM warnings WHERE user_id=? AND guild_id=? ORDER BY timestamp DESC",
        (member.id, interaction.guild_id),
    )
    if not rows:
        await interaction.response.send_message(f"{member.mention} hat keine Verwarnungen.", ephemeral=True)
        return
    text = "\n".join(f"#{r['id']} — {r['reason']} ({r['timestamp']})" for r in rows)
    await interaction.response.send_message(f"**Verwarnungen von {member}:**\n{text}", ephemeral=True)


@bot.tree.command(name="clear", description="Nachrichten löschen")
@app_commands.default_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"{len(deleted)} Nachrichten gelöscht.", ephemeral=True)


async def run_bot():
    print("Warte auf Discord Token (bitte im Web-Dashboard eintragen)...")
    while True:
        token = await get_config("discord_token")
        if token:
            break
        await asyncio.sleep(5)
    async with bot:
        await bot.start(token)


# ── Web UI ────────────────────────────────────────────────────────────────────

web = FastAPI()
templates = Jinja2Templates(directory="templates")

ACTION_COLORS = {
    "ban": "#ef4444", "kick": "#f97316", "timeout": "#eab308",
    "warn": "#3b82f6", "unban": "#22c55e", "clear": "#8b5cf6",
}


@web.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    actions = await db_rows("SELECT * FROM mod_actions ORDER BY timestamp DESC LIMIT 50")
    stats = {r["action"]: r["count"] for r in await db_rows("SELECT action, COUNT(*) as count FROM mod_actions GROUP BY action")}
    token_set = bool(await get_config("discord_token"))
    return templates.TemplateResponse("index.html", {"request": request, "actions": actions, "stats": stats, "colors": ACTION_COLORS, "token_set": token_set})


@web.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False):
    token = await get_config("discord_token")
    masked = ("•" * 40 + token[-6:]) if token else None
    return templates.TemplateResponse("settings.html", {"request": request, "masked": masked, "saved": saved})


@web.post("/settings")
async def settings_save(token: str = Form(...)):
    if token.strip():
        await set_config("discord_token", token.strip())
    return RedirectResponse("/settings?saved=true", status_code=303)


@web.get("/api/actions")
async def api_actions():
    return await db_rows("SELECT * FROM mod_actions ORDER BY timestamp DESC LIMIT 100")


@web.get("/api/warnings")
async def api_warnings():
    return await db_rows("SELECT * FROM warnings ORDER BY timestamp DESC LIMIT 100")


# ── Entrypoint ────────────────────────────────────────────────────────────────

async def main():
    await init_db()
    server = uvicorn.Server(uvicorn.Config(web, host="0.0.0.0", port=8080, log_level="warning"))
    await asyncio.gather(server.serve(), run_bot())


asyncio.run(main())
