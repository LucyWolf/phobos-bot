#!/usr/bin/env python3
"""Stimmen APK, version.txt und Release-Notiz ueberein?

Beim Veroeffentlichen einer neuen APK gibt es drei Stellen, die dieselbe Version nennen
muessen: die APK selbst (versionName), die version.txt daneben - gegen die die
Android-Fassung prueft - und die Release-Notiz, die Menschen lesen. Laufen sie
auseinander, meldet die Update-Seite etwas, das die APK nicht liefert, oder die Notiz
beschreibt einen Stand, der laengst ersetzt ist. Beides ist schon passiert.

Aufruf (ohne Argumente prueft es das veroeffentlichte Release):
    python3 tools/apk_pruefen.py
    python3 tools/apk_pruefen.py android/app/build/outputs/apk/debug/app-debug.apk
"""
import json
import re
import subprocess
import sys
import zipfile

RELEASE = "android-debug"
REPO = "LucyWolf/phobos-bot"


def apk_version(pfad: str) -> str:
    """Die Version aus der APK - aus der mitgepackten app/VERSION, ohne aapt."""
    with zipfile.ZipFile(pfad) as apk:
        with zipfile.ZipFile(__import__("io").BytesIO(apk.read("assets/chaquopy/app.imy"))) as app:
            return app.read("VERSION").decode().strip()


def gh(*args) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def main() -> int:
    fehler = []
    if len(sys.argv) > 1:
        lokal = apk_version(sys.argv[1])
        print(f"APK (lokal):      {lokal}")
    else:
        lokal = None

    roh = gh("api", f"repos/{REPO}/releases/tags/{RELEASE}")
    release = json.loads(roh)
    namen = {a["name"] for a in release.get("assets", [])}
    print(f"Assets:           {', '.join(sorted(namen)) or '-'}")
    if "version.txt" not in namen:
        fehler.append("version.txt fehlt im Release - die Android-Fassung prueft dagegen")

    aus_notiz = re.search(r"Aktueller Stand:\s*\**\s*v?([\d.]+)", release.get("body") or "")
    notiz = aus_notiz.group(1) if aus_notiz else None
    print(f"Notiz nennt:      {notiz or '(keine Angabe gefunden)'}")
    if not notiz:
        fehler.append("die Release-Notiz nennt keinen Stand ('Aktueller Stand: vX.Y.Z')")

    txt = None
    if "version.txt" in namen:
        url = f"https://github.com/{REPO}/releases/download/{RELEASE}/version.txt"
        txt = subprocess.run(["curl", "-sL", url], capture_output=True, text=True).stdout.strip()
        print(f"version.txt:      {txt}")

    werte = {"Notiz": notiz, "version.txt": txt}
    if lokal:
        werte["APK"] = lokal
    verschieden = {v for v in werte.values() if v}
    if len(verschieden) > 1:
        fehler.append("die Versionen gehen auseinander: "
                      + ", ".join(f"{k}={v}" for k, v in werte.items() if v))

    print()
    if fehler:
        for f in fehler:
            print(f"  FEHLER: {f}")
        return 1
    print("  Alles einig.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
