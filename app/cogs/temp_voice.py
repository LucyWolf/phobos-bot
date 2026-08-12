import datetime
import discord
from discord.ext import commands
from database import db_rows, db_exec, db_one


def _apply_template(tpl: str, member: discord.Member, channel_number: int) -> str:
    now = datetime.datetime.now()
    return (
        tpl
        .replace("{user}",    member.display_name)
        .replace("{name}",    member.name)
        .replace("{number}",  str(channel_number))
        .replace("{date}",    now.strftime("%d.%m.%Y"))
        .replace("{time}",    now.strftime("%H:%M"))
        .replace("{count}",   str(member.guild.member_count))
    )


class TempVoice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._temp: set = set()  # active temp channel_ids (strings)

    @commands.Cog.listener()
    async def on_ready(self):
        rows = await db_rows("SELECT channel_id FROM temp_voice_active")
        self._temp = {r["channel_id"] for r in rows}
        # Clean up channels that no longer exist after a restart
        for cid in list(self._temp):
            if not self.bot.get_channel(int(cid)):
                await db_exec("DELETE FROM temp_voice_active WHERE channel_id=?", (cid,))
                self._temp.discard(cid)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild

        # ── Joining a trigger channel → create temp channel ──────────────────
        if after.channel:
            cfg = await db_one(
                "SELECT * FROM temp_voice_config WHERE guild_id=? AND trigger_channel_id=?",
                (str(guild.id), str(after.channel.id)),
            )
            if cfg:
                tpl = cfg["name_template"] or "{user}'s Channel"
                existing = await db_rows(
                    "SELECT channel_id FROM temp_voice_active WHERE guild_id=?", (str(guild.id),)
                )
                name = _apply_template(tpl, member, len(existing) + 1)
                limit = int(cfg["user_limit"] or 0)
                category = (
                    guild.get_channel(int(cfg["category_id"]))
                    if cfg["category_id"]
                    else after.channel.category
                )
                try:
                    ch = await guild.create_voice_channel(
                        name=name,
                        category=category,
                        user_limit=limit,
                        reason="Temp Voice",
                    )
                    await member.move_to(ch)
                    await db_exec(
                        "INSERT OR IGNORE INTO temp_voice_active (channel_id, guild_id, owner_id) VALUES (?,?,?)",
                        (str(ch.id), str(guild.id), str(member.id)),
                    )
                    self._temp.add(str(ch.id))
                except Exception:
                    pass

        # ── Leaving a temp channel → delete if empty ─────────────────────────
        if before.channel and str(before.channel.id) in self._temp:
            if len(before.channel.members) == 0:
                self._temp.discard(str(before.channel.id))
                await db_exec("DELETE FROM temp_voice_active WHERE channel_id=?", (str(before.channel.id),))
                try:
                    await before.channel.delete(reason="Temp Voice leer")
                except Exception:
                    pass


async def setup(bot):
    await bot.add_cog(TempVoice(bot))
