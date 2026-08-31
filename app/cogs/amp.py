from __future__ import annotations

import time

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


# CubeCoders AMP's ApplicationState enum. Originally mapped to 14 fine-grained display
# categories (v1.14.19) - abandoned after two live, directly contradicting observations on this
# project's own "wa" instance proved AppState isn't reliable enough for that level of detail
# (AppState=0/"Stopped" while AMP's own panel showed "Installing"; later AppState=70/"Installing"
# while AMP's own panel showed "Running"). On explicit request ("mach nur 3 stadien oder 4, 4 ist
# error" / "syncron bekommen wir das nicht" - perfect sync isn't achievable, stop chasing it)
# collapsed down to just 4 broad, robust stages: online (handled separately in
# _extract_instance() via the Running bool, which took priority over AppState in v1.14.24 for
# exactly this reliability reason - not part of this dict), offline (cleanly stopped, nothing
# going on), busy (something is actively in progress - starting/stopping/installing/etc., no
# need to distinguish which), and error (a real problem AMP is flagging, or a value nobody
# recognizes - deliberately erring toward "flag it" over confidently guessing "offline" for
# anything unexpected).
AMP_APP_STATES: dict[int, tuple[str, str]] = {
    -1:  ("offline", "gray"),
    0:   ("offline", "gray"),
    5:   ("busy", "yellow"),
    7:   ("busy", "yellow"),
    10:  ("busy", "yellow"),
    20:  ("busy", "yellow"),   # Ready - only reached here when Running is somehow still False
    30:  ("busy", "yellow"),
    40:  ("busy", "yellow"),
    45:  ("busy", "yellow"),
    50:  ("busy", "yellow"),
    60:  ("busy", "yellow"),
    70:  ("busy", "yellow"),
    75:  ("busy", "yellow"),
    80:  ("error", "red"),
    100: ("error", "red"),
    200: ("error", "red"),
    250: ("error", "red"),
    999: ("error", "red"),
}


def _extract_instance(d) -> dict | None:
    """Returns a normalized {"id", "instance_name", "name", "running", "state", "color",
    "app_state", "module"} from a raw dict if it looks like an actual game instance, else None.
    Field names are read defensively (several fallbacks tried per field). "id" (InstanceID, a
    GUID) is used for dashboard URLs/DOM identification - stable and URL-safe. "instance_name"
    (InstanceName, a short string like the AMP module's own generated slug) is kept separately
    since ADSModule's Start/Stop/RestartInstance action methods are documented to take
    InstanceName, not InstanceID - "name" is the human FriendlyName shown in the UI, which can
    differ from both.
    "state" is one of just 4 broad categories now ("online"/"busy"/"offline"/"error") - deliber-
    ately coarse (down from 14 fine-grained ones in v1.14.19-23) per explicit request ("mach nur
    3 stadien oder 4, 4 ist error") after two live, directly contradicting real-world
    observations on this project's own "wa" instance proved finer-grained AppState detail isn't
    reliable enough to show confidently: AMP's own panel showed "Installing" while AppState was
    0 (mapped to "Stopped"), and later showed "Running" while AppState was 70 (mapped to
    "Installing"). Running takes priority for the positive case - "online" whenever Running is
    True, regardless of whatever AppState claims (AMP's own displayed "Running" label matched
    the raw Running bool in both contradicting cases, unlike AppState) - AppState is only
    consulted to distinguish "busy" (something in progress) from "error" (AMP flagging a real
    problem, or a value nobody recognizes) when Running is False.
    "color" is the matching display bucket ("green"/"red"/"yellow"/"gray") for the status pill."""
    if not isinstance(d, dict):
        return None
    iid = d.get("InstanceID") or d.get("InstanceId") or d.get("ID")
    if not iid:
        return None
    module = d.get("Module") or d.get("ModuleDisplayName") or ""
    instance_name = d.get("InstanceName") or str(iid)
    name = d.get("FriendlyName") or instance_name
    app_state = d.get("AppState")
    running = bool(d.get("Running"))
    if running:
        state, color = "online", "green"
    elif app_state in AMP_APP_STATES:
        state, color = AMP_APP_STATES[app_state]
    else:
        # AppState missing entirely or a value nobody recognizes - flagged as "error" rather
        # than confidently guessing "offline" for something genuinely unexpected (same
        # philosophy as the rest of AMP_APP_STATES above).
        state, color = "error", "red"
    ip = d.get("IP") or d.get("ApplicationIP")
    port = d.get("Port")
    address = f"{ip}:{port}" if ip and port else None
    # DisplayImageSource's actual content was never verified against a real instance - used
    # defensively (only if it looks like a real absolute image URL) so an unexpected value
    # (null, a relative AMP-internal path needing its own session/auth, some other shape) just
    # means no background image is shown, never a broken image or a crash.
    image_src = d.get("DisplayImageSource")
    image_url = image_src if isinstance(image_src, str) and image_src.startswith(("http://", "https://")) else None
    return {"id": str(iid), "instance_name": instance_name, "name": name, "running": running,
            "state": state, "color": color, "app_state": app_state, "module": module,
            "address": address, "image_url": image_url}


def _summarize_raw(raw) -> str:
    """Compact structural summary of an AMP API response for debugging - counts and brief
    per-entry identifiers instead of a truncated raw dump, since a real nested instance list
    can easily be larger than any reasonable truncation limit (confirmed live: a 500-char
    truncation cut off after the very first nested entry, before any actual game instances
    could even be seen). Also reused as a generic probe for candidate list methods whose
    response shape isn't known in advance - a top-level dict without a "result" list is shown
    directly (keyed responses, e.g. one entry per instance ID, are just as plausible for some
    of those candidates as a list is)."""
    if isinstance(raw, dict) and not isinstance(raw.get("result"), list):
        keys = list(raw.keys())
        lines = [f"Dict mit {len(keys)} Top-Level-Schlüssel(n): {keys}"]
        for key, value in raw.items():
            if isinstance(value, dict):
                sub_inst = _extract_instance(value)
                if sub_inst:
                    lines.append(f"  '{key}': Module={sub_inst['module']!r} Name={sub_inst['name']!r} Running={sub_inst['running']} AppState={sub_inst['app_state']!r}")
                else:
                    lines.append(f"  '{key}': dict, Felder: {list(value.keys())}")
            else:
                lines.append(f"  '{key}': {type(value).__name__} = {str(value)[:80]}")
        return "\n".join(lines)
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
            lines.append(f"    selbst instanzartig: Module={own['module']!r} Name={own['name']!r} Running={own['running']} AppState={own['app_state']!r}")
        for key, value in item.items():
            if isinstance(value, list):
                lines.append(f"    Liste '{key}': {len(value)} Einträge")
                for j, sub in enumerate(value):
                    sub_inst = _extract_instance(sub)
                    if sub_inst:
                        lines.append(f"      [{j}] Module={sub_inst['module']!r} Name={sub_inst['name']!r} Running={sub_inst['running']} AppState={sub_inst['app_state']!r}")
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


# Short-lived cache for _list_instances(), keyed by the connection's URL+username. Reported
# by the user as "every time I switch away from the Gameserver tab and back, the page loads
# first" - each full page render of that tab did a fresh live AMP login+API round trip with no
# caching at all, so quick back-and-forth tab switching paid that latency every single time.
# TTL is deliberately short (well under the 10s live-poll interval in server_config.html's
# JS) so the poll always sees genuinely fresh data - this only smooths out rapid page reloads,
# it doesn't make the dashboard lag behind real AMP state.
_LIST_CACHE_TTL = 5
_list_cache: dict[str, tuple[float, dict]] = {}


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

    # Confirmed live against a real ADS's Core.GetAPISpec(): ADSModule.GetInstances() only
    # returns the ADS's own control instance wrapped in a Target object, not the actual game
    # instances - these are the next most likely candidates by name for a method that DOES
    # return the actual games, tried directly (no params) rather than guessed at blindly again.
    _CANDIDATE_LIST_METHODS = ["GetLocalInstances", "GetInstanceStatuses", "Servers"]

    async def _probe_ads_methods(self, cfg: dict) -> str:
        """Diagnostic only, not used in normal operation: for each of _CANDIDATE_LIST_METHODS,
        calls it directly (SESSIONID only, no other params) against the real ADS and reports
        what came back - a structural summary on success (via _summarize_raw, reusable since
        the shape is unknown either way), or the actual error otherwise (most usefully, AMP's
        own "missing required parameter" message would reveal what parameter is actually
        needed). Also includes each candidate's declared Parameters from Core.GetAPISpec
        (called authenticated this time - unlike the pre-auth probe used while first designing
        this integration, which only exposed login-related methods, not this one), so a failed
        call's likely cause is visible even without a successful response to inspect. Only ever
        surfaced via the dashboard's debug view when instance discovery already found 0 games,
        never during normal use."""
        try:
            async with aiohttp.ClientSession() as session:
                session_id = await _amp_login(session, cfg["url"], cfg["username"], cfg["password"])
                try:
                    spec = await _amp_call(session, cfg["url"], "Core", "GetAPISpec", SESSIONID=session_id)
                except Exception as e:
                    spec = None
                    spec_error = _err_text(e)
                else:
                    spec_error = None
                ads_meta = {}
                if isinstance(spec, dict):
                    ads_key = next((k for k in spec.keys() if isinstance(k, str) and k.lower() == "adsmodule"), None)
                    if ads_key and isinstance(spec[ads_key], dict):
                        ads_meta = spec[ads_key]

                lines = []
                for method in self._CANDIDATE_LIST_METHODS:
                    lines.append(f"── ADSModule.{method} ──")
                    params = ads_meta.get(method, {}).get("Parameters") if isinstance(ads_meta.get(method), dict) else None
                    if params:
                        lines.append(f"Deklarierte Parameter: {params}")
                    elif spec_error:
                        lines.append(f"(Parameter unbekannt, GetAPISpec fehlgeschlagen: {spec_error})")
                    try:
                        result = await _amp_call(session, cfg["url"], "ADSModule", method, SESSIONID=session_id)
                        lines.append(_summarize_raw(result))
                    except Exception as e:
                        lines.append(f"Aufruf fehlgeschlagen: {_err_text(e)}")
                    lines.append("")
                return "\n".join(lines)
        except Exception as e:
            return f"Login fehlgeschlagen: {_err_text(e)}"

    async def _list_instances(self, cfg: dict) -> dict:
        """A connection can be a single standalone AMP instance OR the main ADS controller
        managing several game instances underneath it (confirmed live for this project's own
        AMP install: a single ADS controller with three game instances configured under it) -
        ADSModule.GetLocalInstances() enumerates the latter (confirmed live - ADSModule.
        GetInstances(), tried first, only returns the ADS's own control instance wrapped in a
        Target object, not the actual games; GetLocalInstances returns a flat list including
        every instance, ADS control instance included, which is filtered out same as before).
        Returns {"instances": [...], "error": str|None} - a standalone (non-ADS) connection is
        expected to error here (no ADSModule available), callers fall back to treating the
        connection itself as the single controllable target in that case."""
        cache_key = f"{cfg.get('url')}|{cfg.get('username')}"
        cached = _list_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < _LIST_CACHE_TTL:
            return cached[1]
        result = await self._list_instances_uncached(cfg)
        _list_cache[cache_key] = (time.monotonic(), result)
        return result

    async def _list_instances_uncached(self, cfg: dict) -> dict:
        try:
            async with aiohttp.ClientSession() as session:
                session_id = await _amp_login(session, cfg["url"], cfg["username"], cfg["password"])
                raw = await _amp_call(session, cfg["url"], "ADSModule", "GetLocalInstances", SESSIONID=session_id)
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
                methods = await self._probe_ads_methods(cfg)
                return {"instances": [], "error": "0 Instanzen erkannt (Details im Debug-Bereich unten)",
                        "raw_debug": f"{summary}\n\n{methods}", "connection_error": False}
            # Debug summary temporarily brought back even on a successful parse (was disabled in
            # v1.14.8 once instance discovery itself was confirmed working) - the AppState enum
            # mapping introduced in v1.14.19 is a much bigger, still-unverified-against-a-real-
            # instance change than discovery itself was, so keeping this visible lets a mismatch
            # be caught and reported directly instead of needing another guess-then-report round.
            return {"instances": parsed, "error": None, "raw_debug": summary, "connection_error": False}
        except Exception as e:
            # Distinct from the "0 recognized" case above: this branch means the call itself
            # never came back cleanly (timeout, DNS/connect failure, bad credentials, ...) -
            # reported live as confusing by the user, since main.py used to treat this exactly
            # like a standalone (non-ADS) connection and fall back to the legacy single-
            # connection status card, which then ALSO tried its own live AMP call (_fetch_status)
            # and typically failed the same way, showing an unrelated "Status — Phobos Game
            # Server" card with a bare "TimeoutError" instead of the admin's actual multi-
            # instance tiles. connection_error=True lets main.py show a plain "AMP currently
            # unreachable, retrying" message tied to the real tile view instead.
            return {"instances": [], "error": _err_text(e), "raw_debug": None, "connection_error": True}

    async def _instance_action(self, cfg: dict, instance_name: str, method: str) -> tuple[bool, str]:
        """method is "Start"/"Stop"/"Restart" (same convention as the legacy whole-connection
        _amp_action), mapped here to ADSModule's own "{method}Instance" methods - confirmed
        live to exist via an authenticated Core.GetAPISpec() call (StartInstance/StopInstance/
        RestartInstance are listed directly under ADSModule). Replaces an earlier, WRONG guess
        that tried to reach a specific instance through a compound passthrough URL
        (/API/ADSModule/Servers/{id}/API/Core/{method}) - never actually verified and abandoned
        once ADSModule's real method list was seen. Takes AMP's own InstanceName directly
        instead of doing its own InstanceID-to-InstanceName lookup via a fresh _list_instances()
        call - that lookup used to run INSIDE this function on every single click, doubling
        every action to two full login+API round trips (list, then act) and making a single
        button press take up to ~40s in the worst case, which the user reported as the whole
        bot appearing to hang. Callers already have instance_name from a prior
        _list_instances()/_resolve_target() call, so it's passed straight through now."""
        try:
            async with aiohttp.ClientSession() as session:
                session_id = await _amp_login(session, cfg["url"], cfg["username"], cfg["password"])
                await _amp_call(session, cfg["url"], "ADSModule", f"{method}Instance",
                                 SESSIONID=session_id, InstanceName=instance_name)
            # Drop any cached listing for this connection so the page the user gets redirected
            # back to (or the next live-poll tick) doesn't show pre-action state for up to
            # _LIST_CACHE_TTL seconds, which would look like the click did nothing.
            _list_cache.pop(f"{cfg.get('url')}|{cfg.get('username')}", None)
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
            ok, err = await self._instance_action(cfg, data["instance_name"], method)
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
