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
1.3.13 — Events-Tab: Info-Button mit Beispielen (ℹ), komplett zweisprachig (de/en) über i18n.py

1.3.12 — Events-Tab: Typ "Ohne Kanal" ist jetzt Standard, Ort optional (fällt sonst auf Servername zurück)

1.3.11 — Native Discord-Events (Server-Events-Tab) im Dashboard erstellen/auflisten/löschen (Tab "🗓️ Events")

Hinweis: nur einmalige Events, keine wiederkehrenden Serien — Discords `recurrence_rule`
ist im gepinnten discord.py 2.3.2 noch nicht unterstützt (Rapptz/discord.py PR #9685 offen).

1.3.10 — Geplante Nachrichten sind jetzt bearbeitbar (nicht mehr nur löschen+neu anlegen)
