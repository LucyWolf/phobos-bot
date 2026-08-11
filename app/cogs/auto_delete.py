import asyncio
import discord
from discord.ext import commands
from database import db_rows, db_exec, db_one


class AutoDelete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._configs: dict = {}  # {guild_id: {channel_id: delay_seconds}}

    async def _load(self):
        rows = await db_rows("SELECT guild_id, channel_id, delay_seconds FROM auto_delete_channels")
        self._configs = {}
        for r in rows:
            gid = r["guild_id"]
            if gid not in self._configs:
                self._configs[gid] = {}
            self._configs[gid][r["channel_id"]] = r["delay_seconds"]

    async def reload(self):
        await self._load()

    @commands.Cog.listener()
    async def on_ready(self):
        await self._load()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        gid = str(message.guild.id)
        cid = str(message.channel.id)
        delay = (self._configs.get(gid) or {}).get(cid)
        if delay:
            asyncio.create_task(self._delete_later(message, delay))

    async def _delete_later(self, message: discord.Message, delay: int):
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(AutoDelete(bot))
