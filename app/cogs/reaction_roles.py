import discord
from discord import app_commands
from discord.ext import commands
from database import db_rows, db_exec, db_exec_rowcount, db_one


class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="reactionrole-add", description="Reaction Role hinzufügen")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_add(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
        # The channel search below makes one fetch_message() API call per text channel until
        # it finds the message - on any server with more than a handful of channels that alone
        # can take longer than Discord's 3-second initial-response window (worst case: the
        # message is in the LAST channel checked, or in none at all). Without deferring first,
        # every send_message() below would then raise "interaction expired" instead of ever
        # reaching the user.
        await interaction.response.defer(ephemeral=True)
        msg = None
        for channel in interaction.guild.text_channels:
            try:
                msg = await channel.fetch_message(int(message_id))
                channel_id = channel.id
                break
            except Exception:
                continue
        if not msg:
            await interaction.followup.send("Nachricht nicht gefunden.", ephemeral=True)
            return
        try:
            await msg.add_reaction(emoji)
        except (discord.HTTPException, discord.NotFound):
            await interaction.followup.send("Ungültiger Emoji.", ephemeral=True)
            return
        # No UNIQUE constraint exists on (guild_id, message_id, emoji) - without this check, a
        # second /reactionrole-add for the same message+emoji (e.g. trying to change which role
        # it grants) would just insert a SECOND row instead of replacing the first. _handle_
        # reaction only ever reads the first matching row, so the "new" role would silently
        # never take effect while the command still reports success.
        existing = await db_one(
            "SELECT id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
            (interaction.guild_id, int(message_id), emoji),
        )
        if existing:
            await db_exec("UPDATE reaction_roles SET role_id=?, channel_id=? WHERE id=?",
                           (role.id, channel_id, existing["id"]))
        else:
            await db_exec(
                "INSERT INTO reaction_roles (guild_id,channel_id,message_id,emoji,role_id) VALUES (?,?,?,?,?)",
                (interaction.guild_id, channel_id, int(message_id), emoji, role.id),
            )
        await interaction.followup.send(f"Reaction Role hinzugefügt: {emoji} → {role.mention}", ephemeral=True)

    @app_commands.command(name="reactionrole-remove", description="Reaction Role entfernen")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_remove(self, interaction: discord.Interaction, message_id: str, emoji: str):
        row = await db_one(
            "SELECT channel_id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
            (interaction.guild_id, int(message_id), emoji),
        )
        deleted = await db_exec_rowcount(
            "DELETE FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
            (interaction.guild_id, int(message_id), emoji),
        )
        if not deleted:
            # Previously said "entfernt" unconditionally, even for a message_id/emoji pair that
            # was never configured (0 rows affected) - misleading confirmation for a no-op.
            await interaction.response.send_message("Diese Reaction Role existiert nicht.", ephemeral=True)
            return
        # Remove the bot's own reaction too - otherwise the emoji stays on the message looking
        # exactly as clickable as before, but silently does nothing once someone clicks it.
        if row:
            channel = interaction.guild.get_channel(row["channel_id"])
            if channel:
                try:
                    msg = await channel.fetch_message(int(message_id))
                    await msg.remove_reaction(emoji, self.bot.user)
                except Exception:
                    pass
        await interaction.response.send_message(f"Reaction Role entfernt.", ephemeral=True)

    @app_commands.command(name="reactionrole-list", description="Alle Reaction Roles anzeigen")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_list(self, interaction: discord.Interaction):
        rows = await db_rows("SELECT * FROM reaction_roles WHERE guild_id=?", (interaction.guild_id,))
        if not rows:
            await interaction.response.send_message("Keine Reaction Roles konfiguriert.", ephemeral=True)
            return
        # Sent as a plain (non-embed) message - Discord's hard limit there is 2000 characters,
        # unguarded before this fix. Stop adding lines once close to that limit instead of
        # letting send_message raise for a server with enough reaction roles configured.
        lines: list[str] = []
        total_len = 0
        for r in rows:
            line = f"{r['emoji']} → <@&{r['role_id']}> (Msg: `{r['message_id']}`)"
            if total_len + len(line) + 1 > 1900:
                break
            lines.append(line)
            total_len += len(line) + 1
        remaining = len(rows) - len(lines)
        text = "\n".join(lines)
        if remaining > 0:
            text += f"\n… und {remaining} weitere"
        await interaction.response.send_message(text, ephemeral=True)

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
        try:
            if add:
                await member.add_roles(role, reason="Reaction Role")
            else:
                await member.remove_roles(role, reason="Reaction Role")
        except discord.HTTPException as e:
            # This is the actual core of the feature failing (missing "Manage Roles", the
            # role sitting above the bot's own top role, ...) with zero other way for an admin
            # to ever find out - there's no interaction to reply to here, only the console log.
            print(f"[ReactionRoles] {'add' if add else 'remove'}_roles failed for role {role.id} in guild {payload.guild_id}: {e}")


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
