"""VRChat account links: a member clicks a button (or runs /vrc-link), gets a personal link to
a page of their own, proves the VRChat account is theirs, and the confirmed link then drives an
automatic role and their Discord nickname.

Rebuilt on request after the first version - type your VRChat name into a slash command, a
moderator eyeballs it - turned out not to work in practice: "das klapt immernoch nicht ...
ueberdenken wir das mal ein user geht auf den server wil sich an melden dann soll dann ein link
erstelt werden", shown alongside a third-party service that answers with a link to a web page.
Two things fall out of that change, and both are improvements rather than cosmetics:

  - Nothing depends on a slash command any more. The entry point is a BUTTON on a message the
    bot posts, and buttons work the moment the message exists. A newly added slash command is
    invisible for up to an hour while Discord propagates it globally, which is exactly what
    went wrong here.

  - Ownership can finally be checked. The member puts a short code into their VRChat status
    bot reads the profile back and compares. That is a real proof and it needs a page to walk
    somebody through it, which a slash command cannot do. It deliberately does NOT ask members
    for their VRChat password: teaching people to type third-party credentials into somebody's
    self-hosted bot is how phishing gets its foothold, and a code on the profile proves the
    same thing.

The moderator step is still there and still optional (vrc_auto_approve), it just no longer
carries the whole weight of deciding whether somebody owns an account.

Configured via main.py's "VRC-Link" tab (guild_configs keys vrc_* plus the vrc_links table);
the pages themselves live in main.py under /vrc/{token}.
"""
import datetime
import json
import secrets
import time
import unicodedata

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import (db_rows, db_one, db_exec, get_config, get_guild_config,
                      set_guild_config,
                      vrc_nickname, DEFAULT_VRC_NICKNAME_FORMAT,
                      DEFAULT_VRC_PANEL_TITLE, DEFAULT_VRC_PANEL_TEXT,
                      DEFAULT_VRC_PANEL_BUTTON, DEFAULT_VRC_INSTANCE_MESSAGE,
                      DEFAULT_VRC_INSTANCE_BUTTON,
                      VRC_ACCOUNT_KEY, VRC_TOKEN_TTL_MINUTES,
                      VRC_STATE_UNVERIFIED, VRC_STATE_PENDING, VRC_STATE_APPROVED)

# VRChat display names are at most 32 characters; anything longer is not a name, it is a paste
# accident. Kept as its own limit rather than reusing the nickname one it happens to match.
MAX_VRCHAT_NAME = 32

# Discord caps a button label at 80 characters and refuses the message outright past that -
# which would leave an admin staring at a panel that never appears, with the reason only in the
# bot's log. Clamped instead, same as every other free-text caption in this project.
MAX_BUTTON_LABEL = 80

# Wie viele Instanz-Meldungen ein Durchlauf hoechstens absetzt. Discord bremst Nachrichten je
# Kanal aus, und ein Schwall am Stueck wird ohnehin nicht gelesen. Was uebrig bleibt, kommt im
# naechsten Durchlauf - offene Instanzen laufen ja nicht weg.
MAX_INSTANCE_POSTS = 5


async def link_base_url() -> str:
    """Where the member-facing pages live, without a trailing slash.

    Two sources, in order. An explicitly configured "base_url" wins - that is the one an admin
    typed on purpose. Otherwise "detected_base_url": the address the dashboard was last opened
    at, recorded by main.py from logged-in requests.

    The second one exists so nothing has to be configured at all, matching how the invite link
    in the user administration behaves - it is simply built from the address the admin already
    has open (window.location.origin). The bot cannot do that itself, because it builds its
    links inside Discord where there is no browser to ask, so the web half remembers and the
    bot reads it back.

    Empty is still possible - a fresh install where nobody has logged in yet - and every caller
    turns that into an explanation rather than a broken half-link.
    """
    base = (await get_config("base_url") or "").strip()
    if not base:
        base = (await get_config("detected_base_url") or "").strip()
    return base.rstrip("/")


async def link_minutes(guild_id) -> int:
    """How long a handed-out link stays valid, in minutes.

    Set per server ("die dauer des links wann der verfelt sol mann selber einstelen können"),
    falling back to VRC_TOKEN_TTL_MINUTES. Clamped rather than trusted: the value comes from a
    text field, and a stray letter or a zero would otherwise hand out links that are dead on
    arrival or never expire at all.
    """
    raw = (await get_guild_config(guild_id, "vrc_link_minutes") or "").strip()
    try:
        return max(1, min(1440, int(raw)))
    except (TypeError, ValueError):
        return VRC_TOKEN_TTL_MINUTES


async def create_link_token(guild_id, user_id) -> str:
    """Hand out a fresh personal link token for this member on this server.

    Any earlier token of theirs is deleted first. Two reasons: a member who asks again has lost
    or ignored the old link, so keeping it alive only widens the window in which a stale link
    still works - and it keeps the table from growing a row per click.
    """
    token = secrets.token_urlsafe(32)
    now = datetime.datetime.utcnow()
    expires = now + datetime.timedelta(minutes=await link_minutes(guild_id))
    await db_exec("DELETE FROM vrc_link_tokens WHERE guild_id=? AND user_id=?",
                  (str(guild_id), str(user_id)))
    await db_exec(
        "INSERT INTO vrc_link_tokens (token, guild_id, user_id, created_at, expires_at) "
        "VALUES (?,?,?,?,?)",
        (token, str(guild_id), str(user_id), now.isoformat(), expires.isoformat()),
    )
    return token


async def personal_link(guild_id, user_id) -> str | None:
    """The full URL a member should open, or None when no base address is configured."""
    base = await link_base_url()
    if not base:
        return None
    token = await create_link_token(guild_id, user_id)
    return f"{base}/vrc/{token}"


async def vrc_session() -> dict | None:
    """The installation's VRChat session, renewed if the cached one has gone stale.

    Returns {"auth_cookie", "two_factor_cookie"} or None when no account is connected. Written
    back to the row whenever the cookies changed, so the next caller starts from the fresh ones
    instead of signing in again - see app/vrchat.py for why repeated password logins are
    something to avoid rather than merely wasteful.

    Everything is swallowed into a None: this runs behind a member's page load, and a VRChat
    outage should degrade the page, not break it.
    """
    row = await db_one("SELECT * FROM vrc_accounts WHERE guild_id=?", (VRC_ACCOUNT_KEY,))
    if not row or not row["username"] or not row["password"]:
        return None
    try:
        from vrchat import login as vrc_login
        result = await vrc_login(
            row["username"], row["password"], row["totp_secret"],
            auth_cookie=row["auth_cookie"], two_factor_cookie=row["two_factor_cookie"],
        )
    except Exception as e:
        # Der Grund muss sichtbar werden, nicht nur in der Konsole stehen. Vorher blieb eine
        # abgelaufene Sitzung - der Zwei-Faktor-Keks haelt etwa einen Monat - voellig stumm:
        # im Dashboard stand weiterhin "verbunden", waehrend jede VRChat-Funktion leise nichts
        # mehr tat. Geschrieben wird nur bei einer AENDERUNG, damit nicht jede Minute eine
        # Schreiboperation anfaellt.
        grund = str(e)[:300]
        print(f"[vrc_link] VRChat session unavailable: {grund}")
        try:
            if (row["last_error"] or "") != grund:
                await db_exec(
                    "UPDATE vrc_accounts SET last_error=?, last_check=? WHERE guild_id=?",
                    (grund, datetime.datetime.utcnow().isoformat(), VRC_ACCOUNT_KEY))
        except Exception as e2:
            print(f"[vrc_link] konnte den Anmeldefehler nicht vermerken: {e2}")
        return None
    if not result["reused"]:
        try:
            await db_exec(
                "UPDATE vrc_accounts SET auth_cookie=?, two_factor_cookie=?, last_error='' "
                "WHERE guild_id=?",
                (result["auth_cookie"], result["two_factor_cookie"], VRC_ACCOUNT_KEY),
            )
        except Exception as e:
            print(f"[vrc_link] could not store refreshed VRChat session: {e}")
    return {"auth_cookie": result["auth_cookie"],
            "two_factor_cookie": result["two_factor_cookie"]}


async def resolve_vrchat(name: str) -> tuple:
    """Look a typed display name up at VRChat and return the FULL profile.

    Returns (status, user) where status is one of:
      "ok"          - found, `user` is the VRChat user object
      "not_found"   - VRChat has no account by that exact name
      "unavailable" - no account connected, or VRChat could not be reached

    "unavailable" is deliberately distinct from "not_found": refusing somebody's link because
    the BOT cannot reach VRChat would blame them for an outage they have nothing to do with.

    The search result is re-fetched by id before it is returned. /users?search= answers with a
    trimmed-down record, and which fields survive that trim is not something VRChat documents
    or keeps still - the profile text is what this flow depends on, so it is read from the endpoint
    that is actually defined to carry it rather than hoped for on the search hit.
    """
    session = await vrc_session()
    if not session:
        return "unavailable", None
    try:
        from vrchat import find_user, get_user
        user = await find_user(name, session["auth_cookie"], session["two_factor_cookie"])
        if user and user.get("id"):
            full = await get_user(str(user["id"]), session["auth_cookie"],
                                  session["two_factor_cookie"])
            if full:
                user = full
    except Exception as e:
        print(f"[vrc_link] lookup of {name!r} failed: {e}")
        return "unavailable", None
    return ("ok", user) if user else ("not_found", None)


async def fetch_profile(vrc_user_id: str) -> tuple:
    """Re-read a known VRChat profile by id. Same (status, user) contract as resolve_vrchat()."""
    session = await vrc_session()
    if not session:
        return "unavailable", None
    try:
        from vrchat import get_user
        user = await get_user(vrc_user_id, session["auth_cookie"],
                              session["two_factor_cookie"])
    except Exception as e:
        print(f"[vrc_link] profile fetch for {vrc_user_id!r} failed: {e}")
        return "unavailable", None
    return ("ok", user) if user else ("not_found", None)


async def group_membership(group_id: str, vrc_user_id: str) -> tuple:
    """Whether this VRChat account is in the configured group.

    Returns (status, member) with status "ok" | "unavailable" and member a bool that only
    means anything when the status is "ok". A group the bot cannot reach must never be read as
    "not a member" - that would quietly strip everybody's group role the first time VRChat
    hiccups.
    """
    if not group_id or not vrc_user_id:
        return "unavailable", False
    session = await vrc_session()
    if not session:
        return "unavailable", False
    try:
        from vrchat import group_member
        row = await group_member(group_id, vrc_user_id, session["auth_cookie"],
                                 session["two_factor_cookie"])
    except Exception as e:
        print(f"[vrc_link] group check for {vrc_user_id!r} in {group_id!r} failed: {e}")
        return "unavailable", False
    return "ok", bool(row)


async def send_group_invite(group_id: str, vrc_user_id: str) -> tuple:
    """Invite one VRChat account into the group.

    Returns (status, detail): "sent", "already" (invited or a member already), or "error" with
    the reason in `detail`. The reason is passed through rather than flattened, because the
    two things that actually go wrong here - the bot account lacking the group's invite
    permission, and VRChat rate-limiting - need completely different responses from whoever
    reads it, and "it did not work" tells them neither.
    """
    if not group_id or not vrc_user_id:
        return "error", "Keine Gruppe oder kein VRChat-Konto hinterlegt."
    session = await vrc_session()
    if not session:
        return "error", "Es ist kein VRChat-Konto verbunden."
    try:
        from vrchat import group_invite
        result = await group_invite(group_id, vrc_user_id, session["auth_cookie"],
                                    session["two_factor_cookie"])
    except Exception as e:
        print(f"[vrc_link] group invite for {vrc_user_id!r} to {group_id!r} failed: {e}")
        return "error", str(e)[:200]
    return result, ""


def profile_fields(user: dict) -> dict:
    """The handful of things from a VRChat profile this bot stores and shows."""
    from vrchat import trust_rank, is_age_verified, is_supporter
    return {
        "vrc_user_id": str(user.get("id") or ""),
        "vrchat_name": str(user.get("displayName") or "")[:MAX_VRCHAT_NAME],
        "vrc_trust": trust_rank(user),
        "vrc_age_verified": 1 if is_age_verified(user) else 0,
        "vrc_supporter": 1 if is_supporter(user) else 0,
        "vrc_avatar": str(user.get("currentAvatarThumbnailImageUrl")
                          or user.get("userIcon") or user.get("profilePicOverride") or "")[:500],
    }


# Every field on a VRChat profile the MEMBER can type free text into, status message first.
#
# The bio was the wrong place to send people ("ändere das nicht bio sondern status das war
# falch"), and the reason showed up in testing: a code pasted into the bio was never found,
# the same code in the STATUS was found immediately ("wo ich dan den code in den status
# abgegeben habe hat er den auch gefunden"). So whatever VRChat does or does not hand out for
# somebody else's bio, the status is the field that reliably arrives - and that is the one the
# instructions now point at.
#
# The bio stays accepted anyway: it costs nothing, and a member who put it there, or was told
# to earlier, should not be sent back to do it again. Same for the bio links - a link field is
# still a text box and somebody will use it.
#
# Deliberately NOT "note": that one holds the private note the SIGNED-IN account keeps about
# the user, so it is written by the bot's own account rather than by the member. Accepting it
# would mean a proof the member never gave could pass.
PROFILE_TEXT_FIELDS = ("statusDescription", "bio")

# Characters that a copy-paste picks up but a human does not see. Zero-width spaces and joiners
# come along from web pages constantly; NFKC below already folds non-breaking spaces and
# full-width characters into their plain forms, but these are not whitespace to anyone.
_INVISIBLE = "".join(("\u200b", "\u200c", "\u200d", "\ufeff"))
# Every dash Unicode offers. The code carries a hyphen, and an editor that "helpfully" turns it
# into an en dash must not be the reason somebody's proof is rejected.
_DASHES = "-" + "".join(("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212"))


def profile_text(user: dict) -> str:
    """Everything the member could have typed on their profile, as one string.

    Also used to tell them what the bot actually read when the code is not found - "it is not
    there" without saying what WAS there is the kind of answer that costs an evening.
    """
    parts = []
    for key in PROFILE_TEXT_FIELDS:
        value = user.get(key)
        if isinstance(value, str):
            parts.append(value)
    links = user.get("bioLinks")
    if isinstance(links, list):
        parts.extend(str(x) for x in links if isinstance(x, str))
    return "\n".join(p for p in parts if p)


def _squash(text: str) -> str:
    """Strip everything that can differ between what was pasted and what VRChat stored."""
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(ch for ch in text if ch not in _INVISIBLE)
    text = "".join(ch for ch in text if not ch.isspace())
    for dash in _DASHES:
        text = text.replace(dash, "")
    return text.upper()


def code_present(user: dict, code: str) -> bool:
    """Whether the ownership code shows up anywhere the member can put text on their profile.

    Compared on a squashed copy of both sides - no whitespace of any kind, no invisible
    characters, no dash, upper case. A correctly pasted code that merely wrapped across a line,
    picked up a zero-width space from a web page, or had its hyphen prettified into an en dash
    still counts, because all three are the member doing exactly what they were told.
    """
    if not code:
        return False
    return _squash(code) in _squash(profile_text(user))


async def desired_vrc_roles(guild_id, member: discord.Member) -> set:
    """Which VRChat group roles this member's DISCORD roles entitle them to."""
    rows = await db_rows("SELECT * FROM vrc_role_map WHERE guild_id=?", (str(guild_id),))
    if not rows:
        return set()
    have = {str(r.id) for r in member.roles}
    return {r["vrc_role_id"] for r in rows if r["discord_role_id"] in have}


async def sync_vrc_roles(guild, member: discord.Member, link) -> list:
    """Bring this member's VRChat group roles in line with their Discord roles.

    Returns the roles actually changed, as human-readable strings - an empty list means there
    was nothing to do, which is the normal case and costs NO VRChat request at all.

    That last part is the whole design. Comparing against the roles we last wrote (stored on
    the link) rather than asking VRChat every time is what makes running this on a timer
    affordable: with nothing changed on Discord, a hundred members cost a hundred database
    reads and zero network calls. Asking VRChat per member per interval is exactly the traffic
    that gets a bot account banned.

    The trade is stated plainly: a role changed by hand INSIDE VRChat is not noticed until
    something else about that member changes. This syncs Discord to VRChat, not the reverse.
    """
    group_id = (await get_guild_config(guild.id, "vrc_group_id") or "").strip()
    if not group_id or not link or not link["vrc_user_id"] or not link["vrc_group_member"]:
        # Roles can only be held by a member of the group. Somebody outside it has nothing to
        # sync, and asking VRChat to give them a role would just be a 404 per run.
        return []
    want = await desired_vrc_roles(guild.id, member)
    try:
        had = set(json.loads(link["vrc_group_roles"] or "[]"))
    except (ValueError, TypeError):
        had = set()
    if want == had:
        return []

    session = await vrc_session()
    if not session:
        return []
    from vrchat import add_member_role, remove_member_role
    changed, now_have = [], set(had)
    for role_id in sorted(want - had):
        try:
            await add_member_role(group_id, link["vrc_user_id"], role_id,
                                  session["auth_cookie"], session["two_factor_cookie"])
            now_have.add(role_id)
            changed.append(f"VRChat-Rolle +{role_id}")
        except Exception as e:
            # Per role, not per member: one role the bot may not hand out must not stop the
            # others - and it must not be recorded as given either, or the next run would skip
            # it forever.
            print(f"[vrc_link] could not add VRChat role {role_id} to {link['vrc_user_id']}: {e}")
    for role_id in sorted(had - want):
        try:
            await remove_member_role(group_id, link["vrc_user_id"], role_id,
                                     session["auth_cookie"], session["two_factor_cookie"])
            now_have.discard(role_id)
            changed.append(f"VRChat-Rolle −{role_id}")
        except Exception as e:
            print(f"[vrc_link] could not remove VRChat role {role_id} from {link['vrc_user_id']}: {e}")
    try:
        await db_exec("UPDATE vrc_links SET vrc_group_roles=?, vrc_roles_synced=? WHERE id=?",
                      (json.dumps(sorted(now_have)),
                       datetime.datetime.utcnow().isoformat(), link["id"]))
    except Exception as e:
        print(f"[vrc_link] could not store the VRChat roles for link {link['id']}: {e}")
    return changed


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

    # The group role follows the STORED membership flag, never a fresh VRChat call: this runs
    # once a minute for every linked member, and asking VRChat each time is exactly the traffic
    # that gets a bot account banned. The flag is refreshed when the member's own page is used.
    group_role_id = await get_guild_config(guild.id, "vrc_group_role")
    if group_role_id and str(group_role_id).isdigit():
        group_role = guild.get_role(int(group_role_id))
        if group_role:
            row = await db_one(
                "SELECT vrc_group_member FROM vrc_links WHERE guild_id=? AND user_id=?",
                (str(guild.id), str(member.id)),
            )
            in_group = bool(row and row["vrc_group_member"])
            try:
                if in_group and group_role not in member.roles:
                    await member.add_roles(group_role, reason="VRChat-Gruppe")
                    changed.append(f"Rolle {group_role.name}")
                elif not in_group and group_role in member.roles:
                    await member.remove_roles(group_role, reason="Nicht in der VRChat-Gruppe")
                    changed.append(f"Rolle {group_role.name} entfernt")
            except (discord.HTTPException, OSError) as e:
                print(f"[vrc_link] group role {group_role_id} for {member.id} failed: {e}")

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


async def strip_vrc_roles(guild_id, link) -> int:
    """Nimmt einem Mitglied die VRChat-Gruppenrollen wieder ab, die der Bot vergeben hat.

    Muss aufgerufen werden, BEVOR die Zeile geloescht wird - danach weiss niemand mehr, welches
    VRChat-Konto gemeint war und welche Rollen von hier kamen. Genau das fehlte: revoke_link()
    nahm die beiden Discord-Rollen und den Spitznamen zurueck, die auf VRChat-Seite vergebenen
    Rollen blieben dem Mitglied dagegen dauerhaft erhalten. Wer sich loesen liess, behielt
    seine Gruppenrechte.

    Gibt zurueck, wie viele tatsaechlich entfernt wurden.
    """
    group_id = (await get_guild_config(guild_id, "vrc_group_id") or "").strip()
    if not group_id or not link or not link["vrc_user_id"]:
        return 0
    try:
        hatte = set(json.loads(link["vrc_group_roles"] or "[]"))
    except (ValueError, TypeError):
        hatte = set()
    if not hatte:
        return 0
    session = await vrc_session()
    if not session:
        # Lieber nichts als ein halbes Ergebnis: die Zeile verschwindet gleich, aber der
        # Vermerk bleibt so wenigstens im Log stehen.
        print(f"[vrc_link] konnte VRChat-Rollen von {link['vrc_user_id']} nicht abnehmen — "
              f"keine VRChat-Sitzung")
        return 0
    from vrchat import remove_member_role
    weg = 0
    for role_id in sorted(hatte):
        try:
            await remove_member_role(group_id, link["vrc_user_id"], role_id,
                                     session["auth_cookie"], session["two_factor_cookie"])
            weg += 1
        except Exception as e:
            print(f"[vrc_link] VRChat-Rolle {role_id} von {link['vrc_user_id']} nicht "
                  f"abgenommen: {e}")
    return weg


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
    group_role_id = await get_guild_config(guild.id, "vrc_group_role")
    if group_role_id and str(group_role_id).isdigit():
        group_role = guild.get_role(int(group_role_id))
        if group_role and group_role in member.roles:
            try:
                await member.remove_roles(group_role, reason="VRC-Link entfernt")
            except (discord.HTTPException, OSError) as e:
                print(f"[vrc_link] could not remove group role from {member.id}: {e}")
    # Und die Rollen auf VRChat-Seite. Die Zeile steht hier noch, gleich danach nicht mehr -
    # deshalb muss das an dieser Stelle passieren und nicht beim Aufrufer.
    link = await db_one("SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
                        (str(guild.id), str(member.id)))
    if link:
        await strip_vrc_roles(guild.id, link)
        try:
            await db_exec("UPDATE vrc_links SET vrc_group_roles='[]' WHERE id=?", (link["id"],))
        except Exception as e:
            print(f"[vrc_link] konnte den Rollenstand von {link['id']} nicht leeren: {e}")
    if (await get_guild_config(guild.id, "vrc_nickname_enabled") or "0") == "1":
        try:
            # None clears the nickname, putting the member back to their own Discord name.
            await member.edit(nick=None, reason="VRC-Link entfernt")
        except (discord.HTTPException, OSError):
            pass


async def announce_instances(bot, guild) -> int:
    """Post a message for every group instance that has newly opened. Returns how many.

    One VRChat request per server per run, never one per member - which is what makes this
    affordable to run on a short interval at all. What has already been announced is kept in
    vrc_instances, so a room that stays open for three hours is announced once, not sixty
    times; a room that closes is forgotten again so the same world can be announced afresh
    next time it opens.
    """
    group_id = (await get_guild_config(guild.id, "vrc_group_id") or "").strip()
    channel_id = (await get_guild_config(guild.id, "vrc_instance_channel") or "").strip()
    if not group_id or not channel_id.isdigit():
        return 0
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return 0

    session = await vrc_session()
    if not session:
        return 0
    try:
        from vrchat import get_group_instances, launch_url
        instances = await get_group_instances(group_id, session["auth_cookie"],
                                              session["two_factor_cookie"])
    except Exception as e:
        # Swallowed on purpose: this runs on a timer, and an outage at VRChat must not fill
        # the log with a traceback a minute. The line says enough to find it.
        print(f"[vrc_link] instance check for guild {guild.id} failed: {e}")
        return 0

    known = {r["location"]: r for r in
             await db_rows("SELECT * FROM vrc_instances WHERE guild_id=?", (str(guild.id),))}
    open_now = {i["location"] for i in instances}

    # Gone from VRChat's list means closed. Forgetting them is what lets the same world be
    # announced again the next time somebody opens it.
    #
    # Auf Wunsch wird die Meldung dabei auch gleich geloescht, damit der Kanal nicht voller
    # Hinweise auf Instanzen steht, die es nicht mehr gibt. Standardmaessig aus: eine
    # Nachricht ungefragt wegzuraeumen ist nichts, was man einem Bot beibringt, ohne dass es
    # jemand eingeschaltet hat - manche Server wollen die Historie behalten.
    aufraeumen = (await get_guild_config(guild.id, "vrc_instance_cleanup") or "0") == "1"
    for location in set(known) - open_now:
        if aufraeumen:
            nachricht_id = str(known[location]["message_id"] or "")
            if nachricht_id.isdigit():
                try:
                    nachricht = await channel.fetch_message(int(nachricht_id))
                    await nachricht.delete()
                except discord.NotFound:
                    pass  # schon weg - von Hand geloescht oder der Kanal wurde gewechselt
                except discord.Forbidden:
                    print(f"[vrc_link] darf in {channel_id} nichts loeschen ({guild.id})")
                except (discord.HTTPException, OSError) as e:
                    print(f"[vrc_link] Meldung {nachricht_id} nicht geloescht: {e}")
        try:
            # Die Zeile verschwindet in JEDEM Fall, auch wenn das Loeschen scheiterte. Sonst
            # haengt der Bot an einer Nachricht fest, die er nie wegbekommt, und die Welt
            # koennte beim naechsten Oeffnen nicht erneut gemeldet werden.
            await db_exec("DELETE FROM vrc_instances WHERE guild_id=? AND location=?",
                          (str(guild.id), location))
        except Exception as e:
            print(f"[vrc_link] could not forget instance {location}: {e}")

    template = (await get_guild_config(guild.id, "vrc_instance_message") or "").strip() \
        or DEFAULT_VRC_INSTANCE_MESSAGE
    mention_id = (await get_guild_config(guild.id, "vrc_instance_role") or "").strip()
    mention = ""
    if mention_id.isdigit():
        role = guild.get_role(int(mention_id))
        if role:
            mention = role.mention

    # Beim ALLERERSTEN Durchlauf wird nur mitgeschrieben, nicht gemeldet. Sonst kippt der Bot
    # in dem Moment, in dem jemand die Funktion einschaltet, jede gerade offene Instanz auf
    # einmal in den Kanal - bei einer grossen Gruppe ein Dutzend Nachrichten am Stueck.
    # Gemeldet wird, was von da an aufmacht.
    erstlauf = (await get_guild_config(guild.id, "vrc_instance_seeded") or "0") != "1"
    if erstlauf:
        for inst in instances:
            try:
                await db_exec(
                    "INSERT OR IGNORE INTO vrc_instances (guild_id, location, world_name, "
                    "first_seen, message_id) VALUES (?,?,?,?,'')",
                    (str(guild.id), inst["location"], inst["world_name"],
                     datetime.datetime.utcnow().isoformat()),
                )
            except Exception as e:
                print(f"[vrc_link] Erstaufnahme von {inst['location']} fehlgeschlagen: {e}")
        try:
            await set_guild_config(guild.id, "vrc_instance_seeded", "1")
        except Exception as e:
            print(f"[vrc_link] konnte den Erstlauf nicht vermerken: {e}")
        return 0

    posted = 0
    for inst in instances:
        if inst["location"] in known:
            continue
        if posted >= MAX_INSTANCE_POSTS:
            # Deckel je Durchlauf. Der Rest kommt beim naechsten - VRChat vergisst sie ja
            # nicht, und ein Kanal, in den zwanzig Meldungen am Stueck fallen, liest niemand.
            print(f"[vrc_link] {guild.id}: Deckel von {MAX_INSTANCE_POSTS} Meldungen erreicht")
            break
        link = launch_url(inst["location"])
        welt = inst["world_name"] or "Unbekannte Welt"
        text = (template
                .replace("{world}", welt)
                .replace("{count}", str(inst["count"]))
                .replace("{group}", guild.name)
                .replace("{link}", link)).strip()

        # Alles in die Karte, nichts daneben. Vorher stand der Text mitsamt der vollen,
        # sehr langen Beitritts-Adresse als nackte Zeile ueber einer kleinen Karte, und der
        # Weltname doppelt - einmal im Text, einmal als Titel. Jetzt traegt die Nachricht
        # selbst nur noch die Rollen-Erwaehnung, falls eine eingestellt ist.
        embed = discord.Embed(
            title=welt[:256],
            url=link or None,          # macht die Ueberschrift anklickbar
            description=text[:4000] or None,
            color=0x8B5CF6,
        )
        embed.add_field(name="Gerade drin", value=f"👥 {inst['count']}", inline=True)
        # Das GROSSE Bild, nicht das briefmarkengrosse Vorschaubild rechts - das war der
        # Hauptgrund, warum die Meldung mickrig aussah.
        #
        # Nur echte Web-Adressen: was VRChat sonst liefert, laesst Discord die GANZE Nachricht
        # mit 400 abprallen - die Instanz waere dann bei jedem Durchlauf erneut dran und
        # scheiterte jedes Mal.
        if inst["world_image"].startswith(("http://", "https://")):
            embed.set_image(url=inst["world_image"])
        embed.set_footer(text=guild.name[:2048])

        # Ein Bild in einer Karte kann bei Discord nicht selbst auf eine Adresse zeigen -
        # ein Klick darauf oeffnet nur das Bild. Der Knopf ist das, was dem am naechsten
        # kommt: gross, eindeutig, und auf dem Handy genauso gut zu treffen.
        view = None
        if link:
            knopf = (await get_guild_config(guild.id, "vrc_instance_button") or "").strip() \
                or DEFAULT_VRC_INSTANCE_BUTTON
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label=knopf[:MAX_BUTTON_LABEL], emoji="🌍",
                                            style=discord.ButtonStyle.link, url=link))
        try:
            message = await channel.send(mention or None, embed=embed, view=view)
        except discord.Forbidden:
            print(f"[vrc_link] no permission to post instances in {channel_id} ({guild.id})")
            return posted
        except (discord.HTTPException, OSError) as e:
            print(f"[vrc_link] could not announce instance {inst['location']}: {e}")
            continue
        try:
            # Written AFTER the message went out, not before: a failed send must be retried
            # next run, and a row written first would mark it announced forever.
            await db_exec(
                "INSERT OR IGNORE INTO vrc_instances (guild_id, location, world_name, "
                "first_seen, message_id) VALUES (?,?,?,?,?)",
                (str(guild.id), inst["location"], inst["world_name"],
                 datetime.datetime.utcnow().isoformat(), str(message.id)),
            )
        except Exception as e:
            print(f"[vrc_link] could not record instance {inst['location']}: {e}")
        posted += 1
    return posted


class VRCLinkPanelView(discord.ui.View):
    """The single button under the panel message a server posts.

    One registered view with a fixed custom_id for every panel on every server: the handler
    works out which server and which member it is acting for from the interaction itself, so
    the same view routes correctly everywhere and keeps working after a restart (registered
    once in cog_load). Same arrangement as the temp-voice panel, and for the same reason.
    """

    def __init__(self, label: str = ""):
        super().__init__(timeout=None)
        # Only the POSTED message carries a server's own caption; the copy registered in
        # cog_load keeps the default. discord.py routes a component interaction by its
        # custom_id and never looks at the caption, so one registration covers all of them.
        if label:
            self.start.label = label[:MAX_BUTTON_LABEL]

    @discord.ui.button(label=DEFAULT_VRC_PANEL_BUTTON, emoji="🔗",
                       style=discord.ButtonStyle.primary, custom_id="vrc:link:start")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        await send_personal_link(interaction)


async def send_personal_link(interaction: discord.Interaction) -> None:
    """Answer an interaction with the member's own link, as an ephemeral message only they see.

    Shared by the panel button and /vrc-link so both hand out exactly the same thing. The link
    goes in a button rather than as bare text: Discord makes a link button unmistakably
    clickable on mobile too, where a pasted URL in an ephemeral message is easy to miss.
    """
    if not interaction.guild:
        await interaction.response.send_message("❌ Das geht nur auf einem Server.", ephemeral=True)
        return
    if (await get_guild_config(interaction.guild_id, "vrc_enabled") or "0") != "1":
        await interaction.response.send_message(
            "❌ VRC-Link ist auf diesem Server nicht aktiviert.", ephemeral=True)
        return

    # Deferred before anything slow: creating the token writes to the database, and an
    # interaction that is not answered within three seconds is lost for good.
    await interaction.response.defer(ephemeral=True)
    url = await personal_link(interaction.guild_id, interaction.user.id)
    if not url:
        # Nothing the member can do about this one, so it says whose job it is instead of
        # leaving them to guess. Without a public address the bot cannot build a link at all.
        await interaction.followup.send(
            "❌ Der Bot kennt seine eigene Web-Adresse noch nicht, deshalb lässt sich gerade "
            "kein Link erzeugen. Sag der Serverleitung Bescheid — es reicht, das Dashboard "
            "einmal zu öffnen.", ephemeral=True)
        return

    row = await db_one("SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
                       (str(interaction.guild_id), str(interaction.user.id)))
    if row and row["status"] == VRC_STATE_APPROVED:
        text = (f"🔗 Du bist bereits mit **{row['vrchat_name']}** verknüpft.\n"
                f"Auf deiner Seite kannst du die Verknüpfung ansehen, auffrischen oder lösen.")
    else:
        minutes = await link_minutes(interaction.guild_id)
        text = ("🔗 Hier entlang — auf der Seite verknüpfst du dein VRChat-Konto.\n"
                f"Der Link gilt nur für dich und läuft in {minutes} Minuten ab.")

    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Meine Seite öffnen", emoji="↗️",
                                    style=discord.ButtonStyle.link, url=url))
    await interaction.followup.send(text, view=view, ephemeral=True)


async def post_panel(bot, guild: discord.Guild, channel: discord.TextChannel) -> discord.Message:
    """Post the server's link panel. Raises on failure so the dashboard can show the reason -
    a panel that silently never appears is the worst of the possible outcomes here."""
    title = (await get_guild_config(guild.id, "vrc_panel_title") or "").strip() or DEFAULT_VRC_PANEL_TITLE
    text = (await get_guild_config(guild.id, "vrc_panel_text") or "").strip() or DEFAULT_VRC_PANEL_TEXT
    label = (await get_guild_config(guild.id, "vrc_panel_button") or "").strip() or DEFAULT_VRC_PANEL_BUTTON
    embed = discord.Embed(
        title=title[:256],
        description=text.replace("{server}", guild.name)[:4000],
        color=0x8B5CF6,
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    return await channel.send(embed=embed, view=VRCLinkPanelView(label))


class VRCLink(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # When each guild's VRChat role sync last ran, so an interval of "every 30 minutes"
        # means that and not "every minute". In memory: losing it on a restart costs one extra
        # run, which is harmless, and it keeps a write out of the hot loop.
        self._roles_last: dict[int, float] = {}
        self._instances_last: dict[int, float] = {}
        self._check.start()

    async def cog_load(self):
        # Registered once, with the default caption. Every posted panel routes through this
        # same view regardless of the caption it was posted with - see VRCLinkPanelView.
        self.bot.add_view(VRCLinkPanelView())

    def cog_unload(self):
        self._check.cancel()

    @tasks.loop(minutes=1)
    async def _check(self):
        """Keeps Discord in step with the approved links, once a minute.

        Deliberately does NOT talk to VRChat. Re-resolving every linked name every minute would
        be one API call per member per minute - with a few dozen links that is thousands of
        requests an hour against an interface that rate-limits hard and whose operator bans
        accounts for exactly this. What it does instead is cheap and needs no network at all in
        the normal case: apply_link() only calls Discord when something actually differs, so a
        member who still has their role and the right nickname costs nothing.

        That covers what drifts in practice - a role removed by hand, a nickname changed by the
        member, someone who was offline when their link was approved. A VRChat-side rename is
        picked up by the member's own page or by "Alle auffrischen" on the dashboard, both of
        which are a deliberate action rather than a thousand background requests.
        """
        for guild in list(self.bot.guilds):
            try:
                if not await self._enabled(guild.id):
                    continue
                # Instance announcements run on their own clock: one VRChat request per server
                # per interval, independent of how many members are linked.
                try:
                    every_inst = int((await get_guild_config(guild.id, "vrc_instance_minutes") or "0").strip())
                except (TypeError, ValueError):
                    every_inst = 0
                if every_inst > 0:
                    last = self._instances_last.get(guild.id, 0.0)
                    if time.monotonic() - last >= every_inst * 60:
                        self._instances_last[guild.id] = time.monotonic()
                        await announce_instances(self.bot, guild)
                rows = await db_rows(
                    "SELECT * FROM vrc_links WHERE guild_id=? AND status=?",
                    (str(guild.id), VRC_STATE_APPROVED),
                )
                # Whether this guild's Discord -> VRChat role sync is due this minute.
                # 0 or empty means "only when a link is made", which is the default: pushing
                # roles on a timer is useful but it is also the only part of this feature that
                # WRITES to VRChat, so it is switched on deliberately or not at all.
                try:
                    every = int((await get_guild_config(guild.id, "vrc_role_sync_minutes") or "0").strip())
                except (TypeError, ValueError):
                    every = 0
                roles_due = False
                if every > 0:
                    last = self._roles_last.get(guild.id, 0.0)
                    if time.monotonic() - last >= every * 60:
                        self._roles_last[guild.id] = time.monotonic()
                        roles_due = True

                for row in rows:
                    member = guild.get_member(int(row["user_id"])) if str(row["user_id"]).isdigit() else None
                    if member is None:
                        continue  # gone from the server - on_member_join restores them if they return
                    # Je Mitglied abgesichert, nicht je Server: vorher hat ein einziger Fehler
                    # bei Mitglied Nummer fuenf alle danach uebersprungen - und weil der
                    # Zeitstempel oben schon weitergesetzt ist, haetten die bis zum naechsten
                    # Intervall gewartet. Ein Problemfall darf nicht die anderen ausbremsen.
                    try:
                        await apply_link(self.bot, guild, member, row["vrchat_name"])
                        if roles_due:
                            # Kostet nichts, solange die Discord-Rollen zu dem passen, was das
                            # Mitglied schon hat - siehe sync_vrc_roles().
                            await sync_vrc_roles(guild, member, row)
                    except Exception as e:
                        print(f"[vrc_link] Abgleich fuer {row['user_id']} in {guild.id} "
                              f"fehlgeschlagen: {e}")
            except Exception as e:
                print(f"[vrc_link] periodic check failed for guild {guild.id}: {e}")
        try:
            # Expired tokens are dead weight: the page refuses them on sight, so this only
            # keeps the table from growing forever. Cheap enough to ride along here.
            await db_exec("DELETE FROM vrc_link_tokens WHERE expires_at < ?",
                          (datetime.datetime.utcnow().isoformat(),))
        except Exception as e:
            print(f"[vrc_link] token cleanup failed: {e}")

    @_check.before_loop
    async def _before_check(self):
        await self.bot.wait_until_ready()

    @_check.error
    async def _check_error(self, error):
        """Faengt, was bis hierher durchkommt, und startet die Schleife wieder.

        Ohne das beendet discord.py eine Schleife nach der ersten unbehandelten Ausnahme
        endgueltig - der Minutenlauf waere tot, und zwar lautlos: Rollen und Spitznamen
        wuerden einfach nicht mehr nachgezogen, ohne dass irgendwo etwas danach aussieht.
        Innen ist alles je Server und je Mitglied abgesichert; das hier ist das Netz
        darunter, fuer das, woran niemand gedacht hat.
        """
        print(f"[vrc_link] Minutenlauf abgestuerzt, wird neu gestartet: {error!r}")
        try:
            self._check.restart()
        except Exception as e:
            print(f"[vrc_link] Neustart des Minutenlaufs fehlgeschlagen: {e}")

    async def _enabled(self, guild_id: int) -> bool:
        return (await get_guild_config(guild_id, "vrc_enabled") or "0") == "1"

    @app_commands.command(name="vrc-link", description="VRChat-Konto verknüpfen")
    async def vrc_link(self, interaction: discord.Interaction):
        """Hands out the same personal link the panel button does.

        No VRChat name argument any more: the name is typed on the page, where it can be looked
        up, shown back for confirmation and checked for ownership before anything is stored.
        """
        await send_personal_link(interaction)

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
        if row["status"] == VRC_STATE_APPROVED:
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
        state = {
            VRC_STATE_APPROVED: "✅ bestätigt",
            VRC_STATE_PENDING: "⏳ wartet auf Freigabe",
            VRC_STATE_UNVERIFIED: "⏳ Eigentum noch nicht bestätigt",
        }.get(row["status"], row["status"])
        extra = ""
        if row["status"] == VRC_STATE_APPROVED and row["verified_at"]:
            extra = " · Eigentum bestätigt"
        await interaction.response.send_message(
            f"{member.display_name} → **{row['vrchat_name']}** ({state}{extra})", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Someone who left and came back keeps what they had - and someone arriving for the
        first time is offered the link right away, if the server asked for that.

        Without the first half their row sits in the table marked approved while the role and
        nickname are gone with the old membership, and re-linking would just tell them the name
        is already taken, by themselves.
        """
        try:
            row = await db_one(
                "SELECT * FROM vrc_links WHERE guild_id=? AND user_id=?",
                (str(member.guild.id), str(member.id)),
            )
            if row and row["status"] == VRC_STATE_APPROVED:
                await apply_link(self.bot, member.guild, member, row["vrchat_name"])
                return
            if member.bot or not await self._enabled(member.guild.id):
                return
            if (await get_guild_config(member.guild.id, "vrc_dm_on_join") or "0") != "1":
                return
            url = await personal_link(member.guild.id, member.id)
            if not url:
                return
            text = (await get_guild_config(member.guild.id, "vrc_dm_text") or "").strip() \
                or DEFAULT_VRC_PANEL_TEXT
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label="VRChat verknüpfen", emoji="🔗",
                                            style=discord.ButtonStyle.link, url=url))
            try:
                await member.send(text.replace("{server}", member.guild.name)[:2000], view=view)
            except discord.Forbidden:
                # Closed DMs are the normal case on a lot of servers, not an error worth a
                # stack trace - the panel in the channel still reaches them.
                pass
        except Exception as e:
            print(f"[vrc_link] join handling failed for {member.id} in {member.guild.id}: {e}")


async def setup(bot):
    await bot.add_cog(VRCLink(bot))
