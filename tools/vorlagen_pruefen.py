#!/usr/bin/env python3
"""Prueft jede Vorlage auf Klammern, die nicht aufgehen.

Gebaut nach v1.17.36: ein einziges ueberzaehliges </div> in der Karte "Discord-Rolle ->
VRChat-Gruppenrolle" hat den VRC-Link-Reiter mittendrin geschlossen. Alles danach - die
Links-Tabelle, die Instanz-Meldungen, der Debug-Bericht - stand von da an ausserhalb des
Reiters und damit auf JEDEM Tab des Dashboards. Sieben Versionen lang, weil niemand
nachgezaehlt hat.

Laeuft ohne Abhaengigkeiten und in Sekundenbruchteilen, damit ein Git-Hook ihn vor jedem
Commit aufrufen kann:

    ln -s ../../tools/vorlagen_pruefen.py .git/hooks/pre-commit

Rueckgabewert 0 = in Ordnung, 1 = mindestens eine Vorlage ist schief.
"""
import os
import re
import sys

# Tags, bei denen ein fehlendes Endtag das Seitengeruest zerlegt. Bei p, li, td und
# Konsorten ist ein fehlendes Endtag erlaubtes HTML - dort zaehlt nur, dass nicht MEHR
# geschlossen als geoeffnet wird.
STRENG = ("div", "form", "select", "textarea", "script", "table")
LOCKER = ("span", "label", "button", "ul", "ol", "li", "p", "tr", "td", "th",
          "tbody", "thead", "a", "h1", "h2", "h3", "h4")

WURZEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "templates")


def pruefe(pfad: str) -> list:
    """Gibt die Beanstandungen einer Vorlage zurueck, leer heisst in Ordnung."""
    with open(pfad, encoding="utf-8") as f:
        text = f.read()
    zeilen = text.split("\n")
    raus = []

    for tag in STRENG + LOCKER:
        auf = len(re.findall(rf"<{tag}\b", text))
        zu = len(re.findall(rf"</{tag}>", text))
        if zu > auf:
            raus.append(f"<{tag}>: {zu - auf} mal zu viel geschlossen")
        elif tag in STRENG and auf > zu:
            raus.append(f"<{tag}>: {auf - zu} mal nicht geschlossen")

    # Und jeder Reiter fuer sich: ein Reiter, dessen Bilanz nicht aufgeht, schiebt seinen
    # Inhalt in den naechsten oder aus dem Geruest heraus.
    grenzen = [n for n, z in enumerate(zeilen) if 'class="tab-pane"' in z]
    if grenzen:
        grenzen.append(len(zeilen))
        for i in range(len(grenzen) - 1):
            a, b = grenzen[i], grenzen[i + 1]
            name = re.search(r'id="([^"]+)"', zeilen[a])
            name = name.group(1) if name else f"Zeile {a + 1}"
            block = "\n".join(zeilen[a:b])
            d = len(re.findall(r"<div\b", block)) - len(re.findall(r"</div>", block))
            if d:
                raus.append(f"Reiter {name}: Bilanz {d:+d} <div>")
    return raus


def main() -> int:
    schief = 0
    for datei in sorted(os.listdir(WURZEL)):
        if not datei.endswith(".html"):
            continue
        for meldung in pruefe(os.path.join(WURZEL, datei)):
            print(f"{datei}: {meldung}")
            schief += 1
    if schief:
        print(f"\n{schief} Beanstandung(en) - so darf das nicht committet werden.")
        return 1
    print("Vorlagen in Ordnung.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
