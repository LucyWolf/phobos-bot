# 🛡️ Phobos Bot

Ein selbst-hostbarer Discord-Bot – ähnlich wie MEE6 – mit Web-Dashboard. Open Source, kostenlos, für immer.

## Features

| Feature | Commands |
|---|---|
| **Moderation** | `/kick` `/ban` `/unban` `/timeout` `/warn` `/warnings` `/clearwarns` `/clear` |
| **Leveling / XP** | `/rank` `/leaderboard` `/setxp` |
| **Willkommen** | Automatische Beitrittsnachrichten, Verlassensnachrichten, Auto-Rolle |
| **Auto-Moderation** | Spam-Schutz, Link-Filter, Wort-Filter |
| **Reaction Roles** | `/reactionrole-add` `/reactionrole-remove` `/reactionrole-list` |
| **Event-Logging** | Beitritt/Verlassen, Nachrichten, Bans, Rollen |
| **Eigene Commands** | `/addcommand` `/delcommand` `/commands` (Präfix `!`) |
| **Tickets** | `/ticket-panel` – Button-basiertes Ticket-System |
| **Giveaways** | `/giveaway-start` `/giveaway-end` `/giveaway-reroll` |

## Web-Dashboard

- Login mit Benutzername + Passwort
- Dashboard mit Moderations-Statistiken und allen verbundenen Servern
- Einstellungen: Discord-Token, Benutzer verwalten (Admin/Moderator)
- Pro Server: alle Features konfigurieren (Kanäle, Rollen, Auto-Mod, etc.)
- Standardzugang beim ersten Start: `admin` / `admin`

## Installation

### Voraussetzungen
- Docker & Docker Compose
- Nginx Proxy Manager (empfohlen) oder anderer Reverse-Proxy

```bash
git clone https://github.com/LucyWolf/phobos-bot.git
cd phobos-bot
docker compose up -d --build
```

Das Dashboard ist dann auf Port `8080` erreichbar.

### Erster Start

1. `http://server-ip:8080` aufrufen
2. Mit `admin` / `admin` einloggen
3. Unter **Einstellungen** den Discord Bot-Token eintragen
4. Bot verbindet sich automatisch – Server erscheinen in der Sidebar

### Updates

```bash
git pull
docker compose up -d --build
```

## Nginx Proxy Manager

| Feld | Wert |
|---|---|
| Forward Hostname | `localhost` |
| Forward Port | `8080` |

Optional: SSL-Zertifikat über Let's Encrypt.

## Server-Konfiguration

Pro Server im Dashboard konfigurierbar:
- **Willkommen**: Kanal, Nachricht, Auto-Rolle
- **Logging**: Log-Kanal für alle Events
- **Leveling**: Aktivieren, Level-Up-Kanal
- **Auto-Moderation**: Spam, Links, Wortfilter, Aktion (warn/timeout/kick/ban)
- **Tickets**: Support-Rolle, Ticket-Kategorie

## Benutzerverwaltung

| Rolle | Rechte |
|---|---|
| Admin | Dashboard, Einstellungen, Benutzerverwaltung, Server-Konfiguration |
| Moderator | Dashboard, Server-Konfiguration |

## Projektstruktur

```
phobos-bot/
├── docker-compose.yml
├── app/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── VERSION
│   ├── main.py
│   ├── database.py
│   ├── cogs/
│   │   ├── moderation.py
│   │   ├── leveling.py
│   │   ├── welcome.py
│   │   ├── automod.py
│   │   ├── reaction_roles.py
│   │   ├── logging_cog.py
│   │   ├── custom_commands.py
│   │   ├── tickets.py
│   │   └── giveaways.py
│   └── templates/
│       ├── base.html
│       ├── index.html
│       ├── settings.html
│       ├── server_config.html
│       └── login.html
└── data/                # SQLite-Datenbank + Secret-Key (automatisch erstellt)
```

## Technologie

- Python 3.11, discord.py 2.3.2, Cog-Architektur
- FastAPI + Uvicorn + Jinja2 (Bot und Web im selben asyncio-Prozess)
- SQLite via aiosqlite
- bcrypt 4.2.1
- Docker Compose, single-container
