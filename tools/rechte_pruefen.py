#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Haelt fest, dass der Bot im Container nicht als root laeuft.

Bis v1.19.28 lief er als uid 0 - nicht als Entscheidung, sondern weil das Dockerfile nie
eine Zeile dazu hatte und Docker ohne Angabe root nimmt. Genau so kaeme es auch zurueck:
niemand muesste "wieder als root" schreiben, es reicht, dass jemand den ENTRYPOINT
austauscht, das Startskript umbenennt oder in der compose-Datei aufraeumt. Nichts davon
sieht beim Lesen des Diffs nach einer Rechtefrage aus.

Dieses Skript laeuft deshalb vor jedem Commit (.git/hooks/pre-commit) und schlaegt an,
bevor so etwas weggeschickt wird. Es prueft nur den Quelltext - ob es im Betrieb
tatsaechlich klappt, prueft test_rechte.sh am echten Image.

Einzeln aufrufbar:   python3 tools/rechte_pruefen.py
"""
import re
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
fehler: list[str] = []


def lies(pfad: str) -> str:
    datei = WURZEL / pfad
    if not datei.exists():
        fehler.append(f"{pfad} fehlt - ohne diese Datei laeuft der Bot wieder als root.")
        return ""
    return datei.read_text(encoding="utf-8")


dockerfile = lies("app/Dockerfile")
start = lies("app/entrypoint.sh")
compose = lies("docker-compose.yml")

# ── Das Dockerfile muss das Startskript aufrufen ─────────────────────────────
if dockerfile:
    if "entrypoint.sh" not in dockerfile:
        fehler.append(
            "app/Dockerfile ruft app/entrypoint.sh nicht mehr auf. Ohne das Skript "
            "startet der Container wieder direkt als root.")
    if re.search(r"^\s*CMD\s+\[\s*\"python\"", dockerfile, re.M):
        fehler.append(
            "app/Dockerfile startet python wieder direkt per CMD. Der Start gehoert "
            "ueber ENTRYPOINT in app/entrypoint.sh, sonst faellt die Rechteabgabe weg.")
    if re.search(r"^\s*USER\s+root", dockerfile, re.M):
        fehler.append("app/Dockerfile setzt USER root.")
    if "useradd" not in dockerfile:
        fehler.append(
            "app/Dockerfile legt keinen Benutzer mehr an - das Startskript faellt dann "
            "auf root zurueck, weil es niemanden hat, an den es uebergeben koennte.")
    if "--system --add safe.directory" not in dockerfile:
        fehler.append(
            "app/Dockerfile setzt safe.directory nicht mehr systemweit (--system). Mit "
            "--global gilt es nur fuer root, und das Update ueber das Dashboard stirbt "
            "als anderer Benutzer an 'dubious ownership'.")

# ── Das Startskript muss die Rechte auch wirklich abgeben ────────────────────
if start:
    if "setpriv" not in start:
        fehler.append("app/entrypoint.sh gibt die Rechte nicht mehr per setpriv ab.")
    if "--reuid" not in start or "--regid" not in start:
        fehler.append("app/entrypoint.sh wechselt weder Benutzer- noch Gruppennummer.")
    # Der letzte Befehl des Skripts entscheidet, was am Ende laeuft.
    zeilen = [z.strip() for z in start.splitlines() if z.strip() and not z.strip().startswith("#")]
    if not zeilen or not zeilen[-1].startswith("exec setpriv"):
        fehler.append(
            "app/entrypoint.sh endet nicht mit 'exec setpriv ... python main.py'. Was "
            "dort zuletzt steht, ist der Prozess, der laeuft - und der soll nicht root sein.")
    # Die Rueckfalle duerfen bleiben, aber nicht zur Regel werden: wer PHOBOS_ROOT
    # fest einbaut statt es abzufragen, hat die Pruefung ausgehebelt.
    if re.search(r'^\s*PHOBOS_ROOT\s*=\s*["\']?1', start, re.M):
        fehler.append("app/entrypoint.sh setzt PHOBOS_ROOT selbst auf 1.")

# ── Die compose-Datei darf die Rechte nicht wieder aufmachen ─────────────────
if compose:
    if "docker.sock" in compose and not re.search(r"^\s*#.*docker\.sock", compose, re.M):
        fehler.append(
            "docker-compose.yml haengt wieder /var/run/docker.sock ein. Das ist faktisch "
            "root auf dem Wirt und hebt den ganzen Rest auf.")
    if "cap_drop" not in compose:
        fehler.append("docker-compose.yml gibt die Faehigkeiten nicht mehr ab (cap_drop).")
    if "no-new-privileges" not in compose:
        fehler.append("docker-compose.yml setzt no-new-privileges nicht mehr.")
    if re.search(r'^\s*user:\s*["\']?0', compose, re.M):
        fehler.append("docker-compose.yml setzt user auf 0 (root).")
    if re.search(r'^\s*(privileged|PHOBOS_ROOT)\s*[:=]\s*["\']?(true|1)', compose, re.M):
        fehler.append("docker-compose.yml schaltet privileged oder PHOBOS_ROOT ein.")

if fehler:
    print("Der Bot wuerde wieder als root laufen:")
    for e in fehler:
        print(f"  - {e}")
    print()
    print("Wenn das Absicht ist, steht der Weg dafuer im Betrieb offen: PHOBOS_ROOT=1 in")
    print("der Umgebung einer einzelnen Installation. Im Repo gehoert es nicht.")
    sys.exit(1)

print("Rechte in Ordnung: der Bot gibt sie beim Start ab.")
