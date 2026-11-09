"""Ticket panels: a published panel posts a message with an "Open Ticket" button
(PanelButton/OpenTicketView) that creates a private channel per ticket. close_ticket_channel()
either deletes the channel or moves it to an archive category, shared by the in-channel close
button, /ticket-close, and the dashboard's close route. _parse_ticket_blocks() here mirrors
main.py's copy of the same function (kept separate to avoid a circular import, since main.py
already imports from this module)."""
# Chaquopy bringt sein eigenes Python 3.8 mit (siehe android/README.md): dict[str, int]
# und X | Y in einer Annotation sind dort keine Hinweise, sondern Ausdruecke, die beim
# IMPORT ausgewertet werden - das Modul wirft einen TypeError, bevor irgendetwas laeuft.
# Diese Zeile macht alle Annotationen zu Zeichenketten, die nie ausgewertet werden.
from __future__ import annotations
import datetime
import io
import json
import re

import discord
from discord import app_commands, ui
from discord.ext import commands
from database import db_exec, db_one, db_rows, bot_lang


# Was der Bot rund um Tickets sagt, nach Sprache des Servers (Config-Reiter, bot_lang).
# Nur die Texte, die ein Mitglied zu sehen bekommt - was in den Log geht, traegt log_utils
# ohnehin schon uebersetzt weiter.
TICKET_TEXTE = {
    "de": {
        "close_btn":      "Ticket schließen",
        "open_btn":       "Ticket öffnen",
        # Steht in der Auswahlliste, solange nichts eingetragen ist.
        "select_placeholder": "Kategorie wählen",
        "close_this":     "Dieses Ticket schließen",
        "already_closed": "Dieses Ticket ist bereits geschlossen.",
        "closing":        "Ticket wird geschlossen...",
        "closed_by":      "Ticket geschlossen von {wer}",
        "closed_by_grund": "Ticket geschlossen von {wer} · Grund: {grund}",
        "grund_titel":    "Ticket schließen",
        "grund_label":    "Grund (optional)",
        "grund_platz":    "z. B. erledigt, Doppelpost, keine Rückmeldung",
        "in_progress":    "Dein Ticket wird bereits erstellt, bitte warten.",
        "panel_gone":     "Panel nicht gefunden.",
        "panel_off":      "Dieses Panel ist aktuell nicht aktiv.",
        "already_open":   "Du hast bereits ein offenes Ticket: {kanal}",
        "created_reason": "Ticket von {wer} – Panel: {panel}",
        "created":        "Ticket erstellt: {kanal}",
        "failed":         "Ticket konnte nicht erstellt werden. Bitte kontaktiere einen Admin.",
        "not_a_ticket":   "Dieser Kanal ist kein offenes Ticket.",
        "ticket_intro":   "Beschreibe dein Anliegen und wir helfen dir so schnell wie möglich.",
    },
    "en": {
        "close_btn":      "Close ticket",
        "open_btn":       "Open ticket",
        "select_placeholder": "Choose a category",
        "close_this":     "Close this ticket",
        "already_closed": "This ticket is already closed.",
        "closing":        "Closing the ticket...",
        "closed_by":      "Ticket closed by {wer}",
        "closed_by_grund": "Ticket closed by {wer} · Reason: {grund}",
        "grund_titel":    "Close ticket",
        "grund_label":    "Reason (optional)",
        "grund_platz":    "e.g. resolved, duplicate, no reply",
        "in_progress":    "Your ticket is already being created, one moment.",
        "panel_gone":     "Panel not found.",
        "panel_off":      "This panel is currently inactive.",
        "already_open":   "You already have an open ticket: {kanal}",
        "created_reason": "Ticket from {wer} – panel: {panel}",
        "created":        "Ticket created: {kanal}",
        "failed":         "The ticket could not be created. Please contact an admin.",
        "not_a_ticket":   "This channel is not an open ticket.",
        "ticket_intro":   "Describe your issue and we'll help as soon as possible.",
    },
}


async def tt(guild_id, schluessel: str, **werte) -> str:
    """Ein Ticket-Text in der Sprache dieses Servers, mit eingesetzten Werten.

    Faellt auf Deutsch zurueck, wenn die Sprache unbekannt ist oder ein Text dort fehlt -
    lieber ein deutscher Satz als eine leere Antwort auf einen Knopfdruck.
    """
    sprache = TICKET_TEXTE.get(await bot_lang(guild_id), TICKET_TEXTE["de"])
    text = sprache.get(schluessel) or TICKET_TEXTE["de"].get(schluessel, "")
    return text.format(**werte) if werte else text


async def _antwort(interaction: discord.Interaction, text: str) -> None:
    """Dem Benutzer antworten - egal, ob die Interaktion schon bestaetigt wurde.

    Nach einem defer() ist interaction.response verbraucht; ein zweiter Aufruf darauf
    wirft. Und Discord wirft eine unbeantwortete Interaktion nach drei Sekunden weg -
    danach scheitert auch das Nachreichen.

    Deshalb bleiben Fehler hier drin: eine verlorene Bestaetigung ist eine fehlende
    Zeile auf dem Bildschirm, kein Grund, ein fertiges Ticket wieder abzureissen. Genau
    das ist passiert - der Kanal stand, die Bestaetigung kam zu spaet, der Fehler lief
    in den Aufraeumzweig und loeschte ihn sofort wieder.
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except Exception as e:
        print(f"[Tickets] Antwort nicht zugestellt: {e}")
from cogs.log_utils import log_bot_event


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


async def ticket_transcript(channel, guild: discord.Guild, panel: dict | None,
                            grund: str = "") -> bool:
    """Den Gespraechsverlauf als Datei in den Log-Kanal legen, bevor das Ticket verschwindet.

    Ohne das ist der Verlauf weg, sobald der Kanal geloescht wird - und geloescht wird er
    immer dann, wenn keine Archiv-Kategorie eingestellt ist. Wer spaeter wissen will, was
    besprochen wurde, hat dann nichts.

    Laeuft nur, wenn es am Panel eingeschaltet ist. Standard ist aus: ein Ticket kann eine
    Bewerbung oder eine Beschwerde enthalten, und was bisher nicht mitgeschrieben wurde,
    soll nicht durch ein Update anfangen mitgeschrieben zu werden.

    Gibt True zurueck, wenn eine Datei abgelegt wurde. Ein Fehlschlag ist nie ein Grund,
    das Schliessen abzubrechen - lieber ein Ticket ohne Mitschrift als eines, das sich
    nicht schliessen laesst.
    """
    if not panel or not panel.get("transcript"):
        return False
    ziel = None
    for schluessel in ("transcript_channel_id", "log_channel_id"):
        wert = panel.get(schluessel)
        if not wert:
            continue
        try:
            kandidat = guild.get_channel(int(wert))
        except (ValueError, TypeError):
            continue
        if kandidat is not None:
            ziel = kandidat
            break
    if not isinstance(ziel, discord.TextChannel):
        # Ohne Log-Kanal gaebe es keinen Ort dafuer. Still bleiben statt zu raten: in den
        # Ticketkanal selbst zu schreiben waere sinnlos, der verschwindet gleich.
        print(f"[Tickets] Transcript uebersprungen: weder Mitschrift- noch Log-Kanal "
              f"fuer Panel {panel.get('id')}")
        return False
    try:
        zeilen = []
        # Aelteste zuerst, damit die Datei von oben nach unten gelesen werden kann.
        # limit=None holt den ganzen Kanal; Tickets sind kurz, und ein abgeschnittener
        # Verlauf waere schlimmer als keiner - man wuesste nicht, dass etwas fehlt.
        async for m in channel.history(limit=None, oldest_first=True):
            zeit = m.created_at.strftime("%d.%m.%Y %H:%M")
            wer = f"{m.author.display_name} ({m.author.id})"
            text = m.content or ""
            for e in m.embeds:
                # Embeds tragen oft den eigentlichen Inhalt - die Begruessung des Bots etwa.
                teile = [t for t in (e.title, e.description) if t]
                teile += [f"{f.name}: {f.value}" for f in e.fields]
                if teile:
                    text += ("\n" if text else "") + "\n".join(teile)
            for a in m.attachments:
                # Die Datei selbst wird nicht kopiert - nur vermerkt, dass es sie gab. Sie
                # liegt auf Discords Seite und waere nach dem Loeschen ohnehin fort.
                text += ("\n" if text else "") + f"[Anhang: {a.filename}]"
            zeilen.append(f"[{zeit}] {wer}: {text}" if text else f"[{zeit}] {wer}: (leer)")
        kopf = [
            f"Ticket-Mitschrift · #{channel.name}",
            f"Server: {guild.name} ({guild.id})",
            f"Panel: {panel.get('name', '?')}",
            f"Geschlossen: {datetime.datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC"
            + (f" · {grund}" if grund else ""),
            f"Nachrichten: {len(zeilen)}",
            "─" * 60, "",
        ]
        inhalt = "\n".join(kopf + zeilen).encode("utf-8")
        datei = discord.File(io.BytesIO(inhalt), filename=f"ticket-{channel.name}.txt")
        await ziel.send(
            f"📄 Mitschrift zu **#{channel.name}**" + (f" · {grund}" if grund else ""),
            file=datei)
        return True
    except discord.Forbidden:
        # Fehlende Rechte im Log-Kanal oder auf den Verlauf - vermerken und weitermachen.
        print(f"[Tickets] Transcript fuer #{channel.name}: keine Berechtigung")
        return False
    except Exception as e:
        print(f"[Tickets] Transcript fuer #{channel.name} fehlgeschlagen: {e}")
        return False


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
    # Zuerst die Mitschrift, dann erst anfassen: nach dem Loeschen gibt es keinen Verlauf
    # mehr zu holen, und auch ein Verschieben kann fehlschlagen und den Kanal in einem
    # Zustand hinterlassen, in dem niemand mehr nachliest.
    await ticket_transcript(channel, guild, panel, reason)
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


class _GrundModal(ui.Modal):
    """Fragt beim Schliessen nach dem Grund.

    Gewuenscht aus der Community ("nen ticket mit einer bestimmten reason zu schließen").
    Das Feld ist absichtlich NICHT verpflichtend: wer nur aufraeumt, soll nicht erst
    etwas erfinden muessen - und ein Pflichtfeld, in das "." getippt wird, sagt weniger
    als ein leeres.

    Der Grund landet an drei Stellen: in der Meldung im Kanal, im Server-Log und im
    Kopf der Mitschrift. Gerade dort ist er am meisten wert - wer Monate spaeter
    nachliest, sieht sofort, wie die Sache ausgegangen ist.
    """

    def __init__(self, titel: str, feld_label: str, platzhalter: str):
        super().__init__(title=titel[:45], timeout=300)
        self.grund = ui.TextInput(
            label=feld_label[:45],
            placeholder=platzhalter[:100],
            required=False,
            max_length=200,
            style=discord.TextStyle.short,
        )
        self.add_item(self.grund)

    async def on_submit(self, interaction: discord.Interaction):
        await _schliessen(interaction, (self.grund.value or "").strip())


async def _schliessen(interaction: discord.Interaction, grund: str = "") -> None:
    """Der gemeinsame Weg fuer Knopf und /ticket-close.

    Stand vorher zweimal fast gleich da - einmal im Knopf, einmal im Slash-Befehl. Mit
    dem Grund waeren es zwei Stellen gewesen, die ihn beide kennen muessen.
    """
    ticket = await db_one(
        "SELECT * FROM tickets WHERE channel_id=? AND status='open'",
        (interaction.channel_id,))
    if not ticket:
        await _antwort(interaction, await tt(interaction.guild_id, "already_closed"))
        return
    # Das Schliessen dauert: Mitschrift holen, Kanal verschieben oder loeschen. Erst
    # bestaetigen, dann arbeiten - sonst laeuft die Drei-Sekunden-Frist ab.
    await _antwort(interaction, await tt(interaction.guild_id, "closing"))
    panel = await db_one(
        "SELECT * FROM ticket_panels WHERE id=?", (ticket["panel_id"],)
    ) if ticket.get("panel_id") else None
    if grund:
        text = await tt(interaction.guild_id, "closed_by_grund",
                        wer=interaction.user, grund=grund)
    else:
        text = await tt(interaction.guild_id, "closed_by", wer=interaction.user)
    if not await close_ticket_channel(interaction.channel, interaction.guild, panel, text):
        return
    await db_exec("UPDATE tickets SET status='closed' WHERE channel_id=?",
                  (interaction.channel_id,))
    await log_bot_event(
        interaction.client, interaction.guild.id, "🔒", "Ticket geschlossen", "ticket",
        plain=f"#{interaction.channel.name} · von {interaction.user.display_name}"
              + (f" · {grund}" if grund else ""),
    )


class _CloseTicketButton(ui.Button):
    # custom_id is fixed regardless of `label` (unlike PanelButton's per-panel custom_id) -
    # there's only ever one active close button per ticket channel, and keeping it constant is
    # what lets cog_load()'s single self.bot.add_view(CloseTicketView()) route interactions on
    # ALREADY-SENT messages after a restart: discord.py matches a persistent view purely by each
    # component's custom_id, never by its label, so the registered view's own label here is
    # irrelevant for that - only the label baked into an already-posted message (set once, at
    # send time, from the panel's close_button_label at that moment) is ever actually shown.
    def __init__(self, label: str = "Ticket schließen"):
        super().__init__(label=label, style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket")

    async def callback(self, interaction: discord.Interaction):
        ticket = await db_one(
            "SELECT * FROM tickets WHERE channel_id=? AND status='open'", (interaction.channel_id,)
        )
        if not ticket:
            # The button's own message survives an archived (moved, not deleted) ticket - a
            # second click needs a real "already closed" response instead of blindly retrying,
            # which the pre-archive code never had to guard against since the channel (and with
            # it, the button) was always gone after the first successful close.
            await interaction.response.send_message(
                await tt(interaction.guild_id, "already_closed"), ephemeral=True)
            return
        # Das Eingabefenster MUSS die erste Antwort auf die Interaktion sein - nach einem
        # defer() oder einer Nachricht laesst Discord keines mehr zu. Deshalb steht oben
        # nur die eine Abfrage, die entscheidet, ob es ueberhaupt etwas zu schliessen
        # gibt; alles Weitere passiert, nachdem das Fenster abgeschickt wurde.
        await interaction.response.send_modal(_GrundModal(
            await tt(interaction.guild_id, "grund_titel"),
            await tt(interaction.guild_id, "grund_label"),
            await tt(interaction.guild_id, "grund_platz"),
        ))


class CloseTicketView(ui.View):
    def __init__(self, label: str = "Ticket schließen"):
        super().__init__(timeout=None)
        self.add_item(_CloseTicketButton(label))


async def panel_optionen(panel_id: int) -> list:
    """Die Auswahleintraege eines Panels, in der eingestellten Reihenfolge.

    Ein Panel ohne Eintraege verhaelt sich wie bisher: ein Knopf, der direkt ein Ticket
    oeffnet. Mit mehreren wird daraus eine Auswahlliste - erst dann lohnt sie sich, und so
    aendert sich an bestehenden Panels nichts, ohne dass jemand etwas angefasst hat.
    """
    return await db_rows(
        "SELECT * FROM ticket_panel_options WHERE panel_id=? ORDER BY sortierung, id",
        (panel_id,)) or []


def panel_mit_option(panel: dict, opt: dict | None) -> dict:
    """Die Panel-Werte, ueberschrieben von denen des gewaehlten Eintrags.

    Jeder Eintrag darf eigene Zustaendige, eine eigene Kategorie und einen eigenen
    Begruessungstext haben - eine Bewerbung landet bei anderen Leuten als eine
    Supportfrage. Leer gelassene Felder fallen auf das Panel zurueck, damit man nur
    eintragen muss, was sich wirklich unterscheidet.
    """
    if not opt:
        return panel
    zusammen = dict(panel)
    for feld in ("support_role_id", "category_id", "ticket_message"):
        wert = (opt[feld] if feld in opt.keys() else "") or ""
        if wert.strip():
            zusammen[feld] = wert
    # Der Name geht in den Kanalnamen und in die Ueberschrift - bei einer Auswahl soll dort
    # stehen, wofuer das Ticket ist, nicht wie das Panel heisst.
    if (opt["label"] or "").strip():
        zusammen["name"] = opt["label"]
    if (opt["emoji"] or "").strip():
        zusammen["emoji"] = opt["emoji"]
    return zusammen


class PanelSelect(ui.Select):
    """Die Auswahlliste eines Panels mit mehreren Eintraegen.

    Traegt dieselbe feste custom_id-Form wie der Knopf, damit Discord sie nach einem
    Neustart wiedererkennt und die Nachricht im Kanal bedienbar bleibt.
    """

    def __init__(self, panel_id: int, optionen: list, platzhalter: str = "Kategorie wählen"):
        self._optionen = optionen
        super().__init__(
            placeholder=platzhalter,
            min_values=1,
            max_values=1,
            custom_id=f"open_ticket_select:{panel_id}",
            options=[
                discord.SelectOption(
                    label=(o["label"] or "Ticket")[:100],
                    # Discord verlangt eindeutige Werte je Eintrag; die Zeilennummer ist das.
                    value=str(o["id"]),
                    description=(o["description"] or "")[:100] or None,
                    emoji=(o["emoji"] or None),
                )
                for o in optionen[:25]   # Discord nimmt hoechstens 25 Eintraege
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        panel_id = int(self.custom_id.split(":")[1])
        option_id = int(self.values[0])
        guild = interaction.guild
        # Zuerst Bescheid geben, dass gearbeitet wird. Ein Ticket anzulegen kostet drei
        # Anfragen an Discord (Kanal anlegen, Begruessung senden, Serverlog) - mehr, als in
        # die Drei-Sekunden-Frist passt, nach der Discord "reagiert nicht rechtzeitig"
        # anzeigt und die Interaktion verwirft. Das defer() macht aus den drei Sekunden
        # fuenfzehn Minuten.
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            # Schon beantwortet oder schon verfallen - beides kein Grund, das Ticket
            # ausfallen zu lassen. _antwort() kommt damit zurecht.
            print(f"[Tickets] defer fehlgeschlagen: {e}")

        # Derselbe Schutz wie beim Knopf: zwei gleichzeitige Auswahlen wuerden sonst beide
        # "kein offenes Ticket" lesen und je einen Kanal anlegen.
        lock_key = (guild.id, interaction.user.id, panel_id)
        if lock_key in PanelButton._in_progress:
            await _antwort(interaction, await tt(interaction.guild_id, "in_progress"))
            return
        PanelButton._in_progress.add(lock_key)
        try:
            await PanelButton._create_ticket(self, interaction, guild, panel_id, option_id)
        finally:
            PanelButton._in_progress.discard(lock_key)


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
        # Zuerst Bescheid geben, dass gearbeitet wird. Ein Ticket anzulegen kostet drei
        # Anfragen an Discord (Kanal anlegen, Begruessung senden, Serverlog) - mehr, als in
        # die Drei-Sekunden-Frist passt, nach der Discord "reagiert nicht rechtzeitig"
        # anzeigt und die Interaktion verwirft. Das defer() macht aus den drei Sekunden
        # fuenfzehn Minuten.
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            # Schon beantwortet oder schon verfallen - beides kein Grund, das Ticket
            # ausfallen zu lassen. _antwort() kommt damit zurecht.
            print(f"[Tickets] defer fehlgeschlagen: {e}")
        lock_key = (guild.id, interaction.user.id, panel_id)
        if lock_key in PanelButton._in_progress:
            await _antwort(interaction, await tt(interaction.guild_id, "in_progress"))
            return
        PanelButton._in_progress.add(lock_key)
        try:
            await self._create_ticket(interaction, guild, panel_id)
        finally:
            PanelButton._in_progress.discard(lock_key)

    async def _create_ticket(self, interaction: discord.Interaction, guild: discord.Guild,
                             panel_id: int, option_id: int | None = None):
        panel = await db_one("SELECT * FROM ticket_panels WHERE id=?", (panel_id,))
        if panel and option_id:
            # Die Werte des gewaehlten Eintrags gehen vor. Gibt es ihn nicht mehr - geloescht,
            # waehrend die Nachricht im Kanal stand -, bleibt es beim Panel; ein Ticket zu
            # oeffnen ist besser als eine Fehlermeldung fuer etwas, das der Benutzer nicht
            # beeinflussen kann.
            opt = await db_one(
                "SELECT * FROM ticket_panel_options WHERE id=? AND panel_id=?",
                (option_id, panel_id))
            panel = panel_mit_option(panel, opt)
        if not panel:
            await _antwort(interaction, await tt(interaction.guild_id, "panel_gone"))
            return
        if panel.get("status") != "published":
            # Belt-and-suspenders: unpublishing deletes the live message so this button
            # shouldn't be clickable anymore at all, but if that deletion ever failed (missing
            # permission, message already gone) or raced with a click, don't let a stale
            # button still create a ticket for a panel the admin explicitly deactivated.
            await _antwort(interaction, await tt(interaction.guild_id, "panel_off"))
            return

        existing = await db_one(
            "SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=? AND panel_id=? AND status='open'",
            (guild.id, interaction.user.id, panel_id),
        )
        if existing:
            ch = guild.get_channel(existing["channel_id"])
            if ch:
                await _antwort(
                    interaction,
                    await tt(interaction.guild_id, "already_open", kanal=ch.mention))
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
                reason=await tt(interaction.guild_id, "created_reason",
                                wer=interaction.user, panel=panel["name"]),
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
                      or [await tt(guild.id, "ticket_intro")])
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
            close_label = panel.get("close_button_label") or await tt(guild.id, "close_btn")
            await channel.send(content=ping, embeds=embeds, view=CloseTicketView(close_label))
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
            await _antwort(interaction, await tt(interaction.guild_id, "failed"))
            return

        # Ab hier steht das Ticket: der Kanal ist da, die Rechte sitzen, die Begruessung
        # steht drin. Was jetzt noch schiefgeht - der Eintrag im Serverlog, die
        # Bestaetigung an den Benutzer - aendert daran nichts und darf den Kanal nicht
        # mehr anfassen. Deshalb liegt beides ausserhalb des Aufraeumzweigs.
        try:
            await log_bot_event(
                interaction.client, guild.id, "🎫", "Ticket erstellt", "ticket",
                plain=f"{interaction.user.display_name} · Panel: {panel['name']} · #{channel.name}",
            )
        except Exception as e:
            print(f"[Tickets] Serverlog-Eintrag fuer #{channel.name} fehlgeschlagen: {e}")
        await _antwort(interaction,
                       await tt(interaction.guild_id, "created", kanal=channel.mention))


class OpenTicketView(ui.View):
    """Was unter einer Panel-Nachricht steht.

    Ohne Eintraege oder mit genau einem: ein Knopf wie bisher. Mit mehreren: eine
    Auswahlliste. Die Entscheidung faellt an der Anzahl, damit bestehende Panels sich
    nicht veraendern, ohne dass jemand etwas eingetragen hat.
    """

    def __init__(self, panel_id: int, label: str = "Ticket öffnen", emoji: str = "🎫",
                 optionen: list | None = None, platzhalter: str = "Kategorie wählen"):
        super().__init__(timeout=None)
        if optionen and len(optionen) > 1:
            self.add_item(PanelSelect(panel_id, optionen, platzhalter))
        else:
            self.add_item(PanelButton(panel_id, label, emoji))


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(CloseTicketView())
        panels = await db_rows(
            # guild_id kommt mit, weil die Standardbeschriftung in der Sprache DIESES
            # Servers steht - ohne die Spalte gaebe es hier einen KeyError beim Start.
            "SELECT id, guild_id, button_label, emoji FROM ticket_panels WHERE status='published'"
        )
        for p in panels:
            # Die Eintraege muessen beim Wiederherstellen bekannt sein: Discord ordnet eine
            # Auswahlliste nur dann wieder ihrer Nachricht zu, wenn die View dieselbe Form
            # hat wie beim Abschicken.
            self.bot.add_view(OpenTicketView(
                p["id"],
                p.get("button_label") or await tt(p["guild_id"], "open_btn"),
                p.get("emoji") or "🎫",
                await panel_optionen(p["id"]),
                await tt(p["guild_id"], "select_placeholder"),
            ))

    @app_commands.command(name="ticket-close", description="Dieses Ticket schließen")
    @app_commands.describe(grund="Warum wird geschlossen? Steht später in der Mitschrift.")
    async def ticket_close(self, interaction: discord.Interaction, grund: str = ""):
        """Derselbe Weg wie der Knopf - nur dass der Grund hier gleich mitgetippt wird,
        statt in einem Fenster abgefragt zu werden. Leer lassen ist erlaubt."""
        ticket = await db_one(
            "SELECT * FROM tickets WHERE channel_id=? AND status='open'",
            (interaction.channel_id,),
        )
        if not ticket:
            await interaction.response.send_message(await tt(interaction.guild_id, "not_a_ticket"), ephemeral=True)
            return
        await _schliessen(interaction, (grund or "").strip()[:200])


async def setup(bot):
    await bot.add_cog(Tickets(bot))
