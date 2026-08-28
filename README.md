# 🛡️ Phobos Bot

🇬🇧 [English](#english) &nbsp;|&nbsp; 🇩🇪 [Deutsch](#deutsch)

---

<a name="english"></a>
# 🇬🇧 English

A self-hostable Discord bot with a full web dashboard. Open source, free, forever.

<details>
<summary><strong>Table of contents</strong></summary>

- [Features](#features)
  - [Bot Features](#bot-features)
  - [Web Dashboard](#web-dashboard)
- [Multi-Bot](#multi-bot)
- [Docker Compose](#docker-compose)
- [Welcome Card](#welcome-card)
- [Temp Voice Channels](#temp-voice-channels)
- [Spam Protection / Auto-Moderation](#spam-protection--auto-moderation)
- [Auto-Delete](#auto-delete)
- [Scheduled Messages](#scheduled-messages)
- [Discord Events](#discord-events)
- [Birthday System](#birthday-system)
- [Backup & Restore](#backup--restore)
- [Two-Factor Authentication](#two-factor-authentication)
- [Event Logging](#event-logging)
- [Permission System](#permission-system)
- [Installation](#installation)
  - [Requirements](#requirements)
  - [Android (Termux) — no Docker required](#android-termux--no-docker-required)
  - [First Start](#first-start)
  - [Discord Developer Portal](#discord-developer-portal)
- [Updates](#updates)
  - [Automatic (via Dashboard)](#automatic-via-dashboard)
  - [Manual (on the server)](#manual-on-the-server)
  - [RAM Display](#ram-display)
- [Twitch Notifications Setup](#twitch-notifications-setup)
- [Free Stuff & Deals Setup](#free-stuff--deals-setup)
- [Nginx Proxy Manager](#nginx-proxy-manager)
- [Project Structure](#project-structure)
- [Tech Stack](#tech-stack)
- [A Note on This Project](#a-note-on-this-project)

</details>

## Features

### Bot Features

| Feature | Details |
|---|---|
| **Moderation** | `/kick` `/ban` `/unban` `/timeout` `/warn` `/warnings` `/clearwarns` `/clear` |
| **Leveling / XP** | `/rank` `/leaderboard` `/setxp` — configurable XP per message, level-up channel, auto-assign a role at a chosen level, optional custom reward text shown at a level |
| **Welcome** | Auto join/leave messages, auto-role assignment, **generated welcome card image** with custom colors |
| **Auto-Moderation** | Configurable spam threshold/window, link filter, word filter with editable quick-add categories, configurable action (warn/timeout/kick/ban) |
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
| **Discord Events** | Create/edit native Discord scheduled events (voice or external) from the dashboard, with optional reminders and start/end announcements posted to a channel |

### Web Dashboard

| Section | Function |
|---|---|
| **Dashboard** | Bot status, connected servers, moderation statistics — personalized per user |
| **Per Server** | Config, Spam Protection, Leveling, Reaction Roles, Commands, Tickets, Giveaways, Warnings, Twitch, Free Stuff, Log, Temp Voice, Scheduled Messages, Events, Birthdays, Auto-Delete, Bot Design |
| **Server List** | All connected servers, invite bot |
| **🔑 Tokens** *(Admin)* | Manage multiple bot tokens — each token runs its own bot account, hot-reload without restart |
| **👥 Users** *(Admin)* | Create/delete dashboard users, assign roles and server access, **download & restore backups** |
| **🔐 Two-Factor Auth** | Optional TOTP-based 2FA for dashboard login (Google Authenticator, Authy, etc.), with one-time backup codes |
| **📊 Bot Info** | Version, uptime, latency, CPU/RAM, hostname, OS |
| **🔄 Updates** *(Admin)* | Check current version, one-click update from GitHub |
| **🕐 Timezone** *(Admin to change)* | Configure timezone for all timestamps in the dashboard |
| **🟣 Streaming-API** *(Admin)* | Register one or more Twitch apps (Client ID + Secret), optionally shared with specific users |
| **📧 E-Mail / SMTP** *(Admin)* | Configure SMTP for password reset |

---

## Multi-Bot

Phobos supports **multiple bot accounts simultaneously**. Go to **Settings → 🔑 Tokens** (Admin only) to add as many Discord bot tokens as you like. Each token starts its own bot instance — bots start and stop **instantly** without a container restart.

- Token management itself is Admin-only
- Admins can assign moderators to individual bot tokens — those moderators then automatically get access to that bot's servers

---

## Docker Compose

```yaml
services:
  bot:
    build: ./app
    container_name: ${BOT_CONTAINER_NAME:-Phobos-Bot}
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./app:/app
      - ./data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/repo
    environment:
      - TZ=Europe/Berlin
      - PYTHONUNBUFFERED=1
    mem_limit: ${MEM_LIMIT:-1g}
    memswap_limit: ${MEM_LIMIT:-1g}
```

> Running a second full instance (separate dashboard + bot process, e.g. on port 8081) on the same server? Set `BOT_CONTAINER_NAME` in `.env` to something matching that bot (e.g. `SecondBot`) so `docker ps` shows which container belongs to which bot — otherwise it defaults to `Phobos-Bot` for every instance and they become impossible to tell apart at a glance.

> The `/var/run/docker.sock` mount lets the dashboard talk to the Docker Engine API directly (needed for the one-click update feature under **Settings → 🔄 Updates**). The `.:/repo` mount gives the container access to the git repository itself so updates can fetch and hard-reset to the new code (`git fetch` + `git reset --hard origin/main`, not a plain `git pull` — this forcibly overwrites any local drift instead of risking a merge conflict). Both are optional if you're fine doing updates manually from the server shell instead (`git pull` + `docker compose up -d --build`).

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

## Spam Protection / Auto-Moderation

Under **Server → 🛡️ Spam-Schutz** (its own tab, separate from general config):

- **Spam threshold & time window** — e.g. flag a member after 5 messages within 5 seconds, both configurable
- **Link filter** — blocks messages containing URLs or Discord invites
- **Word filter** — blocks messages containing any banned word, matched on whole-word boundaries (so a banned word like "ass" won't trigger on "class")
- **Action on violation** — warn (logged to `/warnings`), timeout (configurable duration, up to Discord's 28-day max), kick, or ban
- **Custom warning DM** — sent to the member on every violation, with `{server}`/`{reason}` placeholders

Members with the **Manage Messages** permission are always exempt.

**Word-list categories:** instead of typing banned words from scratch, quick-add buttons above the words field insert a whole category at once (without removing what's already there). Categories are fully editable per server — create, rename, edit their words, or delete them under "🗂️ Wortlisten-Kategorien" further down the same tab. A few starter categories (spam phrases, fake-Nitro bait, crypto scams, Nazi references) are pre-filled on first use — feel free to edit or delete them.

---

## Auto-Delete

Under **Server → Auto-Delete** you can configure which channels should have their messages automatically deleted after a set time (5 min – 7 days). Changes take effect immediately without a restart, and scheduled deletions are persisted — a bot restart in between doesn't lose them. Requires the **Manage Messages** permission in the target channel.

---

## Scheduled Messages

Under **Server → Scheduled Messages** you can schedule a message to be sent to any channel at a specific date and time. Useful for announcements, reminders or recurring events.

---

## Discord Events

Under **Server → Events** you can create native Discord scheduled events directly from the dashboard — either tied to a voice channel or as an "external" event (custom location, e.g. a game or an outside venue). Events can be edited as long as they haven't started yet; once Discord marks them active or completed, only deletion remains.

Optional extras when creating an event:
- **Announcement channel** — the bot posts a message there automatically once the event starts (and, if enabled, once it ends), including name, time, location and a link to the event
- **Reminders** — any number of custom messages posted a chosen number of minutes before the event starts

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

## Two-Factor Authentication

Every dashboard user can enable TOTP-based two-factor authentication under **Profile → Two-Factor Authentication** — compatible with Google Authenticator, Authy, Aegis and similar apps. After entering the confirmation code once, 8 one-time backup codes are shown (for account recovery if you lose your device); they can be regenerated anytime with your password. Login then requires the app code (or a backup code) after the password, and repeated failed codes temporarily lock the account.

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

Phobos keeps this deliberately simple — just two roles, no custom permission sets to configure:

| Role | Access |
|---|---|
| **Admin** | Everything: global settings, user management, bot tokens, Streaming-API credentials, SMTP, updates, bot design, and every connected server |
| **Moderator** | Only the servers explicitly granted to them under **Users**, or inherited automatically from a bot token they've been assigned to. Can still view (but not change) some read-only pages like Bot Info |

The very first account (`admin` / `admin`, see Installation below) is always an Admin. There must always be at least one Admin — the dashboard blocks demoting or deleting the last remaining one.

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

> **Does this need to be reachable from the internet?** No. The bot itself only ever makes
> *outbound* connections to Discord — it works fine behind a normal home router with no port
> forwarding at all. The dashboard only needs to be reachable from whatever device(s) you
> actually use it from: a local IP (`http://192.168.x.x:8080`) is enough if that's just your
> own network. Public reachability (port forwarding + a domain, see
> [Nginx Proxy Manager](#nginx-proxy-manager) below) only matters if other moderators need to
> reach the dashboard from a *different* network than the one it's running on.

> **Raspberry Pi:** Supported on **Pi 3, 4 and 5**, running Raspberry Pi OS in either 64-bit (`aarch64`) or 32-bit (`armv7`) — same `docker compose up -d --build` command. A couple of Python dependencies (`psutil`, and `bcrypt`/`Pillow` on 32-bit) have no prebuilt wheel for ARM and get compiled from source during the build — the first build takes noticeably longer than on a regular PC/server (several minutes, more on an older Pi), later builds are unaffected since the image layer gets cached. **Pi Zero / Pi 1** (`armv6`) are not guaranteed — the Python base image this project builds on doesn't publish a dedicated armv6 build, and such old hardware would likely struggle with the bot's workload regardless.

### Android (Termux) — no Docker required

Android doesn't support Docker, so an old phone runs Phobos Bot as a plain Python process
under [Termux](https://termux.dev/) instead of a container. Get Termux from
[F-Droid](https://f-droid.org/packages/com.termux/) or its GitHub releases — the Play Store
build is outdated and no longer maintained.

```bash
pkg update && pkg upgrade
pkg install python git clang make rust libjpeg-turbo zlib openssl
git clone https://github.com/LucyWolf/phobos-bot.git
cd phobos-bot/app
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export PHOBOS_DATA_DIR="$HOME/phobos-data"
export PHOBOS_DB_PATH="$HOME/phobos-data/phobos.db"
python main.py
```

The dashboard is then reachable at `http://<phone-ip>:8080` from any other device on the same
network (find the phone's IP under Android's Wi-Fi settings). For 24/7 uptime:

- Disable battery optimization for Termux (Android **Settings → Apps → Termux → Battery →
  Unrestricted**) — otherwise Android kills the background process.
- Install [Termux:Boot](https://f-droid.org/packages/com.termux.boot/) and drop a start script
  under `~/.termux/boot/` to relaunch the bot automatically after a phone reboot.
- Keep the phone charging and connected to Wi-Fi.

The in-dashboard auto-updater (**Bot-Update** page) drives `docker compose` and doesn't apply
here — update with `git pull` inside the `phobos-bot` folder instead, then restart the process.
This path hasn't been tested on real hardware yet — if `pip install` fails compiling a
dependency, check which Termux `pkg` package provides the missing native library first.

Prefer an actual installable app over a terminal session? See [`android/README.md`](android/README.md)
for a Chaquopy-based Android Studio project that packages the same bot as a real APK with a
foreground service and a start/stop screen. **Confirmed working on real hardware** (tested on an
old Android 6 phone): builds into a working `app-debug.apk`, starts the bot automatically when
the app is opened, survives the screen being locked, and shows live CPU/RAM stats on the Bot-Info
page. The in-dashboard auto-updater works here too, unlike the Termux path above — it downloads
the latest APK straight from this repo's Releases and hands off to Android's own install prompt;
confirming that one tap is the only manual step left. A pre-built APK is available under
[Releases](https://github.com/LucyWolf/phobos-bot/releases) if you'd rather not build it
yourself.

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
2. In the dashboard (Admin only): **Settings → 🟣 Streaming-API** → add the app's Client ID + Secret. You can register more than one Twitch app here — each one is owned by the Admin who added it and can optionally be shared with specific other users
3. Per server: **Server → 🟣 Streaming** → add streamers (plain Twitch username, e.g. `ninja`, or a pasted channel URL — both work). If more than one Twitch app is visible to you, pick which one that server uses at the top of the page
4. Existing streamer entries can be edited (username, channel, custom ping message) via the ✏️ button, not just deleted and re-added

The bot checks every 3 minutes if registered streamers go live and posts a go-live embed once — not again on every subsequent check while they stay live.

---

## Free Stuff & Deals Setup

No API key required. In the dashboard under **Server → 🎁 Free Stuff**, free games and paid-but-discounted deals are configured independently — each with its own channel and its own platform selection, and each stays off until a channel is picked for it.

| Platform | Free games | Deals | Source |
|---|---|---|---|
| Epic Games | ✅ | — | Official Epic API |
| Steam | ✅ | ✅ | CheapShark API |
| GOG | ✅ | ✅ | CheapShark API |
| Humble Bundle | ✅ | ✅ | CheapShark API |
| Fanatical | ✅ | ✅ | CheapShark API |
| GreenManGaming | ✅ | ✅ | CheapShark API |
| EA App | ✅ | — | GamerPower API |
| Ubisoft Connect | ✅ | — | GamerPower API |
| Battle.net | ✅ | — | GamerPower API |
| itch.io | ✅ | — | GamerPower API |

Epic Games, EA App, Ubisoft Connect, Battle.net and itch.io have no public pricing API, so they only ever show up as free games, never as discounted deals. The bot checks every hour.

**Deals:** Optionally configure a max price (e.g. `5 €`) and a minimum discount (e.g. `75%`) — only games meeting both conditions get posted.

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
│   │   ├── automod.py      # Spam/link/word filtering
│   │   ├── reaction_roles.py
│   │   ├── logging_cog.py  # Event logging with audit log
│   │   ├── custom_commands.py
│   │   ├── tickets.py
│   │   ├── giveaways.py
│   │   ├── notifications.py  # Twitch live notifications
│   │   ├── freestuff.py      # Free stuff & deals
│   │   ├── auto_delete.py    # Auto-delete messages by channel
│   │   ├── temp_voice.py     # Join-to-Create temp voice channels
│   │   ├── scheduler.py      # Scheduled messages
│   │   └── birthday.py       # Birthday congratulations
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

<details>
<summary><strong>Inhaltsverzeichnis</strong></summary>

- [Features](#features-1)
  - [Bot-Funktionen](#bot-funktionen)
  - [Web-Dashboard](#web-dashboard-1)
- [Multi-Bot](#multi-bot-1)
- [Docker Compose](#docker-compose-1)
- [Willkommenskarte](#willkommenskarte)
- [Temporäre Voice-Kanäle](#temporäre-voice-kanäle)
- [Spam-Schutz / Auto-Moderation](#spam-schutz--auto-moderation)
- [Auto-Delete](#auto-delete-1)
- [Geplante Nachrichten](#geplante-nachrichten)
- [Discord-Events](#discord-events-1)
- [Geburtstags-System](#geburtstags-system)
- [Backup & Wiederherstellen](#backup--wiederherstellen)
- [Zwei-Faktor-Authentifizierung](#zwei-faktor-authentifizierung)
- [Event-Logging](#event-logging-1)
- [Berechtigungssystem](#berechtigungssystem)
- [Installation](#installation-1)
  - [Voraussetzungen](#voraussetzungen)
  - [Android (Termux) — ohne Docker](#android-termux--ohne-docker)
  - [Erster Start](#erster-start)
  - [Discord Developer Portal](#discord-developer-portal-1)
- [Updates](#updates-1)
  - [Automatisch (über Dashboard)](#automatisch-über-dashboard)
  - [Manuell (auf dem Server)](#manuell-auf-dem-server)
  - [RAM-Anzeige konfigurieren](#ram-anzeige-konfigurieren)
- [Twitch-Benachrichtigungen einrichten](#twitch-benachrichtigungen-einrichten)
- [Free Stuff & Deals einrichten](#free-stuff--deals-einrichten)
- [Nginx Proxy Manager](#nginx-proxy-manager-1)
- [Projektstruktur](#projektstruktur)
- [Technologie](#technologie)
- [Eine Anmerkung zu diesem Projekt](#eine-anmerkung-zu-diesem-projekt)

</details>

## Features

### Bot-Funktionen

| Feature | Details |
|---|---|
| **Moderation** | `/kick` `/ban` `/unban` `/timeout` `/warn` `/warnings` `/clearwarns` `/clear` |
| **Leveling / XP** | `/rank` `/leaderboard` `/setxp` — konfigurierbares XP pro Nachricht, Level-Up-Kanal, automatische Rollenvergabe ab einem gewählten Level, optionaler eigener Belohnungstext ab einem Level |
| **Willkommen** | Automatische Beitrittsnachrichten, Verlassensnachrichten, Auto-Rolle, **generierte Willkommenskarte** mit anpassbaren Farben |
| **Auto-Moderation** | Einstellbare Spam-Schwelle/-Zeitfenster, Link-Filter, Wort-Filter mit bearbeitbaren Schnellauswahl-Kategorien, einstellbare Aktion (warn/timeout/kick/ban) |
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
| **Discord-Events** | Native Discord-Events (Voice oder extern) direkt im Dashboard erstellen/bearbeiten, mit optionalen Erinnerungen und Start-/Ende-Ankündigungen in einem Kanal |

### Web-Dashboard

| Bereich | Funktion |
|---|---|
| **Dashboard** | Bot-Status, verbundene Server, Moderations-Statistiken — personalisiert pro Nutzer |
| **Pro Server** | Konfiguration, Spam-Schutz, Leveling, Reaction Roles, Commands, Tickets, Giveaways, Warnungen, Twitch, Free Stuff, Log, Temp Voice, Geplant, Events, Geburtstage, Auto-Delete, Bot-Design |
| **Server-Übersicht** | Alle verbundenen Server, Bot einladen |
| **🔑 Tokens** *(Admin)* | Mehrere Bot-Tokens verwalten – jeder Token startet einen eigenen Bot-Account, Hot-Reload ohne Neustart |
| **👥 Benutzer** *(Admin)* | Dashboard-Nutzer anlegen/löschen, Rolle und Server-Zugriff vergeben, **Backups erstellen & einspielen** |
| **🔐 Zwei-Faktor-Auth** | Optionale TOTP-2FA für den Dashboard-Login (Google Authenticator, Authy, etc.), mit einmaligen Backup-Codes |
| **📊 Bot-Info** | Version, Uptime, Latenz, CPU/RAM, Hostname, OS |
| **🔄 Updates** *(Admin)* | Aktuelle Version prüfen, One-Click-Update von GitHub |
| **🕐 Zeitzone** *(Ändern: Admin)* | Zeitzone für alle Zeitangaben im Dashboard konfigurieren |
| **🟣 Streaming-API** *(Admin)* | Eine oder mehrere Twitch-Apps (Client-ID + Secret) eintragen, optional für bestimmte Nutzer freigeben |
| **📧 E-Mail / SMTP** *(Admin)* | SMTP für Passwort-Reset konfigurieren |

---

## Multi-Bot

Phobos unterstützt **mehrere Bot-Accounts gleichzeitig**. Unter **Einstellungen → 🔑 Tokens** (nur Admin) können beliebig viele Discord Bot-Tokens eingetragen werden. Jeder Token startet einen eigenen Bot-Account — Bots starten und stoppen **sofort** ohne Container-Neustart.

- Die Token-Verwaltung selbst ist Admin-only
- Admins können Moderatoren einzelnen Bot-Tokens zuweisen — diese erhalten dadurch automatisch Zugriff auf die Server des jeweiligen Bots

---

## Docker Compose

```yaml
services:
  bot:
    build: ./app
    container_name: ${BOT_CONTAINER_NAME:-Phobos-Bot}
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./app:/app
      - ./data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/repo
    environment:
      - TZ=Europe/Berlin
      - PYTHONUNBUFFERED=1
    mem_limit: ${MEM_LIMIT:-1g}
    memswap_limit: ${MEM_LIMIT:-1g}
```

> Läuft eine zweite vollständige Instanz (eigenes Dashboard + Bot-Prozess, z.B. auf Port 8081) auf demselben Server? In der `.env` `BOT_CONTAINER_NAME` auf einen Namen setzen, der zu diesem Bot passt (z.B. `ZweiterBot`), damit `docker ps` zeigt, welcher Container zu welchem Bot gehört — sonst heißt standardmäßig jede Instanz `Phobos-Bot` und sie sind auf den ersten Blick nicht zu unterscheiden.

> Der `/var/run/docker.sock`-Mount erlaubt dem Dashboard direkten Zugriff auf die Docker Engine API (nötig für das One-Click-Update unter **Einstellungen → 🔄 Updates**). Der `.:/repo`-Mount gibt dem Container Zugriff auf das Git-Repository selbst, damit Updates den neuen Code per `git fetch` + `git reset --hard origin/main` holen können (kein normales `git pull` — das würde bei lokalen Abweichungen mit einem Konflikt fehlschlagen, der harte Reset überschreibt stattdessen absichtlich alles). Beide sind optional, falls Updates lieber manuell über die Server-Shell laufen sollen (`git pull` + `docker compose up -d --build`).

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

## Spam-Schutz / Auto-Moderation

Unter **Server → 🛡️ Spam-Schutz** (eigener Reiter, getrennt von der allgemeinen Konfiguration):

- **Spam-Schwelle & Zeitfenster** — z.B. ab 5 Nachrichten in 5 Sekunden, beides einstellbar
- **Link-Filter** — blockiert Nachrichten mit URLs oder Discord-Einladungen
- **Wort-Filter** — blockiert Nachrichten mit verbotenen Wörtern, matcht auf ganze Wörter (ein verbotenes Wort wie "ass" löst also nicht bei "Class" aus)
- **Aktion bei Verstoß** — Warnung (landet in `/warnings`), Timeout (Dauer einstellbar, bis zu Discords 28-Tage-Maximum), Kick oder Bann
- **Eigene Warn-DM** — wird bei jedem Verstoß an das Mitglied gesendet, mit `{server}`/`{reason}`-Platzhaltern

Mitglieder mit der Berechtigung **Nachrichten verwalten** sind immer ausgenommen.

**Wortlisten-Kategorien:** statt verbotene Wörter von Hand einzutippen, fügen Schnellauswahl-Buttons über dem Wörter-Feld eine ganze Kategorie auf einmal hinzu (ohne Vorhandenes zu ersetzen). Kategorien sind pro Server frei bearbeitbar — anlegen, umbenennen, Wörter ändern oder löschen unter "🗂️ Wortlisten-Kategorien" weiter unten im selben Reiter. Ein paar Start-Kategorien (Spam-Floskeln, Nitro-Köder, Krypto-Scam, NS-Bezüge) sind beim ersten Aufruf schon vorausgefüllt — können aber frei angepasst oder gelöscht werden.

---

## Auto-Delete

Unter **Server → Auto-Delete** kann festgelegt werden, in welchen Kanälen Nachrichten automatisch nach einer bestimmten Zeit (5 Min. – 7 Tage) gelöscht werden. Änderungen gelten sofort ohne Neustart, und geplante Löschungen bleiben auch bei einem Bot-Neustart dazwischen erhalten. Der Bot braucht dafür die Berechtigung **Nachrichten verwalten** im jeweiligen Kanal.

---

## Geplante Nachrichten

Unter **Server → Geplant** können Nachrichten für einen beliebigen Kanal zu einem bestimmten Datum und einer Uhrzeit eingeplant werden. Ideal für Ankündigungen, Erinnerungen oder regelmäßige Ereignisse.

---

## Discord-Events

Unter **Server → Events** lassen sich native Discord-Events direkt im Dashboard erstellen — entweder an einen Voice-Kanal gebunden oder als "externes" Event (freier Ort, z.B. ein Spiel oder eine Location außerhalb Discords). Events können bearbeitet werden, solange sie noch nicht gestartet sind; sobald Discord sie als aktiv oder beendet markiert, bleibt nur noch Löschen.

Optionale Extras beim Erstellen:
- **Ankündigungskanal** — der Bot postet dort automatisch eine Nachricht, sobald das Event startet (und optional, wenn es endet), mit Name, Zeit, Ort und einem Link zum Event
- **Erinnerungen** — beliebig viele eigene Nachrichten, die eine wählbare Anzahl Minuten vor Start gepostet werden

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

## Zwei-Faktor-Authentifizierung

Jeder Dashboard-Nutzer kann unter **Profil → Zwei-Faktor-Authentifizierung** TOTP-basierte 2FA aktivieren — kompatibel mit Google Authenticator, Authy, Aegis und ähnlichen Apps. Nach einmaliger Bestätigung mit dem Code aus der App werden 8 Backup-Codes angezeigt (für den Notfall, falls das Handy verloren geht); sie lassen sich jederzeit mit dem Passwort neu erstellen. Der Login verlangt danach zusätzlich zum Passwort den App-Code (oder einen Backup-Code); wiederholt falsche Codes sperren das Konto vorübergehend.

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

Bewusst einfach gehalten — nur zwei Rollen, keine konfigurierbaren Berechtigungssets:

| Rolle | Rechte |
|---|---|
| **Admin** | Alles: globale Einstellungen, Benutzerverwaltung, Bot-Tokens, Streaming-API-Zugangsdaten, SMTP, Updates, Bot-Design und jeder verbundene Server |
| **Moderator** | Nur die Server, die ihm unter **Benutzer** explizit freigegeben wurden, oder automatisch über einen zugewiesenen Bot-Token. Manche rein lesbaren Seiten (z.B. Bot-Info) bleiben trotzdem sichtbar |

Das allererste Konto (`admin` / `admin`, siehe Installation weiter unten) ist immer Admin. Es muss immer mindestens ein Admin existieren — das Dashboard verhindert das Herabstufen oder Löschen des letzten verbleibenden.

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

> **Muss das aus dem Internet erreichbar sein?** Nein. Der Bot selbst baut nur *ausgehende*
> Verbindungen zu Discord auf — läuft problemlos hinter einem normalen Heimrouter, ganz ohne
> Portfreigabe. Das Dashboard muss nur von den Geräten aus erreichbar sein, von denen du es
> tatsächlich nutzt: eine lokale IP (`http://192.168.x.x:8080`) reicht, wenn das nur dein
> eigenes Netzwerk ist. Öffentliche Erreichbarkeit (Portfreigabe + Domain, siehe
> [Nginx Proxy Manager](#nginx-proxy-manager-1) weiter unten) braucht's nur, wenn andere Mods
> das Dashboard aus einem *anderen* Netzwerk erreichen sollen als dem, in dem es läuft.

> **Raspberry Pi:** Unterstützt auf **Pi 3, 4 und 5**, mit Raspberry Pi OS in 64-bit (`aarch64`) oder 32-bit (`armv7`) — gleicher Befehl `docker compose up -d --build`. Ein paar Python-Abhängigkeiten (`psutil`, sowie auf 32-bit zusätzlich `bcrypt`/`Pillow`) haben kein fertiges Wheel für ARM und werden beim Bauen aus dem Quellcode kompiliert — der erste Build dauert dadurch spürbar länger als auf einem normalen PC/Server (mehrere Minuten, auf älteren Pi-Modellen mehr), spätere Builds sind davon nicht betroffen da die Image-Schicht gecacht wird. **Pi Zero / Pi 1** (`armv6`) sind nicht garantiert — das Python-Basis-Image dieses Projekts hat kein eigenes armv6-Build, und so alte Hardware wäre mit der Bot-Last vermutlich ohnehin überfordert.

### Android (Termux) — ohne Docker

Android unterstützt kein Docker, deshalb läuft Phobos Bot auf einem alten Handy als normaler
Python-Prozess unter [Termux](https://termux.dev/) statt in einem Container. Termux gibt's über
[F-Droid](https://f-droid.org/packages/com.termux/) oder die GitHub-Releases — die Play-Store-
Version ist veraltet und wird nicht mehr gepflegt.

```bash
pkg update && pkg upgrade
pkg install python git clang make rust libjpeg-turbo zlib openssl
git clone https://github.com/LucyWolf/phobos-bot.git
cd phobos-bot/app
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export PHOBOS_DATA_DIR="$HOME/phobos-data"
export PHOBOS_DB_PATH="$HOME/phobos-data/phobos.db"
python main.py
```

Das Dashboard ist danach unter `http://<handy-ip>:8080` von jedem anderen Gerät im selben
Netzwerk erreichbar (IP steht in Androids WLAN-Einstellungen). Für dauerhaften Betrieb:

- Akku-Optimierung für Termux deaktivieren (Android **Einstellungen → Apps → Termux → Akku →
  Uneingeschränkt**) — sonst killt Android den Hintergrundprozess.
- [Termux:Boot](https://f-droid.org/packages/com.termux.boot/) installieren und ein Start-
  Skript unter `~/.termux/boot/` ablegen, damit der Bot nach einem Neustart automatisch
  wieder anläuft.
- Handy dauerhaft am Ladekabel und im WLAN lassen.

Der eingebaute Auto-Updater im Dashboard (**Bot-Update**-Seite) steuert `docker compose` und
greift hier nicht — stattdessen im `phobos-bot`-Ordner mit `git pull` aktualisieren und den
Prozess neu starten. Dieser Weg ist noch nicht an echter Hardware getestet — falls `pip install`
beim Kompilieren einer Abhängigkeit scheitert, zuerst prüfen welches Termux-`pkg`-Paket die
fehlende native Bibliothek bereitstellt.

Lieber eine echte installierbare App statt Terminal-Sitzung? Siehe [`android/README.md`](android/README.md)
für ein Chaquopy-basiertes Android-Studio-Projekt, das denselben Bot als echte APK mit
Foreground-Service und Start/Stop-Bildschirm verpackt. **Bestätigt funktionsfähig auf echter
Hardware** (getestet auf einem alten Android-6-Handy): baut zu einer funktionierenden
`app-debug.apk`, startet den Bot automatisch beim Öffnen der App, übersteht das Sperren des
Bildschirms, und zeigt echte CPU/RAM-Werte auf der Bot-Info-Seite an. Der eingebaute
Auto-Updater im Dashboard funktioniert hier ebenfalls, anders als beim Termux-Weg oben — er lädt
die neueste APK direkt aus den Releases dieses Repos herunter und übergibt an Androids eigenen
Installations-Dialog; dieser eine Bestätigungs-Tap ist der einzige verbleibende manuelle
Schritt. Eine fertig gebaute APK gibt's unter
[Releases](https://github.com/LucyWolf/phobos-bot/releases), falls du sie nicht selbst bauen
willst.

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
2. Im Dashboard (nur Admin): **Einstellungen → 🟣 Streaming-API** → Client-ID + Secret der App eintragen. Es können mehrere Twitch-Apps registriert werden — jede gehört dem Admin, der sie angelegt hat, und kann optional für bestimmte andere Nutzer freigegeben werden
3. Pro Server: **Server → 🟣 Streaming** → Streamer hinzufügen (einfacher Twitch-Benutzername, z.B. `ninja`, oder ein eingefügter Kanal-Link — beides funktioniert). Sind mehrere Twitch-Apps für dich sichtbar, kann oben auf der Seite ausgewählt werden, welche dieser Server verwendet
4. Bereits eingetragene Streamer lassen sich über den ✏️-Button bearbeiten (Benutzername, Kanal, eigene Ping-Nachricht), nicht nur löschen und neu anlegen

Der Bot prüft alle 3 Minuten ob eingetragene Streamer live gehen und postet dann einmalig ein Embed — nicht erneut bei jeder weiteren Prüfung solange der Stream weiterläuft.

---

## Free Stuff & Deals einrichten

Kein API-Key nötig. Im Dashboard unter **Server → 🎁 Free Stuff** laufen Gratis-Spiele und bezahlte-aber-reduzierte Angebote komplett unabhängig voneinander — jeweils mit eigenem Kanal und eigener Plattform-Auswahl, und beide bleiben aus bis dort ein Kanal ausgewählt wird.

| Plattform | Gratis-Spiele | Angebote | Quelle |
|---|---|---|---|
| Epic Games | ✅ | — | Offizielle Epic-API |
| Steam | ✅ | ✅ | CheapShark API |
| GOG | ✅ | ✅ | CheapShark API |
| Humble Bundle | ✅ | ✅ | CheapShark API |
| Fanatical | ✅ | ✅ | CheapShark API |
| GreenManGaming | ✅ | ✅ | CheapShark API |
| EA App | ✅ | — | GamerPower API |
| Ubisoft Connect | ✅ | — | GamerPower API |
| Battle.net | ✅ | — | GamerPower API |
| itch.io | ✅ | — | GamerPower API |

Epic Games, EA App, Ubisoft Connect, Battle.net und itch.io haben keine öffentliche Preis-API und tauchen deshalb nur als Gratis-Spiele auf, nie als Angebot. Der Bot prüft stündlich.

**Angebote:** Optional Max-Preis (z.B. `5 €`) und Mindest-Rabatt (z.B. `75%`) konfigurierbar — nur Spiele, die beide Bedingungen erfüllen, werden gepostet.

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
│   │   ├── automod.py        # Spam-/Link-/Wort-Filter
│   │   ├── reaction_roles.py
│   │   ├── logging_cog.py    # Event-Logging mit Audit-Log
│   │   ├── custom_commands.py
│   │   ├── tickets.py
│   │   ├── giveaways.py
│   │   ├── notifications.py  # Twitch Live-Benachrichtigungen
│   │   ├── freestuff.py      # Free Stuff & Deals
│   │   ├── auto_delete.py    # Automatisches Löschen nach Zeit
│   │   ├── temp_voice.py     # Join-to-Create Temp-Voice-Kanäle
│   │   ├── scheduler.py      # Geplante Nachrichten
│   │   └── birthday.py       # Geburtstags-Glückwünsche
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
