# 🛡️ Phobos Bot

Ein Discord Moderations-Bot mit Web-Dashboard, gebaut mit Python und Docker.

## Features

- Slash-Commands für Moderation: `/kick`, `/ban`, `/unban`, `/timeout`, `/warn`, `/warnings`, `/clear`
- Web-Dashboard mit Übersicht aller Moderations-Aktionen
- SQLite-Datenbank (kein extra Datenbank-Container nötig)
- Docker Compose Setup, kompatibel mit Nginx Proxy Manager

## Voraussetzungen

- [Docker](https://www.docker.com/) & Docker Compose
- Einen Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))

## Setup

```bash
# 1. Repo klonen
git clone https://github.com/LucyWolf/phobos-bot.git
cd phobos-bot

# 2. Token eintragen
cp .env.example .env
# .env öffnen und DISCORD_TOKEN eintragen

# 3. Starten
docker compose up -d
```

Das Web-Dashboard läuft auf Port `8080` und kann über Nginx Proxy Manager eingebunden werden.

## Slash-Commands

| Command | Beschreibung | Berechtigung |
|---|---|---|
| `/kick` | Mitglied kicken | Kick Members |
| `/ban` | Mitglied bannen | Ban Members |
| `/unban` | User anhand ID entbannen | Ban Members |
| `/timeout` | Mitglied für X Minuten timen | Moderate Members |
| `/warn` | Mitglied verwarnen | Moderate Members |
| `/warnings` | Verwarnungen eines Mitglieds anzeigen | Moderate Members |
| `/clear` | Nachrichten löschen | Manage Messages |

## Nginx Proxy Manager

Im NPM einfach einen neuen Proxy Host anlegen:

- **Forward Hostname:** `localhost`
- **Forward Port:** `8080`

## Projektstruktur

```
phobos-bot/
├── docker-compose.yml
├── .env.example
├── bot/               # Discord Bot (discord.py)
│   ├── main.py
│   └── cogs/
│       └── moderation.py
├── web/               # Dashboard (FastAPI)
│   ├── app.py
│   └── templates/
│       └── index.html
└── data/              # SQLite Datenbank (automatisch erstellt)
```
