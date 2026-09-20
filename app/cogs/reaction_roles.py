"""Reaction-role messages: react with an emoji on a tracked message to get/lose a role.
Managed via /reactionrole-add/-remove/-list or the dashboard "Reaction Roles" tab - adding one
also actually places the reaction on the Discord message, not just a DB row."""
import discord
from discord import app_commands
from discord.ext import commands
from database import db_rows, db_exec, db_exec_rowcount, db_one, normalize_reaction_emoji


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
        # Same normalization as the dashboard - see normalize_reaction_emoji(). Without it a
        # custom emoji typed as "name:id" here gets its reaction placed and then never matches
        # the "<:name:id>" the gateway reports back, so the role is silently never granted.
        emoji = normalize_reaction_emoji(emoji)
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
        # Checked rather than relying on the UNIQUE index added later on (guild_id,
        # message_id, emoji): a plain INSERT would now raise IntegrityError instead. Without
        # this check, a
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
        # Deferred for the same reason rr_add above defers: this command does a DB lookup, a
        # DELETE, a fetch_message() and a remove_reaction() BEFORE it answers. Any one of those
        # can outlast Discord's 3-second initial-response window on a slow link, and the user
        # then sees a bare "This interaction failed" even though the reaction role was in fact
        # removed - the worst possible combination, since it invites doing it again.
        await interaction.response.defer(ephemeral=True)
        # Normalized so a looser spelling still finds the row the dashboard stored canonically.
        emoji = normalize_reaction_emoji(emoji)
        try:
            message_id_i = int(message_id)
        except ValueError:
            # Unlike rr_add (where a bad message_id just falls through the per-channel search
            # loop's own except and ends up as a friendly "not found"), this int() ran
            # unguarded directly - a non-numeric value would raise here with no interaction
            # response ever sent, showing as a generic "This interaction failed" to the user
            # instead of an actual error message. Same fix pattern already applied elsewhere
            # for a bare int() on user-supplied Discord IDs (e.g. /unban, /giveaway-reroll).
            await interaction.followup.send("Ungültige Nachrichten-ID.", ephemeral=True)
            return
        row = await db_one(
            "SELECT channel_id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
            (interaction.guild_id, message_id_i, emoji),
        )
        deleted = await db_exec_rowcount(
            "DELETE FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
            (interaction.guild_id, message_id_i, emoji),
        )
        if not deleted:
            # Previously said "entfernt" unconditionally, even for a message_id/emoji pair that
            # was never configured (0 rows affected) - misleading confirmation for a no-op.
            await interaction.followup.send("Diese Reaction Role existiert nicht.", ephemeral=True)
            return
        # Remove the bot's own reaction too - otherwise the emoji stays on the message looking
        # exactly as clickable as before, but silently does nothing once someone clicks it.
        if row:
            channel = interaction.guild.get_channel(row["channel_id"])
            if channel:
                try:
                    msg = await channel.fetch_message(message_id_i)
                    await msg.remove_reaction(emoji, self.bot.user)
                except Exception:
                    pass
        await interaction.followup.send("Reaction Role entfernt.", ephemeral=True)

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
        if payload.guild_id is None:
            # A reaction in a DM. Nothing can ever match, but without this the lookup below
            # still opens a fresh SQLite connection for every single one of them.
            return
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
        # payload.member is filled in by Discord for REACTION_ADD only, and is the one source
        # that never needs the cache. For a REMOVE - and for an ADD on a guild whose member
        # cache has evicted this user - get_member() can return None, and the whole feature
        # then silently does nothing at all for that person: no role granted, no role taken
        # away, not even a log line. Falling back to an API fetch costs one request in exactly
        # that case and nothing at all in the normal cached one.
        member = payload.member if add else None
        if member is None:
            member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except discord.NotFound:
                return  # the person has left the server since reacting
            except (discord.HTTPException, OSError) as e:
                print(f"[ReactionRoles] could not resolve member {payload.user_id} "
                      f"in guild {payload.guild_id}: {e}")
                return
        if member.bot:
            # Only THIS bot's own reactions were skipped (by user id, in the two listeners
            # above). In a multi-bot setup - which this project supports as a headline feature,
            # several tokens each running their own bot in the same guild - the reaction bot A
            # places on a reaction-role message is not bot B's user id, so bot B happily
            # treated it as a member reacting and granted the role TO BOT A. Skipping every bot
            # account covers that, and any other bot that reacts for reasons of its own.
            return
        role = guild.get_role(row[0]["role_id"])
        if not role:
            # The configured role was deleted in Discord but the row is still here - silently
            # doing nothing looked identical to "the bot is broken" from the outside.
            print(f"[ReactionRoles] role {row[0]['role_id']} of a reaction role on message "
                  f"{payload.message_id} no longer exists in guild {payload.guild_id}")
            return
        try:
            if add:
                await member.add_roles(role, reason="Reaction Role")
            else:
                await member.remove_roles(role, reason="Reaction Role")
        except (discord.HTTPException, OSError) as e:
            # This is the actual core of the feature failing (missing "Manage Roles", the
            # role sitting above the bot's own top role, ...) with zero other way for an admin
            # to ever find out - there's no interaction to reply to here, only the console log.
            # OSError included alongside HTTPException for the same reason it's now caught
            # throughout this project: discord.py 2.3.2's http.py retry loop only retries a
            # caught OSError on macOS/Windows-specific errno codes, re-raising it unwrapped on
            # Linux (this project's actual runtime) for every other connection failure - without
            # this, a network hiccup here would propagate out of the raw-reaction event handler
            # entirely, silently skipping even this console log line.
            print(f"[ReactionRoles] {'add' if add else 'remove'}_roles failed for role {role.id} in guild {payload.guild_id}: {e}")


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
