from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import aiohttp

from database import db_one


def _err_text(e: Exception) -> str:
    # str(e) is an empty string for several common exception types (e.g. asyncio.TimeoutError
    # on an unreachable AMP host, confirmed live) - falling back to the exception's class name
    # ensures the user always sees SOMETHING instead of a bare, unhelpful "Fehler: " with
    # nothing after the colon.
    return str(e) or type(e).__name__


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


def _extract_instance(d) -> dict | None:
    """Returns a normalized {"id", "name", "running", "module"} from a raw dict if it looks
    like an actual game instance, else None. Field names are read defensively (several
    fallbacks tried per field) since the exact response shape could not be verified without a
    real, authenticated call against a live instance."""
    if not isinstance(d, dict):
        return None
    iid = d.get("InstanceID") or d.get("InstanceId") or d.get("ID")
    if not iid:
        return None
    module = d.get("Module") or d.get("ModuleDisplayName") or ""
    name = d.get("FriendlyName") or d.get("InstanceName") or d.get("Name") or str(iid)
    running = d.get("Running")
    if running is None:
        running = d.get("AppState") not in (None, 10)
    return {"id": str(iid), "name": name, "running": bool(running), "module": module}


def _summarize_raw(raw) -> str:
    """Compact structural summary of ADSModule.GetInstances()'s raw response for debugging -
    counts and brief per-entry identifiers instead of a truncated raw dump, since a real
    nested instance list can easily be larger than any reasonable truncation limit (confirmed
    live: a 500-char truncation cut off after the very first nested entry, before any actual
    game instances could even be seen)."""
    items = raw if isinstance(raw, list) else (raw or {}).get("result") or []
    if not isinstance(items, list):
        return f"Unerwartete Form: {type(raw).__name__}"
    lines = [f"Top-Level-Einträge: {len(items)}"]
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            lines.append(f"[{i}] kein Objekt ({type(item).__name__})")
            continue
        keys = list(item.keys())
        lines.append(f"[{i}] Felder ({len(keys)}): {keys}")
        own = _extract_instance(item)
        if own:
            lines.append(f"    selbst instanzartig: Module={own['module']!r} Name={own['name']!r} Running={own['running']}")
        for key, value in item.items():
            if isinstance(value, list):
                lines.append(f"    Liste '{key}': {len(value)} Einträge")
                for j, sub in enumerate(value):
                    sub_inst = _extract_instance(sub)
                    if sub_inst:
                        lines.append(f"      [{j}] Module={sub_inst['module']!r} Name={sub_inst['name']!r} Running={sub_inst['running']}")
                    elif isinstance(sub, dict):
                        lines.append(f"      [{j}] kein Instanz-Muster, Felder: {list(sub.keys())}")
                    else:
                        lines.append(f"      [{j}] {type(sub).__name__}: {str(sub)[:80]}")
    return "\n".join(lines)


def _parse_instances(raw) -> list[dict]:
    """Parses ADSModule.GetInstances()'s response into a normalized list of
    {"id": str, "name": str, "running": bool, "module": str}. AMP groups instances by hosting
    "Target" (the machine running them) - confirmed live: a top-level entry can be a target
    wrapper (its own ID-like field, but a FriendlyName like the literal "Local Instances" -
    AMP's default name for instances hosted on the same machine as the ADS itself) with the
    actual game instances nested inside one of its list-valued fields, rather than being a
    game instance itself. A naive single-level parse mistook that wrapper for a single game
    and missed everything nested inside it. Prefers nested instance-shaped dicts (scans every
    list-valued field, without needing to guess the exact nested key name) and only falls back
    to treating a top-level entry as an instance itself when nothing nested was found - this
    keeps supporting a hypothetical genuinely flat response shape too. AMP versions differ on
    whether the ADS's own control instance is included (Module == "ADS") - excluded here since
    it isn't a game server to show/manage."""
    items = raw if isinstance(raw, list) else (raw or {}).get("result") or []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        found_nested = False
        for value in item.values():
            if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
                for sub in value:
                    sub_inst = _extract_instance(sub)
                    if sub_inst:
                        found_nested = True
                        if sub_inst["module"] != "ADS":
                            out.append(sub_inst)
        if found_nested:
            continue
        inst = _extract_instance(item)
        if inst and inst["module"] != "ADS":
            out.append(inst)
    return out


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
            return {"online": False, "error": _err_text(e), "raw": None}

    async def _amp_action(self, cfg: dict, method: str) -> tuple[bool, str]:
        try:
            async with aiohttp.ClientSession() as session:
                session_id = await _amp_login(session, cfg["url"], cfg["username"], cfg["password"])
                await _amp_call(session, cfg["url"], "Core", method, SESSIONID=session_id)
            return True, ""
        except Exception as e:
            return False, _err_text(e)

    async def _set_running(self, cfg: dict, start: bool) -> tuple[bool, str]:
        return await self._amp_action(cfg, "Start" if start else "Stop")

    async def _restart(self, cfg: dict) -> tuple[bool, str]:
        return await self._amp_action(cfg, "Restart")

    async def _list_instances(self, cfg: dict) -> dict:
        """A connection can be a single standalone AMP instance OR the main ADS controller
        managing several game instances underneath it (confirmed live for this project's own
        AMP install: a single ADS controller with multiple game instances configured under
        it) - ADSModule.GetInstances() enumerates the latter. Returns
        {"instances": [...], "error": str|None} - a standalone (non-ADS) connection is expected
        to error here (no ADSModule available), callers fall back to treating the connection
        itself as the single controllable target in that case."""
        try:
            async with aiohttp.ClientSession() as session:
                session_id = await _amp_login(session, cfg["url"], cfg["username"], cfg["password"])
                raw = await _amp_call(session, cfg["url"], "ADSModule", "GetInstances", SESSIONID=session_id)
            parsed = _parse_instances(raw)
            summary = _summarize_raw(raw)
            if not parsed:
                # The call itself succeeded (no exception) but nothing was recognized in the
                # response - since the exact field names were never verified against a real ADS,
                # this is just as likely a parsing mismatch as it is a genuinely standalone
                # connection. Surface a structural summary instead of looking identical to "no
                # error, nothing to see" - there'd otherwise be no way to tell those two cases
                # apart or to debug a mismatch without live access to a real ADS instance. A
                # summary rather than a raw dump, because a raw dump truncated to any reasonable
                # length can cut off before showing anything past the first nested entry
                # (confirmed live - a real response's first AvailableInstances entry alone
                # exceeded a 500-char truncation on its own).
                return {"instances": [], "error": "0 Instanzen erkannt (Details im Debug-Bereich unten)",
                        "raw_debug": summary}
            # Always keep the summary even on a successful parse - parsing has already been
            # wrong once before without raising or returning zero results (a wrapper entry was
            # mistaken for a game), so a "looks fine" result here still isn't a strong enough
            # guarantee to skip giving admins a way to double check what AMP actually returned.
            return {"instances": parsed, "error": None, "raw_debug": summary}
        except Exception as e:
            return {"instances": [], "error": _err_text(e), "raw_debug": None}

    async def _instance_action(self, cfg: dict, instance_id: str, method: str) -> tuple[bool, str]:
        # CubeCoders AMP's documented way to target a specific instance from an ADS-authenticated
        # session is a compound URL that proxies the call through the ADS to that instance:
        # /API/ADSModule/Servers/{InstanceID}/API/{Module}/{Method} - NOT verified against a real
        # ADS instance (would need a real login this project deliberately never asks the user
        # for), needs confirming on first live use, same caveat as _amp_is_running's State enum.
        try:
            async with aiohttp.ClientSession() as session:
                session_id = await _amp_login(session, cfg["url"], cfg["username"], cfg["password"])
                url = f"{cfg['url'].rstrip('/')}/API/ADSModule/Servers/{instance_id}/API/Core/{method}"
                async with session.post(url, json={"SESSIONID": session_id}, headers=_HEADERS,
                                         timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp.raise_for_status()
            return True, ""
        except Exception as e:
            return False, _err_text(e)

    async def _resolve_target(self, cfg: dict, server_name: str | None, require_choice: bool):
        """Returns (mode, data, error). mode is "legacy" (connection isn't ADS-style, i.e. no
        instances found - data=None, treat the whole connection as the single target the same
        way this cog always worked before instance support), "instance" (data=the matched
        instance dict), "all" (data=the full instance list - only when require_choice=False
        and server_name was omitted, used by the status command to show everything at once),
        or None (data=None, error=a user-facing message - ambiguous or unmatched server_name,
        or multiple instances exist but the caller requires picking exactly one)."""
        listing = await self._list_instances(cfg)
        instances = listing["instances"]
        if not instances:
            return "legacy", None, None
        if server_name:
            needle = server_name.strip().lower()
            matches = [i for i in instances if i["name"].lower() == needle]
            if not matches:
                matches = [i for i in instances if needle in i["name"].lower()]
            if not matches:
                names = ", ".join(f"„{i['name']}“" for i in instances)
                return None, None, f"Kein Spiel namens „{server_name}“ gefunden. Verfügbar: {names}"
            if len(matches) > 1:
                names = ", ".join(f"„{i['name']}“" for i in matches)
                return None, None, f"Mehrere Treffer für „{server_name}“: {names} — bitte genauer angeben."
            return "instance", matches[0], None
        if len(instances) == 1:
            return "instance", instances[0], None
        if not require_choice:
            return "all", instances, None
        names = ", ".join(f"„{i['name']}“" for i in instances)
        return None, None, f"Mehrere Spiele verknüpft, bitte mit server: angeben welches: {names}"

    @app_commands.command(name="gameserver-status", description="Zeigt ob der verknüpfte Gameserver online ist")
    @app_commands.describe(server="Name des Spiels (nur nötig wenn mehrere verknüpft sind)")
    async def gameserver_status(self, interaction: discord.Interaction, server: str = None):
        cfg = await self._get_config(interaction.guild_id)
        if not cfg:
            await interaction.response.send_message(
                "Für diesen Server ist kein Gameserver verknüpft.", ephemeral=True
            )
            return
        await interaction.response.defer()
        mode, data, error = await self._resolve_target(cfg, server, require_choice=False)
        if error:
            await interaction.followup.send(f"⚠️ {error}", ephemeral=True)
            return
        if mode == "legacy":
            label = cfg.get("label") or "Gameserver"
            result = await self._fetch_status(cfg)
            if result["error"]:
                await interaction.followup.send(f"⚠️ **{label}**: Status nicht abrufbar ({result['error']})")
                return
            icon = "🟢" if result["online"] else "🔴"
            text = "Online" if result["online"] else "Offline"
            await interaction.followup.send(f"{icon} **{label}**: {text}")
        elif mode == "instance":
            icon = "🟢" if data["running"] else "🔴"
            text = "Online" if data["running"] else "Offline"
            await interaction.followup.send(f"{icon} **{data['name']}**: {text}")
        else:  # "all"
            lines = [
                f"{'🟢' if i['running'] else '🔴'} **{i['name']}**: {'Online' if i['running'] else 'Offline'}"
                for i in data
            ]
            await interaction.followup.send("\n".join(lines))

    async def _do_action(self, interaction: discord.Interaction, method: str, server_name: str | None,
                          success_icon: str, success_text: str, fail_text: str):
        cfg = await self._get_config(interaction.guild_id)
        if not cfg:
            await interaction.response.send_message(
                "Für diesen Server ist kein Gameserver verknüpft.", ephemeral=True
            )
            return
        if not await self._check_command_channel(interaction, cfg):
            return
        await interaction.response.defer(ephemeral=True)
        mode, data, error = await self._resolve_target(cfg, server_name, require_choice=True)
        if error:
            await interaction.followup.send(f"⚠️ {error}", ephemeral=True)
            return
        if mode == "legacy":
            ok, err = await self._amp_action(cfg, method)
        else:
            ok, err = await self._instance_action(cfg, data["id"], method)
        name = "" if mode == "legacy" else f" **{data['name']}**"
        if ok:
            await interaction.followup.send(f"{success_icon}{name} {success_text}", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️{name} {fail_text}: {err}", ephemeral=True)

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
    @app_commands.describe(server="Name des Spiels (nur nötig wenn mehrere verknüpft sind)")
    @app_commands.default_permissions(manage_guild=True)
    async def gameserver_start(self, interaction: discord.Interaction, server: str = None):
        await self._do_action(interaction, "Start", server, "🟢", "Startbefehl gesendet.", "Starten fehlgeschlagen")

    @app_commands.command(name="gameserver-stop", description="Stoppt den verknüpften Gameserver")
    @app_commands.describe(server="Name des Spiels (nur nötig wenn mehrere verknüpft sind)")
    @app_commands.default_permissions(manage_guild=True)
    async def gameserver_stop(self, interaction: discord.Interaction, server: str = None):
        await self._do_action(interaction, "Stop", server, "🔴", "Stoppbefehl gesendet.", "Stoppen fehlgeschlagen")

    @app_commands.command(name="gameserver-restart", description="Startet den verknüpften Gameserver neu")
    @app_commands.describe(server="Name des Spiels (nur nötig wenn mehrere verknüpft sind)")
    @app_commands.default_permissions(manage_guild=True)
    async def gameserver_restart(self, interaction: discord.Interaction, server: str = None):
        await self._do_action(interaction, "Restart", server, "🔄", "Neustart-Befehl gesendet.", "Neustart fehlgeschlagen")


async def setup(bot):
    await bot.add_cog(AMP(bot))
