from __future__ import annotations

import random
import discord
from discord import app_commands
from discord.ext import commands, tasks
from database import db_one, db_rows, db_exec, get_guild_config

_CURVE_KEYS = {
    "text": ("leveling_curve_quad", "leveling_curve_linear", "leveling_curve_base"),
    "voice": ("leveling_voice_curve_quad", "leveling_voice_curve_linear", "leveling_voice_curve_base"),
}


def xp_for_level(level: int, quad: int = 5, linear: int = 50, base: int = 100) -> int:
    return quad * (level ** 2) + linear * level + base


def level_from_xp(xp: int, quad: int = 5, linear: int = 50, base: int = 100) -> int:
    # Used to repeatedly subtract xp_for_level(level) in a loop, incrementing level by 1 each
    # time - O(level) per call, and this runs on EVERY single XP grant (a message, a minute in
    # voice), synchronously on the bot's one event loop. With a low-cost curve (e.g. base=1,
    # quad=linear=0 - a valid, dashboard-allowed "many small levels" configuration) and enough
    # XP accumulated over months of normal activity, that could reach hundreds of thousands of
    # iterations on every subsequent message from an active member - real, noticeable lag, not
    # just a theoretical worst case.
    # Cumulative XP needed to reach level n has a closed form (sum of an arithmetic-quadratic
    # series: quad*sum(i^2) + linear*sum(i) + base*n for i in 0..n-1), so this is now a binary
    # search over that closed form instead - O(log(xp)) regardless of curve parameters, and
    # returns the exact same level the old subtraction loop would have.
    base = max(1, base)  # guards the same base=quad=linear=0 infinite-loop case the dashboard
                         # already rejects at save time - defense in depth, not a behavior change
                         # for any value that could actually reach here through normal use.

    def cumulative(n: int) -> int:
        if n <= 0:
            return 0
        return quad * (n - 1) * n * (2 * n - 1) // 6 + linear * (n - 1) * n // 2 + base * n

    lo, hi = 0, 1
    while cumulative(hi) <= xp:
        hi *= 2
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if cumulative(mid) <= xp:
            lo = mid
        else:
            hi = mid - 1
    return lo


class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cooldowns: dict = {}
        self.voice_xp_loop.start()

    def cog_unload(self):
        self.voice_xp_loop.cancel()

    async def _get_curve(self, guild_id: int, kind: str) -> tuple[int, int, int]:
        # Text and voice XP are now fully separate progressions (own totals, own levels, own
        # curve) - only the underlying xp->level math is shared between them.
        defaults = (5, 50, 100)
        values = []
        for key, default in zip(_CURVE_KEYS[kind], defaults):
            raw = await get_guild_config(guild_id, key)
            try:
                values.append(int(raw) if raw else default)
            except ValueError:
                values.append(default)
        return tuple(values)

    async def _add_text_xp(self, member: discord.Member, xp_gain: int):
        quad, linear, base = await self._get_curve(member.guild.id, "text")
        # Atomic upsert-increment instead of read-modify-write, so concurrent grants (e.g. two
        # messages processed close together) can't lose one of the two XP amounts. New rows
        # always start at level 0 (not the pre-computed target level) so the comparison below
        # sees a real change and fires the level-up announcement/role sync - a low-base curve
        # can easily grant enough XP in a single message to clear level 1+ on a brand-new row.
        await db_exec(
            "INSERT INTO levels (user_id, guild_id, xp, level, messages) VALUES (?,?,?,0,?) "
            "ON CONFLICT(user_id, guild_id) DO UPDATE SET "
            "xp = levels.xp + excluded.xp, messages = levels.messages + excluded.messages",
            (member.id, member.guild.id, xp_gain, 1),
        )
        row = await db_one(
            "SELECT xp, level FROM levels WHERE user_id=? AND guild_id=?",
            (member.id, member.guild.id),
        )
        if not row:
            return
        new_level = level_from_xp(row["xp"], quad, linear, base)
        if new_level != row["level"]:
            await db_exec(
                "UPDATE levels SET level=? WHERE user_id=? AND guild_id=?",
                (new_level, member.id, member.guild.id),
            )
            if new_level > row["level"]:
                await self._announce_levelup(member, new_level, "text")
                await self._sync_level_roles(member)

    async def _add_voice_xp(self, member: discord.Member, xp_gain: int):
        quad, linear, base = await self._get_curve(member.guild.id, "voice")
        # New rows start at voice_level 0, same reasoning as _add_text_xp - see comment there.
        await db_exec(
            "INSERT INTO levels (user_id, guild_id, voice_xp, voice_level, voice_minutes) VALUES (?,?,?,0,?) "
            "ON CONFLICT(user_id, guild_id) DO UPDATE SET "
            "voice_xp = levels.voice_xp + excluded.voice_xp, "
            "voice_minutes = levels.voice_minutes + excluded.voice_minutes",
            (member.id, member.guild.id, xp_gain, 1),
        )
        row = await db_one(
            "SELECT voice_xp, voice_level FROM levels WHERE user_id=? AND guild_id=?",
            (member.id, member.guild.id),
        )
        if not row:
            return
        new_level = level_from_xp(row["voice_xp"], quad, linear, base)
        if new_level != row["voice_level"]:
            await db_exec(
                "UPDATE levels SET voice_level=? WHERE user_id=? AND guild_id=?",
                (new_level, member.id, member.guild.id),
            )
            if new_level > row["voice_level"]:
                await self._announce_levelup(member, new_level, "voice")
                await self._sync_level_roles(member)

    async def _sync_level_roles(self, member: discord.Member):
        # Level roles react to whichever of text/voice level is higher - reached either way.
        row = await db_one(
            "SELECT level, voice_level FROM levels WHERE user_id=? AND guild_id=?",
            (member.id, member.guild.id),
        )
        if not row:
            return
        effective_level = max(row["level"], row["voice_level"])
        rows = await db_rows(
            "SELECT level, role_id FROM level_roles WHERE guild_id=? ORDER BY level",
            (member.guild.id,),
        )
        eligible = [r for r in rows if r["level"] <= effective_level]
        if not eligible:
            return
        mode = await get_guild_config(member.guild.id, "leveling_role_mode") or "stack"
        try:
            if mode == "replace":
                # eligible[-1] (highest configured level <= effective_level) used to be taken
                # as the target unconditionally, even if that specific Discord role had since
                # been deleted (config row left behind, matching how deleted level roles are
                # already tolerated elsewhere - "stack" mode below skips them the same way).
                # guild.get_role() then correctly returned None and skipped ADDING it back, but
                # the removal of the member's other, still-valid level roles happened anyway -
                # net effect: a member could lose every level role they had and gain nothing,
                # just because a higher one they'd since qualified for was deleted from Discord.
                target_role = None
                for r in reversed(eligible):
                    candidate = member.guild.get_role(int(r["role_id"]))
                    if candidate:
                        target_role = candidate
                        break
                if target_role:
                    to_remove = [
                        r for r in member.roles
                        if r.id in {int(x["role_id"]) for x in rows} and r.id != target_role.id
                    ]
                    if to_remove:
                        await member.remove_roles(*to_remove, reason="Level-Rolle aktualisiert")
                    if target_role not in member.roles:
                        await member.add_roles(target_role, reason=f"Level {effective_level} erreicht")
                # If no eligible role resolves to an actual Discord role at all, leave the
                # member's current roles untouched rather than stripping them for no replacement.
            else:
                to_add = []
                for r in eligible:
                    role = member.guild.get_role(int(r["role_id"]))
                    if role and role not in member.roles:
                        to_add.append(role)
                if to_add:
                    await member.add_roles(*to_add, reason=f"Level {effective_level} erreicht")
        except Exception as e:
            print(f"[Leveling] role sync failed for {member} in guild {member.guild.id}: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        enabled = await get_guild_config(message.guild.id, "leveling_enabled")
        if enabled != "1":
            return

        allowed_raw = await get_guild_config(message.guild.id, "leveling_channels") or ""
        allowed = {c.strip() for c in allowed_raw.split(",") if c.strip()}
        if allowed:
            # A message inside a thread reports the thread's own ID as message.channel.id, not
            # its parent's - the XP-channel picker only lists top-level text channels, so without
            # this a thread under an allowed channel would silently never grant XP.
            scope_id = message.channel.parent_id if isinstance(message.channel, discord.Thread) else message.channel.id
            if str(scope_id) not in allowed:
                return

        key = (message.guild.id, message.author.id)
        if key in self._cooldowns:
            return
        self._cooldowns[key] = True
        self.bot.loop.call_later(60, lambda: self._cooldowns.pop(key, None))

        xp_gain = random.randint(15, 25)
        await self._add_text_xp(message.author, xp_gain)

    @tasks.loop(minutes=1)
    async def voice_xp_loop(self):
        # Scans live voice-channel membership every minute rather than tracking join/leave
        # events ourselves - simpler, can't desync from Discord's actual state, and a missed
        # tick (e.g. bot restart) only ever costs at most one minute of XP, never a whole session.
        for guild in list(self.bot.guilds):
            try:
                if await get_guild_config(guild.id, "leveling_enabled") != "1":
                    continue
                if await get_guild_config(guild.id, "leveling_voice_enabled") != "1":
                    continue
                rate_raw = await get_guild_config(guild.id, "leveling_voice_xp_per_min")
                try:
                    xp_gain = int(rate_raw) if rate_raw else 5
                except ValueError:
                    xp_gain = 5
                for vc in guild.voice_channels:
                    if guild.afk_channel and vc.id == guild.afk_channel.id:
                        # Long-deferred from when voice XP was first introduced ("afk kommt
                        # noch") - anyone in the server's designated AFK channel isn't actually
                        # participating, just parked there (often muted/deafened by Discord's
                        # own AFK-channel behavior), so it shouldn't earn XP like a real voice
                        # channel would.
                        continue
                    for member in vc.members:
                        if member.bot:
                            continue
                        # Per-member, not just per-guild: one member's XP grant raising (e.g. a
                        # transient DB error) shouldn't cost every other member still in voice in
                        # this same guild their XP for this tick too.
                        try:
                            await self._add_voice_xp(member, xp_gain)
                        except Exception as e:
                            print(f"[Leveling] voice XP error for {member} in guild {guild.id}: {e}")
            except Exception as e:
                print(f"[Leveling] voice XP error in guild {guild.id}: {e}")

    @voice_xp_loop.before_loop
    async def _before_voice_loop(self):
        await self.bot.wait_until_ready()

    async def _announce_levelup(self, member: discord.Member, level: int, kind: str):
        channel_id = await get_guild_config(member.guild.id, "level_channel")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else member.guild.system_channel
        if not channel:
            return
        label = "Voice-Level" if kind == "voice" else "Chat-Level"
        embed = discord.Embed(
            title="Level Up! 🎉",
            description=f"{member.mention} hat **{label} {level}** erreicht!",
            color=0x7c3aed,
        )
        # Rewards are exact-level matches, not "everything up to this level" like level roles -
        # a reward is a one-off, manually-fulfilled prize (Nitro, a game key, ...), not a
        # persistent state the bot can check for "already has it" the way it can with roles, so
        # re-announcing every earlier still-eligible reward on a later level-up would repeat it.
        reward = await db_one(
            "SELECT reward FROM level_rewards WHERE guild_id=? AND level=?",
            (member.guild.id, level),
        )
        if reward:
            embed.add_field(name="🎁 Belohnung", value=reward["reward"], inline=False)
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"[Leveling] level-up announcement failed for {member} in guild {member.guild.id}: {e}")

    @app_commands.command(name="rank", description="Deinen Rang und XP anzeigen")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        row = await db_one(
            "SELECT xp, level, messages, voice_xp, voice_level, voice_minutes FROM levels "
            "WHERE user_id=? AND guild_id=?",
            (member.id, interaction.guild_id),
        )
        if not row:
            await interaction.response.send_message(f"{member.mention} hat noch keine XP.", ephemeral=True)
            return
        tquad, tlinear, tbase = await self._get_curve(interaction.guild_id, "text")
        vquad, vlinear, vbase = await self._get_curve(interaction.guild_id, "voice")
        text_needed = xp_for_level(row["level"], tquad, tlinear, tbase)
        text_in_level = row["xp"] - sum(xp_for_level(i, tquad, tlinear, tbase) for i in range(row["level"]))
        voice_needed = xp_for_level(row["voice_level"], vquad, vlinear, vbase)
        voice_in_level = row["voice_xp"] - sum(xp_for_level(i, vquad, vlinear, vbase) for i in range(row["voice_level"]))
        embed = discord.Embed(title=f"Rang von {member.display_name}", color=0x7c3aed)
        embed.add_field(name="Chat-Level", value=str(row["level"]))
        embed.add_field(name="Chat-XP", value=f"{text_in_level} / {text_needed}")
        embed.add_field(name="Nachrichten", value=str(row["messages"]))
        embed.add_field(name="Voice-Level", value=str(row["voice_level"]))
        embed.add_field(name="Voice-XP", value=f"{voice_in_level} / {voice_needed}")
        embed.add_field(name="Voice-Minuten", value=str(row["voice_minutes"]))
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Top 10 nach Chat-XP")
    async def leaderboard(self, interaction: discord.Interaction):
        rows = await db_rows(
            "SELECT user_id, level, xp FROM levels WHERE guild_id=? ORDER BY xp DESC, voice_xp DESC LIMIT 10",
            (interaction.guild_id,),
        )
        if not rows:
            await interaction.response.send_message("Noch keine Daten.", ephemeral=True)
            return
        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, r in enumerate(rows):
            prefix = medals[i] if i < 3 else f"`{i+1}.`"
            user = self.bot.get_user(r["user_id"]) or f"<@{r['user_id']}>"
            lines.append(f"{prefix} **{user}** — Chat-Level {r['level']} ({r['xp']} XP)")
        embed = discord.Embed(title="🏆 Leaderboard", description="\n".join(lines), color=0x7c3aed)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="setxp", description="XP eines Mitglieds setzen (Admin)")
    @app_commands.describe(track="chat oder voice")
    @app_commands.choices(track=[
        app_commands.Choice(name="Chat", value="text"),
        app_commands.Choice(name="Voice", value="voice"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def setxp(self, interaction: discord.Interaction, member: discord.Member, xp: int, track: str = "text"):
        quad, linear, base = await self._get_curve(interaction.guild_id, track)
        level = level_from_xp(xp, quad, linear, base)
        if track == "voice":
            await db_exec(
                "INSERT INTO levels (user_id,guild_id,voice_xp,voice_level) VALUES (?,?,?,?) "
                "ON CONFLICT(user_id,guild_id) DO UPDATE SET voice_xp=excluded.voice_xp, voice_level=excluded.voice_level",
                (member.id, interaction.guild_id, xp, level),
            )
        else:
            await db_exec(
                "INSERT INTO levels (user_id,guild_id,xp,level) VALUES (?,?,?,?) "
                "ON CONFLICT(user_id,guild_id) DO UPDATE SET xp=excluded.xp, level=excluded.level",
                (member.id, interaction.guild_id, xp, level),
            )
        label = "Voice" if track == "voice" else "Chat"
        await interaction.response.send_message(
            f"{member.mention} hat jetzt {xp} {label}-XP ({label}-Level {level}).", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Leveling(bot))
