import datetime
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
                await ch.send(row["message"])
                await db_exec("UPDATE scheduled_messages SET sent=1 WHERE id=?", (row["id"],))
            except Exception:
                pass

    @_check.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Scheduler(bot))
