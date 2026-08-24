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


async def db_exec_rowcount(query: str, params: tuple = ()) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(query, params)
        await db.commit()
        return cur.rowcount


async def db_insert(query: str, params: tuple = ()) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(query, params)
        await db.commit()
        return cur.lastrowid


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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS invite_codes (
                code TEXT PRIMARY KEY,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT 'Klicke unten um ein Ticket zu öffnen.',
                button_label TEXT DEFAULT 'Ticket öffnen',
                emoji TEXT DEFAULT '🎫',
                support_role_id TEXT DEFAULT '',
                category_id TEXT DEFAULT '',
                log_channel_id TEXT DEFAULT '',
                channel_id TEXT DEFAULT '',
                message_id TEXT DEFAULT '',
                status TEXT DEFAULT 'draft',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS auto_delete_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                delay_seconds INTEGER NOT NULL,
                UNIQUE(guild_id, channel_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS auto_delete_pending (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                delete_at DATETIME NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS automod_word_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                label TEXT NOT NULL,
                words TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS level_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                level INTEGER NOT NULL,
                role_id TEXT NOT NULL,
                UNIQUE(guild_id, level)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS level_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                level INTEGER NOT NULL,
                reward TEXT NOT NULL,
                UNIQUE(guild_id, level)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vrchat_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                known_instances TEXT NOT NULL DEFAULT '',
                UNIQUE(guild_id, group_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS temp_voice_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                trigger_channel_id TEXT NOT NULL,
                category_id TEXT DEFAULT '',
                name_template TEXT DEFAULT '{user}''s Channel',
                user_limit INTEGER DEFAULT 0,
                UNIQUE(guild_id, trigger_channel_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS temp_voice_active (
                channel_id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                owner_id TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                message TEXT NOT NULL,
                send_at TEXT NOT NULL,
                sent INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS birthdays (
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                birthday TEXT NOT NULL,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS birthday_sent (
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                year INTEGER NOT NULL,
                PRIMARY KEY (user_id, guild_id, year)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS twitch_apis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER,
                label TEXT NOT NULL DEFAULT 'Standard',
                client_id TEXT NOT NULL,
                client_secret TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS twitch_api_access (
                api_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (api_id, user_id)
            )
        """)
        # Migrate legacy single Twitch credentials into twitch_apis
        try:
            old_id   = await db.execute("SELECT value FROM config WHERE key='twitch_client_id'")
            old_id   = await old_id.fetchone()
            old_sec  = await db.execute("SELECT value FROM config WHERE key='twitch_client_secret'")
            old_sec  = await old_sec.fetchone()
            count    = await db.execute("SELECT COUNT(*) FROM twitch_apis")
            count    = (await count.fetchone())[0]
            if old_id and old_sec and count == 0:
                await db.execute(
                    "INSERT INTO twitch_apis (label, client_id, client_secret) VALUES (?,?,?)",
                    ("Standard", old_id[0], old_sec[0]),
                )
        except Exception:
            pass
        for col in [
            "ALTER TABLE tickets ADD COLUMN panel_id INTEGER",
            "ALTER TABLE freestuff_channels ADD COLUMN deal_max_price REAL",
            "ALTER TABLE freestuff_channels ADD COLUMN deal_min_discount INTEGER DEFAULT 75",
            "ALTER TABLE freestuff_channels ADD COLUMN deal_channel_id TEXT",
            "ALTER TABLE freestuff_channels ADD COLUMN deal_platforms TEXT",
            "ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN custom_role_id INTEGER",
            "ALTER TABLE bot_tokens ADD COLUMN owner_id INTEGER",
            "ALTER TABLE users ADD COLUMN display_name TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN position TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'de'",
            "ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT ''",
            "DROP TABLE IF EXISTS roles",
            "ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE twitch_apis ADD COLUMN owner_id INTEGER",
            "ALTER TABLE scheduled_messages ADD COLUMN event_id TEXT",
            "ALTER TABLE users ADD COLUMN totp_secret TEXT",
            "ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN totp_fail_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN log_limit INTEGER NOT NULL DEFAULT 200",
            "ALTER TABLE users ADD COLUMN totp_locked_until TEXT",
            """CREATE TABLE IF NOT EXISTS bot_token_users (
                token_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                PRIMARY KEY (token_id, user_id)
            )""",
            """CREATE TABLE IF NOT EXISTS totp_backup_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                code_hash TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            "DROP TABLE IF EXISTS admin_logs",
            "ALTER TABLE users ADD COLUMN admin_log_limit INTEGER NOT NULL DEFAULT 200",
            "ALTER TABLE users ADD COLUMN sidebar_collapsed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN nav_settings_open INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE levels ADD COLUMN voice_minutes INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE levels ADD COLUMN voice_xp INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE levels ADD COLUMN voice_level INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE vrchat_groups ADD COLUMN label TEXT NOT NULL DEFAULT ''",
        ]:
            try:
                await db.execute(col)
            except Exception:
                pass
        # Migrate legacy owner_id → bot_token_users (idempotent)
        try:
            await db.execute("""
                INSERT OR IGNORE INTO bot_token_users (token_id, user_id)
                SELECT id, owner_id FROM bot_tokens WHERE owner_id IS NOT NULL
            """)
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
