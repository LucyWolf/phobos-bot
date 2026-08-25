import asyncio
import datetime
import discord
from discord.ext import commands, tasks
from database import db_rows, db_exec, db_insert


class AutoDelete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._configs: dict = {}  # {guild_id: {channel_id: delay_seconds}}
        self._tasks: dict = {}    # {pending_id: asyncio.Task}
        self._retry_stuck.start()

    def cog_unload(self):
        self._retry_stuck.cancel()

    async def _load_configs(self):
        rows = await db_rows("SELECT guild_id, channel_id, delay_seconds FROM auto_delete_channels")
        self._configs = {}
        for r in rows:
            self._configs.setdefault(r["guild_id"], {})[r["channel_id"]] = r["delay_seconds"]

    async def reload(self):
        await self._load_configs()

    @commands.Cog.listener()
    async def on_ready(self):
        await self._load_configs()
        await self._resume_pending()

    @tasks.loop(minutes=30)
    async def _retry_stuck(self):
        # A deletion that failed for a persistent reason (e.g. missing "Manage Messages")
        # deliberately isn't removed from auto_delete_pending so it can be retried - but the
        # only other place that retried it was on_ready, which fires on an actual reconnect,
        # not on any regular schedule. On a stable connection that could be days away, leaving
        # a permanently-failing message stuck (and invisible) indefinitely. _resume_pending()
        # already skips anything currently in self._tasks, so calling it here is safe - it
        # only ever picks up rows that aren't actively scheduled.
        try:
            await self._resume_pending()
        except Exception as e:
            print(f"[AutoDelete] retry loop error: {e}")

    @_retry_stuck.before_loop
    async def _before_retry(self):
        await self.bot.wait_until_ready()

    async def _resume_pending(self):
        # Deletions scheduled before a restart only lived in memory (asyncio.sleep) and were
        # silently lost when the process stopped — reschedule anything still pending in the DB
        # with whatever time remains (or delete right away if the delay already elapsed).
        rows = await db_rows("SELECT * FROM auto_delete_pending")
        now = datetime.datetime.utcnow()
        for r in rows:
            if r["id"] in self._tasks:
                continue
            try:
                delete_at = datetime.datetime.fromisoformat(r["delete_at"])
            except Exception:
                await db_exec("DELETE FROM auto_delete_pending WHERE id=?", (r["id"],))
                continue
            delay = max((delete_at - now).total_seconds(), 0)
            self._schedule(r["id"], r["channel_id"], r["message_id"], delay)

    def _schedule(self, pending_id: int, channel_id: str, message_id: str, delay: float):
        self._tasks[pending_id] = asyncio.create_task(
            self._delete_later(pending_id, channel_id, message_id, delay)
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        gid = str(message.guild.id)
        cid = str(message.channel.id)
        delay = (self._configs.get(gid) or {}).get(cid)
        if not delay:
            return
        delete_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=delay)
        pending_id = await db_insert(
            "INSERT INTO auto_delete_pending (guild_id, channel_id, message_id, delete_at) VALUES (?,?,?,?)",
            (gid, cid, str(message.id), delete_at.isoformat()),
        )
        self._schedule(pending_id, cid, str(message.id), delay)

    async def _delete_later(self, pending_id: int, channel_id: str, message_id: str, delay: float):
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            # In a multi-bot setup another bot instance may own this channel — if we can't
            # see it, leave the pending row alone so whichever instance does can still process it.
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.delete()
            except discord.NotFound:
                pass
            except Exception as e:
                # Could be a real, persistent problem (e.g. missing "Manage Messages") or just
                # this bot instance dying mid-reconnect (_run_single_bot rebuilds a fresh Bot +
                # cog on every reconnect, not only on a full process restart) — either way we
                # can't confirm the message is actually gone, so leave the row alone instead of
                # deleting it here; _retry_stuck picks it back up on its next tick (on_ready
                # would too, but that's not something to rely on for a timely retry).
                print(f"[AutoDelete] delete failed for message {message_id} in channel {channel_id}: {e}")
                return
            await db_exec("DELETE FROM auto_delete_pending WHERE id=?", (pending_id,))
        finally:
            self._tasks.pop(pending_id, None)


async def setup(bot):
    await bot.add_cog(AutoDelete(bot))
