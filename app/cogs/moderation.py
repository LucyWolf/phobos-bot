import datetime
import discord
from discord import app_commands
from discord.ext import commands
from database import log_mod_action, db_rows, db_exec


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="kick", description="Ein Mitglied kicken")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund angegeben"):
        await member.kick(reason=reason)
        await log_mod_action("kick", member, interaction.user, interaction.guild_id, reason)
        await interaction.response.send_message(f"{member.mention} wurde gekickt. Grund: {reason}", ephemeral=True)

    @app_commands.command(name="ban", description="Ein Mitglied bannen")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund angegeben"):
        await member.ban(reason=reason)
        await log_mod_action("ban", member, interaction.user, interaction.guild_id, reason)
        await interaction.response.send_message(f"{member.mention} wurde gebannt. Grund: {reason}", ephemeral=True)

    @app_commands.command(name="unban", description="User anhand ID entbannen")
    @app_commands.default_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "Kein Grund angegeben"):
        user = await self.bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=reason)
        await log_mod_action("unban", user, interaction.user, interaction.guild_id, reason)
        await interaction.response.send_message(f"{user} wurde entbannt.", ephemeral=True)

    @app_commands.command(name="timeout", description="Mitglied für X Minuten timen")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Kein Grund angegeben"):
        until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        await member.timeout(until, reason=reason)
        await log_mod_action("timeout", member, interaction.user, interaction.guild_id, reason)
        await interaction.response.send_message(f"{member.mention} für {minutes} Min. getimeouted.", ephemeral=True)

    @app_commands.command(name="warn", description="Mitglied verwarnen")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await db_exec(
            "INSERT INTO warnings (user_id,guild_id,moderator_id,reason) VALUES (?,?,?,?)",
            (member.id, interaction.guild_id, interaction.user.id, reason),
        )
        await log_mod_action("warn", member, interaction.user, interaction.guild_id, reason)
        await interaction.response.send_message(f"{member.mention} verwarnt. Grund: {reason}", ephemeral=True)

    @app_commands.command(name="warnings", description="Verwarnungen eines Mitglieds")
    @app_commands.default_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        rows = await db_rows(
            "SELECT * FROM warnings WHERE user_id=? AND guild_id=? ORDER BY timestamp DESC",
            (member.id, interaction.guild_id),
        )
        if not rows:
            await interaction.response.send_message(f"{member.mention} hat keine Verwarnungen.", ephemeral=True)
            return
        text = "\n".join(f"#{r['id']} — {r['reason']} ({r['timestamp']})" for r in rows)
        await interaction.response.send_message(f"**Verwarnungen von {member}:**\n{text}", ephemeral=True)

    @app_commands.command(name="clearwarns", description="Alle Verwarnungen eines Mitglieds löschen")
    @app_commands.default_permissions(moderate_members=True)
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        await db_exec("DELETE FROM warnings WHERE user_id=? AND guild_id=?", (member.id, interaction.guild_id))
        await interaction.response.send_message(f"Verwarnungen von {member.mention} gelöscht.", ephemeral=True)

    @app_commands.command(name="clear", description="Nachrichten löschen")
    @app_commands.default_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"{len(deleted)} Nachrichten gelöscht.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
