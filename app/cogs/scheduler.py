import calendar
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

# Kept identical to main.py's own copies (events_create/events_edit) - both must announce the
# exact same text so a viewer can't tell the difference between a first occurrence created via
# the dashboard and a later one recreated here.
_EVENT_START_MESSAGE = "🔴 Das Event startet jetzt!"
_EVENT_END_MESSAGE = "🏁 Das Event ist jetzt beendet!"


def _aware(dt_naive: datetime.datetime, tz) -> datetime.datetime:
    """Duplicated from main.py (see its own copy's docstring for why plain .replace() is wrong
    under pytz) - main.py is not something a dynamically-loaded cog should import from."""
    return tz.localize(dt_naive) if hasattr(tz, "localize") else dt_naive.replace(tzinfo=tz)


def _add_recurrence_interval(dt: datetime.datetime, recurrence: str) -> datetime.datetime:
    """Duplicated from main.py's own copy (same reasoning as _aware above) - advances a
    timezone-aware datetime by one event_series recurrence step, clamping "monthly" to the
    target month's actual day count."""
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


class Scheduler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._check.start()
        self._check_recurring.start()

    def cog_unload(self):
        self._check.cancel()
        self._check_recurring.cancel()

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

    @tasks.loop(minutes=5)
    async def _check_recurring(self):
        # User-requested ("ich will bei den events wiederholende sachen da auch eintragen
        # können") - discord.py has no native support for Discord's own recurrence_rule field
        # (Rapptz/discord.py#9685, still open/unmerged as of the current release) - this
        # recreates a fresh one-off Discord event whenever a series' next_start_at is reached,
        # functionally recurring without depending on that missing library feature. 5-minute
        # granularity is plenty here (unlike the 1-minute reminder-firing loop above, a new
        # occurrence being created a few minutes into its own start time is harmless - Discord
        # events don't need to exist before they start, only their reminders do, and those are
        # scheduled fresh below relative to the ACTUAL configured start time, not "now").
        berlin_tz = ZoneInfo("Europe/Berlin")
        now = datetime.datetime.now(berlin_tz).strftime("%Y-%m-%dT%H:%M")
        series_rows = await db_rows(
            "SELECT * FROM event_series WHERE active=1 AND next_start_at <= ?", (now,)
        )
        for series in series_rows:
            try:
                await self._create_next_occurrence(series, berlin_tz)
            except Exception as e:
                # Deliberately does NOT advance next_start_at on failure (a transient Discord
                # API hiccup, a since-deleted announcement/voice channel, the guild not being
                # reachable by this token) - retried every tick until it either succeeds or an
                # admin fixes the underlying cause / deletes the series, same "keep retrying,
                # log so it's not silently invisible" principle as the reminder loop above.
                print(f"[Scheduler] recurring event series {series['id']} failed: {e!r}")

    async def _create_next_occurrence(self, series: dict, berlin_tz) -> None:
        guild = self.bot.get_guild(int(series["guild_id"]))
        if not guild:
            return  # a different bot instance's guild in a multi-token setup, or unreachable - retry next tick
        start_dt = _aware(datetime.datetime.fromisoformat(series["next_start_at"]), berlin_tz)
        end_dt = None
        if series.get("duration_minutes") is not None:
            end_dt = start_dt + datetime.timedelta(minutes=series["duration_minutes"])

        kwargs = {
            "name": series["name"],
            "description": series["description"] or None,
            "start_time": start_dt,
            "privacy_level": discord.PrivacyLevel.guild_only,
        }
        if series["entity_type"] == "external":
            kwargs["entity_type"] = discord.EntityType.external
            kwargs["location"] = series["location"] or guild.name
            # Discord requires an end_time for external events - the original occurrence
            # enforced that at creation time (main.py's events_create), so a series row for an
            # external event always has duration_minutes set; this fallback only guards against
            # a theoretical NULL slipping through some future code path, not an expected case.
            kwargs["end_time"] = end_dt or (start_dt + datetime.timedelta(hours=1))
        else:
            channel = None
            if series.get("channel_id"):
                try:
                    channel = guild.get_channel(int(series["channel_id"]))
                except (ValueError, TypeError):
                    channel = None
            if not channel:
                print(f"[Scheduler] recurring event series {series['id']}: voice channel not found, skipping")
                return
            kwargs["entity_type"] = discord.EntityType.voice
            kwargs["channel"] = channel
            if end_dt:
                kwargs["end_time"] = end_dt

        event = await guild.create_scheduled_event(**kwargs)

        if series.get("announce_channel_id"):
            reminders = await db_rows(
                "SELECT offset_minutes, message FROM event_series_reminders WHERE series_id=?", (series["id"],)
            )
            entries = [(0, _EVENT_START_MESSAGE)] + [(r["offset_minutes"], r["message"]) for r in reminders]
            for off_min, msg in entries:
                fire_at = (start_dt - datetime.timedelta(minutes=off_min)).astimezone(berlin_tz)
                await db_exec(
                    "INSERT INTO scheduled_messages (guild_id, channel_id, message, send_at, event_id) VALUES (?,?,?,?,?)",
                    (series["guild_id"], series["announce_channel_id"], msg,
                     fire_at.strftime("%Y-%m-%dT%H:%M"), str(event.id)),
                )
            if series.get("notify_end") and end_dt:
                fire_at_end = end_dt.astimezone(berlin_tz)
                await db_exec(
                    "INSERT INTO scheduled_messages (guild_id, channel_id, message, send_at, event_id) VALUES (?,?,?,?,?)",
                    (series["guild_id"], series["announce_channel_id"], _EVENT_END_MESSAGE,
                     fire_at_end.strftime("%Y-%m-%dT%H:%M"), str(event.id)),
                )

        next_start = _add_recurrence_interval(start_dt, series["recurrence"]).astimezone(berlin_tz)
        await db_exec(
            "UPDATE event_series SET next_start_at=?, last_discord_event_id=? WHERE id=?",
            (next_start.strftime("%Y-%m-%dT%H:%M"), str(event.id), series["id"]),
        )

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

    @_check_recurring.before_loop
    async def _before_recurring(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Scheduler(bot))
