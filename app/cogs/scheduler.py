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
        now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
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
                embed = await self._build_event_embed(row) if row.get("event_id") else None
                if embed:
                    await ch.send(embed=embed)
                else:
                    await ch.send(row["message"])
                await db_exec("UPDATE scheduled_messages SET sent=1 WHERE id=?", (row["id"],))
            except Exception:
                pass

    async def _build_event_embed(self, row):
        try:
            guild = self.bot.get_guild(int(row["guild_id"]))
            if not guild:
                return None
            event = await guild.fetch_scheduled_event(int(row["event_id"]))
        except Exception:
            return None
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
        return embed

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
