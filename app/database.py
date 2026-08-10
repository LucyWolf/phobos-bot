import aiosqlite
from pathlib import Path
from typing import Optional

DB_PATH = Path("/app/data/phobos.db")


async def db_rows(query: str, params: tuple = ()):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(query, params)
            return [dict(r) for r in await cur.fetchall()]
    except Exception:
        return []


async def db_one(query: str, params: tuple = ()):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(query, params)
            row = await cur.fetchone()
            return dict(row) if row else None
    except Exception:
        return None


async def db_exec(query: str, params: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(query, params)
        await db.commit()


async def get_config(key: str) -> Optional[str]:
    row = await db_one("SELECT value FROM config WHERE key = ?", (key,))
    return row["value"] if row else None


async def set_config(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO config (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


async def get_guild_config(guild_id: int, key: str) -> Optional[str]:
    row = await db_one(
        "SELECT value FROM guild_configs WHERE guild_id=? AND key=?", (guild_id, key)
    )
    return row["value"] if row else None


async def set_guild_config(guild_id: int, key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO guild_configs (guild_id,key,value) VALUES (?,?,?) ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",
            (guild_id, key, value),
        )
        await db.commit()


async def get_all_guild_config(guild_id: int) -> dict:
    rows = await db_rows("SELECT key, value FROM guild_configs WHERE guild_id=?", (guild_id,))
    return {r["key"]: r["value"] for r in rows}


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'moderator',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS guild_configs (
                guild_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (guild_id, key)
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
            CREATE TABLE IF NOT EXISTS levels (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                messages INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            );
            CREATE TABLE IF NOT EXISTS reaction_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                role_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS custom_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                trigger TEXT NOT NULL,
                response TEXT NOT NULL,
                UNIQUE(guild_id, trigger)
            );
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT DEFAULT 'open',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                prize TEXT NOT NULL,
                winners INTEGER DEFAULT 1,
                ends_at TEXT NOT NULL,
                ended INTEGER DEFAULT 0,
                created_by INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS freestuff_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL UNIQUE,
                channel_id TEXT NOT NULL,
                platforms TEXT DEFAULT 'epic'
            );
            CREATE TABLE IF NOT EXISTS freestuff_posted (
                guild_id TEXT NOT NULL,
                game_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                PRIMARY KEY (guild_id, game_id, platform)
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                discord_channel_id TEXT NOT NULL,
                target TEXT NOT NULL,
                target_name TEXT DEFAULT '',
                last_id TEXT DEFAULT '',
                live INTEGER DEFAULT 0,
                custom_message TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS server_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                icon TEXT NOT NULL DEFAULT '📋',
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at DATETIME NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bot_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL DEFAULT 'Bot',
                token TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_guild_permissions (
                user_id INTEGER NOT NULL,
                guild_id TEXT NOT NULL,
                PRIMARY KEY (user_id, guild_id)
            );
        """)
        # Migrate legacy discord_token config to bot_tokens table
        try:
            legacy = await db.execute("SELECT value FROM config WHERE key='discord_token'")
            legacy = await legacy.fetchone()
            if legacy:
                count = await db.execute("SELECT COUNT(*) FROM bot_tokens")
                count = (await count.fetchone())[0]
                if count == 0:
                    await db.execute(
                        "INSERT INTO bot_tokens (label, token) VALUES (?, ?)",
                        ("Hauptbot", legacy[0]),
                    )
        except Exception:
            pass
        # Column migrations for existing installs
        for col in [
            "ALTER TABLE freestuff_channels ADD COLUMN deal_max_price REAL",
            "ALTER TABLE freestuff_channels ADD COLUMN deal_min_discount INTEGER DEFAULT 75",
            "ALTER TABLE freestuff_channels ADD COLUMN deal_channel_id TEXT",
            "ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''",
        ]:
            try:
                await db.execute(col)
            except Exception:
                pass
        await db.commit()


async def log_mod_action(action: str, target, moderator, guild_id: int, reason: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO mod_actions (action,target_id,target_name,moderator_id,moderator_name,guild_id,reason) VALUES (?,?,?,?,?,?,?)",
            (action, target.id, str(target), moderator.id, str(moderator), guild_id, reason),
        )
        await db.commit()
