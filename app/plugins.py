"""Plugins: Pakete aus Einstellungen, die man bauen, weitergeben und einspielen kann.

Gewuenscht am 18.11.2026: "baue einen plugin system ein damit leute selber bauen koennen
also in den einstelungen plugins dann inport export und dann sol man wen das das plugin das
macht im server dann hinzufuegen und die einstelungen dafon expotieren und inpotieren".

── Was ein Plugin NICHT ist ──────────────────────────────────────────────────────────────
Kein Code. Ein Plugin fuehrt nichts aus, es beschreibt nur, was angelegt werden soll - der
Bot legt es an. Das ist eine bewusste Entscheidung und der ganze Grund, warum es diese
Datei gibt statt eines Lade-Mechanismus fuer fremde Python-Dateien:

Ein Python-Plugin laeuft im selben Prozess wie der Bot. Es koennte den Bot-Token lesen, die
ganze Datenbank - samt E-Mail-Adressen, Passwort-Hashes und 2FA-Geheimnissen der
Dashboard-Konten -, Dateien auf dem Wirt anfassen und alles davon ins Netz schicken. In
Python gibt es keine Abschottung, die das zuverlaessig verhindert. Wer ein Plugin hochladen
darf, haette damit den ganzen Bot. Eine Beschreibung kann das nicht: hier wird gelesen,
geprueft und in genau die Tabellen geschrieben, die unten aufgezaehlt sind.

── Warum Platzhalter ─────────────────────────────────────────────────────────────────────
Ein Server-Backup darf Rollen- und Kanalnummern roh enthalten: es wandert von einem Server
zum naechsten und wer es einspielt, weiss, was er tut. Ein Plugin ist das Gegenteil - es
soll auf JEDEM Server laufen, auch auf einem, den der Autor nie gesehen hat. Nummern aus
seinem Server waeren dort schlicht falsch.

Deshalb beschreibt ein Plugin seine offenen Stellen selbst ("einstellungen") und setzt im
Inhalt Platzhalter in doppelten geschweiften Klammern. Beim Hinzufuegen fuellt der Admin
ein Formular aus, und erst dann entstehen Zeilen in der Datenbank.

── Warum mitgeschrieben wird, was angelegt wurde ─────────────────────────────────────────
plugin_eintraege haelt zu jeder angelegten Zeile fest, aus welchem Plugin sie stammt. Ein
"Entfernen", das stattdessen nach Namen oder Inhalt sucht, trifft frueher oder spaeter
etwas, das jemand von Hand angelegt hat. Entfernt wird nur, was dieses Plugin auf diesem
Server selbst angelegt hat - nicht mehr und nicht weniger.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.parse

from database import db_rows, db_one, db_exec, db_insert

# Fassung des DATEIFORMATS, nicht des Bots. Erhoeht wird sie nur, wenn sich die Struktur so
# aendert, dass eine aeltere Datei nicht mehr gelesen werden kann - bis dahin bleibt jedes
# jemals exportierte Plugin einspielbar.
FORMAT = "1.0"

MAX_DATEI = 512 * 1024          # ein Paket ist Text; alles darueber ist keins
MAX_EINTRAEGE_JE_ART = 200      # gegen eine Datei, die 100.000 Befehle anlegen will
MAX_TEXT = 4000

# Kennung: das, was ein Plugin ueber Versionen hinweg identifiziert. Streng gehalten, weil
# sie in Dateinamen und Adressen auftaucht.
KENNUNG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,48}$")
PLATZHALTER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]{1,40})\s*\}\}")

# Die Arten von Einstellungen, die ein Plugin abfragen darf. "rolle", "kanal" und
# "kategorie" sind reine Nummern - die Oberflaeche zeigt dafuer eine Auswahlliste des
# jeweiligen Servers, damit niemand Nummern abtippen muss.
EINSTELLUNGSARTEN = ("text", "mehrzeilig", "zahl", "rolle", "kanal", "kategorie")


class PluginFehler(ValueError):
    """Ein Paket, das so nicht eingespielt werden kann - mit einem Satz, der sagt warum."""


# ── Herkunft: Plugins, die sich aktualisieren lassen ──────────────────────────────────────
# Ein Plugin darf sagen, wo seine jeweils neueste Fassung liegt ("quelle"). Dann kann man im
# Dashboard nachsehen lassen, ob es etwas Neueres gibt, statt dass der Autor allen eine neue
# Datei schicken muss.
#
# Der Bot holt damit eine Adresse, die ein FREMDER in eine Datei geschrieben hat. Das ist
# eine Abfrage aus dem Netz des Servers heraus - also genau die Stelle, an der man sich ein
# Loch ins eigene Netz baut, wenn man nicht aufpasst:
#   * nur https, damit unterwegs niemand etwas anderes unterschiebt
#   * keine privaten Adressen (127.*, 10.*, 192.168.*, ::1, und was sonst nicht ins
#     Internet gehoert) - sonst liesse sich der Bot als Fernbedienung fuer Geraete
#     benutzen, die nur er erreicht: der Router, das Dashboard selbst, der Docker-Host
#   * Weiterleitungen werden einzeln nachgeprueft, nicht blind verfolgt. Eine Adresse, die
#     oeffentlich aussieht und dann auf 127.0.0.1 zeigt, ist der uebliche Trick.
#   * Groesse und Zeit begrenzt
MAX_UMLEITUNGEN = 3
HOLZEIT = 15          # Sekunden


def pruefe_quelle(roh: str, aufloesen: bool = True) -> str:
    """Eine Bezugsadresse pruefen und geraderuecken, oder PluginFehler werfen.

    Bequemlichkeit fuer GitHub: die Adresse, die man im Browser in der Leiste stehen hat,
    zeigt auf eine HTML-Seite, nicht auf die Datei. Statt das jedem zu erklaeren, wird sie
    hier in die Rohfassung umgeschrieben - das ist die haeufigste Stolperstelle ueberhaupt.
    """
    url = (roh or "").strip()
    if not url:
        return ""
    if url.startswith("github.com/") or url.startswith("www.github.com/"):
        url = "https://" + url.lstrip("w.")
    teile = urllib.parse.urlsplit(url)
    if teile.scheme != "https":
        raise PluginFehler("Die Adresse muss mit https:// anfangen.")
    if not teile.hostname:
        raise PluginFehler("In der Adresse steht kein Rechnername.")

    # github.com/<nutzer>/<repo>/blob/<zweig>/<pfad>  ->  raw.githubusercontent.com/...
    if teile.hostname in ("github.com", "www.github.com"):
        stuecke = [s for s in teile.path.split("/") if s]
        if len(stuecke) >= 5 and stuecke[2] in ("blob", "raw"):
            url = ("https://raw.githubusercontent.com/"
                   + "/".join(stuecke[:2] + stuecke[3:]))
            teile = urllib.parse.urlsplit(url)
        else:
            raise PluginFehler(
                "Diese GitHub-Adresse zeigt auf eine Seite, nicht auf die Datei. Nimm den "
                "Link der Datei selbst (bei GitHub der Knopf „Raw“).")
    if len(url) > 500:
        raise PluginFehler("Die Adresse ist zu lang.")
    # Die Namensaufloesung bleibt beim Holen, nicht beim Lesen der Datei: ein Plugin, das
    # man auf einem Rechner ohne Netz einspielt, soll deswegen nicht durchfallen.
    if aufloesen:
        pruefe_ziel(teile.hostname)
    return url


def pruefe_ziel(rechner: str) -> None:
    """Zeigt dieser Rechnername ins oeffentliche Netz - oder nach innen?"""
    try:
        eintraege = socket.getaddrinfo(rechner, 443, proto=socket.IPPROTO_TCP)
    except Exception:
        raise PluginFehler(f"Der Rechner „{rechner}“ ist nicht auffindbar.")
    for eintrag in eintraege:
        adresse = ipaddress.ip_address(eintrag[4][0])
        if (adresse.is_private or adresse.is_loopback or adresse.is_link_local
                or adresse.is_reserved or adresse.is_multicast):
            raise PluginFehler(
                f"„{rechner}“ zeigt auf eine Adresse im eigenen Netz ({adresse}). Plugins "
                f"werden nur aus dem offenen Netz geholt.")


def version_neuer(neu: str, alt: str) -> bool:
    """Ist `neu` groesser als `alt`? Zahlenweise, nicht alphabetisch.

    Alphabetisch waere "1.10.0" kleiner als "1.9.0" - ein Fehler, den man erst bemerkt,
    wenn die zehnte Fassung da ist und niemand mehr ein Update angeboten bekommt.
    """
    def zahlen(v: str) -> list:
        return [int(t) for t in re.findall(r"\d+", v or "")[:4]] or [0]
    a, b = zahlen(neu), zahlen(alt)
    laenge = max(len(a), len(b))
    a += [0] * (laenge - len(a))
    b += [0] * (laenge - len(b))
    return a > b


async def hole_paket(url: str) -> dict:
    """Ein Plugin von seiner Bezugsadresse holen und pruefen.

    Weiterleitungen werden von Hand verfolgt, damit jede Zwischenstation dieselbe Pruefung
    durchlaeuft wie die erste - aiohttp wuerde ihnen sonst ungefragt folgen.
    """
    import aiohttp

    ziel = pruefe_quelle(url)
    zeit = aiohttp.ClientTimeout(total=HOLZEIT)
    async with aiohttp.ClientSession(timeout=zeit,
                                     headers={"User-Agent": "phobos-bot"}) as sitzung:
        for _ in range(MAX_UMLEITUNGEN + 1):
            async with sitzung.get(ziel, allow_redirects=False) as antwort:
                if antwort.status in (301, 302, 303, 307, 308):
                    weiter = antwort.headers.get("Location") or ""
                    if not weiter:
                        raise PluginFehler("Die Adresse leitet ins Leere weiter.")
                    ziel = pruefe_quelle(urllib.parse.urljoin(ziel, weiter))
                    continue
                if antwort.status == 404:
                    raise PluginFehler(
                        "Unter dieser Adresse liegt nichts (404). Zeigt der Link wirklich "
                        "auf die Datei?")
                if antwort.status != 200:
                    raise PluginFehler(
                        f"Die Adresse antwortet mit {antwort.status}.")
                roh = await antwort.content.read(MAX_DATEI + 1)
                if len(roh) > MAX_DATEI:
                    raise PluginFehler(
                        f"Die Datei dort ist zu groß (über {MAX_DATEI // 1024} KB).")
                return lese_paket(roh)
    raise PluginFehler("Die Adresse leitet zu oft weiter.")


# ── Was ein Plugin anlegen darf ───────────────────────────────────────────────────────────
# Jede Art nennt ihre Zieltabelle und die Spalten, die aus der Datei kommen duerfen. Alles,
# was hier nicht steht, wird beim Einspielen verworfen - eine Datei kann also keine Spalte
# fuellen, an die hier niemand gedacht hat.
#
# Bewusst NICHT dabei:
#   reaction_roles  - haengt an der Nummer einer bestehenden Nachricht; die kann ein Paket
#                     nicht mitbringen, es wuerde auf jedem Server ins Leere zeigen.
#   guild_configs   - das ist der Generalschluessel des Servers (Rollen, Schalter, der
#                     Schluessel der Profil-Schnittstelle). Ein Paket, das dort schreiben
#                     darf, kann Funktionen anschalten, die niemand bestellt hat.
#   vrc_links, warnings, birthdays - Daten von Personen, nichts, was man verteilt.
ARTEN: dict = {
    "befehle": {
        "tabelle": "custom_commands",
        "titel": ("📢 Befehle", "Commands"),
        "felder": {"trigger": "text", "response": "text"},
        "pflicht": ("trigger", "response"),
        "bezeichner": "trigger",
    },
    "level_rollen": {
        "tabelle": "level_roles",
        "titel": ("🏆 Level-Rollen", "Level roles"),
        "felder": {"level": "zahl", "role_id": "text", "typ": "text"},
        "pflicht": ("level", "role_id"),
        "bezeichner": "level",
    },
    "level_belohnungen": {
        "tabelle": "level_rewards",
        "titel": ("🎁 Level-Belohnungen", "Level rewards"),
        "felder": {"level": "zahl", "reward": "text"},
        "pflicht": ("level", "reward"),
        "bezeichner": "level",
    },
    "wortlisten": {
        "tabelle": "automod_word_presets",
        "titel": ("🛡️ Wortlisten", "Word lists"),
        "felder": {"label": "text", "words": "text"},
        "pflicht": ("label", "words"),
        "bezeichner": "label",
    },
    "ticket_panels": {
        "tabelle": "ticket_panels",
        "titel": ("🎫 Ticket-Panels", "Ticket panels"),
        "felder": {
            "name": "text", "description": "text", "button_label": "text", "emoji": "text",
            "support_role_id": "text", "category_id": "text", "log_channel_id": "text",
            "archive_category_id": "text", "close_button_label": "text",
            "ticket_message": "text", "transcript": "zahl",
            "transcript_channel_id": "text", "ein_ticket_gesamt": "zahl",
        },
        "pflicht": ("name",),
        "bezeichner": "name",
        # Ein eingespieltes Panel steht als Entwurf da und wird nicht von selbst
        # veroeffentlicht: das Veroeffentlichen postet eine Nachricht in einen Kanal, und das
        # soll der Mensch ausloesen, nicht ein Datei-Upload.
        "fest": {"status": "draft", "channel_id": "", "message_id": ""},
        "kinder": {
            "schluessel": "optionen",
            "tabelle": "ticket_panel_options",
            "titel": ("↳ Kategorien", "↳ Categories"),
            "bezeichner": "label",
            "elternspalte": "panel_id",
            "felder": {
                "label": "text", "description": "text", "emoji": "text",
                "support_role_id": "text", "category_id": "text",
                "ticket_message": "text", "sortierung": "zahl",
            },
            "pflicht": ("label",),
        },
    },
}


# Umgekehrte Zuordnung: zu einer Tabelle die Ueberschrift und die Spalte, an der man einen
# Eintrag WIEDERERKENNT ("!team", "Support", "Stufe 10"). Dafuer da, dass auf der Serverseite
# steht, was ein Plugin dort tatsaechlich angelegt hat - eine Zahl ("3 Befehle") sagt nicht,
# ob der richtige dabei ist.
TABELLEN_INFO: dict = {}
for _art, _regel in ARTEN.items():
    TABELLEN_INFO[_regel["tabelle"]] = (_regel["titel"], _regel["bezeichner"])
    if _regel.get("kinder"):
        _k = _regel["kinder"]
        TABELLEN_INFO[_k["tabelle"]] = (_k["titel"], _k["bezeichner"])


# ── Lesen und Pruefen ─────────────────────────────────────────────────────────────────────

def _text(wert, grenze: int = MAX_TEXT) -> str:
    """Alles, was aus einer fremden Datei kommt, wird als Text behandelt und gekuerzt.

    Keine Listen, keine verschachtelten Objekte: wo ein Text stehen soll, steht am Ende ein
    Text. Sonst landet die Struktur einer fremden Datei ungefiltert in einer Spalte.
    """
    if wert is None:
        return ""
    if isinstance(wert, bool):
        return "1" if wert else "0"
    if isinstance(wert, (int, float)):
        return str(wert)
    if not isinstance(wert, str):
        raise PluginFehler("Ein Feld enthält etwas anderes als Text.")
    return wert[:grenze]


def _link(wert: str) -> str:
    """Eine Adresse zum Anklicken - oder leer.

    Nur https. Eine Datei koennte sonst "javascript:..." hineinschreiben, und die Seite
    haette daraus einen Knopf gemacht, der im Browser des Admins etwas ausfuehrt.
    """
    url = (wert or "").strip()
    if not url:
        return ""
    if not url.lower().startswith("https://") or len(url) > 500:
        raise PluginFehler("„homepage“ muss eine https-Adresse sein.")
    return url


def _zahl(wert) -> int:
    try:
        return int(str(wert).strip() or 0)
    except (TypeError, ValueError):
        raise PluginFehler(f"„{wert}“ ist keine Zahl.")


def lese_paket(roh: bytes | str) -> dict:
    """Eine hochgeladene Datei zu einem geprueften Paket machen, oder PluginFehler werfen.

    Streng an jeder Stelle: eine Datei, die hier durchkommt, wird spaeter ohne weitere
    Rueckfragen in die Datenbank geschrieben. Jede Pruefung, die hier fehlt, fehlt dort auch.
    """
    if isinstance(roh, bytes):
        if len(roh) > MAX_DATEI:
            raise PluginFehler(
                f"Die Datei ist zu groß ({len(roh) // 1024} KB, erlaubt sind "
                f"{MAX_DATEI // 1024} KB).")
        try:
            roh = roh.decode("utf-8")
        except UnicodeDecodeError:
            raise PluginFehler("Die Datei ist keine Textdatei (erwartet wird JSON).")
    try:
        data = json.loads(roh)
    except Exception:
        raise PluginFehler("Die Datei ist kein gültiges JSON.")
    if not isinstance(data, dict):
        raise PluginFehler("Die Datei enthält kein Plugin (erwartet wird ein JSON-Objekt).")

    # Der Kopf unterscheidet ein Plugin von einem Server-Backup. Beides sind JSON-Dateien mit
    # Einstellungen darin, und ein Backup hier einzuspielen wuerde etwas voellig anderes tun,
    # als der Mensch davor erwartet.
    if "phobos_plugin" not in data:
        hinweis = (" Das sieht nach einem Server-Backup aus — das wird unter „Config“ "
                   "eingespielt, nicht hier.") if "meta" in data else ""
        raise PluginFehler("Das ist keine Plugin-Datei (die Zeile „phobos_plugin“ fehlt)."
                           + hinweis)
    format_ = _text(data.get("phobos_plugin"), 20)
    if format_.split(".")[0] != FORMAT.split(".")[0]:
        raise PluginFehler(
            f"Das Plugin ist im Format {format_} geschrieben, dieser Bot liest Format "
            f"{FORMAT}. Eine neuere Fassung des Bots kann es vielleicht.")

    kennung = _text(data.get("kennung"), 50).strip().lower()
    if not KENNUNG_RE.match(kennung):
        raise PluginFehler(
            "Die „kennung“ fehlt oder ist ungültig. Erlaubt sind 2 bis 49 Zeichen aus "
            "Kleinbuchstaben, Ziffern, Bindestrich und Unterstrich.")

    paket = {
        "phobos_plugin": FORMAT,
        "kennung": kennung,
        "name": _text(data.get("name"), 100).strip() or kennung,
        "version": _text(data.get("version"), 30).strip() or "1.0.0",
        "autor": _text(data.get("autor"), 100).strip(),
        "beschreibung": _text(data.get("beschreibung"), 2000).strip(),
        # Wo die jeweils neueste Fassung liegt, und wo Menschen nachlesen koennen. Beides
        # freiwillig; ohne "quelle" gibt es fuer dieses Plugin nur den Weg ueber eine Datei.
        "quelle": pruefe_quelle(_text(data.get("quelle"), 500), aufloesen=False),
        "homepage": _link(_text(data.get("homepage"), 500)),
        "einstellungen": _lese_einstellungen(data.get("einstellungen")),
        "inhalt": {},
    }

    inhalt = data.get("inhalt") or {}
    if not isinstance(inhalt, dict):
        raise PluginFehler("„inhalt“ muss ein Objekt sein.")
    unbekannt = [k for k in inhalt if k not in ARTEN]
    if unbekannt:
        raise PluginFehler(
            f"Unbekannte Inhaltsart: {', '.join(sorted(unbekannt)[:3])}. "
            f"Möglich sind: {', '.join(sorted(ARTEN))}.")
    for art, eintraege in inhalt.items():
        zeilen = _lese_eintraege(art, eintraege)
        if zeilen:
            paket["inhalt"][art] = zeilen
    if not paket["inhalt"]:
        raise PluginFehler("Das Plugin legt nichts an — „inhalt“ ist leer.")

    # Ein Platzhalter, den niemand ausfuellen kann, wuerde beim Hinzufuegen als "{{name}}" in
    # einem Befehlstext landen. Lieber die Datei ablehnen als das.
    erklaert = {e["name"] for e in paket["einstellungen"]}
    offen = sorted(benutzte_platzhalter(paket["inhalt"]) - erklaert)
    if offen:
        raise PluginFehler(
            f"Das Plugin benutzt Platzhalter, die es nicht erklärt: "
            f"{', '.join('{{' + n + '}}' for n in offen[:5])}. Jeder Platzhalter braucht "
            f"einen Eintrag unter „einstellungen“.")
    return paket


def _lese_einstellungen(roh) -> list:
    if roh is None:
        return []
    if not isinstance(roh, list):
        raise PluginFehler("„einstellungen“ muss eine Liste sein.")
    if len(roh) > 50:
        raise PluginFehler("Mehr als 50 Einstellungen sind nicht vorgesehen.")
    fertig, gesehen = [], set()
    for eintrag in roh:
        if not isinstance(eintrag, dict):
            raise PluginFehler("Jede Einstellung muss ein Objekt sein.")
        name = _text(eintrag.get("name"), 40).strip()
        if not re.match(r"^[a-zA-Z0-9_]{1,40}$", name):
            raise PluginFehler(
                f"„{name}“ ist kein gültiger Name für eine Einstellung (nur Buchstaben, "
                f"Ziffern und Unterstrich).")
        if name in gesehen:
            raise PluginFehler(f"Die Einstellung „{name}“ kommt doppelt vor.")
        gesehen.add(name)
        art = _text(eintrag.get("art"), 20).strip() or "text"
        if art not in EINSTELLUNGSARTEN:
            raise PluginFehler(
                f"Die Einstellung „{name}“ hat die unbekannte Art „{art}“. Möglich sind: "
                f"{', '.join(EINSTELLUNGSARTEN)}.")
        fertig.append({
            "name": name,
            "art": art,
            "titel": _text(eintrag.get("titel"), 100).strip() or name,
            "hinweis": _text(eintrag.get("hinweis"), 300).strip(),
            "standard": _text(eintrag.get("standard"), MAX_TEXT),
            "pflicht": bool(eintrag.get("pflicht")),
        })
    return fertig


def _lese_eintraege(art: str, roh) -> list:
    regel = ARTEN[art]
    if roh is None:
        return []
    if not isinstance(roh, list):
        raise PluginFehler(f"„{art}“ muss eine Liste sein.")
    if len(roh) > MAX_EINTRAEGE_JE_ART:
        raise PluginFehler(
            f"„{art}“ hat {len(roh)} Einträge — mehr als {MAX_EINTRAEGE_JE_ART} legt ein "
            f"Plugin nicht an.")
    fertig = []
    for zeile in roh:
        if not isinstance(zeile, dict):
            raise PluginFehler(f"Jeder Eintrag unter „{art}“ muss ein Objekt sein.")
        neu = _lese_zeile(art, zeile, regel)
        kinder_regel = regel.get("kinder")
        if kinder_regel:
            roh_kinder = zeile.get(kinder_regel["schluessel"]) or []
            if not isinstance(roh_kinder, list):
                raise PluginFehler(f"„{kinder_regel['schluessel']}“ muss eine Liste sein.")
            if len(roh_kinder) > MAX_EINTRAEGE_JE_ART:
                raise PluginFehler(f"Zu viele Einträge unter „{kinder_regel['schluessel']}“.")
            neu[kinder_regel["schluessel"]] = [
                _lese_zeile(art, k, kinder_regel) for k in roh_kinder
                if isinstance(k, dict)
            ]
        fertig.append(neu)
    return fertig


def _lese_zeile(art: str, zeile: dict, regel: dict) -> dict:
    neu = {}
    for feld, feldart in regel["felder"].items():
        if feld not in zeile:
            continue
        neu[feld] = _zahl(zeile[feld]) if feldart == "zahl" else _text(zeile[feld])
    for pflicht in regel.get("pflicht", ()):
        if not str(neu.get(pflicht, "")).strip():
            raise PluginFehler(f"Ein Eintrag unter „{art}“ hat kein „{pflicht}“.")
    return neu


def benutzte_platzhalter(inhalt: dict) -> set:
    """Alle {{namen}}, die irgendwo im Inhalt vorkommen - auch in verschachtelten Listen."""
    gefunden = set()

    def durchgehen(wert):
        if isinstance(wert, str):
            gefunden.update(PLATZHALTER_RE.findall(wert))
        elif isinstance(wert, dict):
            for v in wert.values():
                durchgehen(v)
        elif isinstance(wert, list):
            for v in wert:
                durchgehen(v)

    durchgehen(inhalt)
    return gefunden


# ── Einstellungen eines Servers ───────────────────────────────────────────────────────────

def pruefe_werte(paket: dict, werte: dict) -> dict:
    """Was der Admin ins Formular geschrieben hat, geprueft gegen das, was das Plugin will.

    Nicht erklaerte Namen fliegen raus: sonst koennte ein importierter Einstellungssatz
    Platzhalter mitbringen, die im Paket gar nicht vorgesehen sind.
    """
    fertig, fehlt = {}, []
    for e in paket.get("einstellungen", []):
        roh = werte.get(e["name"], "")
        wert = _text(roh).strip() if not isinstance(roh, (int, float)) else str(roh)
        if not wert:
            wert = _text(e.get("standard")).strip()
        if e["art"] in ("rolle", "kanal", "kategorie", "zahl") and wert:
            if not re.match(r"^\d{1,25}$", wert):
                raise PluginFehler(
                    f"„{e['titel']}“ erwartet eine Nummer, bekommen hat es „{wert[:40]}“.")
        if e.get("pflicht") and not wert:
            fehlt.append(e["titel"])
        fertig[e["name"]] = wert
    if fehlt:
        raise PluginFehler("Es fehlen Angaben: " + ", ".join(fehlt) + ".")
    return fertig


def einsetzen(wert, werte: dict):
    """Platzhalter durch die Werte des Servers ersetzen - rekursiv durch Listen und Objekte."""
    if isinstance(wert, str):
        return PLATZHALTER_RE.sub(lambda m: werte.get(m.group(1), ""), wert)
    if isinstance(wert, dict):
        return {k: einsetzen(v, werte) for k, v in wert.items()}
    if isinstance(wert, list):
        return [einsetzen(v, werte) for v in wert]
    return wert


# ── Anwenden und Entfernen ────────────────────────────────────────────────────────────────

async def anwenden(plugin_guild_id: int, paket: dict, guild_id, werte: dict) -> dict:
    """Legt den Inhalt des Pakets auf einem Server an und schreibt mit, was entstanden ist.

    Vorher wird entfernt, was dasselbe Plugin dort schon angelegt hat: so ist ein erneutes
    Anwenden (geaenderte Einstellungen, neue Fassung des Plugins) ein Ersetzen und kein
    zweiter Satz Befehle daneben.
    """
    await entfernen(plugin_guild_id)
    gid = str(guild_id)
    bilanz: dict = {}

    for art, zeilen in (paket.get("inhalt") or {}).items():
        regel = ARTEN.get(art)
        if not regel:
            continue
        kinder_regel = regel.get("kinder")
        for zeile in zeilen:
            gefuellt = einsetzen(zeile, werte)
            spalten = {k: v for k, v in gefuellt.items() if k in regel["felder"]}
            spalten.update(regel.get("fest", {}))
            spalten["guild_id"] = gid
            neue_id = await _einfuegen(regel["tabelle"], spalten)
            if neue_id is None:
                continue
            await _merken(plugin_guild_id, regel["tabelle"], neue_id)
            bilanz[art] = bilanz.get(art, 0) + 1

            if kinder_regel:
                for kind in gefuellt.get(kinder_regel["schluessel"], []):
                    k_spalten = {k: v for k, v in kind.items()
                                 if k in kinder_regel["felder"]}
                    k_spalten[kinder_regel["elternspalte"]] = neue_id
                    kind_id = await _einfuegen(kinder_regel["tabelle"], k_spalten)
                    if kind_id is not None:
                        await _merken(plugin_guild_id, kinder_regel["tabelle"], kind_id)
    return bilanz


async def _einfuegen(tabelle: str, spalten: dict):
    """Eine Zeile anlegen - und None zurueckgeben, wenn sie nicht hineinpasst.

    Ein einzelner Eintrag, den der Server schon hat (custom_commands ist eindeutig ueber
    guild_id+trigger), darf nicht das ganze Plugin scheitern lassen. Er wird uebersprungen,
    und weil er dann auch nicht mitgeschrieben wird, fasst ihn das Entfernen spaeter nicht
    an: eine Zeile, die vorher da war, bleibt dem Server erhalten.
    """
    felder = ", ".join(spalten)
    frage = ", ".join("?" for _ in spalten)
    try:
        return await db_insert(
            f"INSERT INTO {tabelle} ({felder}) VALUES ({frage})", tuple(spalten.values()))
    except Exception:
        return None


async def _merken(plugin_guild_id: int, tabelle: str, zeile_id: int) -> None:
    await db_exec(
        "INSERT INTO plugin_eintraege (plugin_guild_id, tabelle, zeile_id) VALUES (?,?,?)",
        (plugin_guild_id, tabelle, int(zeile_id)))


async def entfernen(plugin_guild_id: int) -> int:
    """Alles wieder wegnehmen, was dieses Plugin auf diesem Server angelegt hat.

    Nur ueber die mitgeschriebenen Nummern, nie ueber Namen oder Inhalt - was jemand von Hand
    angelegt oder spaeter geaendert hat, bleibt stehen. Die Tabelle kommt aus ARTEN und nicht
    aus der Zeile selbst: so kann in dem Namen nichts stehen, was nicht vorgesehen ist.
    """
    erlaubt = set()
    for regel in ARTEN.values():
        erlaubt.add(regel["tabelle"])
        if regel.get("kinder"):
            erlaubt.add(regel["kinder"]["tabelle"])

    zeilen = await db_rows(
        "SELECT id, tabelle, zeile_id FROM plugin_eintraege WHERE plugin_guild_id=?",
        (plugin_guild_id,))
    weg = 0
    for z in zeilen:
        if z["tabelle"] in erlaubt:
            try:
                await db_exec(f"DELETE FROM {z['tabelle']} WHERE id=?", (z["zeile_id"],))
                weg += 1
            except Exception:
                pass
    await db_exec("DELETE FROM plugin_eintraege WHERE plugin_guild_id=?", (plugin_guild_id,))
    return weg


# ── Datenbank-Hilfen fuer die Oberflaeche ─────────────────────────────────────────────────

async def plugin_liste() -> list:
    zeilen = await db_rows(
        "SELECT id, kennung, name, version, autor, beschreibung, quelle, homepage, "
        "geprueft, neue_version, angelegt, geaendert "
        "FROM plugins ORDER BY name COLLATE NOCASE")
    for z in zeilen:
        z["server"] = (await db_one(
            "SELECT COUNT(*) AS n FROM plugin_guilds WHERE plugin_id=?", (z["id"],)))["n"]
    return zeilen


async def plugin_paket(plugin_id: int) -> dict | None:
    zeile = await db_one("SELECT inhalt FROM plugins WHERE id=?", (plugin_id,))
    if not zeile:
        return None
    try:
        return json.loads(zeile["inhalt"])
    except Exception:
        return None


def paket_als_datei(paket: dict) -> dict:
    """Das Paket so, wie es exportiert wird - ohne alles, was nur hier drinnen gilt."""
    return {
        "phobos_plugin": FORMAT,
        "kennung": paket.get("kennung", ""),
        "name": paket.get("name", ""),
        "version": paket.get("version", ""),
        "autor": paket.get("autor", ""),
        "beschreibung": paket.get("beschreibung", ""),
        "quelle": paket.get("quelle", ""),
        "homepage": paket.get("homepage", ""),
        "einstellungen": paket.get("einstellungen", []),
        "inhalt": paket.get("inhalt", {}),
    }


async def angelegte_eintraege(plugin_guild_id: int, lang: str = "de") -> dict:
    """Was dieses Plugin auf diesem Server angelegt hat - mit Namen, nicht als Anzahl.

    Gewuenscht am 18.11.2026: „wenn man ein Plugin hinzufügt sollte dann das Teil was
    hinzugefügt worden ist dann dort landen mit Namen". Eine Zahl beantwortet die Frage
    nicht, die man davor hat: ist der Befehl dabei, den ich suche?

    Nachgeschlagen wird jede Zeile einzeln, denn genau das ist die Aussage - nicht was in
    der Datei steht, sondern was auf dem Server wirklich existiert. Zeilen, die jemand
    inzwischen von Hand geloescht hat, werden mitgezaehlt und als solche gemeldet, statt
    stillschweigend zu verschwinden.
    """
    i = 0 if lang != "en" else 1
    gruppen: dict = {}
    fehlend = 0
    for z in await db_rows(
            "SELECT tabelle, zeile_id FROM plugin_eintraege WHERE plugin_guild_id=? "
            "ORDER BY id", (plugin_guild_id,)):
        info = TABELLEN_INFO.get(z["tabelle"])
        if not info:
            continue
        titel, bezeichner = info
        # Tabellen- und Spaltenname stammen aus TABELLEN_INFO, also aus diesem Modul - nie
        # aus der Zeile selbst. In der Datenbank koennte sonst stehen, was jemand will.
        zeile = await db_one(
            f"SELECT {bezeichner} AS b FROM {z['tabelle']} WHERE id=?", (z["zeile_id"],))
        if not zeile:
            fehlend += 1
            continue
        name = str(zeile["b"] if zeile["b"] not in (None, "") else "—")
        gruppen.setdefault(titel[i] if i < len(titel) else titel[0], []).append(name[:60])
    return {
        "gruppen": [{"titel": k, "namen": v} for k, v in gruppen.items()],
        "fehlend": fehlend,
    }


def zusammenfassung(paket: dict, lang: str = "de") -> list:
    """„2 Befehle, 1 Ticket-Panel“ - was dieses Paket anlegen wird, in Worten.

    Steht vor dem Hinzufuegen auf der Seite: niemand soll eine fremde Datei einspielen und
    erst hinterher sehen, was sie getan hat.
    """
    i = 0 if lang != "en" else 1
    aus = []
    for art, zeilen in (paket.get("inhalt") or {}).items():
        regel = ARTEN.get(art)
        if not regel:
            continue
        titel = regel["titel"][i] if i < len(regel["titel"]) else regel["titel"][0]
        kinder = 0
        if regel.get("kinder"):
            kinder = sum(len(z.get(regel["kinder"]["schluessel"], [])) for z in zeilen)
        aus.append({"art": art, "titel": titel, "anzahl": len(zeilen), "kinder": kinder})
    return aus
