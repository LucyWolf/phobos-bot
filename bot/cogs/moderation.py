import datetime
import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from pathlib import Path

DB_PATH = Path("/app/data/modbot.db")


async def log_action(action: str, target, moderator, guild_id: int, reason: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO mod_actions
               (action, target_id, target_name, moderator_id, moderator_name, guild_id, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (action, target.id, str(target), moderator.id, str(moderator), guild_id, reason),
        )
        await db.commit()


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="kick", description="Ein Mitglied kicken")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund angegeben"):
        await member.kick(reason=reason)
        await log_action("kick", member, interaction.user, interaction.guild_id, reason)
        await interaction.response.send_message(
            f"{member.mention} wurde gekickt. Grund: {reason}", ephemeral=True
        )

    @app_commands.command(name="ban", description="Ein Mitglied bannen")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund angegeben"):
        await member.ban(reason=reason)
        await log_action("ban", member, interaction.user, interaction.guild_id, reason)
        await interaction.response.send_message(
            f"{member.mention} wurde gebannt. Grund: {reason}", ephemeral=True
        )

    @app_commands.command(name="unban", description="Einen User anhand der ID entbannen")
    @app_commands.default_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "Kein Grund angegeben"):
        user = await self.bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=reason)
        await log_action("unban", user, interaction.user, interaction.guild_id, reason)
        await interaction.response.send_message(f"{user} wurde entbannt.", ephemeral=True)

    @app_commands.command(name="timeout", description="Ein Mitglied für X Minuten timeout geben")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Kein Grund angegeben"):
        until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        await member.timeout(until, reason=reason)
        await log_action("timeout", member, interaction.user, interaction.guild_id, reason)
        await interaction.response.send_message(
            f"{member.mention} wurde für {minutes} Minuten getimeouted. Grund: {reason}", ephemeral=True
        )

    @app_commands.command(name="warn", description="Ein Mitglied verwarnen")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO warnings (user_id, guild_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
                (member.id, interaction.guild_id, interaction.user.id, reason),
            )
            await db.commit()
        await log_action("warn", member, interaction.user, interaction.guild_id, reason)
        await interaction.response.send_message(
            f"{member.mention} wurde verwarnt. Grund: {reason}", ephemeral=True
        )

    @app_commands.command(name="warnings", description="Verwarnungen eines Mitglieds anzeigen")
    @app_commands.default_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM warnings WHERE user_id = ? AND guild_id = ? ORDER BY timestamp DESC",
                (member.id, interaction.guild_id),
            )
            rows = await cursor.fetchall()
        if not rows:
            await interaction.response.send_message(f"{member.mention} hat keine Verwarnungen.", ephemeral=True)
            return
        text = "\n".join(f"#{r['id']} — {r['reason']} ({r['timestamp']})" for r in rows)
        await interaction.response.send_message(
            f"**Verwarnungen von {member}:**\n{text}", ephemeral=True
        )

    @app_commands.command(name="clear", description="Nachrichten löschen")
    @app_commands.default_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"{len(deleted)} Nachrichten gelöscht.", ephemeral=True)

    async def cog_load(self):
        await self.bot.tree.sync()
        print("Slash-Commands synchronisiert")


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
