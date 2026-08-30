from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import aiohttp

from database import db_one


# CubeCoders AMP's HTTP API: every call is POST /API/{Module}/{Method} with a JSON body and
# an Accept header of application/json (confirmed live against a real running AMP instance -
# a request without it gets rejected outright with "Invalid accept header value"). Core.Login
# takes username/password/token(TOTP, empty if unused)/rememberMe and returns a sessionID that
# has to be included as "SESSIONID" in the body of every subsequent call.
_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


async def _amp_call(session: aiohttp.ClientSession, base_url: str, module: str, method: str, **params) -> dict:
    url = f"{base_url.rstrip('/')}/API/{module}/{method}"
    async with session.post(url, json=params, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        resp.raise_for_status()
        return await resp.json()


async def _amp_login(session: aiohttp.ClientSession, base_url: str, username: str, password: str) -> str:
    """Returns a sessionID. Raises on any failure (bad credentials, unreachable host, ...) -
    callers are expected to wrap this in their own try/except with a user-facing message,
    same as every other external API call in this project (Twitch, FreeStuff)."""
    data = await _amp_call(session, base_url, "Core", "Login",
                            username=username, password=password, token="", rememberMe=False)
    if not data.get("success", True) or not data.get("sessionID"):
        # AMP returns success=False with a "resultReason" for bad credentials rather than an
        # HTTP error status, so raise_at_url above wouldn't have caught this on its own.
        raise ValueError(data.get("resultReason") or "Login fehlgeschlagen (falsche Zugangsdaten?)")
    return data["sessionID"]


def _amp_is_running(status: dict) -> bool:
    # AMP's Core.GetStatus response shape is well-documented for the fields used here, but the
    # exact numeric State enum values are NOT something we could verify without a real,
    # authenticated call against a live instance (the pre-auth GetAPISpec probe used to design
    # this module only exposes login-related methods, not GetStatus's return schema) - deployed
    # cautiously: prefer an explicit "Running" boolean if AMP provides one, only falling back
    # to the numeric State field (10 = Stopped is the one value that's been stable across AMP
    # versions in every public API reference) if it doesn't. Needs confirming against the
    # user's real instance on first use.
    if "Running" in status:
        return bool(status["Running"])
    return status.get("State") not in (None, 10)


class AMP(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _get_config(self, guild_id: int) -> dict | None:
        cfg = await db_one("SELECT * FROM amp_configs WHERE guild_id=?", (str(guild_id),))
        if not cfg or not cfg.get("url"):
            return None
        return cfg

    async def _fetch_status(self, cfg: dict) -> dict:
        """Returns {"online": bool, "error": str|None, "raw": dict|None}."""
        try:
            async with aiohttp.ClientSession() as session:
                session_id = await _amp_login(session, cfg["url"], cfg["username"], cfg["password"])
                status = await _amp_call(session, cfg["url"], "Core", "GetStatus", SESSIONID=session_id)
            return {"online": _amp_is_running(status), "error": None, "raw": status}
        except Exception as e:
            return {"online": False, "error": str(e), "raw": None}

    async def _set_running(self, cfg: dict, start: bool) -> tuple[bool, str]:
        method = "Start" if start else "Stop"
        try:
            async with aiohttp.ClientSession() as session:
                session_id = await _amp_login(session, cfg["url"], cfg["username"], cfg["password"])
                await _amp_call(session, cfg["url"], "Core", method, SESSIONID=session_id)
            return True, ""
        except Exception as e:
            return False, str(e)

    @app_commands.command(name="gameserver-status", description="Zeigt ob der verknüpfte Gameserver online ist")
    async def gameserver_status(self, interaction: discord.Interaction):
        cfg = await self._get_config(interaction.guild_id)
        if not cfg:
            await interaction.response.send_message(
                "Für diesen Server ist kein Gameserver verknüpft.", ephemeral=True
            )
            return
        await interaction.response.defer()
        result = await self._fetch_status(cfg)
        label = cfg.get("label") or "Gameserver"
        if result["error"]:
            await interaction.followup.send(f"⚠️ **{label}**: Status nicht abrufbar ({result['error']})")
            return
        icon = "🟢" if result["online"] else "🔴"
        text = "Online" if result["online"] else "Offline"
        await interaction.followup.send(f"{icon} **{label}**: {text}")

    async def _check_command_channel(self, interaction: discord.Interaction, cfg: dict) -> bool:
        """Only gameserver-start/-stop are restrictable (per explicit request) - status stays
        usable everywhere, since the whole point of it is letting anyone check at a glance."""
        restricted_id = cfg.get("command_channel_id")
        if not restricted_id or str(interaction.channel_id) == str(restricted_id):
            return True
        channel = interaction.guild.get_channel(int(restricted_id)) if interaction.guild else None
        where = channel.mention if channel else "einem anderen Kanal"
        await interaction.response.send_message(
            f"Dieser Befehl ist nur in {where} erlaubt.", ephemeral=True
        )
        return False

    @app_commands.command(name="gameserver-start", description="Startet den verknüpften Gameserver")
    @app_commands.default_permissions(manage_guild=True)
    async def gameserver_start(self, interaction: discord.Interaction):
        cfg = await self._get_config(interaction.guild_id)
        if not cfg:
            await interaction.response.send_message(
                "Für diesen Server ist kein Gameserver verknüpft.", ephemeral=True
            )
            return
        if not await self._check_command_channel(interaction, cfg):
            return
        await interaction.response.defer(ephemeral=True)
        ok, error = await self._set_running(cfg, start=True)
        if ok:
            await interaction.followup.send("🟢 Startbefehl gesendet.", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ Starten fehlgeschlagen: {error}", ephemeral=True)

    @app_commands.command(name="gameserver-stop", description="Stoppt den verknüpften Gameserver")
    @app_commands.default_permissions(manage_guild=True)
    async def gameserver_stop(self, interaction: discord.Interaction):
        cfg = await self._get_config(interaction.guild_id)
        if not cfg:
            await interaction.response.send_message(
                "Für diesen Server ist kein Gameserver verknüpft.", ephemeral=True
            )
            return
        if not await self._check_command_channel(interaction, cfg):
            return
        await interaction.response.defer(ephemeral=True)
        ok, error = await self._set_running(cfg, start=False)
        if ok:
            await interaction.followup.send("🔴 Stoppbefehl gesendet.", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ Stoppen fehlgeschlagen: {error}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AMP(bot))
