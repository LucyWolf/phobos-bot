import discord
from discord import app_commands
from discord.ext import commands
from database import db_rows, db_exec


class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="reactionrole-add", description="Reaction Role hinzufügen")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_add(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
        msg = None
        for channel in interaction.guild.text_channels:
            try:
                msg = await channel.fetch_message(int(message_id))
                channel_id = channel.id
                break
            except Exception:
                continue
        if not msg:
            await interaction.response.send_message("Nachricht nicht gefunden.", ephemeral=True)
            return
        await db_exec(
            "INSERT INTO reaction_roles (guild_id,channel_id,message_id,emoji,role_id) VALUES (?,?,?,?,?)",
            (interaction.guild_id, channel_id, int(message_id), emoji, role.id),
        )
        await msg.add_reaction(emoji)
        await interaction.response.send_message(f"Reaction Role hinzugefügt: {emoji} → {role.mention}", ephemeral=True)

    @app_commands.command(name="reactionrole-remove", description="Reaction Role entfernen")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_remove(self, interaction: discord.Interaction, message_id: str, emoji: str):
        await db_exec(
            "DELETE FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
            (interaction.guild_id, int(message_id), emoji),
        )
        await interaction.response.send_message(f"Reaction Role entfernt.", ephemeral=True)

    @app_commands.command(name="reactionrole-list", description="Alle Reaction Roles anzeigen")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_list(self, interaction: discord.Interaction):
        rows = await db_rows("SELECT * FROM reaction_roles WHERE guild_id=?", (interaction.guild_id,))
        if not rows:
            await interaction.response.send_message("Keine Reaction Roles konfiguriert.", ephemeral=True)
            return
        lines = [f"{r['emoji']} → <@&{r['role_id']}> (Msg: `{r['message_id']}`)" for r in rows]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        await self._handle_reaction(payload, add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        await self._handle_reaction(payload, add=False)

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent, add: bool):
        emoji = str(payload.emoji)
        row = await db_rows(
            "SELECT role_id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
            (payload.guild_id, payload.message_id, emoji),
        )
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        role = guild.get_role(row[0]["role_id"])
        if not member or not role:
            return
        if add:
            await member.add_roles(role, reason="Reaction Role")
        else:
            await member.remove_roles(role, reason="Reaction Role")


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
