"""Ticket panels: a published panel posts a message with an "Open Ticket" button
(PanelButton/OpenTicketView) that creates a private channel per ticket. close_ticket_channel()
either deletes the channel or moves it to an archive category, shared by the in-channel close
button, /ticket-close, and the dashboard's close route. _parse_ticket_blocks() here mirrors
main.py's copy of the same function (kept separate to avoid a circular import, since main.py
already imports from this module)."""
import json
import re

import discord
from discord import app_commands, ui
from discord.ext import commands
from database import db_exec, db_one, db_rows


def _fill_ticket_placeholders(text: str, member: discord.Member, guild: discord.Guild) -> str:
    """Substitutes {user}/{server} in a single pass (not chained .replace() calls, which would
    re-substitute a later placeholder's literal text if it happened to appear inside an earlier
    substitution's value - the same bug class already fixed for welcome.py/automod.py/
    auto_kick.py elsewhere in this project)."""
    placeholders = {"{user}": member.mention, "{server}": guild.name}
    return re.sub(
        "|".join(re.escape(k) for k in placeholders), lambda m: placeholders[m.group(0)], text
    )


def _parse_ticket_blocks(raw) -> list:
    """Mirrors main.py's _parse_ticket_blocks() exactly (duplicated rather than imported - main.py
    already imports FROM this module, so importing back would be circular). A ticket_panels.
    description/ticket_message value is either a legacy plain string (pre-dates the multi-embed
    "+" feature - treated as a single block) or a JSON array of block strings, each of which
    becomes its own Discord embed."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list) and all(isinstance(b, str) for b in data):
            return [b for b in data if b.strip()]
    except (ValueError, TypeError):
        pass
    return [raw]


async def close_ticket_channel(channel, guild: discord.Guild, panel: dict | None, reason: str) -> bool:
    """Shared by all three "close a ticket" entry points (the in-channel button, /ticket-close,
    and the dashboard's close route in main.py - imported from there, safe in that one
    direction since main.py already imports OTHER things from this module). Moves the channel
    to the panel's configured archive category instead of deleting it, if one is set and still
    resolvable to a real category ("ich wil halt auch tikets damit aufbewahren die wichtig
    sind") - otherwise deletes it exactly as before. Returns True on success (archived or
    deleted - a channel already gone, discord.NotFound, counts as success either way), False on
    a real failure, so the caller can decide not to mark the ticket closed and let it be retried."""
    archive_category = None
    if panel and panel.get("archive_category_id"):
        try:
            cat = guild.get_channel(int(panel["archive_category_id"]))
            if isinstance(cat, discord.CategoryChannel):
                archive_category = cat
        except (ValueError, TypeError):
            pass
    try:
        if archive_category:
            await channel.edit(category=archive_category, reason=reason)
        else:
            await channel.delete(reason=reason)
    except discord.NotFound:
        pass
    except Exception as e:
        print(f"[Tickets] failed to close channel {channel.id}: {e}")
        return False
    return True


class CloseTicketView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Ticket schließen", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        ticket = await db_one(
            "SELECT * FROM tickets WHERE channel_id=? AND status='open'", (interaction.channel_id,)
        )
        if not ticket:
            # The button's own message survives an archived (moved, not deleted) ticket - a
            # second click needs a real "already closed" response instead of blindly retrying,
            # which the pre-archive code never had to guard against since the channel (and with
            # it, the button) was always gone after the first successful close.
            await interaction.response.send_message("Dieses Ticket ist bereits geschlossen.", ephemeral=True)
            return
        await interaction.response.send_message("Ticket wird geschlossen...", ephemeral=True)
        panel = await db_one(
            "SELECT archive_category_id FROM ticket_panels WHERE id=?", (ticket["panel_id"],)
        ) if ticket.get("panel_id") else None
        if not await close_ticket_channel(
            interaction.channel, interaction.guild, panel, f"Ticket geschlossen von {interaction.user}"
        ):
            return
        await db_exec("UPDATE tickets SET status='closed' WHERE channel_id=?", (interaction.channel_id,))


class PanelButton(ui.Button):
    # In-Flight-Guard gegen Doppelklick/retried Interaction — sonst können zwei
    # gleichzeitige Callbacks beide "kein offenes Ticket" lesen und je einen Channel anlegen.
    _in_progress: set = set()

    def __init__(self, panel_id: int, label: str = "Ticket öffnen", emoji: str = "🎫"):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary,
            emoji=emoji,
            custom_id=f"open_ticket:{panel_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        panel_id = int(self.custom_id.split(":")[1])
        guild = interaction.guild
        lock_key = (guild.id, interaction.user.id, panel_id)
        if lock_key in PanelButton._in_progress:
            await interaction.response.send_message(
                "Dein Ticket wird bereits erstellt, bitte warten.", ephemeral=True
            )
            return
        PanelButton._in_progress.add(lock_key)
        try:
            await self._create_ticket(interaction, guild, panel_id)
        finally:
            PanelButton._in_progress.discard(lock_key)

    async def _create_ticket(self, interaction: discord.Interaction, guild: discord.Guild, panel_id: int):
        panel = await db_one("SELECT * FROM ticket_panels WHERE id=?", (panel_id,))
        if not panel:
            await interaction.response.send_message("Panel nicht gefunden.", ephemeral=True)
            return
        if panel.get("status") != "published":
            # Belt-and-suspenders: unpublishing deletes the live message so this button
            # shouldn't be clickable anymore at all, but if that deletion ever failed (missing
            # permission, message already gone) or raced with a click, don't let a stale
            # button still create a ticket for a panel the admin explicitly deactivated.
            await interaction.response.send_message("Dieses Panel ist aktuell nicht aktiv.", ephemeral=True)
            return

        existing = await db_one(
            "SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=? AND panel_id=? AND status='open'",
            (guild.id, interaction.user.id, panel_id),
        )
        if existing:
            ch = guild.get_channel(existing["channel_id"])
            if ch:
                await interaction.response.send_message(
                    f"Du hast bereits ein offenes Ticket: {ch.mention}", ephemeral=True
                )
                return
            # Channel wurde extern gelöscht — altes Ticket bereinigen
            await db_exec("UPDATE tickets SET status='closed' WHERE channel_id=?", (existing["channel_id"],))

        category = None
        if panel.get("category_id"):
            try:
                cat = guild.get_channel(int(panel["category_id"]))
                if isinstance(cat, discord.CategoryChannel):
                    category = cat
            except (ValueError, TypeError):
                pass

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        support_role = None
        if panel.get("support_role_id"):
            try:
                support_role = guild.get_role(int(panel["support_role_id"]))
                if support_role:
                    overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            except (ValueError, TypeError):
                pass

        slug = panel["name"].lower().replace(" ", "-")[:18]
        channel = None
        try:
            channel = await guild.create_text_channel(
                f"ticket-{slug}-{interaction.user.name[:10]}",
                overwrites=overwrites,
                category=category,
                reason=f"Ticket von {interaction.user} – Panel: {panel['name']}",
            )
            await db_exec(
                "INSERT INTO tickets (guild_id, channel_id, user_id, panel_id) VALUES (?,?,?,?)",
                (guild.id, channel.id, interaction.user.id, panel_id),
            )

            # ticket_message is its OWN field, split from the panel's advertisement text
            # ("description") so a long panel message isn't repeated verbatim inside every
            # newly created ticket. Falls back to "description" only for rows that predate this
            # split (ticket_message empty from before the database migration's one-time
            # backfill, or a very old already-restored backup) - never to a hardcoded default
            # while a real description exists.
            blocks = (_parse_ticket_blocks(panel.get("ticket_message"))
                      or _parse_ticket_blocks(panel.get("description"))
                      or ["Beschreibe dein Anliegen und wir helfen dir so schnell wie möglich."])
            embeds = []
            for i, block in enumerate(blocks[:10]):
                # User-reported ("Hallo @Zerafi! {user}, your ticket has been created." - the
                # admin had typed their own {user} placeholder expecting it to be substituted,
                # same as the {user}/{server} placeholders already supported elsewhere in this
                # project (welcome messages, Auto-Kick reminders) - there was no substitution at
                # all before this, so it just showed up as literal, unreplaced text.
                e = discord.Embed(
                    description=_fill_ticket_placeholders(block, interaction.user, guild),
                    color=0x7C3AED,
                )
                if i == 0:
                    e.title = f"{panel.get('emoji', '🎫')} {panel['name']}"
                embeds.append(e)
            # User-reported ("die werden nicht gepinkt die leute" / "die rolle sol gepinkt
            # werden und der den tiket erstelt sol auch gepinkt werden") - a mention that only
            # appears inside an embed's description does NOT trigger a real ping/notification,
            # by Discord's own design (embeds are meant for rich content, not notifications) -
            # only a mention in the message's plain content does. Both the ticket creator AND
            # the panel's configured support role (if any - pinging is skipped entirely when no
            # support role is set, same as the permission overwrite above) go into `content`,
            # separate from the embeds which keep describing them in prose for readability.
            ping = interaction.user.mention
            if support_role:
                ping += f" {support_role.mention}"
            await channel.send(content=ping, embeds=embeds, view=CloseTicketView())
            await interaction.response.send_message(f"Ticket erstellt: {channel.mention}", ephemeral=True)
        except Exception as e:
            # If channel creation itself fails (missing "Manage Channels" permission, guild
            # hit Discord's 500-channel cap, invalid category) the interaction would otherwise
            # never get a response at all ("This interaction failed" with no explanation). If
            # a channel WAS created but a later step failed (DB insert, embed send), clean it
            # up instead of leaving an orphaned, untracked channel behind - same lesson as the
            # temp-voice orphaned-channel fix earlier in this project's history.
            print(f"[Tickets] ticket creation failed for panel {panel_id}: {e}")
            if channel is not None:
                try:
                    await db_exec("DELETE FROM tickets WHERE channel_id=?", (channel.id,))
                except Exception:
                    pass
                try:
                    await channel.delete(reason="Ticket-Erstellung fehlgeschlagen")
                except Exception:
                    pass
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ticket konnte nicht erstellt werden. Bitte kontaktiere einen Admin.", ephemeral=True
                )


class OpenTicketView(ui.View):
    def __init__(self, panel_id: int, label: str = "Ticket öffnen", emoji: str = "🎫"):
        super().__init__(timeout=None)
        self.add_item(PanelButton(panel_id, label, emoji))


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(CloseTicketView())
        panels = await db_rows(
            "SELECT id, button_label, emoji FROM ticket_panels WHERE status='published'"
        )
        for p in panels:
            self.bot.add_view(OpenTicketView(
                p["id"],
                p.get("button_label") or "Ticket öffnen",
                p.get("emoji") or "🎫",
            ))

    @app_commands.command(name="ticket-close", description="Dieses Ticket schließen")
    async def ticket_close(self, interaction: discord.Interaction):
        ticket = await db_one(
            "SELECT * FROM tickets WHERE channel_id=? AND status='open'",
            (interaction.channel_id,),
        )
        if not ticket:
            await interaction.response.send_message("Dieser Kanal ist kein offenes Ticket.", ephemeral=True)
            return
        await interaction.response.send_message("Ticket wird geschlossen...")
        panel = await db_one(
            "SELECT archive_category_id FROM ticket_panels WHERE id=?", (ticket["panel_id"],)
        ) if ticket.get("panel_id") else None
        if not await close_ticket_channel(
            interaction.channel, interaction.guild, panel, f"Ticket geschlossen von {interaction.user}"
        ):
            return
        await db_exec("UPDATE tickets SET status='closed' WHERE channel_id=?", (interaction.channel_id,))


async def setup(bot):
    await bot.add_cog(Tickets(bot))
