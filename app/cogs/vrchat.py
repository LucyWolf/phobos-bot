import aiohttp
import discord
import pyotp
from discord.ext import commands, tasks

from database import get_config, get_guild_config, set_guild_config

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
                if resp.status == 401:
                    # Session cookie expired - one fresh login + retry before giving up.
                    self._logged_in = False
                    if not await self._login():
                        return None
                    async with session.get(f"{API_BASE}/groups/{group_id}/instances") as resp2:
                        if resp2.status != 200:
                            return None
                        return await resp2.json(content_type=None)
                if resp.status != 200:
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
                group_id = (await get_guild_config(guild.id, "vrchat_group_id") or "").strip()
                if not group_id:
                    continue
                channel_id = await get_guild_config(guild.id, "vrchat_channel")
                if not channel_id:
                    continue

                instances = await self._get_group_instances(group_id)
                if not isinstance(instances, list):
                    continue

                # The exact instance-identifier field isn't confirmed against a live account
                # yet - falling back from id to location covers either shape the API returns.
                current = {
                    str(i.get("id") or i.get("location") or ""): i
                    for i in instances if isinstance(i, dict) and (i.get("id") or i.get("location"))
                }
                known_raw = await get_guild_config(guild.id, "vrchat_known_instances") or ""
                known_ids = {x.strip() for x in known_raw.split(",") if x.strip()}
                new_ids = set(current.keys()) - known_ids

                if new_ids:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        for inst_id in new_ids:
                            try:
                                await self._announce(channel, current[inst_id])
                            except Exception as e:
                                print(f"[VRChat] Ankündigung fehlgeschlagen (Guild {guild.id}): {e}")

                await set_guild_config(guild.id, "vrchat_known_instances", ",".join(current.keys()))
            except Exception as e:
                print(f"[VRChat] Fehler in Guild {guild.id}: {e}")

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
