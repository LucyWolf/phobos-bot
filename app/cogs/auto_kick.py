import datetime

import discord
from discord.ext import commands, tasks

from database import db_one, db_rows, db_exec, get_guild_config

# User-requested ("die wenn die eine bestimte zeit nicht frei gegeben sind ... dann gekickt
# wirt also eine pm ... das wen der das nicht bals macht kekickt wirt", later: "mach das so
# das man mehrer zeiten einstelen kann"): members who haven't received a given role within a
# configurable time after joining get one or more reminder DMs at admin-configured offsets,
# then get kicked at a final, separately configurable time if they still don't have it. What
# the role actually represents (age verification via a support ticket + photo ID, in the
# requesting user's case) stays entirely manual/staff-side - this only automates the
# "remind repeatedly, then remove" part for whoever never finishes it.
DEFAULT_REMINDER_MESSAGE = (
    "Hallo {user}! Auf **{server}** ist eine Freigabe nötig, die du noch nicht abgeschlossen "
    "hast. Bitte kümmere dich zeitnah darum, sonst wirst du automatisch vom Server entfernt, "
    "sobald {kick_hours} Stunden seit deinem Beitritt vergangen sind."
)


class AutoKick(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._check.start()

    def cog_unload(self):
        self._check.cancel()

    async def _get_config(self, guild_id: int) -> dict | None:
        enabled = await get_guild_config(guild_id, "auto_kick_enabled")
        if enabled != "1":
            return None
        role_id = await get_guild_config(guild_id, "auto_kick_role_id")
        kick_hours = await get_guild_config(guild_id, "auto_kick_kick_hours")
        enabled_at = await get_guild_config(guild_id, "auto_kick_enabled_at")
        if not role_id or not kick_hours or not enabled_at:
            # Saved as "enabled" but missing a required field (shouldn't happen via the
            # dashboard - server_config_save() requires these together, see main.py) - fail
            # safe rather than guess a default kick delay no admin actually chose.
            return None
        try:
            kick_hours = int(kick_hours)
            enabled_at_dt = datetime.datetime.fromisoformat(enabled_at)
        except ValueError:
            return None
        reminders = await db_rows(
            "SELECT id, hours, message FROM auto_kick_reminders WHERE guild_id=? ORDER BY hours",
            (str(guild_id),),
        )
        return {
            "role_id": role_id, "kick_hours": kick_hours, "enabled_at": enabled_at_dt,
            "reminders": reminders,
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
                print(f"[AutoKick] Prüfung für Guild {guild.id} fehlgeschlagen: {e}")

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
        kick_delta = datetime.timedelta(hours=cfg["kick_hours"])
        for member in guild.members:
            if member.bot or role in member.roles:
                continue
            # Guild owner and anyone with real admin-level access is skipped unconditionally -
            # staff/the owner often predate the tracked role entirely and would otherwise risk
            # getting auto-kicked from their own server. Not something the user asked for
            # explicitly, but the failure mode (silently kicking an admin) is severe enough to
            # guard against by default rather than wait for it to happen once.
            if member.id == guild.owner_id or member.guild_permissions.administrator:
                continue
            joined_at = member.joined_at
            if not joined_at or joined_at < cfg["enabled_at"]:
                # Joined before this was ever turned on for this guild - per explicit request,
                # only members who join AFTER enabling are subject to this at all, so existing
                # unmarked members never get swept up by turning the feature on.
                continue
            elapsed = now - joined_at
            if elapsed >= kick_delta:
                await self._kick(guild, member)
                continue
            for reminder in cfg["reminders"]:
                if elapsed >= datetime.timedelta(hours=reminder["hours"]):
                    await self._remind_if_needed(guild, member, reminder, cfg["kick_hours"])

    async def _remind_if_needed(self, guild: discord.Guild, member: discord.Member, reminder: dict, kick_hours: int):
        joined_iso = member.joined_at.isoformat()
        row = await db_one(
            "SELECT joined_at FROM auto_kick_sent WHERE guild_id=? AND user_id=? AND reminder_id=?",
            (str(guild.id), str(member.id), reminder["id"]),
        )
        if row and row["joined_at"] == joined_iso:
            return  # this specific reminder was already sent for this exact membership
        text = (reminder["message"].replace("{user}", member.mention)
                                    .replace("{server}", guild.name)
                                    .replace("{kick_hours}", str(kick_hours)))
        try:
            await member.send(text)
        except discord.HTTPException:
            pass  # DMs closed/blocked - still record the attempt so we don't retry every tick
        await db_exec(
            "INSERT INTO auto_kick_sent (guild_id, user_id, reminder_id, joined_at) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id, user_id, reminder_id) DO UPDATE SET joined_at=excluded.joined_at",
            (str(guild.id), str(member.id), reminder["id"], joined_iso),
        )

    async def _kick(self, guild: discord.Guild, member: discord.Member):
        try:
            await guild.kick(member, reason="Frist ohne erforderliche Rolle abgelaufen (Auto-Kick)")
        except discord.Forbidden:
            # Missing "Mitglieder kicken" permission - nothing to clean up, just retry next tick.
            return
        except discord.HTTPException as e:
            print(f"[AutoKick] Kick von {member.id} in Guild {guild.id} fehlgeschlagen: {e}")
            return
        await db_exec(
            "DELETE FROM auto_kick_sent WHERE guild_id=? AND user_id=?",
            (str(guild.id), str(member.id)),
        )


async def setup(bot):
    await bot.add_cog(AutoKick(bot))
