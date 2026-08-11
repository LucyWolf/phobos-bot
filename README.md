# 🛡️ Phobos Bot

> Developed by **lucy_wolf** in collaboration with **Claude AI**

🇬🇧 [English](#english) &nbsp;|&nbsp; 🇩🇪 [Deutsch](#deutsch)

---

<a name="english"></a>
# 🇬🇧 English

A self-hostable Discord bot with a full web dashboard. Open source, free, forever.

## Features

### Bot Features

| Feature | Commands |
|---|---|
| **Moderation** | `/kick` `/ban` `/unban` `/timeout` `/warn` `/warnings` `/clearwarns` `/clear` |
| **Leveling / XP** | `/rank` `/leaderboard` `/setxp` |
| **Welcome** | Auto join/leave messages, auto-role assignment |
| **Auto-Moderation** | Spam protection, link filter, word filter |
| **Reaction Roles** | `/reactionrole-add` `/reactionrole-remove` `/reactionrole-list` |
| **Event Logging** | Join/leave, messages, bans, roles |
| **Custom Commands** | `/addcommand` `/delcommand` `/commands` |
| **Tickets** | Button-based ticket system |
| **Giveaways** | `/giveaway-start` `/giveaway-end` `/giveaway-reroll` |
| **Twitch Notifications** | Go-live alerts with embed (game, viewers, thumbnail) |
| **Free Stuff & Deals** | Automatic free game alerts + configurable deal notifications |

### Web Dashboard

| Section | Function |
|---|---|
| **Dashboard** | Bot status, connected servers, moderation statistics — personalized per user |
| **Per Server** | Config, Leveling, Reaction Roles, Commands, Tickets, Giveaways, Warnings, Twitch, Free Stuff, Log, Bot Design |
| **Server List** | All connected servers, invite bot |
| **🔑 Tokens** | Manage multiple bot tokens — each token runs its own bot account, hot-reload without restart |
| **👥 Users** | Create/delete dashboard users, assign roles and server access |
| **🎭 Roles** | Create custom roles with fine-grained permissions |
| **📊 Bot Info** | Version, uptime, latency, CPU/RAM, hostname, OS |
| **🔄 Updates** | Check current version, one-click update from GitHub |
| **🕐 Timezone** | Configure timezone for all timestamps in the dashboard |
| **🟣 Twitch API** | Set global Twitch Client ID and Secret |
| **📧 E-Mail / SMTP** | Configure SMTP for password reset |

---

## Multi-Bot

Phobos supports **multiple bot accounts simultaneously**. Go to **Settings → 🔑 Tokens** to add as many Discord bot tokens as you like. Each token starts its own bot instance — bots start and stop **instantly** without a container restart.

- Users can only see and manage tokens assigned to them
- Admins see all tokens and can assign users to any token
- Token owners automatically get access to their bot's servers

---

## Permission System

| Role | Access |
|---|---|
| **Admin** | Everything: settings, user management, all tokens, bot design, updates |
| **Normal User** | Own tokens, own servers |
| **Custom Role** | Freely configurable via **Settings → Roles** |

### Custom Role Permissions

| Flag | Grants access to |
|---|---|
| `Settings` | Timezone, Twitch API, SMTP |
| `Tokens` | Manage own bot tokens |
| `Users` | User management |
| `Bots` | Bot info page |
| `Streaming` | Twitch notifications |
| `SMTP` | E-mail settings |
| `Updates` | Update page |
| `Server` | Server configuration |

A pre-configured **"Normal User"** role (tokens + server access) is created automatically on first start.

---

## Installation

### Requirements

- Docker & Docker Compose
- Nginx Proxy Manager (recommended) or another reverse proxy

```bash
git clone https://github.com/LucyWolf/phobos-bot.git
cd phobos-bot
docker compose up -d --build
```

The dashboard is available on port `8080`.

### First Start

1. Open `http://server-ip:8080`
2. Log in with `admin` / `admin` → **change the password immediately!**
3. Go to **Settings → 🔑 Tokens** and add your Discord bot token
4. The bot connects automatically — servers appear in the sidebar

### Discord Developer Portal

1. Create an app at [discord.com/developers](https://discord.com/developers/applications)
2. Under **Bot** → copy token → paste into Phobos dashboard
3. Under **Bot** → enable all three **Privileged Gateway Intents**:
   - Presence Intent
   - Server Members Intent
   - Message Content Intent
4. Invite the bot via **Settings → Server**

---

## Updates

### Automatic (via Dashboard)

1. Open **Settings → 🔄 Updates**
2. If a new version is available: click **"Update Now"**
3. The bot pulls the new code from GitHub and restarts automatically

> The bot checks for updates every 5 minutes. The footer shows `🔔 Update vX.Y.Z available` when a new version is ready.

### Manual (on the server)

```bash
cd phobos-bot
git pull
docker compose up -d --build
```

> A manual rebuild is only needed when `requirements.txt` changes (new Python packages). For template or code-only changes, `git pull` is enough.

### RAM Display

The container is limited to **1 GB RAM** by default (for correct display in Bot Info). Adjustable via `.env`:

```env
MEM_LIMIT=2g
```

Then restart: `docker compose up -d`

---

## Twitch Notifications Setup

1. Create a Twitch app at [dev.twitch.tv](https://dev.twitch.tv/console/apps/create)
   - OAuth Redirect URL: `http://localhost`
   - Category: `Chat Bot`
2. In the dashboard: **Settings → 🟣 Twitch API** → enter Client ID + Secret
3. Per server: **Server → 🟣 Twitch** → add streamers

The bot checks every 3 minutes if registered streamers go live.

---

## Free Stuff & Deals Setup

No API key required. In the dashboard under **Server → 🎁 Free Stuff**:

| Platform | Source | Interval |
|---|---|---|
| Epic Games | Official Epic API | Thursdays (new free games) |
| Steam | CheapShark API | Every 2h |
| GOG | CheapShark API | Every 2h |
| Humble Bundle | CheapShark API | Every 2h |

**Deals:** Optionally configure a max price (e.g. `5 €`) and minimum discount (e.g. `75%`). The bot will also post discounted games to the selected channel.

---

## Nginx Proxy Manager

| Field | Value |
|---|---|
| Forward Hostname | `localhost` |
| Forward Port | `8080` |

Optionally enable an SSL certificate via Let's Encrypt.

---

## Project Structure

```
phobos-bot/
├── docker-compose.yml
├── app/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── VERSION
│   ├── main.py           # FastAPI routes + bot setup
│   ├── database.py       # SQLite schema + helpers
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
│   │   ├── notifications.py  # Twitch live notifications
│   │   └── freestuff.py      # Free stuff & deals
│   └── templates/            # Jinja2 HTML templates
└── data/                     # SQLite database + secret key (auto-created, do not commit)
```

---

## Tech Stack

| Component | Version |
|---|---|
| Python | 3.11 |
| discord.py | 2.3.2 |
| FastAPI + Uvicorn | 0.111.0 / 0.29.0 |
| Jinja2 | 3.1.4 |
| aiosqlite | 0.19.0 |
| bcrypt | 4.2.1 |
| psutil | 5.9.8 |

Bot and web dashboard run in the **same asyncio process** — no separate web server needed.

---

<a name="deutsch"></a>
# 🇩🇪 Deutsch

Ein selbst-hostbarer Discord-Bot mit vollständigem Web-Dashboard. Open Source, kostenlos, für immer.

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
| **Dashboard** | Bot-Status, verbundene Server, Moderations-Statistiken — personalisiert pro Nutzer |
| **Pro Server** | Konfiguration, Leveling, Reaction Roles, Commands, Tickets, Giveaways, Warnungen, Twitch, Free Stuff, Log, Bot-Design |
| **Server-Übersicht** | Alle verbundenen Server, Bot einladen |
| **🔑 Tokens** | Mehrere Bot-Tokens verwalten – jeder Token startet einen eigenen Bot-Account, Hot-Reload ohne Neustart |
| **👥 Benutzer** | Dashboard-Nutzer anlegen/löschen, Rolle und Server-Zugriff vergeben |
| **🎭 Rollen** | Eigene Rollen mit feingranularen Berechtigungen erstellen |
| **📊 Bot-Info** | Version, Uptime, Latenz, CPU/RAM, Hostname, OS |
| **🔄 Updates** | Aktuelle Version prüfen, One-Click-Update von GitHub |
| **🕐 Zeitzone** | Zeitzone für alle Zeitangaben im Dashboard konfigurieren |
| **🟣 Twitch-API** | Twitch Client-ID und Secret global eintragen |
| **📧 E-Mail / SMTP** | SMTP für Passwort-Reset konfigurieren |

---

## Multi-Bot

Phobos unterstützt **mehrere Bot-Accounts gleichzeitig**. Unter **Einstellungen → 🔑 Tokens** können beliebig viele Discord Bot-Tokens eingetragen werden. Jeder Token startet einen eigenen Bot-Account — Bots starten und stoppen **sofort** ohne Container-Neustart.

- Normale Nutzer sehen und verwalten nur ihre eigenen Tokens
- Admins sehen alle Tokens und können Nutzer beliebigen Tokens zuweisen
- Token-Besitzer erhalten automatisch Zugriff auf die Server ihres Bots

---

## Berechtigungssystem

| Rolle | Rechte |
|---|---|
| **Admin** | Alles: Einstellungen, Benutzerverwaltung, alle Tokens, Bot-Design, Updates |
| **Normal User** | Eigene Tokens, eigene Server |
| **Custom-Rolle** | Frei konfigurierbar über **Einstellungen → Rollen** |

### Custom-Rollen Berechtigungen

| Flag | Zugriff auf |
|---|---|
| `Einstellungen` | Zeitzone, Twitch-API, SMTP |
| `Tokens` | Eigene Bot-Tokens verwalten |
| `Benutzer` | Benutzerverwaltung |
| `Bots` | Bot-Info |
| `Streaming` | Twitch-Benachrichtigungen |
| `SMTP` | E-Mail-Einstellungen |
| `Updates` | Update-Seite |
| `Server` | Server-Konfiguration |

Eine vorkonfigurierte **„Normal User"**-Rolle (Tokens + Server-Zugriff) wird beim ersten Start automatisch angelegt.

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
4. Bot über **Einstellungen → Server** einladen

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

> Manueller Rebuild ist nur nötig wenn sich `requirements.txt` geändert hat (neue Python-Pakete). Bei Template- oder Code-Änderungen reicht `git pull`.

### RAM-Anzeige konfigurieren

Der Container ist standardmäßig auf **1 GB RAM** begrenzt (für korrekte Anzeige in Bot-Info). Per `.env`-Datei anpassbar:

```env
MEM_LIMIT=2g
```

Danach: `docker compose up -d`

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

Bot und Web-Dashboard laufen im **selben asyncio-Prozess** — kein separater Web-Server nötig.
