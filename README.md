# 🛡️ Phobos Bot

Ein Discord Moderations-Bot mit Web-Dashboard, gebaut mit Python und Docker.

## Features

- Slash-Commands für Moderation: `/kick`, `/ban`, `/unban`, `/timeout`, `/warn`, `/warnings`, `/clear`
- Web-Dashboard mit Übersicht aller Moderations-Aktionen
- Login-System mit Benutzerverwaltung (Rollen: Admin / Moderator)
- Discord Token direkt im Web-Dashboard eintragen — kein manuelles Konfigurieren nötig
- Alles in einem einzigen Docker-Container
- SQLite-Datenbank (kein extra Datenbank-Container nötig)
- Kompatibel mit Nginx Proxy Manager

## Voraussetzungen

- [Docker](https://www.docker.com/) & Docker Compose
- Einen Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))

## Installation

```bash
git clone https://github.com/LucyWolf/phobos-bot.git
cd phobos-bot
docker compose up -d --build
```

Das Web-Dashboard ist danach erreichbar unter `http://server-ip:8080`.

## Erster Start

1. `http://server-ip:8080` aufrufen
2. Mit den Standard-Zugangsdaten einloggen: **admin** / **admin**
3. Unter **Einstellungen** den Discord Bot Token eintragen
4. Unter **Benutzer** einen eigenen Admin-Account anlegen und den Standard-User löschen

## Updates

```bash
git pull
docker compose up -d --build
```

## Nginx Proxy Manager

Neuen Proxy Host anlegen:

| Feld | Wert |
|---|---|
| Forward Hostname | `localhost` |
| Forward Port | `8080` |

Danach optional ein SSL-Zertifikat über Let's Encrypt ausstellen lassen.

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

## Benutzerverwaltung

| Rolle | Rechte |
|---|---|
| Admin | Dashboard, Einstellungen, Benutzerverwaltung |
| Moderator | Dashboard, Einstellungen |

## Projektstruktur

```
phobos-bot/
├── docker-compose.yml
├── app/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── VERSION
│   ├── main.py          # Bot + Web UI in einem Prozess
│   └── templates/
│       ├── index.html   # Dashboard
│       ├── settings.html
│       ├── users.html
│       ├── login.html
│       └── setup.html
└── data/                # SQLite Datenbank (automatisch erstellt)
```
