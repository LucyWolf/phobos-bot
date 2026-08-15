# Phobos Bot — Claude Code Kontext

## Projekt-Übersicht
Discord-Bot mit Web-Dashboard. Python 3.11, discord.py 2.3.2, FastAPI + Uvicorn, Jinja2, aiosqlite/SQLite.

## Wichtige Regeln
- **`app/VERSION` bei JEDEM Commit erhöhen** — User hat mehrfach darauf hingewiesen, niemals vergessen
- Deploy: `git pull && docker compose restart` auf Linux-Server (root@Phobos-Bot)
- Commit immer mit `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

## Pfade
- Server: `/root/projekte/discord-bot`
- Datenbank: `/app/data/phobos.db` (im Container)
- VERSION: `app/VERSION`

## Docker
```yaml
services:
  bot:
    build: ./app
    container_name: discord-bot
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./app:/app
      - ./data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/repo          # für git-basierte Updates
    environment:
      - TZ=Europe/Berlin
      - PYTHONUNBUFFERED=1
```

## Datenbank-Helfer (`database.py`)
```python
db_rows(query, params)        # → list[dict]
db_one(query, params)         # → dict | None
db_exec(query, params)        # → None
db_exec_rowcount(query, params) # → int (betroffene Zeilen)
db_insert(query, params)      # → int (lastrowid)
get_guild_config(guild_id, key)
set_guild_config(guild_id, key, value)
get_config(key) / set_config(key, value)
```

## Auth-Helfer (`main.py`)
```python
auth_redirect(request)              # → redirect wenn nicht eingeloggt
admin_redirect(request)             # → redirect wenn kein Admin
perm_redirect(request, "perm_xyz")  # → redirect wenn Berechtigung fehlt
has_perm(request, "perm_xyz")       # → bool
_guild_access(request, guild_id)    # → bool
bot._bot_for_guild(guild_id)        # → Bot-Instanz für diese Guild
```

## Berechtigungen (perm_* Spalten in roles-Tabelle)
`perm_settings`, `perm_tokens`, `perm_server`, `perm_moderation`, `perm_notifications`

## Twitch API
- Client Credentials Flow, Token gecacht pro api_id
- Tabelle `twitch_apis`: owner_id, name, client_id, client_secret
- Tabelle `twitch_api_access`: api_id, user_id (Freigabe für andere User)

## XP / Leveling
```python
def xp_for_level(level: int) -> int:
    return 5 * (level ** 2) + 50 * level + 100

def level_from_xp(xp: int) -> int:
    # iterativ, kumulativ
```
XP wird kumulativ in DB gespeichert. Für Level-relativen Fortschritt:
```python
xp_in_level = row["xp"] - sum(xp_for_level(i) for i in range(row["level"]))
```

## Update-System (im Container)
```python
git -C /repo fetch origin main
git -C /repo reset --hard origin/main
docker-compose restart
```

## Cogs (app/cogs/)
- `leveling.py` — XP, /rank, /leaderboard, /setxp
- `moderation.py` — Warn, Kick, Ban, Timeout
- `tickets.py` — Ticket-Panels mit Buttons
- `giveaways.py` — Giveaway start/end/reroll (atomisch via db_exec_rowcount)
- `scheduler.py` — Geplante Nachrichten (sent=1 nur bei Erfolg)
- `notifications.py` — Twitch Live-Benachrichtigungen
- `freestuff.py` — Epic/Steam/GOG kostenlose Spiele
- `birthday.py` — Geburtstags-Glückwünsche (INSERT-first Race Condition Fix)
- `automod.py` — Spam/Link/Wort-Filter (delete in try/except)
- `reaction_roles.py`, `custom_commands.py`, `temp_voice.py`, `logging_cog.py`

## Bekannte fixes (v1.3.9, alle committed)
Sechste Review-Runde (v1.3.9) — 7 weitere Bugs gefixt:
- `/bot/design` (POST) änderte global Namen/Avatar des Bots ohne `perm_settings`-Check
- Token rename/toggle/delete prüften `perm_tokens` nicht (nur Zuweisung)
- Twitch-Notifications fielen ohne explizite Auswahl auf eine beliebige fremde API zurück
- `!`-alleine als Nachricht crashte custom_commands (IndexError)
- Reaction-Role-DB-Eintrag wurde vor der Discord-Reaction angelegt (verwaiste Mappings bei ungültigem Emoji)
- Ticket-Panel-Button: Doppelklick/retried Interaction konnte zwei Ticket-Channels erzeugen (In-Flight-Guard ergänzt)
- Scheduler: nicht-numerische channel_id (z.B. aus Backup-Restore) konnte den `@tasks.loop` dauerhaft stoppen

Über 5 vorherige Review-Runden wurden 30 Bugs gefixt (v1.3.4–1.3.8):
- API-Endpunkte abgesichert (Auth/Admin)
- Backup-Datenlecks geschlossen
- Token-Management-Berechtigungen
- Giveaway Cross-Guild-Zugriff
- Race Conditions (Giveaway, Geburtstag)
- Automod try/except
- FreeStuff/Scheduler sent-Flag-Logik
- perm_server funktioniert jetzt korrekt
- Avatar-Endpoint gesichert
- Alle int()-Casts abgesichert
- automod: try/except um kick/ban/timeout
- giveaways: __import__-Hack durch db_insert ersetzt
- roles_page URL-Bug (? statt & als zweiter Parameter)
- server_config/server_config_save: auth_redirect hinzugefügt

## Aktuelle VERSION
1.4.0 — Zwei-Faktor-Authentifizierung (TOTP, Google-Authenticator-kompatibel) für den Dashboard-
Login. Neu: app/totp.py (Secret/QR/Verify/Backup-Codes), users.totp_secret/totp_enabled,
totp_backup_codes-Tabelle, /profile/2fa/setup (+Bestätigung, zeigt 8 Backup-Codes einmalig),
/profile/2fa/disable (Passwort-Pflicht), /login/2fa als zweiter Login-Schritt nach Passwort
(Session-Key pending_2fa_user_id, komplett getrennt von echtem user_id — kein Zugriff ohne
bestandene 2FA). Einfache Brute-Force-Bremse: 5 Fehlversuche pro Pending-Session, danach zurück
zu /login. Neue Deps: pyotp, qrcode (nutzt vorhandenes Pillow).

1.3.25 — Events "Ende festlegen"-Checkbox (Erstellen + Bearbeiten): required-Attribut wurde beim
Checkbox-Toggle nie gesetzt, nur disabled/value. Checkbox anhaken machte das Datumsfeld sichtbar,
aber nicht zur Browser-Pflicht — leer lassen + absenden hätte das Ende stillschweigend NICHT
gesetzt bzw. (im Bearbeiten-Formular, wenn Datum manuell geleert ohne Checkbox anzufassen) ein
bestehendes Enddatum unbemerkt gelöscht. required wird jetzt in beiden Toggle-Funktionen synchron
zum checked-Status gesetzt, im Bearbeiten-Formular zusätzlich beim initialen Rendern.

1.3.24 — Events-Bereich weitere Bug-Review, zwei echte Fixes:
(1) Erinnerungen (inkl. Start-/Ende-Benachrichtigung) wurden beim Bearbeiten eines Events NICHT
mitverschoben, wenn Start/Ende geändert wurden — feuerten danach zum falschen, alten Zeitpunkt.
events_edit rekonstruiert jetzt pro Erinnerung den ursprünglichen Offset (alte Startzeit − alter
send_at) und wendet ihn auf die neue Startzeit an; die Ende-Benachrichtigung wird per fixem
Nachrichtentext (_EVENT_END_MESSAGE-Konstante) erkannt und exakt auf die neue Endzeit gelegt bzw.
gelöscht, falls kein Ende mehr gesetzt ist.
(2) Bearbeiten-Formular bei Voice-Events: fehlte der zugehörige Kanal (z.B. gelöscht), wählte der
Browser stillschweigend den ersten Kanal der Liste vor — beim Speichern wäre das Event unbemerkt
auf einen falschen Kanal umgehängt worden. Jetzt explizite Platzhalter-Option, erzwingt bewusste
Auswahl bzw. liefert "Kanal nicht gefunden"-Fehler statt stiller Fehlzuweisung.

1.3.23 — Info-Box-Texte im Events-Tab aktualisiert: "Ende: leer lassen" ersetzt durch Hinweis auf
die neue "Ende festlegen"-Checkbox (v1.3.21), Erinnerungs-Beispiel korrigiert (Start-Meldung ist
seit v1.3.18 automatisch, nicht mehr manuell per "0 Min. vorher"-Reminder nachzustellen). Deutsch
und Englisch synchron (127/127 Keys geprüft).

1.3.22 — Neue Checkbox "🏁 Auch bei Event-Ende benachrichtigen" im Events-Erstellen-Formular:
postet zusätzlich zur Start-Meldung eine weitere Nachricht (über denselben scheduled_messages/
event_id-Mechanismus) in den Ankündigungskanal, sobald das Event endet. Braucht ein gesetztes
Enddatum + Ankündigungskanal, sonst Fehlermeldung. Nur im Erstellen-Formular, nicht nachträglich
im Bearbeiten-Panel änderbar.

1.3.21 — "Ende"-Feld bei Voice-Kanal-Events (Erstellen + Bearbeiten) jetzt mit Checkbox
"Ende festlegen" statt einem leeren, unklaren Datumsfeld. Bugfix dabei: beim Bearbeiten wurde
end_time bisher nur gesetzt, nie explizit auf None geleert — Checkbox abwählen entfernte das
Enddatum bei Discord bisher nicht wirklich.

1.3.20 — Events-Bereich Bug-Review: (1) Erinnerungs-Platzhaltertext mit Apostroph brach das
komplette <script>-Tag im Events-Tab (alle Buttons kaputt) — neue Jinja-Filter `js` (HTML-Attribut-
Kontext, z.B. onsubmit) und `jsraw` (<script>-Element-Kontext) lösen das JSON-sicher, unabhängig
von Jinja-Autoescape. (2) Gleiches Muster fixiert bei Event-Namen mit Anführungszeichen im
Lösch-Confirm-Dialog. (3) Löschen eines Events räumt jetzt auch dessen noch nicht gefeuerte
Erinnerungen in scheduled_messages auf (vorher: verwaiste Erinnerungen feuerten trotzdem noch).
Info-Box erwähnt jetzt auch die Bearbeiten-Einschränkung (nur solange "Geplant").

1.3.19 — Bugfix: Bearbeiten-Button bei Events tat nichts, weil die Discord-Snowflake-ID als rohe
JS-Zahl im onclick Präzision verlor (>2^53) und dadurch nicht mehr zur gerenderten Zeilen-ID
passte — jetzt als String übergeben. Zusätzlich: Beschreibung + Erinnerungs-Zeitpunkte werden
direkt in der Events-Tabellenzeile angezeigt statt nur versteckt im Bearbeiten-Panel.

1.3.18 — Bugfix: Ankündigung postete bisher sofort bei Event-Erstellung statt beim Event-Start.
Läuft jetzt über denselben Mechanismus wie die Erinnerungen (Offset 0 = bei Start), scheduler.py
baut das Embed live beim Versenden aus dem aktuellen Event-Zustand statt es vorab zu bauen.

1.3.17 — Events bearbeitbar (nur solange Status "scheduled", danach nur noch löschbar) via
POST /servers/{id}/events/edit/{event_id}. scheduled_messages hat neue Spalte event_id, um
Erinnerungen ihrem Event zuzuordnen — im Bearbeiten-Panel wird angezeigt, wann die verknüpften
Erinnerungen feuern. Neue Jinja-Filter: dtlocal (für datetime-local value=).

1.3.16 — Events: mehrere Erinnerungen (X Min. vorher + eigene Nachricht, 0 = bei Start) —
werden als Einträge in scheduled_messages angelegt, laufen über den bestehenden Scheduler-Cog
und sind im Tab "Geplant" bearbeitbar. Erfordert einen gesetzten Ankündigungskanal.

1.3.15 — Events-Info-Karte (ℹ) um Beispiel-Block zur Ankündigungsfunktion ergänzt

1.3.14 — Events-Tab: optionaler Ankündigungskanal — Bot postet Embed (Name/Start/Ende/Ort, Link zum Event) in einen Textkanal bei Event-Erstellung

1.3.13 — Events-Tab: Info-Button mit Beispielen (ℹ), komplett zweisprachig (de/en) über i18n.py

1.3.12 — Events-Tab: Typ "Ohne Kanal" ist jetzt Standard, Ort optional (fällt sonst auf Servername zurück)

1.3.11 — Native Discord-Events (Server-Events-Tab) im Dashboard erstellen/auflisten/löschen (Tab "🗓️ Events")

Hinweis: nur einmalige Events, keine wiederkehrenden Serien — Discords `recurrence_rule`
ist im gepinnten discord.py 2.3.2 noch nicht unterstützt (Rapptz/discord.py PR #9685 offen).

1.3.10 — Geplante Nachrichten sind jetzt bearbeitbar (nicht mehr nur löschen+neu anlegen)
