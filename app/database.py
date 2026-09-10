"""SQLite access layer - a handful of generic query helpers, then init_db() which both
creates the schema on a fresh install AND runs every later migration on an existing one.

Layout of this file, top to bottom:
  - db_rows/db_one/db_exec/db_exec_rowcount/db_insert - generic query helpers used
    everywhere else in the app instead of raw aiosqlite calls
  - get_config/set_config, get_guild_config/set_guild_config/get_all_guild_config -
    thin wrappers around the "config" (global) and "guild_configs" (per-server) key/value
    tables that most features store their settings in
  - init_db() - the original CREATE TABLE statements (two executescript() blocks, then a
    few standalone db.execute() calls) for the tables that existed from early on, followed
    by a long list of ALTER TABLE / later CREATE TABLE statements, each run individually in
    its own try/except so an already-applied migration on an existing install is a silent
    no-op instead of crashing startup. New tables/columns always go at the END of that list,
    never edited into the original CREATE TABLE - that's what keeps this idempotent across
    every existing deployment. Most entries carry their own comment explaining which user
    request/feature they belong to - grep for a feature name (e.g. "embed_posts") to find it.
  - log_mod_action() - shared helper for writing to "mod_actions", used by every
    moderation-style command across the cogs (warn/kick/ban/timeout/...)
"""
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
            -- Core dashboard state: global settings, dashboard accounts, per-guild settings
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

            -- Moderation: /warn, /kick, /ban etc. all log to mod_actions; warnings is just /warn
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
            -- Leveling (cogs/leveling.py): one row per member per guild, chat XP only here -
            -- voice_xp/voice_level/voice_minutes were added much later, see the migration list
            CREATE TABLE IF NOT EXISTS levels (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                messages INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            );

            -- Reaction Roles (cogs/reaction_roles.py)
            CREATE TABLE IF NOT EXISTS reaction_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                role_id INTEGER NOT NULL
            );

            -- Custom Commands (cogs/custom_commands.py): admin-defined "!trigger" -> response
            CREATE TABLE IF NOT EXISTS custom_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                trigger TEXT NOT NULL,
                response TEXT NOT NULL,
                UNIQUE(guild_id, trigger)
            );

            -- Tickets (cogs/tickets.py): one row per open/closed ticket channel; the panel
            -- config itself (name/description/button/etc.) is ticket_panels, added later
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT DEFAULT 'open',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- Giveaways (cogs/giveaways.py)
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

            -- Free Stuff (cogs/freestuff.py): free-game alerts; deal-related columns
            -- (deal_max_price/deal_channel_id/...) were added later, see migration list
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

            -- Notifications (cogs/notifications.py): Twitch live-stream alerts
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
            -- Server Log (cogs/logging_cog.py): one row per logged Discord event
            CREATE TABLE IF NOT EXISTS server_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                icon TEXT NOT NULL DEFAULT '📋',
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- Dashboard auth / multi-bot-token / access control
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
        # Feature tables added after the two executescript() blocks above, each as its own
        # db.execute() call - one CREATE TABLE per statement, in the order the feature shipped:
        # invite_codes, ticket_panels, auto_delete_channels/_pending, automod_word_presets,
        # level_roles, level_rewards, temp_voice_config/_active, scheduled_messages,
        # birthdays/_sent, twitch_apis/_access. The actual ALTER TABLE column migrations start
        # further down, at "for col in [".
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
        # ── Migration list ──────────────────────────────────────────────────────────
        # Everything from here on is ALTER TABLE (add a column to an existing table) or
        # CREATE TABLE (a whole new feature table) mixed together in chronological order -
        # each entry runs individually in its own try/except a few lines below, so an
        # already-applied one on an existing install just fails silently and moves on. Add
        # new entries at the END of this list, never edit an earlier one in place - most
        # carry their own short comment naming the feature/user-request they belong to.
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
            # User-requested ("mus das eine bild url sein kanst du nicht beides machen eins
            # reinladen und die url") - an uploaded file and a pasted URL are mutually
            # exclusive per post (only one of image_url / image_data ever populated at once),
            # enforced in main.py's embed_post_create/embed_post_update. image_data is TEXT,
            # not BLOB - stores the raw uploaded bytes base64-encoded, deliberately NOT re-
            # encoded through Pillow so animated GIFs/transparency survive untouched. TEXT
            # instead of BLOB matters here: every backup/restore path (_build_full_backup/
            # _build_guild_backup) does a blanket "SELECT *" per table and dumps the result
            # straight to JSON - a real BLOB/bytes value would crash json.dumps() the moment
            # any guild has an uploaded image, for EVERY table in that same backup, not just
            # this one. Sent to Discord as a real message attachment
            # (embed.set_image(url="attachment://" + image_filename)) rather than a URL, which
            # works regardless of whether this dashboard is itself publicly reachable (Discord
            # hosts the file once it's attached, unlike a self-served URL Discord would need to
            # be able to fetch).
            "ALTER TABLE embed_posts ADD COLUMN image_data TEXT",
            "ALTER TABLE embed_posts ADD COLUMN image_filename TEXT NOT NULL DEFAULT ''",
            # User-requested ("wäre cool wenn der bot embeded nachrichten auch in einem discord
            # forum posten könnte") - a forum channel isn't directly messageable like a text
            # channel; posting there creates a new THREAD (a "post"), and the actual embed
            # content lives on that thread's starter message, not on the forum channel itself.
            # thread_id is only ever populated when channel_id resolves to a discord.ForumChannel
            # - '' means "channel_id is/was a normal text channel", exactly like message_id
            # already means "no live message yet" when empty. Kept as a separate column rather
            # than overloading message_id, since a forum post needs BOTH the thread id (to find
            # it again / delete the whole post) and the starter message id (which happens to
            # equal the thread id in Discord's own data model, but storing it explicitly avoids
            # relying on that implementation detail staying true forever).
            "ALTER TABLE embed_posts ADD COLUMN thread_id TEXT NOT NULL DEFAULT ''",
            # Follow-up fix, found live: a forum can be configured to REQUIRE at least one tag
            # on every new post (ForumChannel.flags.require_tag) - create_thread() without
            # applied_tags then gets rejected outright by Discord's own API ("der sagt das der
            # tag fehlt ich kan keinen eintragen" - no UI existed yet to pick one). Comma-
            # separated ForumTag ids, applied via Thread.edit(applied_tags=...) - a thread's
            # tags are metadata on the THREAD, not on its starter message like the embed
            # content is, so this is edited through a different call than the message content.
            "ALTER TABLE embed_posts ADD COLUMN applied_tags TEXT NOT NULL DEFAULT ''",
            # User-requested ("ich will das du das einbaust", role-management screenshots of a
            # competing bot's dashboard) - admin-defined "IF a member has/lacks certain roles,
            # THEN add/remove roles" rules, evaluated live on every role change
            # (on_member_update in cogs/role_rules.py) or on a configurable periodic interval
            # instead (guild_configs key role_rules_interval_minutes, 0 = live). The action can
            # target a DIFFERENT guild than the one the condition was checked against
            # (action_guild_id != guild_id) for cross-server role sync between servers sharing
            # the same bot token - see cogs/role_rules.py for why that's the only reachable
            # cross-server case. match_role_ids/action_role_ids are comma-separated Discord role
            # ids, resolved defensively at evaluation time (a since-deleted role id is just
            # skipped, same convention as every other comma-list-of-ids column in this project).
            """CREATE TABLE IF NOT EXISTS role_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                match_type TEXT NOT NULL DEFAULT 'any',
                match_role_ids TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL DEFAULT 'add',
                action_guild_id TEXT NOT NULL,
                action_role_ids TEXT NOT NULL DEFAULT '',
                priority INTEGER NOT NULL DEFAULT 100,
                enabled INTEGER NOT NULL DEFAULT 1
            )""",
            # Opt-in per-channel flag: when set, Auto-Delete also deletes messages posted BY
            # THE BOT ITSELF in that channel (not other bots) - off by default, since the
            # existing "message.author.bot" early-return in on_message has always exempted
            # every bot's own messages, and the user asked for this to stay off unless
            # explicitly enabled.
            "ALTER TABLE auto_delete_channels ADD COLUMN include_bot_messages INTEGER NOT NULL DEFAULT 0",
            # Polls (cogs/polls.py) - user-requested "Abstimmungen verwalten" feature. One
            # button per option (poll_options), one row per (poll, user, option) vote so a
            # multiple-choice poll's per-user toggle and a single-choice poll's "replace the
            # whole vote" both just become simple DELETE/INSERT pairs against poll_votes,
            # no separate "current choice" column to keep in sync. Deliberately NOT added to
            # _BACKUP_FEATURE_TABLES in main.py - same reasoning as giveaways (also absent
            # there): a poll is a time-bound live event, not reusable admin configuration like
            # a ticket panel.
            """CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                message_id TEXT NOT NULL DEFAULT '',
                question TEXT NOT NULL,
                multiple_choice INTEGER NOT NULL DEFAULT 0,
                ends_at TEXT NOT NULL DEFAULT '',
                ended INTEGER NOT NULL DEFAULT 0,
                created_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS poll_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER NOT NULL,
                option_index INTEGER NOT NULL,
                label TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS poll_votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                option_id INTEGER NOT NULL,
                UNIQUE(poll_id, user_id, option_id)
            )""",
            # Optional per-poll image, dashboard-only (not settable via /poll-create - a file
            # upload doesn't fit a slash command, and one more text param felt like scope creep
            # for a chat-quick-poll command). Same three-column shape as embed_posts
            # (image_url XOR image_data+image_filename) so the already-existing
            # _read_embed_image_upload()/_embed_post_files() helpers in main.py can be reused
            # as-is instead of duplicating that validation/encoding logic.
            "ALTER TABLE polls ADD COLUMN image_url TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE polls ADD COLUMN image_data TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE polls ADD COLUMN image_filename TEXT NOT NULL DEFAULT ''",
            # Per-OPTION image + link (e.g. a VRChat world's cover image + its world page URL,
            # one per map/option in the same poll) - user-requested follow-up, distinct from the
            # per-POLL image above which is one shared banner for the whole poll.
            "ALTER TABLE poll_options ADD COLUMN image_url TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE poll_options ADD COLUMN link_url TEXT NOT NULL DEFAULT ''",
            # Follow-up to the above: per-option upload was initially left out (25 option rows
            # each with their own file input seemed unwieldy) but the user asked for it anyway
            # right after shipping URL-only - same image_url XOR image_data+image_filename
            # shape as the per-poll image, reusing the identical upload/attachment helpers.
            "ALTER TABLE poll_options ADD COLUMN image_data TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE poll_options ADD COLUMN image_filename TEXT NOT NULL DEFAULT ''",
            # User-requested per-option image size toggle - Discord's embeds only offer two
            # actual size variants for an image (there's no continuous scale): a large one
            # (Embed.set_image, full embed width, rendered below the text) or a small one
            # (Embed.set_thumbnail, a small square in the embed's top-right corner). Default
            # 'large' preserves the exact existing look for every option created before this.
            "ALTER TABLE poll_options ADD COLUMN image_size TEXT NOT NULL DEFAULT 'large'",
            # Follow-up: 'large'/'small' only expose Discord's two native embed-image variants,
            # with no size in between - user asked for a real adjustable in-between size after
            # finding 'small' (the fixed ~80x80px thumbnail) too small for what they wanted.
            # image_size gains a third value 'custom': when set, the image is actually resized
            # server-side (via Pillow, see _resize_image_bytes in main.py) to image_width pixels
            # wide before being attached, so Discord renders it at that real pixel size via
            # set_image() instead of being locked to the thumbnail's fixed square. 0 (default)
            # means "no custom width set" - only meaningful when image_size == 'custom'.
            "ALTER TABLE poll_options ADD COLUMN image_width INTEGER NOT NULL DEFAULT 0",
            # User liked the emoji vote bar (v1.15.26) and asked for several selectable variants
            # instead of the one fixed purple-square look - one style PER POLL (set at creation,
            # changeable when editing), not a single server-wide default. 'purple_square' as the
            # default is deliberately the exact style that already shipped, so an existing poll's
            # bar keeps looking exactly the same after this migration - selectable emoji pairs
            # used to live in a BAR_STYLES dict in cogs/polls.py, since removed (see below).
            "ALTER TABLE polls ADD COLUMN bar_style TEXT NOT NULL DEFAULT 'purple_square'",
            # bar_style above was rejected on sight ("so meinte ich das nicht ... ich meinte ein
            # Slider") in favor of a genuine RGB color picker whose bar is rendered to actually
            # LOOK smoothly colored (see cogs/polls.py's _render_combined_poll_image) - column
            # kept per this project's "never drop a column" convention, but now unused/superseded
            # by bar_color below; every current codepath ignores it.
            "ALTER TABLE polls ADD COLUMN bar_color TEXT NOT NULL DEFAULT '#7c3aed'",
            # User-requested: schedule a poll to start in the future instead of always posting
            # immediately on creation ("ich will angeben können wann die anfängt und wann die
            # aufhärt"). '' means "start immediately" (the only behavior that existed before
            # this column) - a set value is a Europe/Berlin-normalized ISO datetime string,
            # same storage convention as scheduled_messages.send_at/event_series.next_start_at.
            "ALTER TABLE polls ADD COLUMN starts_at TEXT NOT NULL DEFAULT ''",
            # Paired with starts_at: when the end mode is "duration" rather than a fixed
            # ends_at datetime, the actual duration (in minutes) is persisted here so it can be
            # resolved into a real ends_at at the moment the poll actually starts (which, for a
            # scheduled poll, is later than poll-creation time - ends_at itself can't be
            # precomputed at creation for that mode). 0 = no duration set (poll never
            # auto-ends). For an immediately-started poll this is resolved into ends_at right
            # away, same as before this column existed.
            "ALTER TABLE polls ADD COLUMN duration_minutes INTEGER NOT NULL DEFAULT 0",
            # User-requested: the "Gestartet: vor X" line is now OFF by default ("das gestartet
            # brauche wir nicht") - only shown when this is explicitly turned on per poll ("mach
            # die möglichkeit rein das mann das aktivieren kann"), hence defaulting to 0/off for
            # both brand-new polls and every already-existing one.
            "ALTER TABLE polls ADD COLUMN show_started INTEGER NOT NULL DEFAULT 0",
            # User-requested: a per-poll opt-in ranking list ("Spiel 1: X", "Spiel 2: Y", ...)
            # sorted by vote count, for game-night-style polls with 3+ options - off by default
            # ("nur wenn ich das dann aktiviere"), shown alongside the existing bar chart, live
            # (updates with every vote, not just once the poll ends).
            "ALTER TABLE polls ADD COLUMN show_ranking INTEGER NOT NULL DEFAULT 0",
            # Ratings (cogs/ratings.py) - separate, persistent feature from polls: an admin-
            # curated catalog of maps/sites/games/whatever ("die maps oder seiten in eine liste
            # eintragen") that members can star-rate at any time via /bewerten, not a one-shot
            # time-boxed vote. One row per item, one row per (item, user) star rating - a re-
            # rating REPLACES the user's previous one rather than accumulating (confirmed:
            # "pro map/link/spiel ... hat einer nur 1 stern"), so a plain UNIQUE(item_id,user_id)
            # + INSERT OR REPLACE is enough, no separate "current rating" bookkeeping needed.
            # `recommended` is a manual per-item admin flag, independent of the star average -
            # both signals ("automatisch die best-bewerteten" AND "Admin markiert manuell") are
            # meant to coexist side by side, not be an either/or choice (confirmed: "beides
            # einstellbar") - the average is simply computed on read from rating_votes, never
            # stored redundantly on rating_items itself.
            """CREATE TABLE IF NOT EXISTS rating_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                label TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                recommended INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS rating_votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                stars INTEGER NOT NULL,
                UNIQUE(item_id, user_id)
            )""",
            # User-reported: "der button zum schließen von tickets sollte einfach umbenennbar
            # sein weil englisch und so" - the in-ticket "Ticket schließen" close button
            # (cogs/tickets.py's CloseTicketView) was the only remaining hardcoded-label button
            # in the whole ticket flow; the panel's OWN open-ticket button already got this via
            # `button_label` back when tickets first shipped. Default matches the previous
            # hardcoded text exactly, so an already-published panel's behavior is unchanged
            # until an admin explicitly edits it.
            "ALTER TABLE ticket_panels ADD COLUMN close_button_label TEXT DEFAULT 'Ticket schließen'",
            # User-requested ("wäre cool wenn man da auch ein bild rein machen könnte genau wie
            # bei umfragen") - same three-column URL-XOR-upload shape as poll_options'
            # image_url/image_data/image_filename, so main.py can reuse the same
            # _read_embed_image_upload()/_embed_post_files() validation/encoding helpers as-is
            # instead of duplicating that logic a third time.
            "ALTER TABLE rating_items ADD COLUMN image_url TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE rating_items ADD COLUMN image_data TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE rating_items ADD COLUMN image_filename TEXT NOT NULL DEFAULT ''",
            # User-requested ("es wäre schön wenn mann den moderatoren nur zu bestimmte rechte
            # geben kann mansche brauchen nur umfragen oder tikets") - a per-moderator, per-
            # server restriction ON TOP OF the existing user_guild_permissions grant (that one
            # is all-or-nothing: this whole server's dashboard, or none of it). Empty/unset
            # means UNRESTRICTED (every tab the server itself has enabled) - the opposite
            # default of guild_configs' own "enabled_features" column, since this is an opt-in
            # NARROWING an admin applies to an already-granted moderator, not an opt-in
            # enabling - an existing grant keeps working exactly as before until an admin
            # explicitly restricts it on the "👥 Nutzer" tab.
            "ALTER TABLE user_guild_permissions ADD COLUMN allowed_tabs TEXT NOT NULL DEFAULT ''",
            # User-requested ("ich brauche einen einstelbaren filter was ich im log sehen
            # will") - a stable, machine-readable category per server_logs row so the
            # dashboard Log page can filter by event type. Needed because the existing
            # `icon` column alone can't disambiguate: multiple event types share the same
            # icon (✏️ covers nickname/message-edit/channel-rename, 🗑️ covers message-
            # delete/bulk-delete/channel-delete, ✅ covers unban/timeout-lifted) - filtering
            # on icon would group unrelated events together. Empty default keeps every
            # already-logged row matching "show all" until the next event writes a real
            # category (cogs/logging_cog.py backfills nothing retroactively - old rows
            # simply always pass an active filter, same "don't touch history" precedent as
            # ticket_panels.status/message_id on backup restore).
            "ALTER TABLE server_logs ADD COLUMN category TEXT NOT NULL DEFAULT ''",
            # Per-user display preference (same mechanism as the existing log_limit column
            # from v1.4.15) - which of the 9 event categories to show on the Log page.
            # Empty = show everything (unrestricted), same "empty = all" convention as
            # user_guild_permissions.allowed_tabs above - a user who's never touched the
            # filter, or who re-checks every box, sees the full log exactly like before
            # this feature existed.
            "ALTER TABLE users ADD COLUMN log_categories TEXT NOT NULL DEFAULT ''",
            # User-requested ("🗓️ Events pausierbar machen") - a recurring event series'
            # existing `active` column is never actually set to 0 anywhere in the code (the
            # delete route hard-DELETEs the row instead) - reusing it for pause/resume would
            # have meant a paused series either vanishes from _event_series_list's own
            # `WHERE active=1` filter (no way to see/resume it) or that query would need
            # loosening in a way that risks conflating "paused" with a future real soft-delete
            # need. A dedicated column keeps both concepts separate: `_check_recurring` skips
            # paused series (no new occurrence gets created while paused), but the dashboard
            # list keeps showing them so there's something to click "Fortsetzen" on. Resuming
            # an overdue series fires its next occurrence immediately on the next 5-minute
            # tick - same "catch up on what was missed" behavior already used everywhere else
            # in this project for a bot that was offline/paused past a due time (giveaways,
            # polls), not silently skipped.
            "ALTER TABLE event_series ADD COLUMN paused INTEGER NOT NULL DEFAULT 0",
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
