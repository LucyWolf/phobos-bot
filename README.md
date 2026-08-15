# 🛡️ Phobos Bot

🇬🇧 [English](#english) &nbsp;|&nbsp; 🇩🇪 [Deutsch](#deutsch)

---

<a name="english"></a>
# 🇬🇧 English

A self-hostable Discord bot with a full web dashboard. Open source, free, forever.

## Features

### Bot Features

| Feature | Details |
|---|---|
| **Moderation** | `/kick` `/ban` `/unban` `/timeout` `/warn` `/warnings` `/clearwarns` `/clear` |
| **Leveling / XP** | `/rank` `/leaderboard` `/setxp` — configurable XP per message, level-up channel |
| **Welcome** | Auto join/leave messages, auto-role assignment, **generated welcome card image** with custom colors |
| **Auto-Moderation** | Spam protection, link filter, word filter |
| **Reaction Roles** | `/reactionrole-add` `/reactionrole-remove` `/reactionrole-list` |
| **Event Logging** | Join/leave, bans, roles, messages, voice — **shows who deleted a message** via audit log, bulk-delete detection, exclude channels |
| **Custom Commands** | `/addcommand` `/delcommand` `/commands` |
| **Tickets** | Button-based ticket system with panels |
| **Giveaways** | `/giveaway-start` `/giveaway-end` `/giveaway-reroll` |
| **Twitch Notifications** | Go-live alerts with embed (game, viewers, thumbnail) |
| **Free Stuff & Deals** | Automatic free game alerts + configurable deal notifications + test button |
| **Auto-Delete** | Automatically delete messages in selected channels after a configurable time |
| **Temp Voice** | Join-to-Create temporary voice channels — auto-created on join, auto-deleted when empty |
| **Scheduled Messages** | Schedule messages to be sent to any channel at a specific date and time |
| **Birthday System** | `!geburtstag DD.MM` — daily congratulations at 8 AM, configurable channel and message |

### Web Dashboard

| Section | Function |
|---|---|
| **Dashboard** | Bot status, connected servers, moderation statistics — personalized per user |
| **Per Server** | Config, Leveling, Reaction Roles, Commands, Tickets, Giveaways, Warnings, Twitch, Free Stuff, Log, Temp Voice, Scheduled Messages, Birthdays, Auto-Delete, Bot Design |
| **Server List** | All connected servers, invite bot |
| **🔑 Tokens** | Manage multiple bot tokens — each token runs its own bot account, hot-reload without restart |
| **👥 Users** | Create/delete dashboard users, assign roles and server access, **download & restore backups** |
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

## Docker Compose

```yaml
services:
  bot:
    build: ./app
    container_name: ${BOT_CONTAINER_NAME:-Phobos-Bot}
    ports:
      - "8080:8080"
    volumes:
      - ./app:/app
      - ./data:/app/data
```

> Running a second full instance (separate dashboard + bot process, e.g. on port 8081) on the same server? Set `BOT_CONTAINER_NAME` in `.env` to something matching that bot (e.g. `SecondBot`) so `docker ps` shows which container belongs to which bot — otherwise it defaults to `Phobos-Bot` for every instance and they become impossible to tell apart at a glance.

---

## Welcome Card

When a member joins, the bot can send a **generated image card** instead of a plain text embed:

- Avatar displayed in a customizable colored circle
- "WELCOME" title with configurable color
- Username and member count
- All colors freely configurable in the dashboard under **Server → Config**

Requires the `fonts-dejavu-core` package (included in the Docker image). If image generation fails, falls back to a plain embed automatically.

---

## Temp Voice Channels

Under **Server → Temp Voice** you can set up **Join-to-Create** channels:

1. Select any existing voice channel as the **trigger**
2. Set a **name template** (e.g. `{user}'s Channel` → `Wolfi's Channel`)
3. Optionally set a **user limit** and **category**

When a member joins the trigger channel, the bot creates a private voice channel and moves them into it. When the last member leaves, the channel is deleted automatically.

---

## Auto-Delete

Under **Server → Auto-Delete** you can configure which channels should have their messages automatically deleted after a set time (5 min – 7 days). Changes take effect immediately without a restart.

---

## Scheduled Messages

Under **Server → Scheduled Messages** you can schedule a message to be sent to any channel at a specific date and time. Useful for announcements, reminders or recurring events.

---

## Birthday System

Under **Server → Birthdays** you can configure a birthday channel and a custom message. Members can register their birthday with `!geburtstag DD.MM` (or delete it with `!geburtstag löschen`). Every day at 8 AM the bot automatically congratulates members whose birthday it is — each person only once per year.

---

## Backup & Restore

Every user can export their own data (account, bot tokens, all server configurations) as a JSON file via their **profile page**. Admins can additionally:

- Download a backup for any individual user
- Download a **full backup** of the entire system (all users, tokens, configs)
- **Restore** any backup via file upload — existing entries are updated, new ones are added, nothing is deleted

Passwords of existing accounts are never overwritten during a restore. This makes it easy to migrate to a new server or hand off a bot setup to someone else.

---

## Event Logging

Under **Server → Log** configure:

- **Log channel** — Discord channel where events are posted
- **Exclude channels** — channels whose messages are NOT logged (e.g. spam channels)

Logged events include:
- Member join / leave (with roles on leave)
- Role changes, nickname changes, timeouts
- Bans / unbans
- Message deleted — **including who deleted it** (requires "View Audit Log" permission)
- **Bulk message delete** (e.g. `/clear` command) with responsible moderator
- Message edited (before + after + jump link)
- Voice channel join / leave / switch
- Channel created / deleted / renamed
- Server boost changes

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

> For the "who deleted" logging feature, grant the bot the **View Audit Log** permission on your server.

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
docker compose restart
```

> A full rebuild (`docker compose up -d --build`) is only needed when `requirements.txt` or `Dockerfile` changes. For code or template changes, `docker compose restart` is enough.

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

**Test button:** In the dashboard under **Server → 🎁 Free Stuff** you can send the current free games to the Discord channel on demand.

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
│   ├── main.py             # FastAPI routes + bot setup
│   ├── database.py         # SQLite schema + helpers
│   ├── i18n.py             # DE/EN translations
│   ├── cogs/
│   │   ├── moderation.py
│   │   ├── leveling.py
│   │   ├── welcome.py      # Welcome card image generation
│   │   ├── automod.py
│   │   ├── reaction_roles.py
│   │   ├── logging_cog.py  # Event logging with audit log
│   │   ├── custom_commands.py
│   │   ├── tickets.py
│   │   ├── giveaways.py
│   │   ├── notifications.py  # Twitch live notifications
│   │   ├── freestuff.py      # Free stuff & deals
│   │   ├── auto_delete.py    # Auto-delete messages by channel
│   │   └── temp_voice.py     # Join-to-Create temp voice channels
│   └── templates/            # Jinja2 HTML templates
├── data/                     # SQLite database + secret key (auto-created, do not commit)
└── data-*/                   # Additional instance databases (if using multi-instance)
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
| Pillow | 10.4.0 |
| psutil | 5.9.8 |

Bot and web dashboard run in the **same asyncio process** — no separate web server needed.

---

## A Note on This Project

This code was created by Claude AI — and I know, many people roll their eyes at those words. Even so, this bot stands for a simple idea: to be there for everyone, without exception. AI is not a miracle that solves every problem on its own — it's a tool that only unfolds its power through the hands that guide it. And because there is no paid work behind this, only the time I was happy to invest, this bot will never cost anything. All files are open, freely accessible and freely usable by anyone.

I want to be honest here: this is AI-generated, and I make no claim to have written it myself. That credit is not mine to take. The 3D printer once gave rise to hobby engineers who used it to solve everyday problems they previously lacked the knowledge or resources for. That is exactly what AI can — and should — be: not a miracle, but a tool that makes our lives easier. A tool that allows people without a computer science background to tackle the small, nagging problems we all encounter. Not out of any claim to genius, but out of the simple desire to make something better.

> *— lucy_wolf*

---

<a name="deutsch"></a>
# 🇩🇪 Deutsch

Ein selbst-hostbarer Discord-Bot mit vollständigem Web-Dashboard. Open Source, kostenlos, für immer.

## Features

### Bot-Funktionen

| Feature | Details |
|---|---|
| **Moderation** | `/kick` `/ban` `/unban` `/timeout` `/warn` `/warnings` `/clearwarns` `/clear` |
| **Leveling / XP** | `/rank` `/leaderboard` `/setxp` — konfigurierbares XP pro Nachricht, Level-Up-Kanal |
| **Willkommen** | Automatische Beitrittsnachrichten, Verlassensnachrichten, Auto-Rolle, **generierte Willkommenskarte** mit anpassbaren Farben |
| **Auto-Moderation** | Spam-Schutz, Link-Filter, Wort-Filter |
| **Reaction Roles** | `/reactionrole-add` `/reactionrole-remove` `/reactionrole-list` |
| **Event-Logging** | Beitritt/Verlassen, Bans, Rollen, Nachrichten, Voice — **zeigt wer eine Nachricht gelöscht hat** via Audit-Log, Massenlöschungs-Erkennung, Kanäle ausschließen |
| **Eigene Commands** | `/addcommand` `/delcommand` `/commands` |
| **Tickets** | Button-basiertes Ticket-System mit Panels |
| **Giveaways** | `/giveaway-start` `/giveaway-end` `/giveaway-reroll` |
| **Twitch-Benachrichtigungen** | Go-Live-Alerts mit Embed (Spiel, Zuschauer, Thumbnail) |
| **Free Stuff & Deals** | Automatische Meldung kostenloser Spiele + konfigurierbare Angebote + Test-Button |
| **Auto-Delete** | Nachrichten in gewählten Kanälen automatisch nach konfigurierbarer Zeit löschen |
| **Temp Voice** | Join-to-Create temporäre Voice-Kanäle — automatisch erstellt beim Beitritt, automatisch gelöscht wenn leer |
| **Geplante Nachrichten** | Nachrichten zu einem bestimmten Datum und Uhrzeit in jeden Kanal planen |
| **Geburtstags-System** | `!geburtstag TT.MM` — tägliche Glückwünsche um 8 Uhr, konfigurierbarer Kanal und Text |

### Web-Dashboard

| Bereich | Funktion |
|---|---|
| **Dashboard** | Bot-Status, verbundene Server, Moderations-Statistiken — personalisiert pro Nutzer |
| **Pro Server** | Konfiguration, Leveling, Reaction Roles, Commands, Tickets, Giveaways, Warnungen, Twitch, Free Stuff, Log, Temp Voice, Geplant, Geburtstage, Auto-Delete, Bot-Design |
| **Server-Übersicht** | Alle verbundenen Server, Bot einladen |
| **🔑 Tokens** | Mehrere Bot-Tokens verwalten – jeder Token startet einen eigenen Bot-Account, Hot-Reload ohne Neustart |
| **👥 Benutzer** | Dashboard-Nutzer anlegen/löschen, Rolle und Server-Zugriff vergeben, **Backups erstellen & einspielen** |
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

## Docker Compose

```yaml
services:
  bot:
    build: ./app
    container_name: ${BOT_CONTAINER_NAME:-Phobos-Bot}
    ports:
      - "8080:8080"
    volumes:
      - ./app:/app
      - ./data:/app/data
```

> Läuft eine zweite vollständige Instanz (eigenes Dashboard + Bot-Prozess, z.B. auf Port 8081) auf demselben Server? In der `.env` `BOT_CONTAINER_NAME` auf einen Namen setzen, der zu diesem Bot passt (z.B. `SecondBot`), damit `docker ps` zeigt, welcher Container zu welchem Bot gehört — sonst heißt standardmäßig jede Instanz `Phobos-Bot` und sie sind auf den ersten Blick nicht zu unterscheiden.

---

## Willkommenskarte

Wenn ein Mitglied beitritt, kann der Bot statt einer Text-Nachricht eine **generierte Bildkarte** senden:

- Avatar in einem farblich anpassbaren Kreis
- „WELCOME"-Titel mit konfigurierbarer Farbe
- Username und Mitgliedsnummer
- Alle Farben frei einstellbar im Dashboard unter **Server → Konfiguration**

Benötigt das Paket `fonts-dejavu-core` (im Docker-Image bereits enthalten). Schlägt die Bildgenerierung fehl, wird automatisch auf ein Text-Embed zurückgefallen.

---

## Temporäre Voice-Kanäle

Unter **Server → Temp Voice** können **Join-to-Create**-Kanäle eingerichtet werden:

1. Beliebigen bestehenden Voice-Kanal als **Trigger** wählen
2. **Name-Vorlage** festlegen (z.B. `{user}'s Channel` → `Wolfi's Channel`)
3. Optional **Nutzer-Limit** und **Kategorie** setzen

Sobald ein Mitglied den Trigger-Kanal betritt, erstellt der Bot einen eigenen Voice-Kanal und verschiebt die Person hinein. Wenn das letzte Mitglied den Kanal verlässt, wird er automatisch gelöscht.

---

## Auto-Delete

Unter **Server → Auto-Delete** kann festgelegt werden, in welchen Kanälen Nachrichten automatisch nach einer bestimmten Zeit (5 Min. – 7 Tage) gelöscht werden. Änderungen gelten sofort ohne Neustart.

---

## Geplante Nachrichten

Unter **Server → Geplant** können Nachrichten für einen beliebigen Kanal zu einem bestimmten Datum und einer Uhrzeit eingeplant werden. Ideal für Ankündigungen, Erinnerungen oder regelmäßige Ereignisse.

---

## Geburtstags-System

Unter **Server → Geburtstage** können ein Geburtstags-Kanal und ein eigener Glückwunsch-Text konfiguriert werden. Mitglieder tragen ihren Geburtstag mit `!geburtstag TT.MM` ein (oder löschen ihn mit `!geburtstag löschen`). Jeden Tag um 8 Uhr morgens gratuliert der Bot automatisch — jede Person nur einmal pro Jahr.

---

## Backup & Wiederherstellen

Jeder Nutzer kann seine eigenen Daten (Konto, Bot-Tokens, alle Server-Konfigurationen) als JSON-Datei über die **Profilseite** exportieren. Admins können zusätzlich:

- Backup eines einzelnen Nutzers herunterladen
- **Komplett-Backup** des gesamten Systems (alle Nutzer, Tokens, Konfigurationen)
- Beliebiges Backup per Datei-Upload **wiederherstellen** — bestehende Einträge werden aktualisiert, neue hinzugefügt, nichts wird gelöscht

Passwörter bestehender Konten werden beim Einspielen nie überschrieben. So lässt sich ein Bot-Setup einfach auf einen neuen Server migrieren oder an jemand anderen weitergeben.

---

## Event-Logging

Unter **Server → Log** konfigurierbar:

- **Log-Kanal** — Discord-Kanal für die Ereignis-Meldungen
- **Kanäle ausschließen** — Kanäle, deren Nachrichten NICHT geloggt werden (z.B. Spam-Kanal)

Geloggte Ereignisse:
- Mitglied beigetreten / verlassen (mit Rollen beim Verlassen)
- Rollen-Änderungen, Nickname-Änderungen, Timeouts
- Bans / Entbannungen
- Nachricht gelöscht — **inkl. wer gelöscht hat** (benötigt „Audit-Log anzeigen"-Berechtigung)
- **Massenlöschung** (z.B. `/clear`-Befehl) mit verantwortlichem Moderator
- Nachricht bearbeitet (vorher + nachher + Sprung-Link)
- Voice-Kanal beigetreten / verlassen / gewechselt
- Kanal erstellt / gelöscht / umbenannt
- Server-Boost-Änderungen

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

> Für das „Wer hat gelöscht"-Logging braucht der Bot die Berechtigung **Audit-Log anzeigen** auf dem Server.

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
docker compose restart
```

> Vollständiger Rebuild (`docker compose up -d --build`) ist nur nötig wenn sich `requirements.txt` oder `Dockerfile` geändert hat. Bei Code- oder Template-Änderungen reicht `docker compose restart`.

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

**Test-Button:** Im Dashboard unter **Server → 🎁 Free Stuff** können die aktuellen Gratis-Spiele auf Knopfdruck sofort in den Discord-Kanal gesendet werden.

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
│   ├── main.py               # FastAPI-Routen + Bot-Setup
│   ├── database.py           # SQLite-Schema + Hilfsfunktionen
│   ├── i18n.py               # DE/EN Übersetzungen
│   ├── cogs/
│   │   ├── moderation.py
│   │   ├── leveling.py
│   │   ├── welcome.py        # Willkommenskarte (Pillow-Bildgenerierung)
│   │   ├── automod.py
│   │   ├── reaction_roles.py
│   │   ├── logging_cog.py    # Event-Logging mit Audit-Log
│   │   ├── custom_commands.py
│   │   ├── tickets.py
│   │   ├── giveaways.py
│   │   ├── notifications.py  # Twitch Live-Benachrichtigungen
│   │   ├── freestuff.py      # Free Stuff & Deals
│   │   ├── auto_delete.py    # Automatisches Löschen nach Zeit
│   │   └── temp_voice.py     # Join-to-Create Temp-Voice-Kanäle
│   └── templates/            # Jinja2 HTML-Templates
├── data/                     # SQLite-Datenbank + Secret-Key (auto-erstellt, nicht committen)
└── data-*/                   # Weitere Instanz-Datenbanken (bei Multi-Instanz)
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
| Pillow | 10.4.0 |
| psutil | 5.9.8 |

Bot und Web-Dashboard laufen im **selben asyncio-Prozess** — kein separater Web-Server nötig.

---

## Eine Anmerkung zu diesem Projekt

Dieser Code wurde von Claude AI erschaffen – und ich weiß, viele rümpfen bei diesen Worten die Nase. Trotzdem steht dieser Bot für einen einfachen Gedanken: für alle da zu sein, ohne Ausnahme. Eine KI ist kein Wundermittel, das jedes Problem von selbst löst – sie ist ein Werkzeug, das seine Kraft erst durch die Hände entfaltet, die es führen. Und weil dahinter keine bezahlte Arbeit steckt, sondern nur die Zeit, die ich gerne investiert habe, wird dieser Bot niemals etwas kosten. Alle Dateien liegen offen, für jeden frei zugänglich, frei verwendbar.

Ich will an dieser Stelle ehrlich sein: Das hier ist KI-generiert, und ich beanspruche nicht, es selbst geschrieben zu haben. Diese Ehre gebührt mir nicht. Der 3D-Drucker hat einst Hobby-Ingenieure entstehen lassen, die damit Probleme des Alltags lösten, für die ihnen früher Wissen oder Mittel fehlten. Genau das kann – und sollte – auch KI sein: kein Wundermittel, sondern ein Werkzeug, das unser Leben einfacher macht. Ein Werkzeug, mit dem auch Menschen ohne Informatik-Hintergrund die kleinen, nervigen Probleme angehen können, die uns allen begegnen. Nicht aus Anspruch auf Genialität, sondern aus dem einfachen Wunsch, etwas besser zu machen.

> *— lucy_wolf*
