import datetime
import discord
from discord.ext import commands
from database import db_rows, db_exec, db_one

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from pytz import timezone as ZoneInfo


def _apply_template(tpl: str, member: discord.Member, channel_number: int) -> str:
    # A naive now() only happens to show the right {date}/{time} because the reference
    # docker-compose.yml sets TZ=Europe/Berlin - same underlying assumption already fixed for
    # scheduler.py/birthday.py, here it's cosmetic (a channel name) rather than a scheduling bug.
    now = datetime.datetime.now(ZoneInfo("Europe/Berlin"))
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
        # Must be an actual channel change, not just any voice state update (mute/deafen
        # toggles etc. also fire on_voice_state_update with before.channel == after.channel) -
        # otherwise a member stuck in the trigger channel (e.g. move_to() failed once due to a
        # permissions hiccup) would get a brand new temp channel created on every single
        # unrelated state change while they're still sitting there.
        if after.channel and before.channel != after.channel:
            cfg = await db_one(
                "SELECT * FROM temp_voice_config WHERE guild_id=? AND trigger_channel_id=?",
                (str(guild.id), str(after.channel.id)),
            )
            if cfg:
                tpl = cfg["name_template"] or "{user}'s Channel"
                existing = await db_rows(
                    "SELECT channel_id FROM temp_voice_active WHERE guild_id=?", (str(guild.id),)
                )
                # A short-looking template can still expand past Discord's 100-char channel
                # name limit once {user}/{name}/{count} are substituted (a long display name,
                # a large member count, ...) - the admin only controls the template, not the
                # final length, and create_voice_channel() would otherwise fail with an
                # HTTPException that the broad except below swallows silently, leaving this
                # member without a temp channel and no explanation.
                name = _apply_template(tpl, member, len(existing) + 1)[:100]
                limit = int(cfg["user_limit"] or 0)
                category = (
                    guild.get_channel(int(cfg["category_id"]))
                    if cfg["category_id"]
                    else after.channel.category
                )
                ch = None
                try:
                    ch = await guild.create_voice_channel(
                        name=name,
                        category=category,
                        user_limit=limit,
                        reason="Temp Voice",
                    )
                    # Register as tracked BEFORE move_to, not after - if move_to fails (member
                    # disconnects in the same instant, a permissions hiccup, ...) the channel
                    # would otherwise exist but be untracked in both the DB and self._temp,
                    # meaning it can never be cleaned up: the normal "delete if empty" cleanup
                    # only fires reactively when someone LEAVES a tracked channel, which never
                    # happens for a channel nobody ever successfully joined.
                    await db_exec(
                        "INSERT OR IGNORE INTO temp_voice_active (channel_id, guild_id, owner_id) VALUES (?,?,?)",
                        (str(ch.id), str(guild.id), str(member.id)),
                    )
                    self._temp.add(str(ch.id))
                    await member.move_to(ch)
                except Exception:
                    # Something after channel creation failed (move_to, or even the tracking
                    # db_exec/self._temp.add above) - checked directly on ch.members rather
                    # than "is it in self._temp", since that step itself might be the one that
                    # failed. discard()/DELETE are safe no-ops if it was never tracked.
                    if ch is not None and len(ch.members) == 0:
                        self._temp.discard(str(ch.id))
                        await db_exec("DELETE FROM temp_voice_active WHERE channel_id=?", (str(ch.id),))
                        try:
                            await ch.delete(reason="Temp Voice - Beitritt fehlgeschlagen")
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
