import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    # See main.py's import of the same name for why: Chaquopy (Android) bundles Python 3.8,
    # which predates zoneinfo (3.9+); pytz is the pure-Python, self-contained substitute there.
    from pytz import timezone as ZoneInfo

import discord
from discord.ext import commands, tasks
from database import db_rows, db_exec


class Scheduler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._check.start()

    def cog_unload(self):
        self._check.cancel()

    @tasks.loop(minutes=1)
    async def _check(self):
        # main.py's events_create/events_edit always normalize event reminder/announcement
        # send_at values to Europe/Berlin wall-clock time before storing (see berlin_tz there).
        # Comparing against a naive datetime.now() only happened to work because the reference
        # docker-compose.yml sets TZ=Europe/Berlin - on any deployment where the container's
        # system timezone differs (a real risk given self-hosting by others, e.g. the planned
        # hosting product), reminders/announcements would fire at a systematically wrong time.
        now = datetime.datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%dT%H:%M")
        rows = await db_rows(
            "SELECT * FROM scheduled_messages WHERE sent=0 AND send_at <= ?", (now,)
        )
        for row in rows:
            try:
                ch = self.bot.get_channel(int(row["channel_id"]))
            except (ValueError, TypeError):
                continue
            if not ch:
                continue
            try:
                if row.get("event_id"):
                    embed, event_gone = await self._build_event_embed(row)
                    if event_gone:
                        # The event was deleted directly via Discord's own UI, not through the
                        # dashboard's delete route (which cleans up its pending reminders
                        # itself) - suppress this stale reminder instead of falling back to
                        # plain text, which would announce an event that no longer exists.
                        await db_exec("UPDATE scheduled_messages SET sent=1 WHERE id=?", (row["id"],))
                        continue
                    if embed:
                        await ch.send(embed=embed)
                    else:
                        await ch.send(row["message"])
                else:
                    await ch.send(row["message"])
                await db_exec("UPDATE scheduled_messages SET sent=1 WHERE id=?", (row["id"],))
            except Exception as e:
                # Unlike `if not ch: continue` above (which can legitimately mean another bot
                # instance owns this channel in a multi-bot setup), reaching this point means
                # THIS instance did resolve the channel - a failure here is a real, likely
                # persistent problem (missing "Send Messages" permission, etc.). Without this
                # log the row just silently retries every single minute forever with zero
                # visibility for the admin, unlike every other retry-on-failure path in the
                # project (auto_delete.py, notifications.py) which all print on failure.
                print(f"[Scheduler] failed to send scheduled message {row['id']} to channel {row['channel_id']}: {e!r}")

    async def _build_event_embed(self, row):
        """Returns (embed, event_gone). event_gone=True means the event was confirmed deleted
        (404 from Discord) - any other failure (network hiccup, guild not found) returns
        (None, False) so the caller still falls back to sending the plain reminder text,
        rather than silently dropping a reminder for an event that might still exist."""
        guild = self.bot.get_guild(int(row["guild_id"]))
        if not guild:
            return None, False
        try:
            event = await guild.fetch_scheduled_event(int(row["event_id"]))
        except discord.NotFound:
            return None, True
        except Exception:
            return None, False
        embed = discord.Embed(
            title=f"🗓️ {event.name}",
            description=row["message"] or event.description,
            url=event.url,
            color=0x7C3AED,
        )
        start_str = self._fmt_local(event.start_time)
        if start_str:
            embed.add_field(name="Start", value=start_str, inline=True)
        end_str = self._fmt_local(event.end_time)
        if end_str:
            embed.add_field(name="Ende", value=end_str, inline=True)
        if event.entity_type.name == "external" and event.location:
            embed.add_field(name="Ort", value=event.location, inline=False)
        elif event.channel:
            embed.add_field(name="Ort", value=event.channel.mention, inline=False)
        return embed, False

    def _fmt_local(self, dt):
        if not dt:
            return None
        try:
            return dt.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M")
        except Exception:
            return None

    @_check.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Scheduler(bot))
