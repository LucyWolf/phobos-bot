import math
import random
import discord
from discord import app_commands
from discord.ext import commands
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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        enabled = await get_guild_config(message.guild.id, "leveling_enabled")
        if enabled != "1":
            return

        key = (message.guild.id, message.author.id)
        if key in self._cooldowns:
            return
        self._cooldowns[key] = True
        self.bot.loop.call_later(60, lambda: self._cooldowns.pop(key, None))

        xp_gain = random.randint(15, 25)
        row = await db_one(
            "SELECT xp, level, messages FROM levels WHERE user_id=? AND guild_id=?",
            (message.author.id, message.guild.id),
        )
        if row:
            new_xp = row["xp"] + xp_gain
            new_msgs = row["messages"] + 1
            new_level = level_from_xp(new_xp)
            await db_exec(
                "UPDATE levels SET xp=?, level=?, messages=? WHERE user_id=? AND guild_id=?",
                (new_xp, new_level, new_msgs, message.author.id, message.guild.id),
            )
            if new_level > row["level"]:
                await self._announce_levelup(message, new_level)
        else:
            new_level = level_from_xp(xp_gain)
            await db_exec(
                "INSERT INTO levels (user_id,guild_id,xp,level,messages) VALUES (?,?,?,?,1)",
                (message.author.id, message.guild.id, xp_gain, new_level),
            )

    async def _announce_levelup(self, message: discord.Message, level: int):
        channel_id = await get_guild_config(message.guild.id, "level_channel")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else message.channel
        if channel:
            embed = discord.Embed(
                title="Level Up! 🎉",
                description=f"{message.author.mention} hat **Level {level}** erreicht!",
                color=0x7c3aed,
            )
            await channel.send(embed=embed)

    @app_commands.command(name="rank", description="Deinen Rang und XP anzeigen")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        row = await db_one(
            "SELECT xp, level, messages FROM levels WHERE user_id=? AND guild_id=?",
            (member.id, interaction.guild_id),
        )
        if not row:
            await interaction.response.send_message(f"{member.mention} hat noch keine XP.", ephemeral=True)
            return
        needed = xp_for_level(row["level"])
        embed = discord.Embed(title=f"Rang von {member.display_name}", color=0x7c3aed)
        embed.add_field(name="Level", value=str(row["level"]))
        embed.add_field(name="XP", value=f"{row['xp']} / {row['xp'] + needed}")
        embed.add_field(name="Nachrichten", value=str(row["messages"]))
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
