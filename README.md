# 🛡️ Phobos Bot

Ein selbst-hostbarer Discord-Bot – ähnlich wie MEE6 – mit Web-Dashboard. Open Source, kostenlos, für immer.

**Aktuelle Version: 1.2.10**

---

## Features

### Bot-Funktionen

| Feature | Commands |
|---|---|
| **Moderation** | `/kick` `/ban` `/unban` `/timeout` `/warn` `/warnings` `/clearwarns` `/clear` |
| **Leveling / XP** | `/rank` `/leaderboard` `/setxp` |
| **Willkommen** | Automatische Beitrittsnachrichten, Verlassensnachrichten, Auto-Rolle |
| **Auto-Moderation** | Spam-Schutz, Link-Filter, Wort-Filter |
| **Reaction Roles** | `/reactionrole-add` `/reactionrole-remove` `/reactionrole-list` |
| **Event-Logging** | Beitritt/Verlassen, Nachrichten, Bans, Rollen |
| **Eigene Commands** | `/addcommand` `/delcommand` `/commands` |
| **Tickets** | Button-basiertes Ticket-System |
| **Giveaways** | `/giveaway-start` `/giveaway-end` `/giveaway-reroll` |
| **Twitch-Benachrichtigungen** | Go-Live-Alerts mit Embed (Spiel, Zuschauer, Thumbnail) |
| **Free Stuff & Deals** | Automatische Meldung kostenloser Spiele + konfigurierbare Angebote |

### Web-Dashboard

| Bereich | Funktion |
|---|---|
| **Dashboard** | Bot-Status, verbundene Server, Moderations-Statistiken |
| **Rangsystem** | XP-Leaderboard pro Server mit Avataren und Medaillen |
| **Server** | Übersicht aller verbundenen Server, Bot einladen |
| **Server-Konfiguration** | 7 Tabs: Konfiguration, Leveling/Ränge, Reaction Roles, Commands, Tickets, Giveaways, Warnungen |
| **Twitch-Benachrichtigungen** | Streamer pro Server verwalten, Discord-Kanal und Ping-Nachricht einstellbar |
| **Free Stuff & Deals** | Plattformen wählen (Epic, Steam, GOG, Humble), Max-Preis und Mindest-Rabatt für Deals |
| **Einstellungen → Token** | Discord Bot-Token speichern |
| **Einstellungen → Benutzer** | Dashboard-Nutzer anlegen / löschen (Admin) |
| **Einstellungen → Bot-Design** | Bot-Name und Profilbild ändern |
| **Einstellungen → Bot-Info** | Version, Uptime, Latenz, CPU/RAM, Hostname, OS |
| **Einstellungen → Updates** | Aktuelle Version prüfen, One-Click-Update von GitHub |

---

## Installation

### Voraussetzungen

- Docker & Docker Compose
- Nginx Proxy Manager (empfohlen) oder anderer Reverse-Proxy

```bash
git clone https://github.com/LucyWolf/phobos-bot.git
cd phobos-bot
docker compose up -d --build
```

Dashboard ist auf Port `8080` erreichbar.

### Erster Start

1. `http://server-ip:8080` aufrufen
2. Mit `admin` / `admin` einloggen → **Passwort sofort ändern!**
3. Unter **Einstellungen → Token** den Discord Bot-Token eintragen
4. Bot verbindet sich automatisch — Server erscheinen in der Sidebar

### Discord Developer Portal

1. App auf [discord.com/developers](https://discord.com/developers/applications) erstellen
2. Unter **Bot** → Token kopieren → in Phobos-Dashboard eintragen
3. Unter **Bot** → alle drei **Privileged Gateway Intents** aktivieren:
   - Presence Intent
   - Server Members Intent
   - Message Content Intent
4. Bot über **Einstellungen → Server** auf deinen Server einladen

---

## Updates

### Automatisch (über Dashboard)

1. **Einstellungen → 🔄 Updates** öffnen
2. Wenn neue Version verfügbar: **„Jetzt updaten"** klicken
3. Bot lädt neuen Code von GitHub, startet sich automatisch neu

> Der Bot prüft alle 5 Minuten ob es ein Update gibt. Der Footer zeigt `🔔 Update vX.Y.Z verfügbar` wenn eine neue Version bereitsteht.

### Manuell (auf dem Server)

```bash
cd phobos-bot
git pull
docker compose up -d --build
```

> Manueller Rebuild ist nötig wenn sich `requirements.txt` geändert hat (neue Python-Pakete).

### RAM-Anzeige konfigurieren

Die `docker-compose.yml` enthält standardmäßig `mem_limit: 1g`. Das begrenzt den Container auf 1 GB RAM und sorgt dafür, dass Bot-Info den korrekten Wert anzeigt. Wert nach Bedarf anpassen:

```yaml
mem_limit: 2g   # oder 512m, 4g, etc.
```

Danach Container neu starten: `docker compose up -d`

---

## Twitch-Benachrichtigungen einrichten

1. Twitch-App auf [dev.twitch.tv](https://dev.twitch.tv/console/apps/create) erstellen
   - OAuth Redirect URL: `http://localhost`
   - Kategorie: `Chat Bot`
2. Im Dashboard: **Einstellungen → 📡 Benachrichtigungs-API** → Client-ID + Secret eintragen
3. Pro Server: **Server → 📡 Benachrichtigungen** → Streamer hinzufügen

Der Bot prüft alle 3 Minuten ob eingetragene Streamer live gehen.

---

## Free Stuff & Deals einrichten

Kein API-Key nötig. Im Dashboard unter **Server → 🎁 Free Stuff**:

| Plattform | Quelle | Intervall |
|---|---|---|
| Epic Games | Offizielle Epic-API | Donnerstags (neue Gratis-Spiele) |
| Steam | CheapShark API | Alle 2h |
| GOG | CheapShark API | Alle 2h |
| Humble Bundle | CheapShark API | Alle 2h |

**Angebote:** Optional Max-Preis (z.B. `5 €`) und Mindest-Rabatt (z.B. `75%`) konfigurierbar. Der Bot postet dann auch reduzierte Spiele in den gewählten Kanal.

---

## Nginx Proxy Manager

| Feld | Wert |
|---|---|
| Forward Hostname | `localhost` |
| Forward Port | `8080` |

Optional: SSL-Zertifikat über Let's Encrypt aktivieren.

---

## Benutzerverwaltung

| Rolle | Rechte |
|---|---|
| **Admin** | Alles: Einstellungen, Benutzerverwaltung, Bot-Design, Updates, Server-Konfiguration |
| **Moderator** | Dashboard, Server-Konfiguration, Leaderboard |

Standard-Login beim ersten Start: `admin` / `admin` — **bitte sofort ändern.**

---

## Projektstruktur

```
phobos-bot/
├── docker-compose.yml
├── app/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── VERSION
│   ├── main.py           # FastAPI-Routen + Bot-Setup
│   ├── database.py       # SQLite-Schema + Hilfsfunktionen
│   ├── cogs/
│   │   ├── moderation.py
│   │   ├── leveling.py
│   │   ├── welcome.py
│   │   ├── automod.py
│   │   ├── reaction_roles.py
│   │   ├── logging_cog.py
│   │   ├── custom_commands.py
│   │   ├── tickets.py
│   │   ├── giveaways.py
│   │   ├── notifications.py  # Twitch Live-Benachrichtigungen
│   │   └── freestuff.py      # Free Stuff & Deals
│   └── templates/            # Jinja2 HTML-Templates
└── data/                     # SQLite-Datenbank + Secret-Key (auto-erstellt, nicht committen)
```

---

## Technologie

| Komponente | Version |
|---|---|
| Python | 3.11 |
| discord.py | 2.3.2 |
| FastAPI + Uvicorn | 0.111.0 / 0.29.0 |
| Jinja2 | 3.1.4 |
| aiosqlite | 0.19.0 |
| bcrypt | 4.2.1 |
| psutil | 5.9.8 |

Bot und Web-Dashboard laufen im **selben asyncio-Prozess** via `asyncio.gather()` — kein separater Web-Server nötig.
