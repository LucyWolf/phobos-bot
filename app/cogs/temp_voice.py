"""Auto-created temporary voice channels: joining a configured trigger channel spawns a new
voice channel from a name template (e.g. "{user}'s Room #{count}"), auto-deleted once empty.

When the trigger is configured for it (temp_voice_config.panel_enabled), a control panel is
posted into the new channel so its owner can rename it, limit it, lock or hide it and manage
who may join - all without leaving Discord. The panel's title and text are the server's own.
"""
import datetime
import time

import discord
from discord import ui
from discord.ext import commands
from database import (db_rows, db_exec, db_one, DEFAULT_TEMPVOICE_PANEL_TITLE,
                      DEFAULT_TEMPVOICE_PANEL_TEXT, parse_panel_labels)

# Discord allows a channel to be renamed only TWICE per 10 minutes, and discord.py answers a
# breach by sleeping until the bucket frees up - which would leave the owner staring at a
# spinner for minutes and then an expired interaction. Counted here instead so the third
# attempt gets an immediate, honest answer.
RENAME_WINDOW_SECONDS = 600
RENAME_MAX_PER_WINDOW = 2

MAX_CHANNEL_NAME = 100

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from pytz import timezone as ZoneInfo


def _apply_template(tpl: str, member: discord.Member, channel_number: int) -> str:
    # A naive now() only happens to show the right {date}/{time} because the reference
    # docker-compose.yml sets TZ=Europe/Berlin - same underlying assumption already fixed for
    # scheduler.py/birthday.py, here it's cosmetic (a channel name) rather than a scheduling bug.
    now = datetime.datetime.now(ZoneInfo("Europe/Berlin"))
    return (
        tpl
        .replace("{user}",    member.display_name)
        .replace("{name}",    member.name)
        .replace("{number}",  str(channel_number))
        .replace("{date}",    now.strftime("%d.%m.%Y"))
        .replace("{time}",    now.strftime("%H:%M"))
        .replace("{count}",   str(member.guild.member_count))
    )


# Discord's hard limits for the two embed fields the panel uses.
MAX_EMBED_TITLE = 256
MAX_EMBED_DESCRIPTION = 4096


def _panel_text(raw: str, default: str, member, channel, *, as_title: bool = False) -> str:
    """Render the panel heading or body from the server's template.

    Clamped AFTER substitution, not before: the dashboard already caps the stored text at 4000
    characters, but "{user}" is five characters and the mention it becomes is twenty-odd - a
    text near that cap with a handful of placeholders comes out over Discord's 4096 limit, and
    the whole embed is then rejected. The panel simply never appeared, with nothing but a line
    in the bot log to say why.

    A heading gets the plain display name rather than a mention: embed titles do not resolve
    mentions, so "{user}" there would show the raw "<@123456>" to everyone.
    """
    text = raw if (raw or "").strip() else default
    text = (text.replace("{user}", member.display_name if as_title else member.mention)
                .replace("{channel}", channel.name if as_title else channel.mention)
                .replace("{server}", member.guild.name))
    return text[:MAX_EMBED_TITLE] if as_title else text[:MAX_EMBED_DESCRIPTION]


async def _owner_id(channel_id: int):
    row = await db_one("SELECT owner_id FROM temp_voice_active WHERE channel_id=?", (str(channel_id),))
    return int(row["owner_id"]) if row and str(row["owner_id"]).isdigit() else None


class TempVoicePanelView(ui.View):
    """The buttons under the panel embed.

    One single registered view with fixed custom_ids, rather than one per channel: every handler
    works out which channel it is acting on from interaction.channel_id and who owns it from
    temp_voice_active, so the same view routes correctly for every temp channel on every server
    and keeps working after a restart (registered once in cog_load).
    """

    def __init__(self, labels: dict | None = None):
        super().__init__(timeout=None)
        # Only the POSTED message carries a server's own captions; the copy registered once in
        # cog_load keeps the defaults. That is enough, because discord.py routes a component
        # interaction by its custom_id and never looks at the caption - the same reason
        # cogs/tickets.py can register one close-button view for every ticket panel there is.
        if labels:
            for child in self.children:
                key = (getattr(child, "custom_id", "") or "").removeprefix("tv:")
                if key in labels:
                    child.label = labels[key]

    @staticmethod
    async def _guard(interaction: discord.Interaction):
        """Returns the voice channel to act on, or None after answering the interaction itself.

        Everything the buttons do is owner-only. A member who is merely IN the channel must not
        be able to rename it out from under the person who created it.
        """
        channel = interaction.channel
        if not isinstance(channel, discord.VoiceChannel):
            # Not necessarily "this is no voice channel" - it can just as well be "I do not
            # know this channel yet". discord.py 2.3.2 builds Interaction.channel by resolving
            # the id against the guild cache and leaves it None when that misses, falling back
            # to an object assembled from the interaction payload's own partial channel data
            # (checked in its source, not assumed). Taken at face value, a cold cache made
            # every button on every panel answer with the error below, and the whole feature
            # looked dead. Resolving through the guild ourselves gives the real object.
            resolved = interaction.guild.get_channel(interaction.channel_id) if interaction.guild else None
            if not isinstance(resolved, discord.VoiceChannel):
                await interaction.response.send_message(
                    "❌ Dieses Panel gehört zu keinem Sprachkanal mehr.", ephemeral=True)
                return None
            channel = resolved
        owner = await _owner_id(channel.id)
        if owner is None:
            await interaction.response.send_message(
                "❌ Dieser Kanal wird nicht mehr als temporärer Kanal geführt.", ephemeral=True)
            return None
        if interaction.user.id != owner:
            member_ids = {m.id for m in channel.members}
            if owner in member_ids:
                await interaction.response.send_message(
                    f"❌ Nur <@{owner}> kann diesen Kanal steuern.", ephemeral=True)
                return None
            # The owner has left but the channel still has people in it - whoever is left
            # inside may take it over, otherwise the channel is stuck uncontrollable until it
            # empties. Being CONNECTED is the condition, not merely being able to read the
            # panel: a voice channel's text chat is readable by anyone who can see the channel,
            # so without this check a passer-by could claim a room they are not even in and
            # then lock the people inside out of their own conversation.
            if interaction.user.id not in member_ids:
                await interaction.response.send_message(
                    "❌ Du musst im Kanal sein, um ihn zu übernehmen.", ephemeral=True)
                return None
            await db_exec("UPDATE temp_voice_active SET owner_id=? WHERE channel_id=?",
                          (str(interaction.user.id), str(channel.id)))
        return channel

    @ui.button(label="Umbenennen", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="tv:rename", row=0)
    async def rename(self, interaction: discord.Interaction, button: ui.Button):
        channel = await self._guard(interaction)
        if channel:
            await interaction.response.send_modal(RenameModal(channel))

    @ui.button(label="Limit", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="tv:limit", row=0)
    async def limit(self, interaction: discord.Interaction, button: ui.Button):
        channel = await self._guard(interaction)
        if channel:
            await interaction.response.send_modal(LimitModal(channel))

    @ui.button(label="Sperren", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="tv:lock", row=0)
    async def lock(self, interaction: discord.Interaction, button: ui.Button):
        channel = await self._guard(interaction)
        if not channel:
            return
        everyone = channel.guild.default_role
        overwrite = channel.overwrites_for(everyone)
        # None (inherited) counts as allowed, so the toggle has to treat it as "currently open".
        locked_now = overwrite.connect is False
        overwrite.connect = None if locked_now else False
        # The owner needs an explicit allow, otherwise the @everyone deny locks THEM out of
        # their own channel: step outside for a moment while somebody else keeps the channel
        # alive, and there is no way back in - from the one person holding the unlock button.
        mine = channel.overwrites_for(interaction.user)
        mine.connect = None if locked_now else True

        async def run():
            await channel.set_permissions(everyone, overwrite=overwrite, reason="Temp Voice Panel")
            await channel.set_permissions(interaction.user, overwrite=mine, reason="Temp Voice Panel")

        await _edit(interaction, run,
                    "🔓 Kanal ist wieder offen." if locked_now else "🔒 Kanal gesperrt — nur zugelassene Leute kommen rein.",
                    needs="Rollen verwalten")

    @ui.button(label="Verstecken", emoji="👁️", style=discord.ButtonStyle.secondary, custom_id="tv:hide", row=0)
    async def hide(self, interaction: discord.Interaction, button: ui.Button):
        channel = await self._guard(interaction)
        if not channel:
            return
        everyone = channel.guild.default_role
        overwrite = channel.overwrites_for(everyone)
        hidden_now = overwrite.view_channel is False
        overwrite.view_channel = None if hidden_now else False
        # Same reasoning as the lock button: without this the owner hides the channel from
        # themselves too and loses the panel along with it.
        mine = channel.overwrites_for(interaction.user)
        mine.view_channel = None if hidden_now else True

        async def run():
            await channel.set_permissions(everyone, overwrite=overwrite, reason="Temp Voice Panel")
            await channel.set_permissions(interaction.user, overwrite=mine, reason="Temp Voice Panel")

        await _edit(interaction, run, "👁️ Kanal ist wieder sichtbar." if hidden_now else "🙈 Kanal versteckt.",
                    needs="Rollen verwalten")

    @ui.button(label="Zulassen", emoji="➕", style=discord.ButtonStyle.success, custom_id="tv:permit", row=1)
    async def permit(self, interaction: discord.Interaction, button: ui.Button):
        channel = await self._guard(interaction)
        if channel:
            await interaction.response.send_message(
                "Wen möchtest du zulassen?", view=MemberPickView(channel, "permit"), ephemeral=True)

    @ui.button(label="Rauswerfen", emoji="👢", style=discord.ButtonStyle.danger, custom_id="tv:kick", row=1)
    async def kick(self, interaction: discord.Interaction, button: ui.Button):
        channel = await self._guard(interaction)
        if channel:
            await interaction.response.send_message(
                "Wen möchtest du rauswerfen?", view=MemberPickView(channel, "kick"), ephemeral=True)


async def _edit(interaction: discord.Interaction, action, ok_text: str,
                needs: str = "Kanäle verwalten") -> None:
    """Run a channel change and answer the interaction, whatever happens.

    `action` is an async callable, not a ready-made coroutine: some buttons need TWO API calls
    (see lock/hide, which also have to keep the owner's own access intact), and pre-creating
    both would leave the second one un-awaited - and warned about - whenever the first raises.

    Every button below would otherwise be able to leave the interaction unanswered - which
    Discord shows the member as a bare "This interaction failed", indistinguishable from the
    bot being down.
    """
    try:
        await action()
    except discord.Forbidden:
        # The needed permission differs per button and is passed in: renaming and the limit
        # want "Manage Channels", lock/hide/permit go through set_permissions and want
        # "Manage Roles", and kicking wants "Move Members". One generic message naming only
        # the first of those sent admins looking in the wrong place for two thirds of the
        # panel - verified against discord.py 2.3.2's own documented requirements.
        await interaction.response.send_message(
            f"❌ Dem Bot fehlt hier die Berechtigung „{needs}“.", ephemeral=True)
        return
    except (discord.HTTPException, OSError) as e:
        await interaction.response.send_message(f"❌ Hat nicht geklappt: {e}", ephemeral=True)
        return
    await interaction.response.send_message(ok_text, ephemeral=True)


class RenameModal(ui.Modal, title="Kanal umbenennen"):
    name = ui.TextInput(label="Neuer Name", max_length=MAX_CHANNEL_NAME, required=True)

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("TempVoice")
        if cog is not None and not cog.may_rename(self.channel.id):
            await interaction.response.send_message(
                "⏳ Discord erlaubt nur zwei Umbenennungen pro 10 Minuten je Kanal. "
                "Versuch es gleich nochmal.", ephemeral=True)
            return
        new_name = str(self.name).strip()[:MAX_CHANNEL_NAME]
        if not new_name:
            await interaction.response.send_message("❌ Der Name darf nicht leer sein.", ephemeral=True)
            return
        async def run():
            await self.channel.edit(name=new_name, reason="Temp Voice Panel")
            # Counted only once Discord has actually accepted it. Counting beforehand meant a
            # rename that failed for an unrelated reason (missing permission, network hiccup)
            # still burned one of the two slots per 10 minutes, so the next honest attempt was
            # refused by our own guard for a rename that never happened.
            if cog is not None:
                cog.note_rename(self.channel.id)

        await _edit(interaction, run, f"✏️ Kanal heißt jetzt **{new_name}**.")


class LimitModal(ui.Modal, title="Teilnehmer-Limit"):
    limit = ui.TextInput(label="Limit (0 = unbegrenzt)", max_length=2, required=True)

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(str(self.limit).strip())
        except ValueError:
            await interaction.response.send_message("❌ Bitte eine Zahl von 0 bis 99.", ephemeral=True)
            return
        if not 0 <= value <= 99:
            await interaction.response.send_message("❌ Bitte eine Zahl von 0 bis 99.", ephemeral=True)
            return
        await _edit(interaction, lambda: self.channel.edit(user_limit=value, reason="Temp Voice Panel"),
                    "👥 Limit aufgehoben." if value == 0 else f"👥 Limit steht jetzt bei **{value}**.")


class MemberPickView(ui.View):
    """Short-lived (not persistent): it only exists inside one ephemeral reply."""

    def __init__(self, channel: discord.VoiceChannel, mode: str):
        super().__init__(timeout=120)
        self.channel = channel
        self.mode = mode
        self.add_item(MemberPick(channel, mode))


class MemberPick(ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, mode: str):
        super().__init__(
            placeholder="Person auswählen…", min_values=1, max_values=1,
            custom_id=f"tv:pick:{mode}",
        )
        self.channel = channel
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):
        # Re-checked here, not just when the button was pressed: the ephemeral picker stays
        # usable for two minutes, and ownership can change in between (the owner leaves, some-
        # body still inside claims the channel). Without this, the previous owner could still
        # kick people out of a room that is no longer theirs, from a dropdown left open.
        owner = await _owner_id(self.channel.id)
        if owner is not None and interaction.user.id != owner:
            await interaction.response.send_message(
                f"❌ Der Kanal gehört inzwischen <@{owner}>.", ephemeral=True)
            return
        target = self.values[0]
        # UserSelect hands back a Member for a guild interaction - use it directly. Going
        # through guild.get_member() instead made the whole thing depend on the member cache,
        # so on a large or freshly started guild the bot answered "Person nicht gefunden" for
        # somebody it had just listed in its own picker.
        member = target if isinstance(target, discord.Member) else self.channel.guild.get_member(target.id)
        if member is None:
            try:
                member = await self.channel.guild.fetch_member(target.id)
            except (discord.HTTPException, OSError):
                await interaction.response.send_message("❌ Person nicht gefunden.", ephemeral=True)
                return
        if self.mode == "permit":
            overwrite = self.channel.overwrites_for(member)
            overwrite.connect = True
            overwrite.view_channel = True
            await _edit(interaction,
                        lambda: self.channel.set_permissions(member, overwrite=overwrite, reason="Temp Voice Panel"),
                        f"➕ {member.display_name} darf jetzt rein.", needs="Rollen verwalten")
            return
        if member.id == interaction.user.id:
            await interaction.response.send_message("❌ Dich selbst rauszuwerfen ergibt wenig Sinn.", ephemeral=True)
            return
        if member not in self.channel.members:
            await interaction.response.send_message(
                f"❌ {member.display_name} ist gar nicht in diesem Kanal.", ephemeral=True)
            return
        # move_to(None) disconnects. Kicking does NOT revoke access - the person can walk right
        # back in unless the owner locks the channel, which is deliberate: a permanent ban from
        # a channel that disappears in five minutes would be a strange thing to hand out by
        # accident.
        await _edit(interaction, lambda: member.move_to(None, reason="Temp Voice Panel"),
                    f"👢 {member.display_name} wurde aus dem Kanal entfernt.", needs="Mitglieder verschieben")


class TempVoice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._temp: set = set()  # active temp channel_ids (strings)
        # channel_id -> [monotonic timestamps of recent renames], see RENAME_MAX_PER_WINDOW.
        self._renames: dict = {}

    async def cog_load(self):
        # One registration for every temp channel on every server - the view's custom_ids are
        # fixed and each handler resolves its channel from the interaction, so the panels keep
        # working after a restart without storing a view per channel.
        self.bot.add_view(TempVoicePanelView())

    def may_rename(self, channel_id: int) -> bool:
        now = time.monotonic()
        recent = [t for t in self._renames.get(channel_id, []) if now - t < RENAME_WINDOW_SECONDS]
        self._renames[channel_id] = recent
        return len(recent) < RENAME_MAX_PER_WINDOW

    def note_rename(self, channel_id: int) -> None:
        self._renames.setdefault(channel_id, []).append(time.monotonic())

    @commands.Cog.listener()
    async def on_ready(self):
        rows = await db_rows("SELECT channel_id, guild_id FROM temp_voice_active")
        # Only the rows belonging to guilds THIS bot instance actually serves. The project runs
        # several bot tokens side by side, each loading this cog against the SAME database -
        # and the cleanup below deletes every row whose channel it cannot see. Unfiltered, the
        # first instance to become ready wiped every other token's tracked temp channels out
        # of the table, purely because those channels live on servers it was never in. Those
        # channels then existed in Discord with nothing tracking them, so nothing ever deleted
        # them when they emptied - exactly the leak the tracking exists to prevent.
        mine = {str(g.id) for g in self.bot.guilds}
        own_rows = [r for r in rows if str(r["guild_id"]) in mine]
        self._temp = {r["channel_id"] for r in own_rows}
        # Clean up channels that no longer exist after a restart
        for cid in list(self._temp):
            if not self.bot.get_channel(int(cid)):
                await db_exec("DELETE FROM temp_voice_active WHERE channel_id=?", (cid,))
                self._temp.discard(cid)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild

        # ── Joining a trigger channel → create temp channel ──────────────────
        # Must be an actual channel change, not just any voice state update (mute/deafen
        # toggles etc. also fire on_voice_state_update with before.channel == after.channel) -
        # otherwise a member stuck in the trigger channel (e.g. move_to() failed once due to a
        # permissions hiccup) would get a brand new temp channel created on every single
        # unrelated state change while they're still sitting there.
        if after.channel and before.channel != after.channel:
            cfg = await db_one(
                "SELECT * FROM temp_voice_config WHERE guild_id=? AND trigger_channel_id=?",
                (str(guild.id), str(after.channel.id)),
            )
            if cfg:
                tpl = cfg["name_template"] or "{user}'s Channel"
                existing = await db_rows(
                    "SELECT channel_id FROM temp_voice_active WHERE guild_id=?", (str(guild.id),)
                )
                # A short-looking template can still expand past Discord's 100-char channel
                # name limit once {user}/{name}/{count} are substituted (a long display name,
                # a large member count, ...) - the admin only controls the template, not the
                # final length, and create_voice_channel() would otherwise fail with an
                # HTTPException that the broad except below swallows silently, leaving this
                # member without a temp channel and no explanation.
                name = _apply_template(tpl, member, len(existing) + 1)[:100]
                limit = int(cfg["user_limit"] or 0)
                category = (
                    guild.get_channel(int(cfg["category_id"]))
                    if cfg["category_id"]
                    else after.channel.category
                )
                ch = None
                try:
                    ch = await guild.create_voice_channel(
                        name=name,
                        category=category,
                        user_limit=limit,
                        reason="Temp Voice",
                    )
                    # Register as tracked BEFORE move_to, not after - if move_to fails (member
                    # disconnects in the same instant, a permissions hiccup, ...) the channel
                    # would otherwise exist but be untracked in both the DB and self._temp,
                    # meaning it can never be cleaned up: the normal "delete if empty" cleanup
                    # only fires reactively when someone LEAVES a tracked channel, which never
                    # happens for a channel nobody ever successfully joined.
                    await db_exec(
                        "INSERT OR IGNORE INTO temp_voice_active (channel_id, guild_id, owner_id) VALUES (?,?,?)",
                        (str(ch.id), str(guild.id), str(member.id)),
                    )
                    self._temp.add(str(ch.id))
                    await member.move_to(ch)
                    # .get(), not [...]: this line sits OUTSIDE the inner try below, so a
                    # missing key here does not land in the harmless panel-failed handler - it
                    # falls through to the outer except, which deletes the channel the member
                    # was just moved into. A database that never got the panel columns (a
                    # half-applied migration, a restore into an older schema) would take the
                    # whole feature down that way, not just the panel.
                    if cfg.get("panel_enabled"):
                        # Deliberately after move_to and in its own try/except: a panel that
                        # fails to post (the bot may speak in voice-channel chat only if it has
                        # "Send Messages" there) must not undo a channel the member is already
                        # sitting in - the outer except would delete it right back out from
                        # under them.
                        try:
                            embed = discord.Embed(
                                title=_panel_text(cfg["panel_title"], DEFAULT_TEMPVOICE_PANEL_TITLE,
                                                  member, ch, as_title=True),
                                description=_panel_text(cfg["panel_text"], DEFAULT_TEMPVOICE_PANEL_TEXT,
                                                        member, ch),
                                color=0xff73fa,
                            )
                            await ch.send(embed=embed, view=TempVoicePanelView(
                                parse_panel_labels(cfg.get("panel_labels") or "")))
                        except Exception as e:
                            print(f"[TempVoice] panel could not be posted in channel {ch.id}: {e}")
                except Exception:
                    # Something after channel creation failed (move_to, or even the tracking
                    # db_exec/self._temp.add above) - checked directly on ch.members rather
                    # than "is it in self._temp", since that step itself might be the one that
                    # failed. discard()/DELETE are safe no-ops if it was never tracked.
                    if ch is not None and len(ch.members) == 0:
                        self._temp.discard(str(ch.id))
                        await db_exec("DELETE FROM temp_voice_active WHERE channel_id=?", (str(ch.id),))
                        try:
                            await ch.delete(reason="Temp Voice - Beitritt fehlgeschlagen")
                        except Exception:
                            pass

        # ── Leaving a temp channel → delete if empty ─────────────────────────
        if before.channel and str(before.channel.id) in self._temp:
            if len(before.channel.members) == 0:
                self._temp.discard(str(before.channel.id))
                self._renames.pop(before.channel.id, None)
                await db_exec("DELETE FROM temp_voice_active WHERE channel_id=?", (str(before.channel.id),))
                try:
                    await before.channel.delete(reason="Temp Voice leer")
                except Exception:
                    pass


async def setup(bot):
    await bot.add_cog(TempVoice(bot))
