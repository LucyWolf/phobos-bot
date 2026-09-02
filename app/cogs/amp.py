from __future__ import annotations

import asyncio
import re
import time

import discord
from discord import app_commands
from discord.ext import commands

import aiohttp

from database import db_one, db_rows, db_exec


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

# Discord-side label for the same 4 states the dashboard tile shows (main.py's
# _AMP_STATE_TR_KEYS/_amp_state_label do the i18n'd equivalent for the web UI - cogs in this
# project don't use i18n, Discord output is hardcoded German throughout, same as everywhere
# else in this bot). Kept in sync manually with AMP_APP_STATES' 4 category keys.
_STATE_LABELS = {
    "online": ("🟢", "Online"),
    "busy": ("🟡", "Beschäftigt"),
    "offline": ("⚫", "Offline"),
    "error": ("🔴", "Fehler"),
}


def _extract_instance(d) -> dict | None:
    """Returns a normalized {"id", "instance_name", "name", "running", "state", "color",
    "app_state", "module", "game_name"} from a raw dict if it looks like an actual game
    instance, else None.
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
    # ModuleDisplayName reliably holds the actual game ("Palworld", "Satisfactory", "Space
    # Engineers", ...) - confirmed live across three real instances after Description/
    # WelcomeMessage/SpecificDockerImage (the originally guessed candidates) all turned out
    # empty or too coarse to tell games apart (SpecificDockerImage was identical - "cubecoders/
    # ampbase:debian" - for two different games). Distinct from `module` above (the raw AMP
    # "Module" field, e.g. "GenericModule" - used only to filter out the ADS controller itself,
    # not for display).
    game_name = d.get("ModuleDisplayName") or ""
    return {"id": str(iid), "instance_name": instance_name, "name": name, "running": running,
            "state": state, "color": color, "app_state": app_state, "module": module,
            "game_name": game_name, "address": address, "image_url": image_url}


def _debug_game_fields(d) -> str:
    """One-off diagnostic addition to _summarize_raw()'s per-instance debug lines: the dashboard
    tile currently only shows the admin-chosen FriendlyName (e.g. "wa"), not what game is
    actually running - User: "kann man da nicht auch einblenden lassen was das für ein Game ist,
    und nicht wie der Container heißt". Description/WelcomeMessage/SpecificDockerImage are
    candidate fields that might carry that (their field NAMES were already visible in a prior
    debug dump, but never their actual VALUES) - surfaced here in the existing, already-open
    debug panel so the admin can check without needing AMP credentials or another live-probe
    round from me. Not yet wired into the tile itself - depends on which of these, if any,
    actually holds something useful."""
    if not isinstance(d, dict):
        return ""
    parts = []
    for field in ("Description", "WelcomeMessage", "SpecificDockerImage"):
        value = d.get(field)
        if value:
            parts.append(f"{field}={str(value)[:80]!r}")
    return " " + " ".join(parts) if parts else ""


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
                    lines.append(f"  '{key}': Module={sub_inst['module']!r} Name={sub_inst['name']!r} Running={sub_inst['running']} AppState={sub_inst['app_state']!r}{_debug_game_fields(value)}")
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
            lines.append(f"    selbst instanzartig: Module={own['module']!r} Name={own['name']!r} Running={own['running']} AppState={own['app_state']!r}{_debug_game_fields(item)}")
        for key, value in item.items():
            if isinstance(value, list):
                lines.append(f"    Liste '{key}': {len(value)} Einträge")
                for j, sub in enumerate(value):
                    sub_inst = _extract_instance(sub)
                    if sub_inst:
                        lines.append(f"      [{j}] Module={sub_inst['module']!r} Name={sub_inst['name']!r} Running={sub_inst['running']} AppState={sub_inst['app_state']!r}{_debug_game_fields(sub)}")
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

# Reported live: Running flips True the instant AMP's underlying process/container starts, well
# before a slow-loading game is actually joinable ("dieser braucht sehr lange zum starten...und
# dennoch steht schon online drauf"). A TCP-connect check against the game's own port was tried
# and deliberately abandoned (see git history) since most game servers use UDP, not TCP.
#
# A live-timed trace against the real "wa" (Palworld) instance then found an actual, precise
# signal instead of a guessed timer: AppState went 0 (Running already True, container starting)
# -> 70 for ~2 minutes (loading, port still closed, CPU=0%) -> port opened (still AppState=70)
# -> 20 (port open AND CPU jumped to a sustained 3-4%, i.e. the game engine is genuinely
# ticking, not just the container having booted) -> stayed stable at 20 for several more
# minutes. AppState=20 is exactly the point where two independent signals (port + CPU) agree the
# game is really ready - this matches the community ampapi wrapper's own claim that 20="Ready",
# even though that same wrapper's claim about 70="Installing" doesn't hold here (this was a
# fully-installed instance loading normally, nothing being installed) - so AppState as a whole is
# still not blindly trusted (see AMP_APP_STATES's own comment), just this one specific value,
# now with two independent live confirmations behind it.
#
# Only verified against Palworld so far - a game/module where AppState never actually reaches 20
# (or means something else there) must not get stuck on "busy" forever, so a time ceiling is
# kept as a fallback: AppState=20 lets an instance flip to "online" as soon as it's confirmed
# (can happen well before the ceiling, as fast as the game itself loads), but if the ceiling
# elapses first without ever seeing AppState=20, Running alone is trusted anyway.
_STARTUP_CEILING_SECONDS = 240  # covers the observed ~134s Palworld load time with headroom
_AMP_STATE_READY = 20
# How long _notify_when_online() (Discord "server is now online" follow-up) keeps polling before
# giving up silently - kept under Discord's ~15 minute interaction-followup webhook validity.
_NOTIFY_TIMEOUT_SECONDS = 600
_running_since: dict[str, float] = {}


def _apply_startup_grace(instances: list[dict]) -> None:
    now = time.monotonic()
    for inst in instances:
        iid = inst["id"]
        if inst.get("running"):
            since = _running_since.setdefault(iid, now)
            confirmed_ready = inst.get("app_state") == _AMP_STATE_READY
            if not confirmed_ready and now - since < _STARTUP_CEILING_SECONDS:
                inst["state"], inst["color"] = "busy", "yellow"
        else:
            _running_since.pop(iid, None)


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
            _apply_startup_grace(parsed)
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
            icon, text = _STATE_LABELS.get(data["state"], _STATE_LABELS["error"])
            game = f" ({data['game_name']})" if data.get("game_name") else ""
            await interaction.followup.send(f"{icon} **{data['name']}**{game}: {text}")
        else:  # "all"
            lines = []
            for i in data:
                icon, text = _STATE_LABELS.get(i["state"], _STATE_LABELS["error"])
                game = f" ({i['game_name']})" if i.get("game_name") else ""
                lines.append(f"{icon} **{i['name']}**{game}: {text}")
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
            # Requested live: "wäre cool wenn da stehen würde server ist jetzt online oder so" -
            # the confirmation above only means the command was accepted, not that the game is
            # actually playable yet (same real load-time gap the dashboard tile now accounts for
            # via AppState=20 detection - see _apply_startup_grace()'s comment). Only for a
            # genuine Start on a resolved multi-instance target (mode=="instance") - a "legacy"
            # single-connection target has no per-instance id to track, and Stop/Restart don't
            # have an equally clear "done" signal to wait for.
            if method == "Start" and mode == "instance":
                asyncio.create_task(self._notify_when_online(
                    interaction, cfg, data["id"], data["name"], data.get("game_name") or ""))
        else:
            await interaction.followup.send(f"⚠️{name} {fail_text}: {err}", ephemeral=True)

    async def _notify_when_online(self, interaction: discord.Interaction, cfg: dict,
                                   instance_id: str, name: str, game_name: str) -> None:
        """Background follow-up after a successful Start: polls (through the existing cached
        _list_instances(), so this doesn't add extra load beyond what the dashboard tile already
        causes) until the instance reaches "online" - the same AppState=20-confirmed readiness
        the tile shows, not just a raw Running flip - then sends a second message so the user
        doesn't have to keep checking. Discord's interaction followup webhook stays valid for
        15 minutes after the original interaction; _NOTIFY_TIMEOUT_SECONDS is kept safely under
        that. Times out silently (no message) rather than spamming an "still not sure" notice -
        the tile and /gameserver-status remain available for a manual check either way."""
        deadline = time.monotonic() + _NOTIFY_TIMEOUT_SECONDS
        game = f" ({game_name})" if game_name else ""
        while time.monotonic() < deadline:
            await asyncio.sleep(_LIST_CACHE_TTL + 2)
            try:
                listing = await self._list_instances(cfg)
            except Exception:
                continue
            match = next((i for i in listing["instances"] if i["id"] == instance_id), None)
            if not match:
                continue
            if match["state"] == "online":
                try:
                    await interaction.followup.send(f"🟢 **{name}**{game} ist jetzt online!", ephemeral=True)
                except discord.HTTPException:
                    pass
                return
            if match["state"] == "error":
                try:
                    await interaction.followup.send(f"🔴 **{name}**{game} meldet einen Fehler beim Starten.", ephemeral=True)
                except discord.HTTPException:
                    pass
                return

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

    # ── Custom per-instance slash commands ──────────────────────────────────────────────────
    # User-requested: "kanst du bei jeden server ein zahnrad dran machen wo ich dann befehle
    # selber eingeben kan wie die dan heisen sollen" - confirmed via follow-up as dedicated
    # per-instance slash commands (e.g. /wa-start), not just aliases for the server: parameter
    # on the existing global commands above. First version used one shared prefix generating
    # {prefix}-start/-stop/-restart automatically - turned out not to be what was wanted either:
    # "ich kann dort nur start befehl anpassen ich will aber auch getrent vom start auch stop
    # und restart befehl anpassen können" - each of the 3 actions now has its own fully
    # independent, freely-typed command name (amp_instance_commands.start_name/stop_name/
    # restart_name), no shared prefix/suffix pattern at all. Status stays covered by the
    # existing global /gameserver-status only (explicitly declined, see the v1.14.33 note in
    # CLAUDE.md's changelog).
    #
    # Registered as GUILD commands (tree.add_command(..., guild=...) + tree.sync(guild=...)),
    # not global ones - main.py's only existing tree.sync() call (on_ready) syncs globally,
    # which can take up to an hour to propagate. A feature that changes the moment an admin
    # types a name into the dashboard can't wait that long; guild-scoped commands sync in
    # seconds, completely independent of the global sync.

    _RESERVED_COMMAND_NAMES = {  # would collide with the existing global commands above
        "gameserver-status", "gameserver-start", "gameserver-stop", "gameserver-restart",
    }

    @staticmethod
    def _valid_command_name(name: str) -> str | None:
        """Returns the normalized command name if valid, else None. These are full Discord
        slash command names now (no fixed suffix gets appended anymore), so the real 32-char
        Discord limit applies directly."""
        name = (name or "").strip().lower()
        if not name or len(name) > 32:
            return None
        if not re.fullmatch(r"[a-z0-9_-]+", name):
            return None
        if name in AMP._RESERVED_COMMAND_NAMES:
            return None
        return name

    def _build_instance_commands(self, cfg: dict, instance_id: str, names: dict) -> list[app_commands.Command]:
        """Builds one command per non-empty entry in `names` ({"Start": "...", "Stop": "...",
        "Restart": "..."}, any subset). Instance is re-resolved by ID against a fresh
        _list_instances() call on every single invocation (not captured once here) - it could
        have been renamed in AMP since the command name was configured, and instance_name (not
        the stable id) is what ADSModule's Start/Stop/RestartInstance actually take."""
        async def _resolve(interaction: discord.Interaction) -> dict | None:
            listing = await self._list_instances(cfg)
            match = next((i for i in listing["instances"] if i["id"] == instance_id), None)
            if not match:
                await interaction.followup.send(
                    "⚠️ Instanz nicht mehr gefunden (evtl. inzwischen entfernt?)", ephemeral=True
                )
            return match

        def _action_callback(method: str, icon: str, verb: str):
            async def callback(interaction: discord.Interaction):
                cfg_now = await self._get_config(interaction.guild_id)
                if not cfg_now:
                    await interaction.response.send_message(
                        "Für diesen Server ist kein Gameserver verknüpft.", ephemeral=True
                    )
                    return
                if not await self._check_command_channel(interaction, cfg_now):
                    return
                await interaction.response.defer(ephemeral=True)
                match = await _resolve(interaction)
                if not match:
                    return
                ok, err = await self._instance_action(cfg_now, match["instance_name"], method)
                if ok:
                    await interaction.followup.send(f"{icon} **{match['name']}** {verb} gesendet.", ephemeral=True)
                    if method == "Start":
                        asyncio.create_task(self._notify_when_online(
                            interaction, cfg_now, instance_id, match["name"], match.get("game_name") or ""))
                else:
                    await interaction.followup.send(f"⚠️ **{match['name']}** {verb} fehlgeschlagen: {err}", ephemeral=True)
            return callback

        commands_ = []
        for method, icon, verb in (
            ("Start", "🟢", "Startbefehl"),
            ("Stop", "🔴", "Stoppbefehl"),
            ("Restart", "🔄", "Neustart-Befehl"),
        ):
            name = names.get(method)
            if not name:
                continue
            cmd = app_commands.Command(
                name=name, description=f"{verb} für diese Instanz",
                callback=_action_callback(method, icon, verb),
            )
            cmd.default_permissions = discord.Permissions(manage_guild=True)
            commands_.append(cmd)
        return commands_

    async def resync_guild_commands(self, guild_id: int) -> None:
        """Rebuilds and re-syncs this guild's custom per-instance commands from scratch -
        called both after a save/delete in the dashboard (immediate effect) and once per guild
        on every bot startup (dynamically-added tree commands don't persist across a process
        restart, unlike the statically-decorated global ones above)."""
        guild_obj = discord.Object(id=guild_id)
        self.bot.tree.clear_commands(guild=guild_obj)
        cfg = await self._get_config(guild_id)
        if cfg:
            rows = await db_rows(
                "SELECT instance_id, start_name, stop_name, restart_name FROM amp_instance_commands WHERE guild_id=?",
                (str(guild_id),),
            )
            for row in rows:
                names = {"Start": row["start_name"], "Stop": row["stop_name"], "Restart": row["restart_name"]}
                for cmd in self._build_instance_commands(cfg, row["instance_id"], names):
                    self.bot.tree.add_command(cmd, guild=guild_obj)
        await self.bot.tree.sync(guild=guild_obj)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            cfg = await self._get_config(guild.id)
            if not cfg:
                continue
            try:
                listing = await self._list_instances(cfg)
                await self.ensure_default_commands(guild.id, listing["instances"])
            except Exception as e:
                print(f"[AMP] Guild-Befehl-Sync für {guild.id} fehlgeschlagen: {_err_text(e)}")

    @staticmethod
    def _slugify(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")

    async def ensure_default_commands(self, guild_id: int, instances: list[dict]) -> None:
        """Auto-provisions default /​{slug}-start/-stop/-restart commands for any instance that
        doesn't have custom command names configured yet - requested live: "der soll dort
        automatich schon sachen drine haben die standart sind und wenn neue server dazu kommen
        das der auch automatich das genau so macht" (defaults should already be there, and a
        newly-added instance should get the same treatment automatically, no manual typing).
        Called both on every bot startup (covers instances that already existed) and from
        main.py's server_config() whenever the Gameserver tab is loaded (covers an instance
        that got added to AMP while the bot was already running - discovery only happens
        through _list_instances(), there's no separate "instance added" event to hook). Skips
        an instance if its slug-derived names would collide with anything already used in this
        guild, rather than silently overwriting or erroring - it just stays without custom
        commands until the admin sets one manually in that case."""
        existing = await db_rows(
            "SELECT instance_id, start_name, stop_name, restart_name FROM amp_instance_commands WHERE guild_id=?",
            (str(guild_id),),
        )
        have_row = {r["instance_id"] for r in existing}
        used = {r[col] for r in existing for col in ("start_name", "stop_name", "restart_name") if r[col]}
        changed = False
        for inst in instances:
            if inst["id"] in have_row:
                continue
            slug = self._slugify(inst.get("name") or inst.get("instance_name") or "")
            if not slug:
                continue
            candidates = {f"{slug}-start", f"{slug}-stop", f"{slug}-restart"}
            if candidates & used or candidates & AMP._RESERVED_COMMAND_NAMES:
                continue  # would collide - leave unconfigured rather than guess further
            await db_exec(
                "INSERT INTO amp_instance_commands (guild_id, instance_id, prefix, start_name, stop_name, restart_name) "
                "VALUES (?,?,?,?,?,?)",
                (str(guild_id), inst["id"], "", f"{slug}-start", f"{slug}-stop", f"{slug}-restart"),
            )
            used |= candidates
            changed = True
        if changed:
            await self.resync_guild_commands(guild_id)

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
