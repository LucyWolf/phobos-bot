import os
import aiosqlite
from pathlib import Path
from typing import Optional

# Defaults to the Docker container path - override via PHOBOS_DB_PATH for non-Docker setups
# (e.g. running directly under Termux on Android, where /app/data doesn't exist/isn't writable).
DB_PATH = Path(os.environ.get("PHOBOS_DB_PATH", "/app/data/phobos.db"))
# Harmless no-op under Docker (the volume mount already provides /app/data) - needed for a
# non-Docker PHOBOS_DB_PATH pointing at a directory nothing else has created yet.
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


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
            "ALTER TABLE giveaways ADD COLUMN winner_ids TEXT DEFAULT ''",
            # reaction_roles never had a DB-level uniqueness guarantee on (guild_id,
            # message_id, emoji) - the application layer (rr_add/rr_remove in main.py) has
            # deduplicated new inserts since v1.7.6, but backup restore writes directly via
            # INSERT OR IGNORE with no matching index to ignore against, so restoring the same
            # (or an overlapping) server backup more than once silently piles up duplicate
            # rows - confirmed live by actually restoring a test backup twice. Existing
            # duplicates have to be cleaned up BEFORE the unique index below can even be
            # created (SQLite refuses to build a unique index over data that already violates
            # it) - keeps the highest id (most recently inserted/most likely most current) per
            # group, discards the rest.
            """DELETE FROM reaction_roles WHERE id NOT IN (
                SELECT MAX(id) FROM reaction_roles GROUP BY guild_id, message_id, emoji
            )""",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_reaction_roles_unique ON reaction_roles(guild_id, message_id, emoji)",
            """CREATE TABLE IF NOT EXISTS amp_configs (
                guild_id TEXT PRIMARY KEY,
                label TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                password TEXT NOT NULL DEFAULT ''
            )""",
            "ALTER TABLE amp_configs ADD COLUMN command_channel_id TEXT DEFAULT ''",
            """CREATE TABLE IF NOT EXISTS amp_instance_commands (
                guild_id TEXT NOT NULL,
                instance_id TEXT NOT NULL,
                prefix TEXT NOT NULL,
                PRIMARY KEY (guild_id, instance_id)
            )""",
            # A single shared prefix (generating {prefix}-start/-stop/-restart) turned out not
            # to be what was wanted - "ich kann dort nur start befehl anpassen ich will aber
            # auch getrent vom start auch stop und restart befehl anpassen können" - replaced by
            # three fully independent, freely-named columns. `prefix` itself is left in place,
            # unused (same "don't drop columns" convention as elsewhere in this file) - every
            # future write always supplies '' for it since the column is still NOT NULL. The old
            # per-prefix unique index no longer makes sense once every row's prefix is just ''
            # (would reject a second instance's row outright) - name collisions across the three
            # new columns are checked at the application level in main.py instead, since a
            # single-column UNIQUE INDEX can't express "unique across any of these 3 columns".
            "DROP INDEX IF EXISTS idx_amp_cmd_prefix",
            "ALTER TABLE amp_instance_commands ADD COLUMN start_name TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE amp_instance_commands ADD COLUMN stop_name TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE amp_instance_commands ADD COLUMN restart_name TEXT NOT NULL DEFAULT ''",
            # Renamed from age_verify_* to auto_kick_* (v1.14.50 shipped under the old name for
            # under a day before the rename request came in) - the single warn_hours/message
            # pair also became a full list of admin-managed reminders at that same rename, so
            # the old age_verify_warned tracking table's shape no longer fits either. Nothing
            # to migrate forward (the feature had just shipped, not yet in real use) - dropped
            # outright rather than left behind as a permanently dead table.
            "DROP TABLE IF EXISTS age_verify_warned",
            # One row per configured reminder DM for a guild - hours is the offset after join it
            # fires at, admin-managed via the dashboard (add/delete rows), same list-of-rows
            # pattern as level_roles/automod_word_presets elsewhere in this file.
            """CREATE TABLE IF NOT EXISTS auto_kick_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                hours INTEGER NOT NULL,
                message TEXT NOT NULL
            )""",
            # Tracks which specific reminder(s) a member has already received, keyed together
            # with the exact member.joined_at each row was sent for - if that no longer matches
            # the member's CURRENT joined_at (they left and rejoined), the row is stale and
            # cogs/auto_kick.py treats it as if that reminder was never sent, so a rejoin always
            # gets a fresh reminder/kick cycle instead of silently inheriting leftover rows from
            # a previous membership.
            """CREATE TABLE IF NOT EXISTS auto_kick_sent (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                reminder_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, reminder_id)
            )""",
            # User-requested ("ich will bei den events wiederholende sachen da auch eintragen
            # können") - Discord's own native recurring-event field (recurrence_rule) is still
            # unsupported by discord.py even as of its latest release (Rapptz/discord.py#9685,
            # open since 2024, unmerged) - checked directly against the library's GitHub repo
            # before building this, an upgrade would not have helped. This table instead drives
            # a bot-side workaround: cogs/scheduler.py periodically creates a fresh one-off
            # Discord scheduled event whenever `next_start_at` is reached, then advances it by
            # one recurrence interval - functionally recurring, without ever depending on
            # Discord's own (nonexistent) recurrence support. Everything needed to recreate the
            # NEXT occurrence's `create_scheduled_event()` call lives here; `duration_minutes`
            # (not an absolute end_at) so a fresh end_time can be derived relative to each new
            # occurrence's own start instead of drifting toward a single fixed original end.
            """CREATE TABLE IF NOT EXISTS event_series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                entity_type TEXT NOT NULL,
                channel_id TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                duration_minutes INTEGER,
                announce_channel_id TEXT NOT NULL DEFAULT '',
                notify_end INTEGER NOT NULL DEFAULT 0,
                recurrence TEXT NOT NULL,
                next_start_at TEXT NOT NULL,
                last_discord_event_id TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1
            )""",
            # Reminder TEMPLATES (offset+message), copied from the series' first occurrence at
            # creation time - re-instantiated as fresh scheduled_messages rows (with a fresh
            # event_id) for every future occurrence the series creates, per explicit request
            # ("Ja, automatisch mitübernehmen").
            """CREATE TABLE IF NOT EXISTS event_series_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                series_id INTEGER NOT NULL,
                offset_minutes INTEGER NOT NULL,
                message TEXT NOT NULL
            )""",
            # User-requested ("ich wil halt auch tikets damit aufbewahren die wichtig sind") -
            # optional per-panel category a closed ticket's channel gets MOVED to instead of
            # being deleted, so important tickets can be kept for later reference. Empty =
            # unchanged default behavior (delete on close).
            "ALTER TABLE ticket_panels ADD COLUMN archive_category_id TEXT NOT NULL DEFAULT ''",
            # User-requested ("ich will damit texte in schanels dort eintragen im bot ist es
            # einfacher die zu bearbeiten also in dc selber ... wo ich die chanels auswählen
            # kann und der das dan einbettet") - standalone, admin-composed rich-text posts
            # (one or more embeds each, same "+"-adds-a-separate-embed block model as
            # ticket_panels' description/ticket_message) that get posted to a chosen channel
            # and stay editable afterward from the dashboard - the actual point of the request,
            # editing a multi-line embed in a browser textarea beats doing it in Discord's own
            # message box, which has no native rich-embed authoring at all. `content` mirrors
            # ticket_panels' JSON-array-of-blocks storage format exactly (same
            # _parse_ticket_blocks()-style parsing, reused rather than reinvented).
            """CREATE TABLE IF NOT EXISTS embed_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                name TEXT NOT NULL,
                channel_id TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                message_id TEXT NOT NULL DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            # User-requested ("bei den einbettungen wäre es cool noch bilder an hängen zu
            # können und einen so genannten footer hinzu zu fügen") - per confirmed answer, ONE
            # image + ONE footer per whole post (not per "+" block) - Discord's image/footer are
            # per-embed properties, applied to the LAST embed in the post's block list.
            "ALTER TABLE embed_posts ADD COLUMN image_url TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE embed_posts ADD COLUMN footer_text TEXT NOT NULL DEFAULT ''",
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
        # User-requested ("das mann es einstelen kann das mann in den tiket eine eigene
        # nachricht verfassen kann") - the panel's own posted message and the message shown
        # inside a newly created ticket used to share the single `description` column
        # (cogs/tickets.py's _create_ticket() reused it verbatim). Splitting them into two
        # independent columns must not silently blank the in-ticket text for panels that were
        # already configured - the ALTER + backfill sit in the SAME try block so the backfill
        # only ever runs once, exactly when the column is first added: on every later restart
        # the ALTER TABLE fails first (column already exists), so this whole block is skipped
        # and a since-cleared ticket_message is never overwritten again.
        try:
            await db.execute("ALTER TABLE ticket_panels ADD COLUMN ticket_message TEXT NOT NULL DEFAULT ''")
            await db.execute("UPDATE ticket_panels SET ticket_message=description")
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
