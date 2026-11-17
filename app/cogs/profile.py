"""Profile: was jemand ueber sich selbst hinterlegt - und wer es lesen darf.

Gewuenscht am 17.11.2026 fuer eine VRChat-Welt ("the main thing I want the bot for is to add
information about people in our world"): Befehle wie /bio, /kinks, /triggers, /limits zum
Eintragen, /inspect zum Nachsehen, und die Anzeige derselben Angaben in der Welt selbst.

Drei Entscheidungen, die bewusst anders sind als in der urspruenglichen Beschreibung:

1. **Kein Pastebin, kein Gist.** Gewuenscht war, die Texte dorthin zu schieben. Das sind
   intime Angaben - auf einem fremden Dienst heisst das: eine Adresse, die jeder mit dem
   Link lesen kann, kein verlaessliches Loeschen, und ein Zugangsschluessel, der im Bot
   liegen muss. Die Texte bleiben hier in der Datenbank; fuer die Welt gibt es eine eigene
   Leseadresse mit Schluessel (siehe main.py, /api/profil). Loescht jemand sein Profil, ist
   es wirklich weg.

2. **18+ ist Pflicht, keine Einstellung.** Bei Feldern wie kinks/limits fuehrt kein Weg
   daran vorbei. Als Nachweis zaehlt entweder die VRChat-Altersbestaetigung aus dem
   VRC-Link-Reiter oder eine Rolle, die der Server dafuer bestimmt. Fuer reine Bio-Felder
   laesst sich die Pflicht je Feld abschalten - fuer die anderen nicht.

3. **Nichts ist oeffentlich, bis jemand es selbst freigibt.** Ein Eintrag ist zunaechst nur
   ueber /inspect im Server sichtbar. In der Welt erscheint er erst, wenn die Person das
   mit /profil ausdruecklich einschaltet - einmal fuer alle ihre Felder, sichtbar im selben
   Fenster, in dem sie schreibt.

Kein Cog importiert einen anderen (feste Hausregel hier, siehe cogs/tickets.py); geteilte
Teile kommen aus database.py.
"""
import datetime

import discord
from discord import app_commands, ui
from discord.ext import commands

from database import db_exec, db_one, db_rows, get_guild_config

# Welche Felder es gibt. Reihenfolge = Reihenfolge in der Anzeige.
# "erwachsen": ob der Eintrag ohne 18+-Nachweis ueberhaupt gesetzt oder gelesen werden darf.
FELDER = [
    {"name": "bio",      "titel": "Bio",      "emoji": "📝", "erwachsen": False,
     "platz": "Wer du bist, was du in der Welt machst."},
    {"name": "kinks",    "titel": "Kinks",    "emoji": "🔥", "erwachsen": True,
     "platz": "Was du magst."},
    {"name": "triggers", "titel": "Triggers", "emoji": "⚠️", "erwachsen": True,
     "platz": "Was bei dir nicht geht - auch ohne Begruendung."},
    {"name": "limits",   "titel": "Limits",   "emoji": "🚫", "erwachsen": True,
     "platz": "Harte Grenzen."},
]
FELD_NACH_NAME = {f["name"]: f for f in FELDER}

MAX_LAENGE = 1000   # Discord nimmt bis 4000; so viel liest in der Welt ohnehin niemand

PROFIL_TEXTE = {
    "de": {
        "aus":          "Profile sind auf diesem Server nicht eingeschaltet.",
        "kein_18":      "Dafür ist eine Bestätigung als 18+ nötig. Verknüpfe dein VRChat-Konto "
                        "(/vrc-link) oder frag die Serverleitung nach der Rolle dafür.",
        "darf_nicht":   "Du darfst die Profile anderer hier nicht ansehen.",
        "gespeichert":  "{feld} gespeichert.",
        "geleert":      "{feld} gelöscht.",
        "leer_eigen":   "Du hast noch nichts eingetragen. Fang mit /bio an.",
        "leer_fremd":   "{wer} hat nichts eingetragen.",
        # Eigener Text, damit nicht "hat nichts eingetragen" dasteht, wo in Wahrheit nur
        # die Felder hinter der Altersschranke gefuellt sind. Er gilt fuer BEIDE Faelle -
        # leer und nicht sichtbar -, sonst verraet schon die Wahl der Antwort, dass da
        # etwas steht.
        "nichts_sichtbar": "Hier ist für dich nichts zu sehen. Für die weiteren Angaben "
                           "ist eine Bestätigung als 18+ nötig.",
        "titel_eigen":  "Dein Profil",
        "titel_fremd":  "Profil von {wer}",
        "welt_an":      "Dein Profil wird in der Welt angezeigt.",
        "welt_aus":     "Dein Profil wird in der Welt nicht mehr angezeigt.",
        "welt_knopf_an":  "In der Welt anzeigen",
        "welt_knopf_aus": "In der Welt verbergen",
        "welt_hinweis_an":  "Sichtbar in der Welt.",
        "welt_hinweis_aus": "Nur hier im Server sichtbar.",
        "alles_weg":    "Dein Profil ist gelöscht - alle Felder.",
        "modal_titel":  "{feld} bearbeiten",
        "modal_label":  "Text (leer lassen = löschen)",
        "geaendert":    "Zuletzt geändert: {datum}",
    },
    "en": {
        "aus":          "Profiles are not enabled on this server.",
        "kein_18":      "This needs a confirmed 18+ status. Link your VRChat account "
                        "(/vrc-link) or ask the server staff for the role.",
        "darf_nicht":   "You are not allowed to view other people's profiles here.",
        "gespeichert":  "{feld} saved.",
        "geleert":      "{feld} deleted.",
        "leer_eigen":   "You haven't written anything yet. Start with /bio.",
        "leer_fremd":   "{wer} hasn't written anything.",
        "nichts_sichtbar": "There is nothing here for you to see. The remaining entries "
                           "need a confirmed 18+ status.",
        "titel_eigen":  "Your profile",
        "titel_fremd":  "{wer}'s profile",
        "welt_an":      "Your profile will be shown in the world.",
        "welt_aus":     "Your profile is no longer shown in the world.",
        "welt_knopf_an":  "Show in the world",
        "welt_knopf_aus": "Hide in the world",
        "welt_hinweis_an":  "Visible in the world.",
        "welt_hinweis_aus": "Only visible here on the server.",
        "alles_weg":    "Your profile is deleted - every field.",
        "modal_titel":  "Edit {feld}",
        "modal_label":  "Text (leave empty to delete)",
        "geaendert":    "Last changed: {datum}",
    },
}


async def pt(guild_id, schluessel: str, **werte) -> str:
    """Ein Profiltext in der Sprache dieses Servers. Faellt auf Deutsch zurueck."""
    sprache = (await get_guild_config(guild_id, "bot_lang")) or "de"
    tabelle = PROFIL_TEXTE.get(sprache) or PROFIL_TEXTE["de"]
    text = tabelle.get(schluessel) or PROFIL_TEXTE["de"].get(schluessel, schluessel)
    try:
        return text.format(**werte)
    except (KeyError, IndexError):
        return text


async def profile_an(guild_id) -> bool:
    return (await get_guild_config(guild_id, "profil_enabled")) == "1"


async def ist_18(guild_id, member: discord.Member) -> bool:
    """Zwei Nachweise, einer genuegt.

    Die VRChat-Bestaetigung ist der ehrlichere: sie kommt von VRChat selbst und nicht davon,
    dass jemand eine Rolle verteilt hat. Die Rolle gibt es trotzdem, weil nicht jeder Server
    VRC-Link benutzt - und ohne irgendeinen Weg waere die Funktion dort tot.
    """
    link = await db_one(
        "SELECT vrc_age_verified FROM vrc_links WHERE guild_id=? AND user_id=? "
        "AND status='approved'",
        (str(guild_id), str(member.id)))
    if link and link["vrc_age_verified"]:
        return True
    rolle_id = await get_guild_config(guild_id, "profil_18_role")
    if rolle_id:
        try:
            return any(str(r.id) == str(rolle_id) for r in getattr(member, "roles", []))
        except Exception:
            return False
    return False


async def darf_lesen(guild_id, member: discord.Member) -> bool:
    """Wer /inspect benutzen darf. Ohne eingestellte Rolle: jeder, der 18+ nachweisen kann."""
    rolle_id = await get_guild_config(guild_id, "profil_inspect_role")
    if not rolle_id:
        return True
    try:
        return any(str(r.id) == str(rolle_id) for r in getattr(member, "roles", []))
    except Exception:
        return False


async def eintraege(guild_id, user_id) -> list:
    rows = await db_rows(
        "SELECT * FROM profil_eintraege WHERE guild_id=? AND user_id=? AND text<>''",
        (str(guild_id), str(user_id)))
    # In der Reihenfolge von FELDER, nicht in der der Datenbank.
    nach_name = {r["feld"]: r for r in rows}
    return [nach_name[f["name"]] for f in FELDER if f["name"] in nach_name]


def nur_erlaubte(eintr: list, ist_erwachsen: bool) -> list:
    """Was diese lesende Person sehen darf.

    Der erste Entwurf verlangte 18+ fuer /inspect und /profil insgesamt - damit kam jemand,
    der nur eine Bio geschrieben hat, nicht einmal an sein EIGENES Profil. Richtig ist:
    gelesen werden darf immer, aber die Felder hinter der Altersschranke sind nur fuer
    Leute sichtbar, die sie passiert haben. Das gilt auch fuer das eigene Profil - wer
    kinks ohnehin nicht eintragen darf, hat dort auch nichts stehen.
    """
    if ist_erwachsen:
        return eintr
    return [r for r in eintr
            if not FELD_NACH_NAME.get(r["feld"], {"erwachsen": True})["erwachsen"]]


async def welt_sichtbar(guild_id, user_id) -> bool:
    row = await db_one(
        "SELECT MAX(welt) AS w FROM profil_eintraege WHERE guild_id=? AND user_id=?",
        (str(guild_id), str(user_id)))
    return bool(row and row["w"])


async def setze_welt(guild_id, user_id, an: bool):
    await db_exec(
        "UPDATE profil_eintraege SET welt=? WHERE guild_id=? AND user_id=?",
        (1 if an else 0, str(guild_id), str(user_id)))


async def profil_embed(guild_id, member, eintr: list, eigenes: bool) -> discord.Embed:
    titel = await pt(guild_id, "titel_eigen" if eigenes else "titel_fremd",
                     wer=getattr(member, "display_name", "?"))
    e = discord.Embed(title=titel, color=0x7C3AED)
    try:
        e.set_thumbnail(url=member.display_avatar.url)
    except Exception:
        pass
    for r in eintr:
        feld = FELD_NACH_NAME.get(r["feld"], {"titel": r["feld"], "emoji": "•"})
        e.add_field(name=f"{feld['emoji']} {feld['titel']}", value=r["text"][:1024],
                    inline=False)
    if eintr:
        neueste = max((r["geaendert"] or "") for r in eintr)
        if neueste:
            e.set_footer(text=await pt(guild_id, "geaendert", datum=str(neueste)[:16]))
    return e


class FeldModal(ui.Modal):
    """Ein Fenster je Feld. Der bisherige Text steht schon drin - sonst muesste jeder, der
    eine Kleinigkeit ergaenzen will, alles neu tippen."""

    def __init__(self, feld: dict, vorhanden: str, titel: str, label: str, platz: str):
        super().__init__(title=titel[:45])
        self.feld = feld
        self.eingabe = ui.TextInput(
            label=label[:45], style=discord.TextStyle.paragraph, required=False,
            max_length=MAX_LAENGE, default=vorhanden or None, placeholder=platz[:100])
        self.add_item(self.eingabe)

    async def on_submit(self, interaction: discord.Interaction):
        text = (self.eingabe.value or "").strip()
        name = self.feld["name"]
        if not text:
            await db_exec(
                "DELETE FROM profil_eintraege WHERE guild_id=? AND user_id=? AND feld=?",
                (str(interaction.guild_id), str(interaction.user.id), name))
            await interaction.response.send_message(
                await pt(interaction.guild_id, "geleert", feld=self.feld["titel"]),
                ephemeral=True)
            return
        # Die Welt-Freigabe haengt an der Person, nicht am einzelnen Feld: ein neues Feld
        # uebernimmt deshalb, was fuer die anderen schon gilt. Sonst waere ein frisch
        # geschriebener Text ploetzlich oeffentlich - oder, andersherum, unsichtbar, ohne
        # dass jemand das irgendwo sieht.
        welt = 1 if await welt_sichtbar(interaction.guild_id, interaction.user.id) else 0
        await db_exec(
            "INSERT INTO profil_eintraege (guild_id, user_id, feld, text, welt, geaendert) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(guild_id, user_id, feld) DO UPDATE SET "
            "text=excluded.text, geaendert=excluded.geaendert",
            (str(interaction.guild_id), str(interaction.user.id), name, text[:MAX_LAENGE],
             welt, datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
        await interaction.response.send_message(
            await pt(interaction.guild_id, "gespeichert", feld=self.feld["titel"]),
            ephemeral=True)


class WeltKnopf(ui.Button):
    """Der einzige Weg, wie ein Eintrag die Welt erreicht - und er liegt bei der Person.

    Der Zustand wird beim Druecken frisch gelesen und nicht aus dem Knopf genommen. Sonst
    haengt er an dem Moment, in dem die Nachricht entstanden ist: wer zweimal drueckt oder
    die Anzeige nebenher in einem zweiten Fenster umstellt, schaltet beim zweiten Mal auf
    denselben Wert wie beim ersten - der Knopf sagt dann "ausgeschaltet", und es bleibt an.
    Bei einer Freigabe fuer sehr private Angaben ist das kein Schoenheitsfehler.
    """

    def __init__(self, label: str):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        neu = not await welt_sichtbar(interaction.guild_id, interaction.user.id)
        await setze_welt(interaction.guild_id, interaction.user.id, neu)
        self.label = await pt(interaction.guild_id,
                              "welt_knopf_aus" if neu else "welt_knopf_an")
        bescheid = await pt(interaction.guild_id, "welt_an" if neu else "welt_aus")

        # Zwei getrennte Schritte, zwei getrennte Fehlerfaelle. Vorher standen beide in
        # EINEM try: schlug das Nachrichtensenden fehl, lief derselbe Versand im except
        # noch einmal - die Person bekam die Meldung doppelt. Und scheiterte schon das
        # Umschreiben, war die Interaktion unbeantwortet, und followup lief ins Leere.
        geantwortet = False
        try:
            await interaction.response.edit_message(view=self.view)
            geantwortet = True
        except Exception as e:
            print(f"[Profile] Knopf liess sich nicht umschreiben: {e!r}")

        # Die Umstellung ist passiert - das muss ankommen, auch wenn die alte Nachricht
        # nicht mehr erreichbar war.
        try:
            if geantwortet:
                await interaction.followup.send(bescheid, ephemeral=True)
            else:
                await interaction.response.send_message(bescheid, ephemeral=True)
        except Exception as e:
            print(f"[Profile] Rueckmeldung zur Welt-Freigabe nicht zugestellt: {e!r}")


class ProfilView(ui.View):
    def __init__(self, label: str):
        super().__init__(timeout=900)
        self.add_item(WeltKnopf(label))


async def _vorpruefung(interaction: discord.Interaction, feld: dict | None) -> bool:
    """An/aus und 18+ an einer Stelle. Antwortet selbst, wenn etwas fehlt.

    feld=None heisst "nur nachsehen" - dafuer wird kein Alter verlangt, sondern spaeter
    gefiltert (siehe nur_erlaubte). Sonst saehe jemand ohne Nachweis nicht einmal die
    eigene Bio.
    """
    if not await profile_an(interaction.guild_id):
        await interaction.response.send_message(
            await pt(interaction.guild_id, "aus"), ephemeral=True)
        return False
    if feld is not None and feld["erwachsen"] and not await ist_18(interaction.guild_id,
                                                                  interaction.user):
        await interaction.response.send_message(
            await pt(interaction.guild_id, "kein_18"), ephemeral=True)
        return False
    return True


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _bearbeiten(self, interaction: discord.Interaction, name: str):
        feld = FELD_NACH_NAME[name]
        if not await _vorpruefung(interaction, feld):
            return
        row = await db_one(
            "SELECT text FROM profil_eintraege WHERE guild_id=? AND user_id=? AND feld=?",
            (str(interaction.guild_id), str(interaction.user.id), name))
        await interaction.response.send_modal(FeldModal(
            feld, (row or {}).get("text", ""),
            await pt(interaction.guild_id, "modal_titel", feld=feld["titel"]),
            await pt(interaction.guild_id, "modal_label"),
            feld["platz"]))

    @app_commands.guild_only()
    @app_commands.command(name="bio", description="Deine Bio eintragen oder ändern")
    async def bio(self, interaction: discord.Interaction):
        await self._bearbeiten(interaction, "bio")

    @app_commands.guild_only()
    @app_commands.command(name="kinks", description="Deine Kinks eintragen oder ändern (18+)")
    async def kinks(self, interaction: discord.Interaction):
        await self._bearbeiten(interaction, "kinks")

    @app_commands.guild_only()
    @app_commands.command(name="triggers", description="Deine Triggers eintragen oder ändern (18+)")
    async def triggers(self, interaction: discord.Interaction):
        await self._bearbeiten(interaction, "triggers")

    @app_commands.guild_only()
    @app_commands.command(name="limits", description="Deine Limits eintragen oder ändern (18+)")
    async def limits(self, interaction: discord.Interaction):
        await self._bearbeiten(interaction, "limits")

    @app_commands.guild_only()
    @app_commands.command(name="profil", description="Dein eigenes Profil ansehen")
    async def profil(self, interaction: discord.Interaction):
        if not await _vorpruefung(interaction, None):
            return
        erwachsen = await ist_18(interaction.guild_id, interaction.user)
        eintr = nur_erlaubte(await eintraege(interaction.guild_id, interaction.user.id),
                             erwachsen)
        if not eintr:
            await interaction.response.send_message(
                await pt(interaction.guild_id,
                         "leer_eigen" if erwachsen else "nichts_sichtbar"), ephemeral=True)
            return
        an = await welt_sichtbar(interaction.guild_id, interaction.user.id)
        embed = await profil_embed(interaction.guild_id, interaction.user, eintr, True)
        embed.description = await pt(interaction.guild_id,
                                     "welt_hinweis_an" if an else "welt_hinweis_aus")
        label = await pt(interaction.guild_id,
                         "welt_knopf_aus" if an else "welt_knopf_an")
        await interaction.response.send_message(
            embed=embed, view=ProfilView(label), ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="inspect", description="Das Profil einer Person ansehen")
    @app_commands.describe(person="Wessen Profil? Ohne Angabe dein eigenes.")
    async def inspect(self, interaction: discord.Interaction,
                      person: discord.Member | None = None):
        if not await _vorpruefung(interaction, None):
            return
        ziel = person or interaction.user
        eigenes = ziel.id == interaction.user.id
        if not eigenes and not await darf_lesen(interaction.guild_id, interaction.user):
            await interaction.response.send_message(
                await pt(interaction.guild_id, "darf_nicht"), ephemeral=True)
            return
        erwachsen = await ist_18(interaction.guild_id, interaction.user)
        eintr = nur_erlaubte(await eintraege(interaction.guild_id, ziel.id), erwachsen)
        if not eintr:
            # Wer selbst keine Bestaetigung hat, bekommt IMMER denselben Satz - egal ob die
            # Person nichts geschrieben hat oder nur Felder, die er nicht sehen darf. Sonst
            # verriete die Antwort, was er gerade nicht sehen soll.
            schluessel = ("leer_eigen" if eigenes else "leer_fremd") if erwachsen \
                else "nichts_sichtbar"
            await interaction.response.send_message(
                await pt(interaction.guild_id, schluessel, wer=ziel.display_name),
                ephemeral=True)
            return
        # Immer nur fuer den Fragenden sichtbar. Ein Profil in den Kanal zu stellen waere
        # eine Weitergabe, die die betroffene Person nie erlaubt hat - auch dann nicht,
        # wenn sie den Text selbst geschrieben hat.
        await interaction.response.send_message(
            embed=await profil_embed(interaction.guild_id, ziel, eintr, eigenes),
            ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="profil-loeschen",
                          description="Dein Profil vollständig löschen")
    async def loeschen(self, interaction: discord.Interaction):
        await db_exec("DELETE FROM profil_eintraege WHERE guild_id=? AND user_id=?",
                      (str(interaction.guild_id), str(interaction.user.id)))
        await interaction.response.send_message(
            await pt(interaction.guild_id, "alles_weg"), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Profile(bot))
