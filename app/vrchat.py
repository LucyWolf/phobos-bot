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
        if resp.status == 401:
            raise VRChatError("Benutzername oder Passwort wurde von VRChat abgelehnt.")
        if resp.status == 429:
            raise VRChatError("VRChat bremst gerade zu viele Anmeldeversuche aus. "
                              "Bitte später nochmal versuchen.")
        if resp.status == 403:
            raise VRChatError("VRChat hat die Anfrage abgelehnt (403). Das passiert auch, wenn "
                              "das Konto gesperrt ist oder eine Bestätigung im Browser aussteht.")
        if resp.status != 200:
            raise VRChatError(f"VRChat antwortete mit Status {resp.status}.")

        new_auth = _cookie_from(resp, "auth") or auth_cookie
        needed = payload.get("requiresTwoFactorAuth") or []

        # ── 3. Two-factor, if this login needs it ────────────────────────────
        if needed:
            if "totp" not in needed and "otp" not in needed:
                # emailOtp: the code goes to the account's mailbox, so there is nothing this
                # bot could fill in unattended. Saying which kind is missing beats a generic
                # failure, because the fix ("switch that account to an authenticator app") is
                # not something anyone would guess.
                raise VRChatError(
                    "Dieses Konto verlangt einen Code per E-Mail. Der Bot kann nur "
                    "Authenticator-Codes (TOTP) erzeugen — stell die Zwei-Faktor-Anmeldung "
                    "des VRChat-Kontos auf eine Authenticator-App um.")
            code = (one_time_code or "").strip().replace(" ", "")
            if code:
                if not code.isdigit() or len(code) != 6:
                    raise VRChatError("Der eingegebene Code muss aus sechs Ziffern bestehen.")
            elif totp_secret:
                import pyotp
                try:
                    code = pyotp.TOTP(totp_secret.replace(" ", "")).now()
                except Exception:
                    raise VRChatError("Das 2FA-Geheimnis ist unbrauchbar — erwartet wird die "
                                      "Zeichenfolge, die beim Einrichten neben dem QR-Code steht.")
            else:
                raise VRChatError(
                    "Das Konto verlangt Zwei-Faktor-Anmeldung. Trag entweder das 2FA-Geheimnis "
                    "ein (dann erneuert der Bot die Anmeldung selbst) oder einmalig den "
                    "sechsstelligen Code aus deiner Authenticator-App.")
            verify_headers = _headers(new_auth, two_factor_cookie)
            verify_headers["Content-Type"] = "application/json"
            async with session.post(f"{API_BASE}/auth/twofactorauth/totp/verify",
                                    json={"code": code}, headers=verify_headers,
                                    timeout=TIMEOUT) as vresp:
                try:
                    vdata = await vresp.json(content_type=None)
                except Exception:
                    vdata = {}
                if vresp.status != 200 or not vdata.get("verified"):
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
