"""Shared writer for the opt-in "bot action" log entries (polls posted/ended, tickets opened/
closed, giveaways started/ended, warnings issued, auto-mod punishments, scheduled messages
sent, birthday congratulations sent) - user-requested addition to the Server-Log tab
("ich möchte auch in den logs haben was auf dem bot passiert aber aktivierbar und ich will
auch sehen wann umfragen gepostet werden und alles").

Deliberately a plain module, not a Cog - this project's established convention is that cogs
never import each other (see cogs/tickets.py's own duplicated _parse_ticket_blocks() docstring
for the same reasoning), only main.py imports FROM cogs. A shared plain utility module used by
several cogs is a different thing from one cog reaching into another cog's class/instance -
same category as every cog already importing from database.py.

Unlike cogs/logging_cog.py's native Discord-event hooks (always on, can only be narrowed down
via the per-channel exclude list), these bot-action categories are OFF by default per server -
an admin has to explicitly tick them on under the Log tab's "Bot-Aktionen loggen" settings
(guild_configs key `log_bot_events`, comma-separated list of enabled categories, empty =
none enabled) - matching the user's own wording, "aktivierbar" (activatable), rather than the
existing native-event categories which have no such switch.
"""
import datetime
import discord
from database import get_guild_config, db_exec

# One entry per loggable bot action. Also unioned into main.py's LOG_CATEGORIES so the
# existing per-user display filter (server_log.html's "🔍 Filter" checkboxes) covers these
# the same way it already covers the 9 native Discord-event categories.
BOT_EVENT_CATEGORIES = ("poll", "ticket", "giveaway", "warning", "automod", "scheduled", "birthday")


async def log_bot_event(bot, guild_id: int, icon: str, title: str, category: str, plain: str = ""):
    """Writes to server_logs (same 200-row-per-guild prune as logging_cog.py's _log()) and
    posts to the guild's configured log channel, but only if `category` is one of the
    categories this guild has explicitly enabled - a no-op otherwise, so calling this
    unconditionally from every relevant cog is cheap and safe even when nothing is enabled."""
    enabled_raw = await get_guild_config(guild_id, "log_bot_events") or ""
    enabled = {c.strip() for c in enabled_raw.split(",") if c.strip()}
    if category not in enabled:
        return

    try:
        await db_exec(
            "INSERT INTO server_logs (guild_id, icon, title, description, category) VALUES (?,?,?,?,?)",
            (str(guild_id), icon, title, plain[:300], category),
        )
        await db_exec(
            """DELETE FROM server_logs WHERE guild_id=? AND id NOT IN (
                SELECT id FROM server_logs WHERE guild_id=? ORDER BY id DESC LIMIT 200
            )""",
            (str(guild_id), str(guild_id)),
        )
    except Exception as e:
        print(f"[log_utils] server_logs insert failed for guild {guild_id} ({title!r}): {e!r}")

    channel_id = await get_guild_config(guild_id, "log_channel")
    if not channel_id:
        return
    try:
        channel = bot.get_channel(int(channel_id))
    except (ValueError, TypeError):
        channel = None
    if not channel:
        return
    embed = discord.Embed(
        title=f"{icon} {title}", description=plain[:2000] or None,
        color=0x8b5cf6, timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[log_utils] failed to send log embed to channel {channel_id}: {e!r}")
