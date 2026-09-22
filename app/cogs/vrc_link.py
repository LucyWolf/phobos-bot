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

  - Ownership can finally be checked. The member puts a short code into their VRChat bio, the
    bot reads the profile back and compares. That is a real proof and it needs a page to walk
    somebody through it, which a slash command cannot do. It deliberately does NOT ask members
    for their VRChat password: teaching people to type third-party credentials into somebody's
    self-hosted bot is how phishing gets its foothold, and a bio code proves the same thing.

The moderator step is still there and still optional (vrc_auto_approve), it just no longer
carries the whole weight of deciding whether somebody owns an account.

Configured via main.py's "VRC-Link" tab (guild_configs keys vrc_* plus the vrc_links table);
the pages themselves live in main.py under /vrc/{token}.
"""
import datetime
import secrets

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import (db_rows, db_one, db_exec, get_config, get_guild_config,
                      vrc_nickname, DEFAULT_VRC_NICKNAME_FORMAT,
                      DEFAULT_VRC_PANEL_TITLE, DEFAULT_VRC_PANEL_TEXT,
                      DEFAULT_VRC_PANEL_BUTTON, VRC_ACCOUNT_KEY, VRC_TOKEN_TTL_MINUTES,
                      VRC_STATE_UNVERIFIED, VRC_STATE_PENDING, VRC_STATE_APPROVED)

# VRChat display names are at most 32 characters; anything longer is not a name, it is a paste
# accident. Kept as its own limit rather than reusing the nickname one it happens to match.
MAX_VRCHAT_NAME = 32

# Discord caps a button label at 80 characters and refuses the message outright past that -
# which would leave an admin staring at a panel that never appears, with the reason only in the
# bot's log. Clamped instead, same as every other free-text caption in this project.
MAX_BUTTON_LABEL = 80


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


async def create_link_token(guild_id, user_id) -> str:
    """Hand out a fresh personal link token for this member on this server.

    Any earlier token of theirs is deleted first. Two reasons: a member who asks again has lost
    or ignored the old link, so keeping it alive only widens the window in which a stale link
    still works - and it keeps the table from growing a row per click.
    """
    token = secrets.token_urlsafe(32)
    now = datetime.datetime.utcnow()
    expires = now + datetime.timedelta(minutes=VRC_TOKEN_TTL_MINUTES)
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
        print(f"[vrc_link] VRChat session unavailable: {e}")
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
    or keeps still - the bio is the one this flow depends on, so it is read from the endpoint
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


def code_present(user: dict, code: str) -> bool:
    """Whether the ownership code shows up anywhere the member can put text on their profile.

    Bio and status message are both accepted because both are one edit away in the client and
    people reach for whichever they find first. Matched case-insensitively on a whitespace-free
    copy of the text: the code contains a hyphen, and VRChat's bio field happily wraps or
    reformats around one, which would otherwise fail a perfectly correct paste.
    """
    if not code:
        return False
    haystack = " ".join(str(user.get(k) or "") for k in ("bio", "statusDescription"))
    return code.replace("-", "").upper() in haystack.replace(" ", "").replace("-", "").upper()


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
    if (await get_guild_config(guild.id, "vrc_nickname_enabled") or "0") == "1":
        try:
            # None clears the nickname, putting the member back to their own Discord name.
            await member.edit(nick=None, reason="VRC-Link entfernt")
        except (discord.HTTPException, OSError):
            pass


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
        text = ("🔗 Hier entlang — auf der Seite verknüpfst du dein VRChat-Konto.\n"
                f"Der Link gilt nur für dich und läuft in {VRC_TOKEN_TTL_MINUTES} Minuten ab.")

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
                rows = await db_rows(
                    "SELECT * FROM vrc_links WHERE guild_id=? AND status=?",
                    (str(guild.id), VRC_STATE_APPROVED),
                )
                for row in rows:
                    member = guild.get_member(int(row["user_id"])) if str(row["user_id"]).isdigit() else None
                    if member is None:
                        continue  # gone from the server - on_member_join restores them if they return
                    await apply_link(self.bot, guild, member, row["vrchat_name"])
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
