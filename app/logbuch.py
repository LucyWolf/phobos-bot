"""Das eigene Protokoll des Bots - eine Datei, die er selbst lesen und loeschen kann.

Warum ueberhaupt, wo Docker doch schon alles mitschreibt: genau deshalb. Docker legt die
Ausgabe in /var/lib/docker/containers/<id>/<id>-json.log, also AUSSERHALB des Containers.
Der Bot sieht diesen Pfad nicht und hat keine Rechte darauf - er koennte dort nichts
anzeigen und erst recht nichts loeschen. Ein Knopf im Dashboard waere eine Anzeige, die
beschreibt statt zu handeln.

Am 02.11.2026 war genau diese Datei auf 21 GB angewachsen und die Platte des Servers voll.
Aufgefallen ist es erst, als nichts mehr gespeichert werden konnte - der Bot selbst hatte
keine Moeglichkeit, davon zu wissen, geschweige denn es zu sagen.

Also schreibt er hier zusaetzlich in sein eigenes Verzeichnis, hart begrenzt. Was hier
steht, kann er zeigen, messen und wegwerfen.

Der Weg dorthin ist sys.stdout: jedes print() im ganzen Projekt laeuft darueber, vom Cog
bis zur Route. Statt ueber dreihundert Aufrufe umzuschreiben, wird der Strom einmal
umgelenkt - und zwar WEITERGEREICHT, nicht abgefangen: Docker und journalctl sehen alles
unveraendert, es kommt nur eine Kopie dazu.
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import sys
import threading
from pathlib import Path

# Hoechstens so gross wird eine Protokolldatei, dann wird umbenannt.
MAX_BYTES = 5 * 1024 * 1024
# So viele alte Staende bleiben daneben liegen (.1, .2). Zusammen also hoechstens
# dreimal MAX_BYTES - ein Deckel, der sich nicht verschieben kann.
MAX_DATEIEN = 2

_pfad: Path | None = None
_sperre = threading.Lock()


def datei() -> Path | None:
    """Wohin geschrieben wird - None, solange nichts eingerichtet ist."""
    return _pfad


class _Abzweig:
    """Schreibt in den urspruenglichen Strom UND in die Datei.

    Keine Unterklasse von io.TextIOBase: hier wird nur das gebraucht, was print() und
    Dritt-Bibliotheken tatsaechlich aufrufen. Alles andere wird an das Original
    durchgereicht, damit nichts kaputtgeht, was sonst noch an stdout haengt.
    """

    def __init__(self, original, ziel: Path):
        self._original = original
        self._ziel = ziel
        # Gegen Endlosschleifen: scheitert das Schreiben und WIR wuerden das wiederum
        # ueber print() melden, landete diese Meldung erneut hier. Also still bleiben.
        self._stumm = False

    def write(self, text):
        # Zuerst das Original - was auch immer hier schiefgeht, die Ausgabe nach Docker
        # darf nie davon abhaengen, ob eine Datei beschreibbar ist.
        geschrieben = self._original.write(text)
        if text and not self._stumm:
            try:
                self._anhaengen(text)
            except Exception:
                # Volle Platte, fehlende Rechte, entferntes Verzeichnis: der Bot laeuft
                # weiter. Ein Protokoll, das den Betrieb anhaelt, waere schlimmer als
                # keines - und ausgerechnet bei voller Platte ist beides zugleich los.
                self._stumm = True
        return geschrieben

    def _anhaengen(self, text: str) -> None:
        with _sperre:
            # Umbenennen, BEVOR geschrieben wird: so bleibt die aktive Datei immer unter
            # dem Deckel, statt erst darueber hinauszuwachsen und dann aufzuraeumen.
            try:
                if self._ziel.exists() and self._ziel.stat().st_size >= MAX_BYTES:
                    _rotieren(self._ziel)
            except OSError:
                pass
            with open(self._ziel, "a", encoding="utf-8", errors="replace") as f:
                f.write(text)

    def flush(self):
        self._original.flush()

    def isatty(self):
        try:
            return self._original.isatty()
        except Exception:
            return False

    def fileno(self):
        return self._original.fileno()

    @property
    def encoding(self):
        return getattr(self._original, "encoding", "utf-8")

    def writelines(self, zeilen):
        for z in zeilen:
            self.write(z)

    def __getattr__(self, name):
        # Alles Uebrige (closed, errors, buffer, ...) unveraendert vom Original.
        return getattr(self._original, name)


def _rotieren(ziel: Path) -> None:
    """phobos.log -> phobos.log.1 -> phobos.log.2, und was darueber hinausgeht, faellt weg."""
    try:
        aeltester = ziel.with_suffix(ziel.suffix + f".{MAX_DATEIEN}")
        if aeltester.exists():
            aeltester.unlink()
    except OSError:
        pass
    for nummer in range(MAX_DATEIEN - 1, 0, -1):
        alt = ziel.with_suffix(ziel.suffix + f".{nummer}")
        neu = ziel.with_suffix(ziel.suffix + f".{nummer + 1}")
        try:
            if alt.exists():
                alt.replace(neu)
        except OSError:
            pass
    try:
        ziel.replace(ziel.with_suffix(ziel.suffix + ".1"))
    except OSError:
        pass


def einrichten(verzeichnis) -> Path | None:
    """stdout und stderr zusaetzlich in eine Datei leiten. Gibt den Pfad zurueck.

    Mehrfaches Aufrufen ist harmlos: beim zweiten Mal wuerde sonst ein Abzweig auf einem
    Abzweig sitzen und jede Zeile doppelt in der Datei stehen.
    """
    global _pfad
    if isinstance(sys.stdout, _Abzweig):
        return _pfad
    try:
        ordner = Path(verzeichnis) / "logs"
        ordner.mkdir(parents=True, exist_ok=True)
        _pfad = ordner / "phobos.log"
        sys.stdout = _Abzweig(sys.stdout, _pfad)
        sys.stderr = _Abzweig(sys.stderr, _pfad)
        return _pfad
    except Exception:
        # Ohne eigenes Protokoll laeuft der Bot wie bisher weiter.
        _pfad = None
        return None


def groesse() -> int:
    """Wieviel Platz das Protokoll samt alter Staende belegt, in Bytes."""
    if not _pfad:
        return 0
    gesamt = 0
    for kandidat in _alle_dateien():
        try:
            gesamt += kandidat.stat().st_size
        except OSError:
            pass
    return gesamt


def _alle_dateien() -> list:
    if not _pfad:
        return []
    dateien = [_pfad]
    for nummer in range(1, MAX_DATEIEN + 1):
        dateien.append(_pfad.with_suffix(_pfad.suffix + f".{nummer}"))
    return dateien


def zeilen(anzahl: int = 300) -> list:
    """Die letzten Zeilen, neueste zuerst, als {stufe, zeit, text}.

    Liest nur das Ende der Datei, nicht ihren Anfang: bei fuenf Megabyte waere das sonst
    jedes Mal die ganze Datei, nur um dreihundert Zeilen zu zeigen.
    """
    if not _pfad or not _pfad.exists():
        return []
    try:
        # Grosszuegig geschaetzt 400 Byte je Zeile, mindestens 64 KB.
        brocken = max(64 * 1024, anzahl * 400)
        with open(_pfad, "rb") as f:
            f.seek(0, os.SEEK_END)
            ende = f.tell()
            f.seek(max(0, ende - brocken))
            roh = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    # Die erste Zeile kann abgeschnitten sein, wenn mitten hineingesprungen wurde.
    teile = roh.splitlines()
    if len(teile) > 1 and brocken < ende:
        teile = teile[1:]
    ergebnis = []
    for text in reversed(teile):
        if not text.strip():
            continue
        ergebnis.append({"stufe": stufe(text), "text": text})
        if len(ergebnis) >= anzahl:
            break
    return ergebnis


# "0 Fehler", "keine Fehler", "0 errors" - eine Zaehlung, die sagt, dass nichts war.
# Ohne diese Ausnahme faerbte ausgerechnet die Erfolgsmeldung des Reihendurchlaufs
# ("71 geprueft, 0 geaendert, 0 Fehler, 0.2s") rot, weil das Wort darin vorkommt.
_KEINE_FEHLER = re.compile(r"\b(0|keine?|no)\s+(fehler|errors?|warnungen|warnings?)\b",
                           re.IGNORECASE)


def stufe(text: str) -> str:
    """fehler / warnung / info - geraten am Wortlaut, mehr gibt eine print()-Zeile nicht her.

    Absichtlich grob: es geht darum, Fehler in einer langen Liste zu finden, nicht darum,
    jede Zeile richtig einzuordnen. Was durchrutscht, steht als "info" trotzdem da.
    """
    # Zuerst die Zaehlungen herausnehmen, dann erst nach den Woertern suchen - sonst
    # entscheidet das blosse Vorkommen des Wortes, nicht seine Bedeutung.
    klein = _KEINE_FEHLER.sub(" ", text).lower()
    for wort in ("fehler", "error", "exception", "traceback", "failed",
                 "fehlgeschlagen", "critical", "nicht erreichbar"):
        if wort in klein:
            return "fehler"
    for wort in ("warn", "achtung", "veraltet", "deprecated", "konnte nicht",
                 "could not", "uebersprungen", "übersprungen"):
        if wort in klein:
            return "warnung"
    return "info"


def leeren() -> bool:
    """Protokoll und alte Staende wegwerfen. True, wenn danach nichts mehr da ist.

    Die aktive Datei wird auf null gesetzt statt geloescht: der Abzweig haelt sie beim
    Schreiben zwar jedes Mal neu geoeffnet, aber ein geloeschtes Verzeichnis darunter
    waere ein Fall mehr, den niemand braucht.
    """
    if not _pfad:
        return False
    erfolg = True
    with _sperre:
        for kandidat in _alle_dateien():
            try:
                if kandidat == _pfad:
                    if kandidat.exists():
                        with open(kandidat, "w", encoding="utf-8"):
                            pass
                elif kandidat.exists():
                    kandidat.unlink()
            except OSError:
                erfolg = False
    # Ein Abzweig, der nach einem Schreibfehler stumm geworden ist, darf nach dem
    # Aufraeumen wieder schreiben - oft war die volle Platte genau der Grund.
    for strom in (sys.stdout, sys.stderr):
        if isinstance(strom, _Abzweig):
            strom._stumm = False
    return erfolg


def platz(pfad=None) -> tuple:
    """(frei, gesamt) in Bytes fuer die Platte, auf der das Protokoll liegt."""
    for kandidat in (pfad, _pfad.parent if _pfad else None, "/"):
        if not kandidat:
            continue
        try:
            nutzung = shutil.disk_usage(str(kandidat))
            return nutzung.free, nutzung.total
        except Exception:
            continue
    return None, None


def menschlich(zahl) -> str:
    """Bytes als Zahl, die man vorlesen kann."""
    if zahl is None:
        return "?"
    zahl = float(zahl)
    for einheit in ("B", "KB", "MB", "GB", "TB"):
        if zahl < 1024 or einheit == "TB":
            return f"{zahl:.0f} {einheit}" if einheit == "B" else f"{zahl:.1f} {einheit}"
        zahl /= 1024.0


def stand() -> dict:
    """Alles, was die Seite braucht, in einem Aufruf."""
    frei, gesamt = platz()
    belegt = (gesamt - frei) if (frei is not None and gesamt) else None
    return {
        "pfad": str(_pfad) if _pfad else "",
        "groesse": groesse(),
        "groesse_text": menschlich(groesse()),
        "deckel_text": menschlich(MAX_BYTES * (MAX_DATEIEN + 1)),
        "frei": frei,
        "frei_text": menschlich(frei),
        "gesamt_text": menschlich(gesamt),
        "belegt_text": menschlich(belegt),
        "prozent": round(belegt / gesamt * 100) if (belegt and gesamt) else 0,
        "stand_zeit": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
    }
