"""VRChat account links: a member states their VRChat name, a moderator approves it, and the
approved link then drives an automatic role and the member's Discord nickname.

User-requested with screenshots of a third-party VRChat-linking service ("mach ein neues
funktion vrc link"). The approval step is a PERSON rather than an API call on purpose, and
that is worth stating plainly: VRChat has no open API. The community one requires real account
credentials plus 2FA, using it for automation is a bannable offence for whichever account does
it, and profile pages are not readable without a login. So this bot cannot verify by itself
that a VRChat name belongs to the member claiming it - and it could not honestly fill in the
"18+ verified" or trust-rank fields that service shows either, because VRChat does not expose
them. What it CAN do is everything that follows from a link somebody has confirmed.

Configured via main.py's "VRC-Link" tab (guild_configs keys vrc_* plus the vrc_links table).
"""
import datetime

import discord
from discord import app_commands
from discord.ext import commands

from database import (db_rows, db_one, db_exec, get_guild_config,
                      vrc_nickname, DEFAULT_VRC_NICKNAME_FORMAT)

# VRChat display names are at most 32 characters; anything longer is not a name, it is a paste
# accident. Kept as its own limit rather than reusing the nickname one it happens to match.
MAX_VRCHAT_NAME = 32


async def apply_link(bot, guild: discord.Guild, member: discord.Member, vrchat_name: str) -> list:
    """Give the member everything an approved link earns them. Returns what actually changed,
    for the caller to report - an empty list means "nothing to do", not "it failed"."""
    changed = []

    role_id = await get_guild_config(guild.id, "vrc_linked_role")
    if role_id and str(role_id).isdigit():
        role = guild.get_role(int(role_id))
        if role and role not in member.roles:
            try:
                await member.add_roles(role, reason="VRC-Link bestätigt")
                changed.append(f"Rolle {role.name}")
            except (discord.HTTPException, OSError) as e:
                print(f"[vrc_link] could not add role {role_id} to {member.id} in {guild.id}: {e}")

    if (await get_guild_config(guild.id, "vrc_nickname_enabled") or "0") == "1":
        fmt = await get_guild_config(guild.id, "vrc_nickname_format") or DEFAULT_VRC_NICKNAME_FORMAT
        nick = vrc_nickname(fmt, vrchat_name, member.name)
        if nick and nick != member.display_name:
            try:
                await member.edit(nick=nick, reason="VRC-Link bestätigt")
                changed.append(f"Spitzname {nick}")
            except discord.Forbidden:
                # The server owner can never be renamed by a bot, and a member whose top role
                # sits above the bot's cannot either. Worth a log line, not worth failing the
                # whole approval over - the role part may well have worked.
                print(f"[vrc_link] not allowed to rename {member.id} in guild {guild.id}")
            except (discord.HTTPException, OSError) as e:
                print(f"[vrc_link] rename of {member.id} in guild {guild.id} failed: {e}")
    return changed


async def revoke_link(bot, guild: discord.Guild, member: discord.Member) -> None:
    """Undo what apply_link() gave, as far as it is still there."""
    role_id = await get_guild_config(guild.id, "vrc_linked_role")
    if role_id and str(role_id).isdigit():
        role = guild.get_role(int(role_id))
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason="VRC-Link entfernt")
            except (discord.HTTPException, OSError) as e:
                print(f"[vrc_link] could not remove role {role_id} from {member.id}: {e}")
    if (await get_guild_config(guild.id, "vrc_nickname_enabled") or "0") == "1":
        try:
            # None clears the nickname, putting the member back to their own Discord name.
            await member.edit(nick=None, reason="VRC-Link entfernt")
        except (discord.HTTPException, OSError):
            pass


class VRCLink(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _enabled(self, guild_id: int) -> bool:
        return (await get_guild_config(guild_id, "vrc_enabled") or "0") == "1"

    @app_commands.command(name="vrc-link", description="Eigenen VRChat-Namen eintragen")
    async def vrc_link(self, interaction: discord.Interaction, vrchat_name: str):
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ Das geht nur auf einem Server.", ephemeral=True)
            return
        if not await self._enabled(interaction.guild_id):
            await interaction.response.send_message(
                "❌ VRC-Link ist auf diesem Server nicht aktiviert.", ephemeral=True)
            return
        name = " ".join((vrchat_name or "").split())[:MAX_VRCHAT_NAME]
        if not name:
            await interaction.response.send_message(
                "❌ Bitte gib deinen VRChat-Namen an.", ephemeral=True)
            return

        existing = await db_one(
            "SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
            (str(interaction.guild_id), str(interaction.user.id)),
        )
        # The same name may not be claimed twice on one server - two people wearing the same
        # linked nickname is exactly the confusion this feature exists to prevent.
        taken = await db_one(
            "SELECT user_id FROM vrc_links WHERE guild_id=? AND LOWER(vrchat_name)=LOWER(?) AND user_id!=?",
            (str(interaction.guild_id), name, str(interaction.user.id)),
        )
        if taken:
            await interaction.response.send_message(
                f"❌ **{name}** ist auf diesem Server schon mit <@{taken['user_id']}> verknüpft. "
                f"Wenn das ein Fehler ist, wende dich an die Moderation.", ephemeral=True)
            return

        auto = (await get_guild_config(interaction.guild_id, "vrc_auto_approve") or "0") == "1"
        status = "approved" if auto else "pending"
        now = datetime.datetime.utcnow().isoformat()
        # Both unique indexes on this table can still reject the write even though the checks
        # above passed: two people can run /vrc-link with the same name in the same instant,
        # and the database is the only place that can settle that. Unhandled, the exception
        # would escape before any response is sent, which Discord shows as a bare "This
        # interaction failed" - the one outcome that tells the member nothing at all.
        try:
            if existing:
                await db_exec(
                    "UPDATE vrc_links SET vrchat_name=?, status=?, requested_at=?, decided_at='', "
                    "decided_by='' WHERE id=?",
                    (name, status, now, existing["id"]),
                )
            else:
                await db_exec(
                    "INSERT INTO vrc_links (guild_id, user_id, vrchat_name, status, requested_at) "
                    "VALUES (?,?,?,?,?)",
                    (str(interaction.guild_id), str(interaction.user.id), name, status, now),
                )
        except Exception as e:
            print(f"[vrc_link] storing link for {interaction.user.id} in {interaction.guild_id} failed: {e}")
            await interaction.response.send_message(
                f"❌ **{name}** konnte nicht gespeichert werden — der Name ist vermutlich gerade "
                f"von jemand anderem eingetragen worden. Versuch es nochmal.", ephemeral=True)
            return

        if not auto:
            await interaction.response.send_message(
                f"✅ **{name}** eingetragen. Die Moderation schaut es sich an und gibt es frei.",
                ephemeral=True)
            return
        changed = await apply_link(self.bot, interaction.guild, interaction.user, name)
        extra = (" · " + ", ".join(changed)) if changed else ""
        await interaction.response.send_message(
            f"✅ **{name}** verknüpft{extra}.", ephemeral=True)

    @app_commands.command(name="vrc-unlink", description="Eigene VRChat-Verknüpfung entfernen")
    async def vrc_unlink(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ Das geht nur auf einem Server.", ephemeral=True)
            return
        row = await db_one(
            "SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
            (str(interaction.guild_id), str(interaction.user.id)),
        )
        if not row:
            await interaction.response.send_message(
                "❌ Du hast hier keine Verknüpfung.", ephemeral=True)
            return
        await db_exec("DELETE FROM vrc_links WHERE id=?", (row["id"],))
        if row["status"] == "approved":
            await revoke_link(self.bot, interaction.guild, interaction.user)
        await interaction.response.send_message("✅ Verknüpfung entfernt.", ephemeral=True)

    @app_commands.command(name="vrc-whois", description="Verknüpften VRChat-Namen eines Mitglieds anzeigen")
    async def vrc_whois(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ Das geht nur auf einem Server.", ephemeral=True)
            return
        row = await db_one(
            "SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
            (str(interaction.guild_id), str(member.id)),
        )
        if not row:
            await interaction.response.send_message(
                f"{member.display_name} hat keine VRChat-Verknüpfung.", ephemeral=True)
            return
        state = "✅ bestätigt" if row["status"] == "approved" else "⏳ wartet auf Freigabe"
        await interaction.response.send_message(
            f"{member.display_name} → **{row['vrchat_name']}** ({state})", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Someone who left and came back keeps what they had.

        Without this their row sits in the table marked approved while the role and nickname
        are gone with the old membership - and re-running /vrc-link would just tell them the
        name is already taken, by themselves.
        """
        try:
            row = await db_one(
                "SELECT * FROM vrc_links WHERE guild_id=? AND user_id=? AND status='approved'",
                (str(member.guild.id), str(member.id)),
            )
            if row:
                await apply_link(self.bot, member.guild, member, row["vrchat_name"])
        except Exception as e:
            print(f"[vrc_link] rejoin handling failed for {member.id} in {member.guild.id}: {e}")


async def setup(bot):
    await bot.add_cog(VRCLink(bot))
