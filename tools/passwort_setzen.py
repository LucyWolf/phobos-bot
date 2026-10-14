#!/usr/bin/env python3
"""Notausgang: Passwort eines Dashboard-Kontos direkt in der Datenbank setzen.

Fuer den Fall, in dem sonst kein Weg zurueck ins Konto fuehrt - Passwort vergessen, kein
SMTP eingerichtet (also keine Mail zum Zuruecksetzen), kein zweiter Admin, oder das
Telefon mit der 2FA-App ist weg. Das Werkzeug laeuft auf dem Server, nicht im Netz, und
macht damit nichts auf, was nicht schon offen waere: wer eine Shell auf dieser Maschine
hat, kann die Datenbank ohnehin lesen und schreiben.

Aufruf (im Container, in dem auch der Bot laeuft):

    docker exec -it phobos python3 /w/tools/passwort_setzen.py --liste
    docker exec -it phobos python3 /w/tools/passwort_setzen.py --benutzer lucy
    docker exec -it phobos python3 /w/tools/passwort_setzen.py --benutzer lucy --2fa-aus

Das Passwort wird abgefragt, nicht als Argument uebergeben - sonst stuende es in der
Shell-Geschichte und in der Prozessliste.
"""
import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path

try:
    import bcrypt
except ImportError:
    sys.exit("bcrypt fehlt - das Werkzeug gehoert in denselben Container wie der Bot.")

STANDARD_DB = Path(os.environ.get("PHOBOS_DB_PATH", "/app/data/phobos.db"))


def spalten(db: sqlite3.Connection, tabelle: str) -> set:
    return {z[1] for z in db.execute(f"PRAGMA table_info({tabelle})")}


def liste(db: sqlite3.Connection) -> None:
    hat = spalten(db, "users")
    felder = ["id", "username", "role"]
    for f in ("email", "totp_enabled", "active"):
        if f in hat:
            felder.append(f)
    zeilen = db.execute(f"SELECT {','.join(felder)} FROM users ORDER BY id").fetchall()
    if not zeilen:
        print("Keine Konten in dieser Datenbank.")
        return
    breite = [max(len(str(f)), *(len(str(z[i])) for z in zeilen)) for i, f in enumerate(felder)]
    print("  ".join(f.ljust(breite[i]) for i, f in enumerate(felder)))
    print("  ".join("-" * b for b in breite))
    for z in zeilen:
        print("  ".join(str(z[i]).ljust(breite[i]) for i in range(len(felder))))


def main() -> int:
    p = argparse.ArgumentParser(
        description="Passwort eines Dashboard-Kontos setzen, wenn kein anderer Weg mehr geht.")
    p.add_argument("--benutzer", "-b", help="Benutzername oder Konto-ID")
    p.add_argument("--liste", "-l", action="store_true", help="Konten anzeigen und aufhoeren")
    p.add_argument("--2fa-aus", dest="zfa_aus", action="store_true",
                   help="Zwei-Faktor-Anmeldung abschalten und Backup-Codes verwerfen - "
                        "noetig, wenn auch das Telefon weg ist")
    p.add_argument("--db", default=str(STANDARD_DB), help=f"Datenbankdatei (Standard: {STANDARD_DB})")
    a = p.parse_args()

    pfad = Path(a.db)
    if not pfad.exists():
        return f"Datenbank nicht gefunden: {pfad}\nMit --db den richtigen Pfad angeben."

    db = sqlite3.connect(pfad)
    db.row_factory = sqlite3.Row
    try:
        if a.liste or not a.benutzer:
            liste(db)
            if not a.benutzer:
                print("\nMit --benutzer <name> ein Konto auswaehlen.")
            return 0

        zeile = db.execute(
            "SELECT * FROM users WHERE username=? OR CAST(id AS TEXT)=?",
            (a.benutzer, a.benutzer),
        ).fetchone()
        if not zeile:
            return f"Kein Konto namens {a.benutzer!r}. Mit --liste nachsehen."

        hat = spalten(db, "users")
        zfa = bool(zeile["totp_enabled"]) if "totp_enabled" in hat else False
        print(f"Konto: {zeile['username']} (ID {zeile['id']}, {zeile['role']})")
        if zfa:
            print("Zwei-Faktor-Anmeldung: AN"
                  + ("  - wird abgeschaltet" if a.zfa_aus else
                     "  - bleibt an; ohne die App kommst du trotzdem nicht rein (--2fa-aus)"))

        if sys.stdin.isatty():
            neu = getpass.getpass("Neues Passwort: ")
            if neu != getpass.getpass("Noch einmal:    "):
                return "Die beiden Eingaben waren nicht gleich - nichts geaendert."
        else:
            # Fuer Skripte: Passwort auf der Standardeingabe.
            neu = sys.stdin.readline().rstrip("\n")
        if len(neu) < 6:
            return "Mindestens 6 Zeichen - nichts geaendert."

        db.execute("UPDATE users SET password_hash=? WHERE id=?",
                   (bcrypt.hashpw(neu.encode(), bcrypt.gensalt()).decode(), zeile["id"]))

        if a.zfa_aus and zfa:
            felder = ["totp_enabled=0", "totp_secret=NULL"]
            for f, wert in (("totp_fail_count", "0"), ("totp_locked_until", "NULL")):
                if f in hat:
                    felder.append(f"{f}={wert}")
            db.execute(f"UPDATE users SET {','.join(felder)} WHERE id=?", (zeile["id"],))
            try:
                db.execute("DELETE FROM totp_backup_codes WHERE user_id=?", (zeile["id"],))
            except sqlite3.OperationalError:
                pass
            print("Zwei-Faktor-Anmeldung abgeschaltet, Backup-Codes verworfen.")

        # Offene Anmeldungen beenden: wer das Passwort vergisst, weiss nicht, wer sonst noch
        # eingeloggt ist. Dasselbe tut das Dashboard bei jedem Passwortwechsel.
        try:
            weg = db.execute("DELETE FROM user_sessions WHERE user_id=?", (zeile["id"],)).rowcount
            if weg > 0:
                print(f"{weg} offene Anmeldung(en) beendet.")
        except sqlite3.OperationalError:
            pass

        # Ein Sperrzaehler aus dem Reset-Weg darf nicht stehen bleiben.
        for f in ("reset_fail_count", "reset_locked_until"):
            if f in hat:
                db.execute(f"UPDATE users SET {f}={'0' if f.endswith('count') else 'NULL'} "
                           "WHERE id=?", (zeile["id"],))

        db.commit()
        print(f"Passwort gesetzt. Anmelden als {zeile['username']}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
