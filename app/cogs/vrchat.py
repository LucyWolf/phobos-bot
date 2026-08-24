import aiohttp
import discord
import pyotp
from discord.ext import commands, tasks

from database import db_exec, db_rows, get_config, get_guild_config

# VRChat requires a descriptive User-Agent on every request or it rejects them outright.
API_BASE = "https://api.vrchat.cloud/api/1"
USER_AGENT = "PhobosBot/1.0 (Discord bot VRChat integration)"


async def vrchat_login(session: aiohttp.ClientSession) -> tuple[bool, str]:
    """Logs the given session in with the globally configured VRChat account (one shared
    bot-owned account for the whole bot - VRChat has no app-level API keys like Twitch, only
    real account login). Shared between the polling cog and the /settings/vrchat test button
    so both go through the exact same handshake. Returns (success, message)."""
    username = await get_config("vrchat_username")
    password = await get_config("vrchat_password")
    totp_secret = await get_config("vrchat_totp_secret")
    if not username or not password:
        return False, "Kein VRChat-Account konfiguriert."

    auth = aiohttp.BasicAuth(username, password)
    try:
        async with session.get(f"{API_BASE}/auth/user", auth=auth) as resp:
            if resp.status != 200:
                return False, f"Login fehlgeschlagen (HTTP {resp.status}) - Zugangsdaten prüfen."
            data = await resp.json(content_type=None)
    except Exception as e:
        return False, f"Verbindungsfehler: {e}"

    if isinstance(data, dict) and data.get("requiresTwoFactorAuth"):
        if not totp_secret:
            return False, "Account verlangt 2FA, aber kein TOTP-Secret hinterlegt."
        methods = data["requiresTwoFactorAuth"]
        endpoint = "totp" if "totp" in methods else "otp"
        code = pyotp.TOTP(totp_secret).now()
        try:
            async with session.post(
                f"{API_BASE}/auth/twofactorauth/{endpoint}/verify", json={"code": code}
            ) as resp2:
                verify_data = await resp2.json(content_type=None)
        except Exception as e:
            return False, f"2FA-Verifizierung fehlgeschlagen: {e}"
        if not isinstance(verify_data, dict) or not verify_data.get("verified"):
            return False, "2FA-Code wurde von VRChat nicht akzeptiert (TOTP-Secret korrekt?)."

    return True, "Login erfolgreich."


class VRChat(commands.Cog):
    """Polls VRChat group instances and announces newly-opened ones in Discord."""

    def __init__(self, bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None
        self._logged_in = False
        self._warned_no_credentials = False
        self.vrchat_loop.start()

    def cog_unload(self):
        self.vrchat_loop.cancel()
        if self._session and not self._session.closed:
            self.bot.loop.create_task(self._session.close())

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})
        return self._session

    async def reset_session(self):
        """Drops the current login/cookies so the next poll re-authenticates from scratch -
        called after /settings/vrchat saves new credentials, otherwise this cog would keep
        using the old account's still-valid session until it happens to expire on its own."""
        self._logged_in = False
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _login(self) -> bool:
        session = await self._get_session()
        ok, message = await vrchat_login(session)
        if not ok:
            if "Kein VRChat-Account" in message:
                if not self._warned_no_credentials:
                    print(f"[VRChat] {message} Siehe Einstellungen → VRChat.")
                    self._warned_no_credentials = True
            else:
                print(f"[VRChat] {message}")
            return False
        self._logged_in = True
        self._warned_no_credentials = False
        return True

    async def _get_group_instances(self, group_id: str) -> list[dict] | None:
        session = await self._get_session()
        if not self._logged_in and not await self._login():
            return None
        try:
            async with session.get(f"{API_BASE}/groups/{group_id}/instances") as resp:
                if resp.status in (401, 403):
                    # Session cookie expired - one fresh login + retry before giving up. 403 is
                    # included alongside 401 since it isn't confirmed which one VRChat actually
                    # uses for an expired session (not verified against a live account) - worst
                    # case a real permission error just costs one wasted extra login attempt.
                    self._logged_in = False
                    if not await self._login():
                        return None
                    async with session.get(f"{API_BASE}/groups/{group_id}/instances") as resp2:
                        if resp2.status != 200:
                            print(f"[VRChat] HTTP {resp2.status} beim Abrufen der Instanzen "
                                  f"(Gruppe {group_id}) - Gruppen-ID korrekt und öffentlich einsehbar?")
                            return None
                        return await resp2.json(content_type=None)
                if resp.status != 200:
                    # No log for 401/403 here - already handled above, this is any other
                    # unexpected status (404 = falsche/gelöschte Gruppen-ID, 429 = rate limit,
                    # 5xx = VRChat-Ausfall). Silently returning None here made a wrong group ID -
                    # the single most likely first-time mistake - completely undiagnosable.
                    print(f"[VRChat] HTTP {resp.status} beim Abrufen der Instanzen "
                          f"(Gruppe {group_id}) - Gruppen-ID korrekt und öffentlich einsehbar?")
                    return None
                return await resp.json(content_type=None)
        except Exception as e:
            print(f"[VRChat] Fehler beim Abrufen der Instanzen (Gruppe {group_id}): {e}")
            return None

    @tasks.loop(minutes=2)
    async def vrchat_loop(self):
        for guild in list(self.bot.guilds):
            try:
                if await get_guild_config(guild.id, "vrchat_enabled") != "1":
                    continue
                groups = await db_rows(
                    "SELECT * FROM vrchat_groups WHERE guild_id=?", (str(guild.id),)
                )
                for row in groups:
                    # Per-group, not just per-guild: one group's API hiccup shouldn't cost the
                    # other groups this same guild is watching their poll for this tick too.
                    try:
                        await self._poll_group(guild, row)
                    except Exception as e:
                        print(f"[VRChat] Fehler bei Gruppe {row['group_id']} (Guild {guild.id}): {e}")
            except Exception as e:
                print(f"[VRChat] Fehler in Guild {guild.id}: {e}")

    async def _poll_group(self, guild: discord.Guild, row: dict):
        instances = await self._get_group_instances(row["group_id"])
        if instances is None:
            return  # already logged inside _get_group_instances
        if not isinstance(instances, list):
            # 200 OK but an unexpected JSON shape (e.g. an error object instead of a list) -
            # _get_group_instances only validates the HTTP status, not the payload shape.
            print(f"[VRChat] Unerwartete Antwort (kein Array) für Gruppe {row['group_id']}: {instances!r:.200}")
            return

        # The exact instance-identifier field isn't confirmed against a live account yet -
        # falling back from id to location covers either shape the API returns.
        current = {
            str(i.get("id") or i.get("location") or ""): i
            for i in instances if isinstance(i, dict) and (i.get("id") or i.get("location"))
        }
        known_ids = {x.strip() for x in (row["known_instances"] or "").split(",") if x.strip()}
        new_ids = set(current.keys()) - known_ids

        # Only instances still open from last poll (unaffected either way) plus ones we just
        # confirmed announcing count as "known" - one that fails to send (missing channel, a
        # Discord API hiccup) stays out so it's retried next tick instead of silently lost,
        # matching how the Twitch cog defers its own live=1 update until after a successful send.
        confirmed = set(current.keys()) & known_ids
        if new_ids:
            channel = self.bot.get_channel(int(row["channel_id"]))
            if channel:
                for inst_id in new_ids:
                    try:
                        await self._announce(channel, current[inst_id])
                        confirmed.add(inst_id)
                    except Exception as e:
                        print(f"[VRChat] Ankündigung fehlgeschlagen (Guild {guild.id}): {e}")

        await db_exec(
            "UPDATE vrchat_groups SET known_instances=? WHERE id=?",
            (",".join(confirmed), row["id"]),
        )

    @vrchat_loop.before_loop
    async def _before_loop(self):
        await self.bot.wait_until_ready()

    async def _announce(self, channel: discord.TextChannel, instance: dict):
        world = instance.get("world")
        world_name = world.get("name") if isinstance(world, dict) else None
        member_count = instance.get("memberCount", instance.get("userCount", "?"))
        embed = discord.Embed(
            title="🌐 Lobby ist offen!",
            description=world_name or "Eine neue VRChat-Instanz wurde geöffnet.",
            color=0x1f8b4c,
        )
        embed.add_field(name="Mitglieder", value=str(member_count), inline=True)
        await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(VRChat(bot))
