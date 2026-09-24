"""Minimal client for VRChat's API, used to sign the bot in as a dedicated VRChat account.

READ THIS BEFORE EXTENDING IT
-----------------------------
VRChat has no official public API. Everything here targets the same endpoints the website
itself uses, which means three things that shape every decision below:

* Automated use is against VRChat's terms of service. The account doing it can be banned. That
  is why the dashboard asks for a SEPARATE account, never the operator's own - and why the tab
  says so in plain words rather than burying it.
* The endpoints can change without notice. There is no versioning promise and no deprecation
  window; something that works today can stop working tomorrow.
* Logins are rate-limited hard, and repeatedly signing in with a password is itself a pattern
  that gets accounts flagged. The session cookie is therefore cached and reused, and a fresh
  password login only happens when the cached session is actually refused.

The API also rejects requests without a descriptive User-Agent (a 403 that looks nothing like
an auth problem), so USER_AGENT below is not optional decoration.

Deliberately its own module rather than a cog: main.py needs it for the dashboard's connection
test, and a cog will need it later for the actual syncing. A plain module both can import is
the same arrangement database.py already has.
"""
from __future__ import annotations

import base64
import urllib.parse

import aiohttp

API_BASE = "https://api.vrchat.cloud/api/1"

# VRChat requires a User-Agent that identifies the application and offers a way to reach its
# author; requests without one are answered with 403 regardless of credentials.
USER_AGENT = "PhobosBot/1.0 (https://github.com/LucyWolf/phobos-bot)"

# Short on purpose: this runs inside a dashboard request that a person is waiting on, and a
# hanging connection would hold the page instead of saying something useful.
TIMEOUT = aiohttp.ClientTimeout(total=15)


class VRChatError(Exception):
    """Anything that went wrong, with a message meant for the dashboard rather than a log."""


def _basic_auth(username: str, password: str) -> str:
    """VRChat expects the credentials percent-encoded BEFORE base64, unlike normal HTTP Basic.

    Skipping that step works fine right up until someone's password contains a colon, a plus or
    a non-ASCII character - and then produces an "invalid credentials" that sends them checking
    a password that was correct all along.
    """
    user = urllib.parse.quote(username, safe="")
    pw = urllib.parse.quote(password, safe="")
    raw = f"{user}:{pw}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _headers(auth_cookie: str = "", two_factor_cookie: str = "") -> dict:
    cookies = []
    if auth_cookie:
        cookies.append(f"auth={auth_cookie}")
    if two_factor_cookie:
        cookies.append(f"twoFactorAuth={two_factor_cookie}")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if cookies:
        headers["Cookie"] = "; ".join(cookies)
    return headers


def _cookie_from(resp: aiohttp.ClientResponse, name: str) -> str:
    """Read a Set-Cookie value off a response.

    Taken from the raw headers rather than a cookie jar: the jar is per-session and this client
    stores the cookies in the database instead, so they survive a restart - which is the whole
    point of not logging in again every time.
    """
    for raw in resp.headers.getall("Set-Cookie", []):
        if raw.startswith(f"{name}="):
            return raw.split("=", 1)[1].split(";", 1)[0]
    return ""


async def _get_user(session: aiohttp.ClientSession, headers: dict) -> tuple:
    """GET /auth/user - returns (payload, response). The single endpoint that both starts a
    login and reports who the current session belongs to."""
    async with session.get(f"{API_BASE}/auth/user", headers=headers, timeout=TIMEOUT) as resp:
        try:
            payload = await resp.json(content_type=None)
        except Exception:
            payload = {}
        return payload, resp


async def login(username: str, password: str, totp_secret: str = "",
                auth_cookie: str = "", two_factor_cookie: str = "",
                one_time_code: str = "") -> dict:
    """Sign in and return {"user", "auth_cookie", "two_factor_cookie", "reused"}.

    Tries the cached session first. Only if that is refused does it fall back to a password
    login - see the module docstring for why that order matters rather than being a nicety.

    Three kinds of account all have to work here:

    * No two-factor at all - VRChat simply does not ask, and the login is done after one call.
    * Two-factor with a stored secret - the bot generates the code itself and can renew the
      session unattended, forever.
    * Two-factor without a stored secret - `one_time_code` carries a code typed in by hand.
      VRChat answers a successful verification with a twoFactorAuth cookie that stays valid for
      about a month, so this gets a working session without the secret ever being written down;
      once that cookie expires somebody has to type a fresh code. The caller is responsible for
      saying so, because a session that silently stops working in a month is worse than one
      that never worked.
    """
    if not username or not password:
        raise VRChatError("Benutzername und Passwort fehlen.")

    async with aiohttp.ClientSession() as session:
        # ── 1. Cached session ────────────────────────────────────────────────
        if auth_cookie:
            payload, resp = await _get_user(session, _headers(auth_cookie, two_factor_cookie))
            if resp.status == 200 and payload.get("id"):
                return {"user": payload, "auth_cookie": auth_cookie,
                        "two_factor_cookie": two_factor_cookie, "reused": True}

        # ── 2. Password login ────────────────────────────────────────────────
        headers = _headers(two_factor_cookie=two_factor_cookie)
        headers["Authorization"] = _basic_auth(username, password)
        payload, resp = await _get_user(session, headers)
        # The two-factor challenge has to be read BEFORE the status is judged: VRChat answers
        # it with a 401 as often as with a 200, and the body is the only thing that tells the
        # two apart. Taking the 401 at face value reported a perfectly correct password as
        # rejected, and sent people re-typing something that was never wrong.
        needed = [str(x) for x in (payload.get("requiresTwoFactorAuth") or [])]
        if resp.status == 401 and not needed:
            raise VRChatError("Benutzername oder Passwort wurde von VRChat abgelehnt.")
        if resp.status == 429:
            raise VRChatError("VRChat bremst gerade zu viele Anmeldeversuche aus. "
                              "Bitte später nochmal versuchen.")
        if resp.status == 403:
            raise VRChatError("VRChat hat die Anfrage abgelehnt (403). Das passiert auch, wenn "
                              "das Konto gesperrt ist oder eine Bestätigung im Browser aussteht.")
        if resp.status not in (200, 401):
            raise VRChatError(f"VRChat antwortete mit Status {resp.status}.")

        new_auth = _cookie_from(resp, "auth") or auth_cookie

        # ── 3. Two-factor, if this login needs it ────────────────────────────
        if needed:
            lowered = {x.lower() for x in needed}
            code = (one_time_code or "").strip().replace(" ", "")
            if code and (not code.isdigit() or len(code) != 6):
                raise VRChatError("Der eingegebene Code muss aus sechs Ziffern bestehen.")

            if "totp" in lowered or "otp" in lowered:
                method = "totp"
                if not code:
                    if not totp_secret:
                        raise VRChatError(
                            "Das Konto verlangt Zwei-Faktor-Anmeldung. Trag entweder das "
                            "2FA-Geheimnis ein (dann erneuert der Bot die Anmeldung selbst) "
                            "oder einmalig den sechsstelligen Code aus deiner "
                            "Authenticator-App.")
                    import pyotp
                    try:
                        code = pyotp.TOTP(totp_secret.replace(" ", "")).now()
                    except Exception:
                        raise VRChatError(
                            "Das 2FA-Geheimnis ist unbrauchbar — erwartet wird die "
                            "Zeichenfolge, die beim Einrichten neben dem QR-Code steht.")
            elif "emailotp" in lowered:
                # VRChat sends a code to the account's mailbox whenever a login comes from an
                # address it has not seen before - and it does that even for accounts that have
                # an authenticator app set up. A server signing in for the first time therefore
                # lands here almost every time. The previous version refused outright and told
                # people to switch their account to an authenticator app, which cannot help:
                # this is about the location of the login, not the account's 2FA method.
                method = "emailotp"
                if not code:
                    raise VRChatError(
                        "VRChat hat einen Code an die E-Mail-Adresse des Kontos geschickt, weil "
                        "die Anmeldung von einem neuen Ort kommt. Trag ihn unten im Code-Feld "
                        "ein und speichere nochmal. Das ist einmalig nötig; danach merkt sich "
                        "VRChat diesen Server.")
            else:
                raise VRChatError(
                    f"VRChat verlangt eine Bestätigungsart, die der Bot nicht kennt: "
                    f"{', '.join(needed)}.")

            verify_headers = _headers(new_auth, two_factor_cookie)
            verify_headers["Content-Type"] = "application/json"
            async with session.post(f"{API_BASE}/auth/twofactorauth/{method}/verify",
                                    json={"code": code}, headers=verify_headers,
                                    timeout=TIMEOUT) as vresp:
                try:
                    vdata = await vresp.json(content_type=None)
                except Exception:
                    vdata = {}
                if vresp.status != 200 or not vdata.get("verified"):
                    if method == "emailotp":
                        raise VRChatError(
                            "Der Code aus der E-Mail wurde abgelehnt. Solche Codes laufen "
                            "schnell ab — fordere einen neuen an, indem du nochmal speicherst, "
                            "und trag dann den neuesten ein.")
                    raise VRChatError(
                        "Der Zwei-Faktor-Code wurde abgelehnt. Meist stimmt das hinterlegte "
                        "Geheimnis nicht, oder die Uhr des Servers geht zu weit falsch.")
                two_factor_cookie = _cookie_from(vresp, "twoFactorAuth") or two_factor_cookie

            # /auth/user answers with the 2FA challenge, not the user, so it has to be asked
            # again once the challenge is done.
            payload, resp = await _get_user(session, _headers(new_auth, two_factor_cookie))
            new_auth = _cookie_from(resp, "auth") or new_auth
            if resp.status != 200 or not payload.get("id"):
                raise VRChatError("Nach der Zwei-Faktor-Anmeldung kamen keine Kontodaten zurück.")

        if not payload.get("id"):
            raise VRChatError("VRChat hat keine Kontodaten zurückgegeben.")
        return {"user": payload, "auth_cookie": new_auth,
                "two_factor_cookie": two_factor_cookie, "reused": False}


# ── Nutzerdaten lesen ────────────────────────────────────────────────────────
# VRChat's trust tags are named one step above what they mean in the UI - "system_trust_veteran"
# is the rank the client shows as "Trusted User", not a separate veteran rank. Mapping them by
# their literal names is the single most common way to get this wrong, so the order here is
# written out rather than derived, and the UI label sits next to the tag it really belongs to.
TRUST_TAGS = (
    ("system_trust_veteran", "trusted"),   # UI: Trusted User
    ("system_trust_trusted", "known"),     # UI: Known User
    ("system_trust_known",   "user"),      # UI: User
    ("system_trust_basic",   "new"),       # UI: New User
)
# No trust tag at all is a Visitor - an account that has not been in VRChat long enough to earn
# one. That is a real rank, not missing data, so it gets a value of its own.
TRUST_VISITOR = "visitor"

TRUST_ORDER = ("visitor", "new", "user", "known", "trusted")


def trust_rank(user: dict) -> str:
    """The member's trust rank, as one of TRUST_ORDER.

    A user carries every tag up to their rank, not just the top one, so this takes the highest
    match rather than the first - reading them in any other order silently reports everybody as
    a New User.
    """
    tags = set(user.get("tags") or [])
    for tag, rank in TRUST_TAGS:
        if tag in tags:
            return rank
    return TRUST_VISITOR


def is_supporter(user: dict) -> bool:
    """VRChat+ subscriber."""
    return "system_supporter" in set(user.get("tags") or [])


def is_age_verified(user: dict) -> bool:
    """18+ verified.

    Read from several fields on purpose: VRChat introduced age verification well after the rest
    of the user object and has shipped it under more than one name, so a client that only knows
    one of them reports "not verified" for people who are.
    """
    if user.get("ageVerified") is True:
        return True
    status = str(user.get("ageVerificationStatus") or "").lower()
    if status in ("verified", "18+", "age_verified"):
        return True
    return "system_age_verified" in set(user.get("tags") or [])


async def find_user(display_name: str, auth_cookie: str, two_factor_cookie: str = "") -> dict | None:
    """Resolve a VRChat display name to its user object, or None if there is no such account.

    Display names are unique in VRChat, but /users?search= is a SEARCH, not a lookup: it also
    returns partial matches, so "Alex" would happily come back with "AlexInVR" first. Only an
    exact, case-insensitive match counts here - anything looser would quietly link members to
    somebody else's account.
    """
    name = (display_name or "").strip()
    if not name:
        return None
    params = {"search": name, "n": "20"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE}/users", params=params,
                               headers=_headers(auth_cookie, two_factor_cookie),
                               timeout=TIMEOUT) as resp:
            if resp.status == 401:
                raise VRChatError("Die VRChat-Sitzung ist abgelaufen — bitte das Konto im "
                                  "Dashboard neu verbinden.")
            if resp.status == 429:
                raise VRChatError("VRChat bremst gerade zu viele Anfragen aus.")
            if resp.status != 200:
                raise VRChatError(f"VRChat antwortete mit Status {resp.status}.")
            try:
                results = await resp.json(content_type=None)
            except Exception:
                results = []
    if not isinstance(results, list):
        return None
    for entry in results:
        if isinstance(entry, dict) and str(entry.get("displayName") or "").lower() == name.lower():
            return entry
    return None


async def get_user(user_id: str, auth_cookie: str, two_factor_cookie: str = "") -> dict | None:
    """The full user object for a known id. Returns None if the account is gone."""
    if not user_id:
        return None
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE}/users/{urllib.parse.quote(user_id, safe='')}",
                               headers=_headers(auth_cookie, two_factor_cookie),
                               timeout=TIMEOUT) as resp:
            if resp.status == 404:
                return None
            if resp.status == 401:
                raise VRChatError("Die VRChat-Sitzung ist abgelaufen — bitte das Konto im "
                                  "Dashboard neu verbinden.")
            if resp.status == 429:
                raise VRChatError("VRChat bremst gerade zu viele Anfragen aus.")
            if resp.status != 200:
                raise VRChatError(f"VRChat antwortete mit Status {resp.status}.")
            try:
                return await resp.json(content_type=None)
            except Exception:
                return None


# ── Gruppen ──────────────────────────────────────────────────────────────────
# Group ids are "grp_" followed by a UUID. Everything below needs the signed-in bot account to
# be a member of the group itself: VRChat answers 403 for a group it cannot see, which is a
# permission problem rather than a bug, so the errors say so in those words.
GROUP_ID_PREFIX = "grp_"


def looks_like_group_id(value: str) -> bool:
    """Whether this could be a VRChat group id at all - checked before any request is made, so
    a typo costs nothing and an obviously wrong value is refused with a clear reason."""
    value = (value or "").strip()
    return value.startswith(GROUP_ID_PREFIX) and 10 < len(value) <= 64


async def get_group(group_id: str, auth_cookie: str, two_factor_cookie: str = "") -> dict | None:
    """The group's own record, or None if there is no such group."""
    if not looks_like_group_id(group_id):
        raise VRChatError("Das ist keine gültige VRChat-Gruppen-ID — sie beginnt mit „grp_“.")
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE}/groups/{urllib.parse.quote(group_id, safe='')}",
                               headers=_headers(auth_cookie, two_factor_cookie),
                               timeout=TIMEOUT) as resp:
            if resp.status == 404:
                return None
            if resp.status == 403:
                raise VRChatError("Das Bot-Konto darf diese Gruppe nicht sehen — es muss selbst "
                                  "Mitglied der Gruppe sein.")
            if resp.status == 401:
                raise VRChatError("Die VRChat-Sitzung ist abgelaufen — bitte das Konto im "
                                  "Dashboard neu verbinden.")
            if resp.status == 429:
                raise VRChatError("VRChat bremst gerade zu viele Anfragen aus.")
            if resp.status != 200:
                raise VRChatError(f"VRChat antwortete mit Status {resp.status}.")
            try:
                return await resp.json(content_type=None)
            except Exception:
                return None


async def group_member(group_id: str, user_id: str, auth_cookie: str,
                       two_factor_cookie: str = "") -> dict | None:
    """The user's membership record in that group, or None if they are not a member.

    404 is the normal "not a member" answer here, not an error - VRChat uses it for both "no
    such membership" and "no such group", and the group itself was already established by
    whoever configured it.
    """
    if not looks_like_group_id(group_id) or not user_id:
        return None
    url = (f"{API_BASE}/groups/{urllib.parse.quote(group_id, safe='')}"
           f"/members/{urllib.parse.quote(user_id, safe='')}")
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=_headers(auth_cookie, two_factor_cookie),
                               timeout=TIMEOUT) as resp:
            if resp.status in (404, 400):
                return None
            if resp.status == 403:
                raise VRChatError("Das Bot-Konto darf die Mitglieder dieser Gruppe nicht sehen.")
            if resp.status == 401:
                raise VRChatError("Die VRChat-Sitzung ist abgelaufen — bitte das Konto im "
                                  "Dashboard neu verbinden.")
            if resp.status == 429:
                raise VRChatError("VRChat bremst gerade zu viele Anfragen aus.")
            if resp.status != 200:
                raise VRChatError(f"VRChat antwortete mit Status {resp.status}.")
            try:
                data = await resp.json(content_type=None)
            except Exception:
                return None
            # An empty object is not a membership. VRChat has answered 200 with one rather than
            # 404 in the past, and taking that at face value would report everybody as a member.
            return data if isinstance(data, dict) and data.get("userId") else None


async def group_invite(group_id: str, user_id: str, auth_cookie: str,
                       two_factor_cookie: str = "") -> str:
    """Send a group invite to one user. Returns "sent", "already" or raises VRChatError.

    This is the one call in this module that CHANGES something on VRChat's side rather than
    just reading. It needs the bot account to hold the group's invite permission; without it
    VRChat answers 403, which is reported as the permission problem it is instead of a generic
    failure - an operator can fix that in the group's settings, but only if they are told.
    """
    if not looks_like_group_id(group_id):
        raise VRChatError("Das ist keine gültige VRChat-Gruppen-ID.")
    if not user_id:
        raise VRChatError("Kein VRChat-Konto zum Einladen.")
    url = f"{API_BASE}/groups/{urllib.parse.quote(group_id, safe='')}/invites"
    headers = _headers(auth_cookie, two_factor_cookie)
    headers["Content-Type"] = "application/json"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"userId": user_id}, headers=headers,
                                timeout=TIMEOUT) as resp:
            if resp.status in (200, 201, 204):
                return "sent"
            try:
                body = await resp.json(content_type=None)
            except Exception:
                body = {}
            message = ""
            if isinstance(body, dict):
                err = body.get("error")
                message = (err.get("message") if isinstance(err, dict) else str(err or "")) or ""
            lowered = message.lower()
            # VRChat reports "already invited" and "already a member" as plain 400s. Neither is
            # a failure from the member's point of view - both mean there is nothing to do.
            if resp.status == 400 and ("already" in lowered or "bereits" in lowered):
                return "already"
            if resp.status == 403:
                raise VRChatError("Das Bot-Konto darf in dieser Gruppe niemanden einladen — "
                                  "dafür braucht es in den Gruppenrechten die Erlaubnis, "
                                  "Einladungen zu verschicken.")
            if resp.status == 401:
                raise VRChatError("Die VRChat-Sitzung ist abgelaufen — bitte das Konto im "
                                  "Dashboard neu verbinden.")
            if resp.status == 429:
                raise VRChatError("VRChat bremst gerade zu viele Anfragen aus. Versuch es "
                                  "in ein paar Minuten nochmal.")
            raise VRChatError(message[:200] or f"VRChat antwortete mit Status {resp.status}.")


# Membership states VRChat reports for a group, and what each one means for the bot account.
# "inactive" is the odd one: it is what comes back for an account that has no relationship
# with the group at all, not a lapsed membership.
GROUP_STATUS_LABELS = {
    "member": "Mitglied",
    "requested": "Beitritt angefragt — die Gruppenleitung muss zustimmen",
    "invited": "Eingeladen — die Einladung ist noch offen",
    "banned": "Gesperrt",
    "userblocked": "Blockiert",
    "inactive": "Kein Mitglied",
}


async def join_group(group_id: str, auth_cookie: str, two_factor_cookie: str = "") -> str:
    """Have the signed-in account join the group, and report what came of it.

    Returns one of GROUP_STATUS_LABELS' keys. Which one depends on how the group is set up:
    an open group answers "member" straight away, a request-based one "requested" and leaves
    the rest to whoever runs the group, and a group that had already invited this account
    turns that invite into a membership here.

    This exists because the bot cannot be given any group permission until it is IN the group
    ("der bot selber muss ja noch in die vrchat gruppe beitretten sonst kann ich den keine
    rechte geheben"), and the alternative was telling an operator to sign into vrchat.com as
    the bot account by hand - password, two-factor and all - just to press one button.
    """
    if not looks_like_group_id(group_id):
        raise VRChatError("Das ist keine gültige VRChat-Gruppen-ID — sie beginnt mit „grp_“.")
    url = f"{API_BASE}/groups/{urllib.parse.quote(group_id, safe='')}/join"
    headers = _headers(auth_cookie, two_factor_cookie)
    headers["Content-Type"] = "application/json"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={}, headers=headers, timeout=TIMEOUT) as resp:
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {}
            if resp.status in (200, 201):
                status = ""
                if isinstance(data, dict):
                    status = str(data.get("membershipStatus") or "")
                # A 200 with no membershipStatus still means the call was accepted; "member" is
                # the honest reading of that, and the tab's own check corrects it either way.
                return status or "member"
            message = ""
            if isinstance(data, dict):
                err = data.get("error")
                message = (err.get("message") if isinstance(err, dict) else str(err or "")) or ""
            lowered = message.lower()
            if resp.status == 400 and "already" in lowered:
                return "member"
            if resp.status == 403:
                raise VRChatError("VRChat hat den Beitritt abgelehnt — die Gruppe nimmt "
                                  "vermutlich nur Mitglieder auf Einladung auf. Lade das "
                                  "Bot-Konto in VRChat ein und versuch es dann erneut.")
            if resp.status == 404:
                raise VRChatError("Diese Gruppe gibt es nicht.")
            if resp.status == 401:
                raise VRChatError("Die VRChat-Sitzung ist abgelaufen — bitte das Konto im "
                                  "Dashboard neu verbinden.")
            if resp.status == 429:
                raise VRChatError("VRChat bremst gerade zu viele Anfragen aus.")
            raise VRChatError(message[:200] or f"VRChat antwortete mit Status {resp.status}.")


async def get_group_roles(group_id: str, auth_cookie: str,
                          two_factor_cookie: str = "") -> list:
    """The roles a group defines, as [{"id", "name", "order", "isManagementRole"}, ...]."""
    if not looks_like_group_id(group_id):
        raise VRChatError("Das ist keine gültige VRChat-Gruppen-ID.")
    url = f"{API_BASE}/groups/{urllib.parse.quote(group_id, safe='')}/roles"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=_headers(auth_cookie, two_factor_cookie),
                               timeout=TIMEOUT) as resp:
            if resp.status == 403:
                raise VRChatError("Das Bot-Konto darf die Rollen dieser Gruppe nicht sehen — "
                                  "dafür braucht es in der Gruppe das Recht, Rollen zu "
                                  "verwalten.")
            if resp.status == 404:
                raise VRChatError("Diese Gruppe gibt es nicht.")
            if resp.status == 401:
                raise VRChatError("Die VRChat-Sitzung ist abgelaufen — bitte das Konto im "
                                  "Dashboard neu verbinden.")
            if resp.status == 429:
                raise VRChatError("VRChat bremst gerade zu viele Anfragen aus.")
            if resp.status != 200:
                raise VRChatError(f"VRChat antwortete mit Status {resp.status}.")
            try:
                data = await resp.json(content_type=None)
            except Exception:
                return []
    if not isinstance(data, list):
        return []
    return [
        {"id": str(r.get("id") or ""), "name": str(r.get("name") or ""),
         "order": r.get("order"), "management": bool(r.get("isManagementRole"))}
        for r in data if isinstance(r, dict) and r.get("id")
    ]


async def _member_role(method: str, group_id: str, user_id: str, role_id: str,
                       auth_cookie: str, two_factor_cookie: str = "") -> None:
    """Add (PUT) or take away (DELETE) one group role for one member.

    Both directions answer the same handful of ways, so they share this. A 404 on DELETE means
    the member did not have the role - the desired end state, so it is not an error; on PUT it
    means the role or the member is gone, which is.
    """
    url = (f"{API_BASE}/groups/{urllib.parse.quote(group_id, safe='')}"
           f"/members/{urllib.parse.quote(user_id, safe='')}"
           f"/roles/{urllib.parse.quote(role_id, safe='')}")
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url,
                                   headers=_headers(auth_cookie, two_factor_cookie),
                                   timeout=TIMEOUT) as resp:
            if resp.status in (200, 201, 204):
                return
            if resp.status == 404 and method == "DELETE":
                return
            if resp.status == 403:
                raise VRChatError("Das Bot-Konto darf in dieser Gruppe keine Rollen vergeben — "
                                  "dafür braucht es dort das Recht, Rollen zu verwalten, und "
                                  "die eigene Rolle muss über der vergebenen stehen.")
            if resp.status == 404:
                raise VRChatError("Die Gruppenrolle oder das Mitglied gibt es nicht (mehr).")
            if resp.status == 401:
                raise VRChatError("Die VRChat-Sitzung ist abgelaufen — bitte das Konto im "
                                  "Dashboard neu verbinden.")
            if resp.status == 429:
                raise VRChatError("VRChat bremst gerade zu viele Anfragen aus.")
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {}
            message = ""
            if isinstance(data, dict):
                err = data.get("error")
                message = (err.get("message") if isinstance(err, dict) else str(err or "")) or ""
            raise VRChatError(message[:200] or f"VRChat antwortete mit Status {resp.status}.")


async def add_member_role(group_id: str, user_id: str, role_id: str, auth_cookie: str,
                          two_factor_cookie: str = "") -> None:
    await _member_role("PUT", group_id, user_id, role_id, auth_cookie, two_factor_cookie)


async def remove_member_role(group_id: str, user_id: str, role_id: str, auth_cookie: str,
                             two_factor_cookie: str = "") -> None:
    await _member_role("DELETE", group_id, user_id, role_id, auth_cookie, two_factor_cookie)


async def get_group_instances(group_id: str, auth_cookie: str,
                              two_factor_cookie: str = "") -> list:
    """The group's currently open instances.

    Each entry: {"instance_id", "world_id", "world_name", "world_image", "count", "location"}.
    "location" is the "worldId:instanceId" pair VRChat itself uses in launch links, which is
    the only part a person can actually act on.

    Returns an empty list for a group with nothing open - that is the normal state, not an
    error. A group the bot cannot see raises instead, because "nothing open" and "I am not
    allowed to look" must not be reported as the same thing: one is quiet, the other needs
    fixing.
    """
    if not looks_like_group_id(group_id):
        raise VRChatError("Das ist keine gültige VRChat-Gruppen-ID.")
    return _parse_group_instances(
        await _fetch_group_instances(group_id, auth_cookie, two_factor_cookie))


async def _fetch_group_instances(group_id: str, auth_cookie: str,
                                 two_factor_cookie: str = "") -> list:
    """Die ROHE Antwort von VRChat, unveraendert. Geteilt von der ausgewerteten und der rohen
    Ansicht, damit beide garantiert dieselbe Abfrage sehen.

    Hier darf NICHT ausgewertet werden. Stand hier einmal ein _parse_group_instances(), lief
    alles doppelt durch die Auswertung: der zweite Durchgang sucht "world" und "memberCount",
    findet aber nur noch die Felder, die der erste daraus gemacht hat - Ergebnis war ein
    Weltname "" und eine Zahl 0, waehrend die Rohdaten-Anzeige gleichzeitig 9 Leute zeigte.
    Genau so gemeldet, und genau daran erkannt.
    """
    if not looks_like_group_id(group_id):
        raise VRChatError("Das ist keine gültige VRChat-Gruppen-ID.")
    url = f"{API_BASE}/groups/{urllib.parse.quote(group_id, safe='')}/instances"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=_headers(auth_cookie, two_factor_cookie),
                               timeout=TIMEOUT) as resp:
            if resp.status == 403:
                raise VRChatError("Das Bot-Konto darf die Instanzen dieser Gruppe nicht sehen — "
                                  "es muss Mitglied der Gruppe sein und dort die Instanzen "
                                  "sehen dürfen.")
            if resp.status == 404:
                raise VRChatError("Diese Gruppe gibt es nicht.")
            if resp.status == 401:
                raise VRChatError("Die VRChat-Sitzung ist abgelaufen — bitte das Konto im "
                                  "Dashboard neu verbinden.")
            if resp.status == 429:
                raise VRChatError("VRChat bremst gerade zu viele Anfragen aus.")
            if resp.status != 200:
                raise VRChatError(f"VRChat antwortete mit Status {resp.status}.")
            try:
                data = await resp.json(content_type=None)
            except Exception:
                return []
    return data if isinstance(data, list) else []


async def get_group_instances_raw(group_id: str, auth_cookie: str,
                                  two_factor_cookie: str = "") -> list:
    """Dasselbe wie get_group_instances(), nur UNVERAENDERT so, wie VRChat es geliefert hat.

    Fuer die Prüfhilfe im Dashboard. Diese Schnittstelle ist nicht dokumentiert und aendert
    sich ohne Ankuendigung - was wirklich in einer Antwort steht, laesst sich nur nachsehen,
    nicht nachlesen. Genau dafuer ist das hier: bevor etwas auf ein Feld gebaut wird, wird
    geschaut, ob es das Feld ueberhaupt gibt und wie es heisst.
    """
    return await _fetch_group_instances(group_id, auth_cookie, two_factor_cookie)


async def get_instance(location: str, auth_cookie: str, two_factor_cookie: str = "") -> dict | None:
    """Die Einzelansicht einer Instanz ("worldId:instanceId"), unveraendert.

    Die Gruppenliste und diese Ansicht liefern nicht dasselbe - Felder wie der Zustand einer
    Instanz stehen erfahrungsgemaess eher hier. Ebenfalls fuer die Prüfhilfe.
    """
    if not location or ":" not in location:
        return None
    url = f"{API_BASE}/instances/{urllib.parse.quote(location, safe='')}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=_headers(auth_cookie, two_factor_cookie),
                               timeout=TIMEOUT) as resp:
            if resp.status in (404, 403):
                return None
            if resp.status == 401:
                raise VRChatError("Die VRChat-Sitzung ist abgelaufen — bitte das Konto im "
                                  "Dashboard neu verbinden.")
            if resp.status == 429:
                raise VRChatError("VRChat bremst gerade zu viele Anfragen aus.")
            if resp.status != 200:
                return None
            try:
                data = await resp.json(content_type=None)
            except Exception:
                return None
    return data if isinstance(data, dict) else None


# Wie VRChat die Zahl der Anwesenden nennt. Mehrere Schreibweisen, weil die Gruppenliste und
# die Einzelansicht sich uneinig sind und beides schon gesehen wurde - steht keine davon drin,
# bleibt es bei 0, und die Rohdaten-Anzeige im Dashboard sagt, wie das Feld hier wirklich
# heisst.
COUNT_FIELDS = ("memberCount", "userCount", "nUsers", "n_users", "users", "playerCount")


def _zahl_drin(entry: dict) -> int:
    for key in COUNT_FIELDS:
        wert = entry.get(key)
        if isinstance(wert, bool):
            continue
        if isinstance(wert, int):
            return wert
        if isinstance(wert, list):
            return len(wert)
        if isinstance(wert, str) and wert.isdigit():
            return int(wert)
    return 0


def _parse_group_instances(data) -> list:
    """Die Gruppenliste in das, was der Bot braucht - jede Adresse hoechstens einmal.

    Doppelte Adressen sind nicht bloss unschoen: der Meldelauf prueft gegen den Stand, den er
    zu Beginn aus der Datenbank gelesen hat, und den aktualisiert er waehrenddessen nicht.
    Stuende dieselbe Instanz zweimal in der Antwort, ginge die Meldung zweimal raus.
    """
    if not isinstance(data, list):
        return []
    out, gesehen = [], set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        world = entry.get("world") if isinstance(entry.get("world"), dict) else {}
        location = str(entry.get("location") or "")
        instance_id = str(entry.get("instanceId") or "")
        # VRChat has answered with either field alone depending on the endpoint's mood, and
        # they carry the same information - "worldId:instance" versus just "instance". Each is
        # derived from the other rather than trusted to be there.
        world_id = str(world.get("id") or entry.get("worldId") or "")
        if location and ":" in location and not world_id:
            world_id = location.split(":", 1)[0]
        if location and ":" in location and not instance_id:
            instance_id = location.split(":", 1)[1]
        if not location and world_id and instance_id:
            location = f"{world_id}:{instance_id}"
        if not location or location in gesehen:
            continue
        gesehen.add(location)
        out.append({
            "location": location,
            "instance_id": instance_id,
            "world_id": world_id,
            "world_name": str(world.get("name") or ""),
            "world_image": str(world.get("thumbnailImageUrl") or world.get("imageUrl") or ""),
            "count": _zahl_drin(entry),
        })
    return out


def instance_state(details: dict) -> dict:
    """Zustand und eigener Name einer Instanz, aus der EINZELANSICHT gelesen.

    Am 23.09.2026 nachgemessen, weil sich das nirgends nachlesen laesst. Eine Gruppe, eine
    Instanz, drei Abrufe - offen, geschlossen (zu fuer neue Leute, die Drinnen bleiben) und
    beendet:

        offen:        closedAt = None                      active = True   in der Gruppenliste
        geschlossen:  closedAt = 2026-09-23T22:42:46.241Z  hardClose = False   weiterhin drin
        beendet:      ueberhaupt nicht mehr in der Gruppenliste

    Zwei Dinge folgen daraus. Erstens steht der Zwischenzustand AUSSCHLIESSLICH in der
    Einzelansicht - die Gruppenliste liefert nur instanceId, location, memberCount und die
    Welt, dort ist nichts zu holen. Zweitens ist "beendet" weiterhin nur am Verschwinden zu
    erkennen; ein eigenes Feld dafuer gibt es nicht.

    hardClose unterscheidet sanft von hart: False heisst zu, aber niemand wurde
    hinausgeworfen. Eingelesen wird es, damit ein Text spaeter darauf eingehen kann.

    Der selbst vergebene Name steht in displayName, waehrend name nur die Instanznummer
    traegt ("displayName = TEST" neben "name = 53164"). Sind beide gleich, hat sich niemand
    einen Namen ausgedacht.
    """
    if not isinstance(details, dict):
        return {"closed_at": "", "hard_close": None, "name": "", "count": 0, "known": False}
    nummer = str(details.get("name") or "").strip()
    eigener = str(details.get("displayName") or "").strip()
    # Nur ein echter Zeitstempel gilt als "geschlossen". Stuende dort eines Tages ein
    # Wahrheitswert oder eine Zahl, wuerde str() daraus "True" oder "0" machen - und damit
    # waere je nach Fall JEDE Instanz sofort geschlossen oder keine mehr. Lieber nichts
    # erkennen als alle Meldungen auf einmal umschreiben.
    roh_zu = details.get("closedAt")
    zu = roh_zu.strip() if isinstance(roh_zu, str) and len(roh_zu.strip()) >= 8 else ""
    return {
        "closed_at": zu,
        "hard_close": details.get("hardClose") if isinstance(details.get("hardClose"), bool) else None,
        "name": eigener if eigener and eigener != nummer else "",
        "count": _zahl_drin(details),
        "known": True,
    }


def launch_url(location: str) -> str:
    """The link that opens an instance in VRChat, from a "worldId:instance" location."""
    if not location or ":" not in location:
        return ""
    world_id, instance = location.split(":", 1)
    return ("https://vrchat.com/home/launch"
            f"?worldId={urllib.parse.quote(world_id, safe='')}"
            f"&instanceId={urllib.parse.quote(instance, safe='')}")
