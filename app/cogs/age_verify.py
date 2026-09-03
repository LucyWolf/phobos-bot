import datetime

import discord
from discord.ext import commands, tasks

from database import db_one, db_exec, get_guild_config

# User-requested ("die wenn die eine bestimte zeit nicht frei gegeben sind ... dann gekickt
# wirt also eine pm ... das wen der das nicht bals macht kekickt wirt"): members who haven't
# received the age-verification role within a configurable time after joining get a warning DM,
# then get kicked if they still don't have it after a second, longer configurable time. The
# verification itself (checking an ID via a support ticket) stays entirely manual/staff-side, as
# it already is - this only automates the "nudge, then remove" part for whoever never finishes it.
DEFAULT_MESSAGE = (
    "Hallo {user}! Auf **{server}** ist eine Altersverifizierung nötig, die du noch nicht "
    "abgeschlossen hast. Bitte erstelle dafür ein Ticket, sonst wirst du automatisch vom Server "
    "entfernt, sobald {kick_hours} Stunden seit deinem Beitritt vergangen sind."
)


class AgeVerify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._check.start()

    def cog_unload(self):
        self._check.cancel()

    async def _get_config(self, guild_id: int) -> dict | None:
        enabled = await get_guild_config(guild_id, "age_verify_enabled")
        if enabled != "1":
            return None
        role_id = await get_guild_config(guild_id, "age_verify_role_id")
        warn_hours = await get_guild_config(guild_id, "age_verify_warn_hours")
        kick_hours = await get_guild_config(guild_id, "age_verify_kick_hours")
        enabled_at = await get_guild_config(guild_id, "age_verify_enabled_at")
        if not role_id or not warn_hours or not kick_hours or not enabled_at:
            # Saved as "enabled" but missing a required field (shouldn't happen via the
            # dashboard - server_config_save() requires all four together, see main.py) - fail
            # safe rather than guess a default kick delay no admin actually chose.
            return None
        try:
            warn_hours = int(warn_hours)
            kick_hours = int(kick_hours)
            enabled_at_dt = datetime.datetime.fromisoformat(enabled_at)
        except ValueError:
            return None
        message = await get_guild_config(guild_id, "age_verify_message") or DEFAULT_MESSAGE
        return {
            "role_id": role_id, "warn_hours": warn_hours, "kick_hours": kick_hours,
            "enabled_at": enabled_at_dt, "message": message,
        }

    @tasks.loop(minutes=30)
    async def _check(self):
        for guild in self.bot.guilds:
            try:
                await self._check_guild(guild)
            except Exception as e:
                # One guild's failure (e.g. a role deleted out from under a saved config)
                # mustn't stop every other guild's check for this tick - same per-guild
                # isolation used throughout this project (freestuff.py, notifications.py).
                print(f"[AgeVerify] Prüfung für Guild {guild.id} fehlgeschlagen: {e}")

    @_check.before_loop
    async def _before_check(self):
        await self.bot.wait_until_ready()

    async def _check_guild(self, guild: discord.Guild):
        cfg = await self._get_config(guild.id)
        if not cfg:
            return
        role = guild.get_role(int(cfg["role_id"]))
        if not role:
            return  # role was deleted in Discord since being configured - nothing sensible to check against
        now = datetime.datetime.now(datetime.timezone.utc)
        warn_delta = datetime.timedelta(hours=cfg["warn_hours"])
        kick_delta = datetime.timedelta(hours=cfg["kick_hours"])
        for member in guild.members:
            if member.bot or role in member.roles:
                continue
            # Guild owner and anyone with real admin-level access is skipped unconditionally -
            # staff/the owner often predate the verification role entirely and would otherwise
            # risk getting auto-kicked from their own server. Not something the user asked for
            # explicitly, but the failure mode (silently kicking an admin) is severe enough to
            # guard against by default rather than wait for it to happen once.
            if member.id == guild.owner_id or member.guild_permissions.administrator:
                continue
            joined_at = member.joined_at
            if not joined_at or joined_at < cfg["enabled_at"]:
                # Joined before this was ever turned on for this guild - per explicit request,
                # only members who join AFTER enabling are subject to this at all, so existing
                # unverified members never get swept up by turning the feature on.
                continue
            elapsed = now - joined_at
            if elapsed >= kick_delta:
                await self._kick(guild, member)
            elif elapsed >= warn_delta:
                await self._warn_if_needed(guild, member, cfg["message"], cfg["kick_hours"])

    async def _warn_if_needed(self, guild: discord.Guild, member: discord.Member, message: str, kick_hours: int):
        joined_iso = member.joined_at.isoformat()
        row = await db_one(
            "SELECT joined_at FROM age_verify_warned WHERE guild_id=? AND user_id=?",
            (str(guild.id), str(member.id)),
        )
        if row and row["joined_at"] == joined_iso:
            return  # already warned for this exact membership - don't resend every 30 minutes
        text = (message.replace("{user}", member.mention)
                       .replace("{server}", guild.name)
                       .replace("{kick_hours}", str(kick_hours)))
        try:
            await member.send(text)
        except discord.HTTPException:
            pass  # DMs closed/blocked - still record the attempt so we don't retry every tick
        await db_exec(
            "INSERT INTO age_verify_warned (guild_id, user_id, joined_at) VALUES (?,?,?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET joined_at=excluded.joined_at",
            (str(guild.id), str(member.id), joined_iso),
        )

    async def _kick(self, guild: discord.Guild, member: discord.Member):
        try:
            await guild.kick(member, reason="Altersverifizierung nicht rechtzeitig abgeschlossen")
        except discord.Forbidden:
            # Missing "Mitglieder kicken" permission - nothing to clean up, just retry next tick.
            return
        except discord.HTTPException as e:
            print(f"[AgeVerify] Kick von {member.id} in Guild {guild.id} fehlgeschlagen: {e}")
            return
        await db_exec(
            "DELETE FROM age_verify_warned WHERE guild_id=? AND user_id=?",
            (str(guild.id), str(member.id)),
        )


async def setup(bot):
    await bot.add_cog(AgeVerify(bot))
