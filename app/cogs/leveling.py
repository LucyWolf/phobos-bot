import random
import discord
from discord import app_commands
from discord.ext import commands, tasks
from database import db_one, db_rows, db_exec, get_guild_config


def xp_for_level(level: int) -> int:
    return 5 * (level ** 2) + 50 * level + 100


def level_from_xp(xp: int) -> int:
    level = 0
    while xp >= xp_for_level(level):
        xp -= xp_for_level(level)
        level += 1
    return level


class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cooldowns: dict = {}
        self.voice_xp_loop.start()

    def cog_unload(self):
        self.voice_xp_loop.cancel()

    async def _add_xp(self, member: discord.Member, xp_gain: int, count_message: bool, count_voice_minute: bool):
        # Atomic upsert-increment instead of read-modify-write: on_message and voice_xp_loop
        # can both grant XP to the same member around the same time (e.g. someone chatting
        # while sitting in voice right as the per-minute tick fires), and a plain
        # SELECT-then-UPDATE would let one of the two grants silently overwrite the other.
        await db_exec(
            "INSERT INTO levels (user_id, guild_id, xp, level, messages, voice_minutes) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(user_id, guild_id) DO UPDATE SET "
            "xp = levels.xp + excluded.xp, "
            "messages = levels.messages + excluded.messages, "
            "voice_minutes = levels.voice_minutes + excluded.voice_minutes",
            (member.id, member.guild.id, xp_gain, level_from_xp(xp_gain),
             1 if count_message else 0, 1 if count_voice_minute else 0),
        )
        row = await db_one(
            "SELECT xp, level FROM levels WHERE user_id=? AND guild_id=?",
            (member.id, member.guild.id),
        )
        if not row:
            return
        new_level = level_from_xp(row["xp"])
        if new_level != row["level"]:
            await db_exec(
                "UPDATE levels SET level=? WHERE user_id=? AND guild_id=?",
                (new_level, member.id, member.guild.id),
            )
            if new_level > row["level"]:
                await self._announce_levelup(member, new_level)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        enabled = await get_guild_config(message.guild.id, "leveling_enabled")
        if enabled != "1":
            return

        if await get_guild_config(message.guild.id, "leveling_channel_mode") == "specific":
            allowed_raw = await get_guild_config(message.guild.id, "leveling_channels") or ""
            allowed = {c.strip() for c in allowed_raw.split(",") if c.strip()}
            if str(message.channel.id) not in allowed:
                return

        key = (message.guild.id, message.author.id)
        if key in self._cooldowns:
            return
        self._cooldowns[key] = True
        self.bot.loop.call_later(60, lambda: self._cooldowns.pop(key, None))

        xp_gain = random.randint(15, 25)
        await self._add_xp(message.author, xp_gain, count_message=True, count_voice_minute=False)

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
                    for member in vc.members:
                        if member.bot:
                            continue
                        await self._add_xp(member, xp_gain, count_message=False, count_voice_minute=True)
            except Exception as e:
                print(f"[Leveling] voice XP error in guild {guild.id}: {e}")

    @voice_xp_loop.before_loop
    async def _before_voice_loop(self):
        await self.bot.wait_until_ready()

    async def _announce_levelup(self, member: discord.Member, level: int):
        channel_id = await get_guild_config(member.guild.id, "level_channel")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else member.guild.system_channel
        if channel:
            embed = discord.Embed(
                title="Level Up! 🎉",
                description=f"{member.mention} hat **Level {level}** erreicht!",
                color=0x7c3aed,
            )
            await channel.send(embed=embed)

    @app_commands.command(name="rank", description="Deinen Rang und XP anzeigen")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        row = await db_one(
            "SELECT xp, level, messages, voice_minutes FROM levels WHERE user_id=? AND guild_id=?",
            (member.id, interaction.guild_id),
        )
        if not row:
            await interaction.response.send_message(f"{member.mention} hat noch keine XP.", ephemeral=True)
            return
        needed = xp_for_level(row["level"])
        xp_in_level = row["xp"] - sum(xp_for_level(i) for i in range(row["level"]))
        embed = discord.Embed(title=f"Rang von {member.display_name}", color=0x7c3aed)
        embed.add_field(name="Level", value=str(row["level"]))
        embed.add_field(name="XP", value=f"{xp_in_level} / {needed}")
        embed.add_field(name="Nachrichten", value=str(row["messages"]))
        embed.add_field(name="Voice-Minuten", value=str(row["voice_minutes"]))
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Top 10 nach XP")
    async def leaderboard(self, interaction: discord.Interaction):
        rows = await db_rows(
            "SELECT user_id, level, xp FROM levels WHERE guild_id=? ORDER BY xp DESC LIMIT 10",
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
            lines.append(f"{prefix} **{user}** — Level {r['level']} ({r['xp']} XP)")
        embed = discord.Embed(title="🏆 Leaderboard", description="\n".join(lines), color=0x7c3aed)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="setxp", description="XP eines Mitglieds setzen (Admin)")
    @app_commands.default_permissions(administrator=True)
    async def setxp(self, interaction: discord.Interaction, member: discord.Member, xp: int):
        level = level_from_xp(xp)
        await db_exec(
            "INSERT INTO levels (user_id,guild_id,xp,level,messages) VALUES (?,?,?,?,0) ON CONFLICT(user_id,guild_id) DO UPDATE SET xp=excluded.xp, level=excluded.level",
            (member.id, interaction.guild_id, xp, level),
        )
        await interaction.response.send_message(f"{member.mention} hat jetzt {xp} XP (Level {level}).", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Leveling(bot))
