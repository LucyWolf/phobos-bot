# 🛡️ Phobos Bot

Ein selbst-hostbarer Discord-Bot mit Web-Dashboard. Open Source, kostenlos, für immer.

> Entwickelt von **lucy_wolf** in Zusammenarbeit mit **Claude AI**

**Aktuelle Version: 1.2.38**

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
| **Pro Server** | Sidebar-Navigation: Konfiguration, Leveling, Reaction Roles, Commands, Tickets, Giveaways, Warnungen, Twitch, Free Stuff, Log, Bot-Design |
| **Server-Übersicht** | Alle verbundenen Server, Bot einladen |
| **🔑 Tokens** | Mehrere Bot-Tokens verwalten – jeder Token startet einen eigenen Bot-Account |
| **👥 Benutzer** | Dashboard-Nutzer anlegen/löschen, Rolle und Server-Zugriff vergeben |
| **🎭 Rollen** | Eigene Rollen mit feingranularen Berechtigungen erstellen |
| **📊 Bot-Info** | Version, Uptime, Latenz, CPU/RAM, Hostname, OS |
| **🔄 Updates** | Aktuelle Version prüfen, One-Click-Update von GitHub |
| **🕐 Zeitzone** | Zeitzone für alle Zeitangaben im Dashboard konfigurieren |
| **🟣 Twitch-API** | Twitch Client-ID und Secret global eintragen |
| **📧 E-Mail / SMTP** | SMTP für Passwort-Reset konfigurieren |

---

## Multi-Bot

Phobos unterstützt **mehrere Bot-Accounts gleichzeitig**. Unter **Einstellungen → Tokens** können beliebig viele Discord Bot-Tokens eingetragen werden. Jeder Token startet einen eigenen Bot-Account der automatisch dem passenden Server zugewiesen wird.

- Normaler Nutzer mit `perm_tokens`-Berechtigung kann **nur seinen eigenen Token** sehen und verwalten
- Admins sehen alle Tokens

---

## Berechtigungssystem

| Rolle | Rechte |
|---|---|
| **Admin** | Alles: Einstellungen, Benutzerverwaltung, alle Tokens, Bot-Design, Updates |
| **Moderator** | Basis-Zugriff + zugewiesene Server |
| **Custom-Rolle** | Frei konfigurierbar über **Einstellungen → Rollen** |

### Custom-Rollen Berechtigungen

| Flag | Zugriff auf |
|---|---|
| `Einstellungen` | Zeitzone, Twitch-API, SMTP |
| `Tokens` | Eigene Bot-Tokens verwalten |
| `Benutzer` | Benutzerverwaltung |
| `Bots` | Bot-Info |

Eine vorkonfigurierte **„Normal User"**-Rolle (nur Tokens) wird beim ersten Start automatisch angelegt.

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
3. Unter **Einstellungen → 🔑 Tokens** den Discord Bot-Token eintragen
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

> Der Bot prüft alle 5 Minuten ob ein Update verfügbar ist. Der Footer zeigt `🔔 Update vX.Y.Z verfügbar` wenn eine neue Version bereitsteht.

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
2. Im Dashboard: **Einstellungen → 🟣 Twitch-API** → Client-ID + Secret eintragen
3. Pro Server: **Server → 🟣 Twitch** → Streamer hinzufügen

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
