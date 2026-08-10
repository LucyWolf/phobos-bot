import asyncio
import aiosqlite
from pathlib import Path
import discord
from discord.ext import commands

DB_PATH = Path("/app/data/modbot.db")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute("""
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
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def get_token() -> str | None:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT value FROM config WHERE key = 'discord_token'")
            row = await cursor.fetchone()
            return row[0] if row else None
    except Exception:
        return None


async def wait_for_token() -> str:
    print("Warte auf Discord Token (bitte im Web-Dashboard eintragen)...")
    while True:
        token = await get_token()
        if token:
            return token
        await asyncio.sleep(5)


@bot.event
async def on_ready():
    await bot.load_extension("cogs.moderation")
    print(f"Bot online als {bot.user} (ID: {bot.user.id})")


async def main():
    await init_db()
    token = await wait_for_token()
    async with bot:
        await bot.start(token)


asyncio.run(main())
