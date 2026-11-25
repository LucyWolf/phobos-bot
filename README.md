<div align="center">

# 🛡️ Phobos Bot

**A self-hosted Discord bot with a full web dashboard.**
Open source, free, no subscription.

![Version](https://img.shields.io/badge/version-1.18.51-7c3aed)
![Python](https://img.shields.io/badge/Python-3.11-3776ab)
![Docker](https://img.shields.io/badge/Docker-ready-2496ed)
![Self-hosted](https://img.shields.io/badge/self--hosted-yes-22c55e)

🇬🇧 [English](#english) &nbsp;·&nbsp; 🇩🇪 [Deutsch](#deutsch)

</div>

---

<a name="english"></a>
# 🇬🇧 English

A self-hostable Discord bot with a full web dashboard. Open source, free, forever.

<details>
<summary><strong>Table of contents</strong></summary>

- [Features](#features)
  - [Bot Features](#bot-features)
- [Multi-Bot](#multi-bot)
- [Docker Compose](#docker-compose)
- [Resource limits](#resource-limits-for-small-machines--step-by-step)
- [Leveling / XP](#leveling--xp)
- [Welcome Card](#welcome-card)
- [Temp Voice Channels](#temp-voice-channels)
- [Spam Protection / Auto-Moderation](#spam-protection--auto-moderation)
- [Auto-Delete](#auto-delete)
- [Auto-Thread](#auto-thread)
- [VRC-Link (VRChat)](#vrc-link-vrchat)
- [Profiles](#profiles)
- [Plugins](#plugins)
- [Scheduled Messages](#scheduled-messages)
- [Discord Events](#discord-events)
- [CrossVerification](#crossverification)
- [Polls](#polls)
- [Ratings](#ratings)
- [Gameserver (AMP)](#gameserver-amp)
- [Auto-Kick](#auto-kick)
- [Embed Messages](#embed-messages)
- [Birthday System](#birthday-system)
- [Working with lists](#working-with-lists)
- [Backup & Restore](#backup--restore)
- [Two-Factor Authentication](#two-factor-authentication)
- [Security](#security)
- [Event Logging](#event-logging)
- [Bug & Feature Reports](#bug--feature-reports)
- [Permission System](#permission-system)
- [Installation](#installation)
  - [Requirements](#requirements)
  - [Android (Termux) — no Docker required](#android-termux--no-docker-required)
  - [First Start](#first-start)
  - [Discord Developer Portal](#discord-developer-portal)
- [Updates](#updates)
  - [Automatic (via Dashboard)](#automatic-via-dashboard)
  - [Manual (on the server)](#manual-on-the-server)
- [Twitch Notifications Setup](#twitch-notifications-setup)
- [Free Stuff & Deals Setup](#free-stuff--deals-setup)
- [Nginx Proxy Manager](#nginx-proxy-manager)
- [Project Structure](#project-structure)
- [Tech Stack](#tech-stack)
- [A Note on This Project](#a-note-on-this-project)

</details>

## Features

### Bot Features

*Updated 18 November 2026.* The short version — what the bot can do. Everything below this table is the long one: settings, limits and the reasoning behind them.

| Feature | What it does |
|---|---|
| **Moderation** | Kick, ban, timeout and warn — from Discord or the dashboard, with a warning history that stays |
| **Leveling / XP** | Members earn XP for chatting and for hanging out in voice, climb levels and get roles for it |
| **Welcome** | Greets every newcomer with a generated welcome card — your colours, your background, your words |
| **Auto-Moderation** | Catches spam, links and words you would rather not read, and warns, mutes, kicks or bans on its own |
| **Reaction Roles** | Members pick their own roles by clicking an emoji |
| **Event Logging** | Keeps a record of what happens on the server — and shows who deleted a message |
| **Custom Commands** | Your own commands, without writing a line of code |
| **Tickets** | A button turns a question into a private ticket channel — support role, category, archive when it closes. One open ticket per category, so a pending verification does not block a report |
| **Giveaways** | Run a giveaway in one click; the bot draws, announces and DMs the winners |
| **Twitch Notifications** | Tells your channel the moment one of your streamers goes live |
| **Free Stuff & Deals** | Posts free games and the deals you care about, by itself |
| **Auto-Delete** | Keeps chosen channels tidy by clearing messages after a time you set |
| **Auto-Thread** | Gives every message in a channel its own thread, named the way you want |
| **VRC-Link** | Members link their VRChat account, prove it is really theirs, and wear their VRChat name on Discord |
| **VRChat group** | Sees who is in your group, hands out the matching Discord role, and sends invites on request |
| **VRChat instances** | Spots every lobby your group opens and announces it — live head count, join button, your own words |
| **Temp Voice** | Join one channel and get your own; it disappears when the last person leaves |
| **Scheduled Messages** | Write it now, let the bot post it later, in any channel |
| **Birthday System** | Members drop their birthday in chat, the bot congratulates them on the day |
| **Discord Events** | Plans real Discord events from the dashboard — reminders, announcements, and repeats if you want |
| **CrossVerification** | Rules of the shape "has this role → gets that one", even onto another server — and cooperations with partner communities running their own Phobos: whoever they vetted is let through here automatically |
| **Polls** | Polls with pictures, a live ranking and a start time |
| **Ratings** | A star list your members keep rating — maps, games, servers, anything |
| **Gameserver (AMP)** | Start, stop and watch your game servers without leaving Discord |
| **Auto-Kick** | Shows still-unverified members the door after a deadline — with reminders first |
| **Embed Messages** | Build a good-looking announcement in the dashboard and post it anywhere |
| **Profiles** | Members fill in what should be known about them, and a VRChat world can read what they released |
| **Plugins** | Packages of settings — commands, ticket panels, rewards — built once, exported, and applied to any server. A plugin can also serve released data to a VRChat world |

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
    image: phobos-bot:latest
    container_name: ${BOT_CONTAINER_NAME:-Phobos-Bot}
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./app:/app
      - ./data:/app/data
      - .:/repo
    environment:
      - TZ=Europe/Berlin
      - PYTHONUNBUFFERED=1
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - DAC_OVERRIDE
      - FOWNER
      - SETUID
      - SETGID
    security_opt:
      - no-new-privileges:true
    logging:
      driver: json-file
      options:
        max-size: "20m"
        max-file: "5"
```

Then:

```bash
docker compose up -d --build
```

The dashboard is at `http://<server>:8080`. First login is `admin` / `admin` — change it right away.

`BOT_CONTAINER_NAME` only matters if you run several instances on one server; without it the container is called `Phobos-Bot`. Nothing else needs configuring on the server side — the Discord token and everything else goes in through the dashboard.

> The `.:/repo` mount gives the container access to the git repository itself, so the one-click update under **Settings → 🔄 Updates** can fetch and hard-reset to the new code (`git fetch` + `git reset --hard`, not a plain `git pull` — this forcibly overwrites any local drift instead of risking a merge conflict). **Leave it out and the dashboard update cannot work at all** — it is only dispensable if you update manually from the server shell (`git pull` + `docker compose up -d --build`). The folder it points at has to be a real `git clone`, not a copy of the files.
>
> There is deliberately **no** `/var/run/docker.sock` mount. Handing the Docker socket to a container is effectively root on the host; the update restarts the process by itself instead, and `restart: unless-stopped` brings it back.

> **The bot does not run as root.** Its container starts as user `1000`, drops every Linux capability it doesn't need (`cap_drop: ALL`) and cannot gain any back (`no-new-privileges`). Because the mounted folders (`app/`, `data/`, the repository) belong to whoever created them on the host, the container's start script fixes their ownership on every start before handing over — so an existing installation keeps working without anyone touching a single file by hand.
>
> Set `PUID`/`PGID` if your files belong to a different user id. If ownership cannot be changed at all (NFS, Docker Desktop, exFAT), the start script says so in the container log and keeps the bot running as before rather than leaving you with a container that won't come up. `PHOBOS_ROOT=1` forces the old behaviour.
>
> **One thing afterwards:** the repository now belongs to the bot, not to root. Using `git` in it as root on the server therefore prints "detected dubious ownership" — fixed once with `git config --global --add safe.directory /path/to/phobos-bot`, after which a manual `git pull` works as before. Creating files there as root (a `git pull`, a quick edit) leaves root-owned files behind again; the container's next start straightens that out by itself.
>
> If the data folders of **other** instances sit in the same directory (`data-xyz/`), they are left alone: only what git tracks gets touched.
>
> This takes effect when the image is **rebuilt** (`docker compose up -d --build`). An update from the dashboard only fetches new code and restarts the process — it does not rebuild the image, so a running installation changes nothing until you rebuild it yourself.

> **The `logging` block is not optional in practice.** Without it Docker writes the bot's output into a file that never gets smaller. On 2 November 2026 one of those had grown to 21 GB and filled the server's disk — the bot kept running the whole time and it only showed up when nothing could be saved any more. 20 MB × 5 files caps it at 100 MB per container.
>
> Docker applies this when a container is **created**, so adding it to an existing installation needs `docker compose up -d`, not a restart. To limit by *time* rather than size, use `tools/logrotate-phobos.conf` — Docker itself only knows size and count.

### Resource limits (for small machines) — step by step

`docker-compose.yml` has three lines that are **commented out by default**, so a normal
install ignores them:

```yaml
    #mem_limit: 512m
    #pids_limit: 200
    #cpus: "1.0"
```

On a regular server you don't need these. On a **Raspberry Pi 4/5** or any small box where
several containers share a little RAM, they keep one runaway container from taking the whole
machine down. **`mem_limit` and `pids_limit` are a ceiling, not a throttle** — the bot takes
what it needs below them and never notices they're there; they only act when something breaks
loose. **`cpus` is different: it really does throttle.** Leave it off unless you want to hold
the bot back on purpose.

**1 — See what the bot actually uses.** On the host:
```bash
docker stats --no-stream <container-name>
```
Look at the `MEM USAGE` column. Phobos normally sits well under 300 MB.

**2 — Pick a memory ceiling comfortably above that.** Roughly double the usage, and at least
256–512 MB. Too low and Docker kills the bot (see step 6); generous is fine — the ceiling
only matters when something runs away.

**3 — Edit `docker-compose.yml`.** Remove the `#` in front of the lines you want and set the
values. For a Pi, memory and process count are the useful two:
```yaml
    mem_limit: 512m
    pids_limit: 200
```
Add `cpus: "1.0"` (at most one core) only if you deliberately want to cap CPU.

**4 — Apply it.** In the folder with `docker-compose.yml`:
```bash
docker compose up -d
```
This **re-creates** the container. A plain restart does **not** apply new limits — Docker
only reads them when a container is created.

**5 — Check it took.**
```bash
docker inspect <container-name> --format 'mem={{.HostConfig.Memory}} pids={{.HostConfig.PidsLimit}}'
```
`mem` is the limit in bytes (`536870912` for 512 MB), `pids` the process cap. Both non-zero
means it's active.

**6 — If the bot keeps restarting, the limit is too low.** `docker ps` showing constant
restarts, or an exit code `137`, means Docker ran it out of memory (OOM-killed). Raise
`mem_limit` and run `docker compose up -d` again.

**To remove the limits:** put the `#` back and run `docker compose up -d` once more.

### Without Compose

The same thing as a single command — useful if you only want to try it out:

```bash
# once, in the directory you cloned into:
docker build -t phobos-bot:latest ./app

docker run -d \
  --name Phobos-Bot \
  --restart unless-stopped \
  -p 8080:8080 \
  -v "$PWD/app:/app" \
  -v "$PWD/data:/app/data" \
  -v "$PWD:/repo" \
  -e TZ=Europe/Berlin \
  -e PYTHONUNBUFFERED=1 \
  -e PUID=1000 -e PGID=1000 \
  --cap-drop ALL \
  --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
  --cap-add SETUID --cap-add SETGID \
  --security-opt no-new-privileges:true \
  --log-opt max-size=20m --log-opt max-file=5 \
  phobos-bot:latest
```

> The two `--log-opt` flags are the ones people leave off, and they are the ones that bite: without them Docker writes the output into a file that never gets smaller. See the note under Docker Compose above.

Updating then means doing by hand what Compose does for you:

```bash
git pull && docker build -t phobos-bot:latest ./app \
  && docker rm -f Phobos-Bot && docker run -d ...   # same line as above
```

Compose is the shorter road for anything you keep running — the `docker run` line is here so you can see what it actually does.

---

## Leveling / XP

Under **Server → 🏆 Leveling**, text messages and time spent in voice channels are tracked as two **independent** progressions — a member has both a text level and a voice level, each with its own XP curve.

- **XP curve** — the amount of XP needed per level follows `quadratic·level² + linear·level + base` (defaults: 5/50/100); all three numbers are configurable separately for text and voice, so the pacing can be tuned per server
- **Channel restriction** — optionally limit which channels count toward text XP (empty = all channels)
- **Level roles** — assign a role once a member reaches a given level (either track), either **stacking** every role earned so far or **replacing** the previous one with the newest
- **Level rewards** — an optional custom text shown in the level-up announcement at a specific level, independent of any role

---

## Welcome Card

When a member joins, the bot can send a **generated image card** instead of a plain text embed, with a live preview in the dashboard while editing:

- **Avatar shape** — circle, hexagon, octagon, square, or diamond, with a configurable border color
- **Layout** — avatar on the left, right, or centered above the text
- **Text** — a freely editable heading and subtitle (no longer fixed to "WELCOME"), supporting the same `{user}`/`{username}`/`{server}`/`{count}` placeholders as the plain welcome message
- **Background** — a custom uploaded image, or the default color gradient
- **Overlay** — an optional image layered on top of everything (your own upload, or one of four bundled presets: shattered glass, hearts, pub, summer/tropical)
- All colors freely configurable under **Server → Config**

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

## Auto-Thread

Under **Server → Auto-Thread** you pick the channels in which **every message automatically gets its own thread** — the usual case being introduction, application or showcase channels where each post should have its own discussion instead of everything running together in the main channel.

Per channel you can set:

- **Thread name** — a template with `{user}` (the author), `{text}` (the start of the message) and `{date}`. If a placeholder renders empty (an image-only post, for instance), the name falls back to the author's name instead of failing.
- **Archive after** — 1 hour, 24 hours, 3 days or 7 days (Discord's four allowed values)
- **Opening message** — optional first post inside the new thread, `{user}` mentions the author
- **Skip bot messages** (on by default) and **only for messages with an attachment** (off by default)

Requires the **Create Public Threads** permission in that channel. Deliberately skipped: messages that are already inside a thread (forum posts included, since those are technically threads), system notices such as joins or pins, and messages that already have a thread attached.

---

## VRC-Link (VRChat)

Links a member's **VRChat account to their Discord account**, and from there connects the server to the VRChat **group** and its **lobbies**. A linked member gets a role and carries their VRChat name as their Discord nickname.

**Once for the whole bot:** under **Settings → VRC Account Link**, connect the account the bot signs in as — a **separate account, not your main one**, because VRChat's API is unofficial and an account that hammers it can be suspended. Two-factor is supported: the bot asks for a one-time code and keeps the session (about a month), so the secret never has to be stored. The page shows the last check and the last error, if there was one.

Everything else lives under **Server → 🔗 VRC-Link**, in two sub-tabs.

### Linking

- **Role** for linked members and a **nickname template** (`{vrchatName}`, `{discordName}`) with a live preview, clamped to Discord's 32 characters
- **Linking button** — the bot posts a message with a button in a channel you pick; heading, text and caption are yours. `/vrc-link` does the same, and new arrivals can get their link by **DM on join**
- **Proof of ownership** (on by default) — the member puts a short code such as `PHOBOS-K7M2QD` into their **VRChat status message**. Switched off, a typed name is enough and the link carries no "ownership confirmed" badge
- **Approve automatically** (off by default) — otherwise every link waits for a moderator
- **Link validity** in minutes, 1 to 1440, default 60
- **Check a VRChat profile** — a read-only lookup showing what VRChat returns for a name and the exact text the ownership check reads, so "the code is right there" and "the bot cannot see that field" stop looking alike

**How a member links:** button or `/vrc-link` → a **personal link**, valid only for them → they type their VRChat name (the bot adopts VRChat's own spelling) → paste the code into their status message and press "Check now" → role and nickname follow, at once or after a moderator approves. The page **sets no cookies**: the key travels inside the forms and never in the address, so it stays out of proxy logs, browser history and `Referer` headers; a countdown shows how long the door stays open. The page **never asks for a VRChat password** — anything that does is phishing, whoever it claims to be. Once linked it shows the account's badges (ownership confirmed, 18+ verified, VRChat+, trust rank) and offers refresh and unlink.

**VRChat group (optional).** Enter a **group ID** (`grp_…`) and the bot checks, after every confirmation and refresh, whether the linked account is in it — optionally handing out a Discord role for that and taking it back when somebody leaves. Members can request an **invite** from their own page. The bot account has to be in the group itself and needs its invite permission, and no permission can be granted before it is in: *Check status* and *Join group* handle that from the dashboard (open groups admit it at once, request-based ones file a request, invite-only ones need it invited there first). Checked only when somebody is waiting anyway, never on a timer.

**Discord role → VRChat group role.** Map one to the other: hold the Discord role, get the group role. Changes take effect immediately and in both directions — a role given or taken, a mapping added or deleted, somebody unlinking or leaving the Discord server; the interval (`0` = only on linking) is a safety net, not the mechanism. The sync compares against the state it last wrote, so nothing changed means no VRChat request at all. **Two Discord servers on one group** — a NA and a EU server, say — do not fight over it: neither takes away a role the other still holds. The bot account needs the group's permission to manage roles, and its own role above the ones it hands out.

### Instances

The bot notices by itself when the group opens a lobby and posts a card in the channel you pick: world name (clickable), world image, head count, **join button**, optional role ping, and your own text (`{world}`, `{count}`, `{group}`, `{link}`, `{name}`). The count keeps updating while the lobby runs. VRChat knows three states, each with its own heading and text:

- **open** — the card as described
- **closed** (shut to new arrivals, the people inside stay) — recognised only with **Look closer** on, which costs one extra VRChat request per open lobby per run, five at most; the card turns orange and loses its join button
- **ended** — gone from the group listing: the card becomes a **farewell text** (`{duration}`) and, if you want, deletes itself after a delay you set

The first run only records what is already open, so switching the feature on does not drop every running lobby into the channel at once, and each lobby is announced exactly once. A run costs **one** VRChat request for the whole server; only *Look closer* adds more. Deleting cards needs "Manage Messages".

**Debug report.** One button prints, ready to copy, everything the bot can see on the VRChat side: the settings in force, the bot account (without password, secret or session cookie), the group, its roles and your mappings, every open lobby raw, a separate lookup per lobby with the state and name fields pulled out, the bot's own stored state, and how many members are linked. It only reads and changes nothing.

The link address is taken from the address you have the dashboard open at — the same way the invite link in the user administration works, so there is nothing to configure. A **base address** set in the settings wins over it.

---

## Profiles

Members fill in what should be known about them with `/bio`, `/kinks`, `/triggers` and
`/limits`, and look at other people's entries with `/inspect`. `/profil` shows your own,
`/profil-loeschen` removes everything. Every reply is only visible to the person who asked —
a profile is never posted into a channel.

**18+ is required** for kinks, triggers and limits, not for the bio. Either the VRChat age
verification from VRC-Link counts as proof, or a role the server picks for it. Somebody
without proof may still look at profiles — they just see the bio and nothing else, and the
answer is the same one they get for an empty profile, so it never gives away that something
is hidden.

Switch it on under **Server → 🪪 Profiles**, where you also pick the 18+ role and who may use
`/inspect`.

### Reading profiles from a VRChat world

A world can fetch the entries over a read address of its own. Three things have to line up,
and all three are deliberate:

1. the server has **Display in the VRChat world** enabled,
2. the request carries that server's **key** (at least 20 characters, set on the same page),
3. the person has **released their own profile** for it — the button under `/profil`.

Without the release the world gets nothing, key or no key. Writing something down is not
publishing it.

```
GET  https://your-dashboard/api/profil?key=<KEY>&vrc=<VRCHAT NAME OR ID>
```

`vrc` takes either the VRChat display name or the `usr_…` id. The lookup goes through the
VRC-Link table, so only members who linked their VRChat account can be found at all.

```json
{
  "gefunden": true,
  "vrchat_name": "LucyVR",
  "felder": [
    {"feld": "bio",      "text": "…", "geaendert": "2026-11-17 15:04", "erwachsen": false},
    {"feld": "kinks",    "text": "…", "geaendert": "2026-11-17 15:04", "erwachsen": true},
    {"feld": "triggers", "text": "…", "geaendert": "2026-11-17 15:04", "erwachsen": true},
    {"feld": "limits",   "text": "…", "geaendert": "2026-11-17 15:04", "erwachsen": true}
  ]
}
```

Fields come in a fixed order (bio, kinks, triggers, limits) and only the filled ones are
included. `gefunden: false` with an empty list means: unknown name, nothing written, or
nothing released — the answer is the same for all three on purpose, so the address cannot be
used to find out who has what.

| Status | Means |
|---|---|
| `200` | Answer as above, `gefunden` tells you whether there is anything. |
| `400` | `key` or `vrc` missing. |
| `403` | Wrong key, or the display is switched off for that server. |
| `429` | More than 60 requests a minute from your address. |

**`erwachsen` is yours to act on.** Inside Discord those fields sit behind an age check. A
VRChat world has no such thing — whatever stands on a board is read by whoever walks past it.
The flag is in the answer so your UI can decide: show the bio to everyone and keep the rest
behind a button, a separate room, or your own 18+ gate. The bot cannot make that call for you.

### What to expect from VRChat itself

- **Untrusted URLs.** VRChat only loads strings from a short list of trusted hosts
  (`*.github.io`, `gist.githubusercontent.com`, `pastebin.com`, `*.disbridge.com`,
  `*.vrcdn.cloud`, `assets.vrchat.com`). A self-hosted dashboard is not on it, so every
  visitor needs **Allow Untrusted URLs** switched on in their settings, or they see nothing.
  Plan for that in the world: say so on the board instead of showing an empty panel. For
  public instances the domain also has to be added to the world's allowed hosts on
  vrchat.com. The current list is served by VRChat's own config endpoint as
  `stringHostUrlList` and can change.
- **Mirroring to a trusted host is not the answer.** Pastebin or a gist would load without
  that setting — and would also put the released profile data on a public address that
  nothing ever takes back. That is exactly why this endpoint exists.
- **One download at a time.** `VRCStringDownloader` has a global cooldown of about five
  seconds across the whole world. Fetch once when a player comes into range, keep the result,
  and queue rather than calling it per frame.
- **HTTPS.** Put the dashboard behind a proxy with a certificate; the key travels in the
  address.

In Udon: `VRCStringDownloader.LoadUrl(url, (IUdonEventReceiver)this)`, then read
`result.Result` in `OnStringLoadSuccess`. `VRCUrl` cannot be built from a string at runtime,
so the address has to sit in a public `VRCUrl` field — one per world, with the key in it.

---

## Plugins

A plugin is a **package of settings**, not a program. One JSON file describes what should be
created — commands, a ticket panel with its categories, level rewards, auto-mod word lists —
and the bot creates it. You can export it, hand it to someone else, and they can apply it to
their own server.

> 📂 **Ready-made examples to copy:** [`tools/plugin-beispiele/`](tools/plugin-beispiele/) — upload one and it runs. Each carries a data-point section and a note on checking it in the 🐞 console.

**A plugin executes no code.** That is deliberate and not a temporary limitation: a Python
plugin would run in the same process as the bot, with access to the bot token, the whole
database (dashboard emails, password hashes, 2FA secrets) and the host's filesystem. Python
offers no sandbox that reliably prevents this. Whoever could upload a plugin would own the
bot. A description cannot do that: it is read, validated, and written into exactly the
tables listed below.

### Where things live

| | |
|---|---|
| **Settings → Plugins** | the installation's plugins: import, export, delete, and add to a server |
| **a server's sidebar** | one entry per plugin running on that server, by its own icon and name |

Importing a plugin applies it to nothing. Under **Settings → Plugins** you then pick a
server for it and fill in that server's values. From there on the plugin shows up in that
server's sidebar under its own name (and `icon`, if it declares one) — there is no generic
"Plugins" tab. Clicking it opens that plugin's settings; removing it there takes it back off
the server and out of the sidebar.

### The file format

```json
{
  "phobos_plugin": "1.0",
  "kennung": "support-basics",
  "name": "Support basics",
  "icon": "🎫",
  "version": "1.0.0",
  "autor": "you",
  "beschreibung": "A ticket panel with three categories and two commands.",
  "quelle": "https://raw.githubusercontent.com/you/repo/main/plugin.json",
  "homepage": "https://github.com/you/repo",

  "einstellungen": [
    { "name": "support_role", "art": "rolle", "titel": "Support role", "pflicht": true },
    { "name": "greeting", "art": "text", "titel": "Greeting", "standard": "Hi!" }
  ],

  "inhalt": {
    "befehle": [
      { "trigger": "!team", "response": "Ask <@&{{support_role}}>." }
    ]
  }
}
```

A full, working example is in [`tools/plugin-beispiele/plugin-beispiel.json`](tools/plugin-beispiele/plugin-beispiel.json).

**`kennung`** identifies the plugin across versions — lowercase letters, digits, `-` and
`_`. Uploading the same identifier again is a *new version*, not a second plugin. Servers
already using it keep running the old one until somebody presses "move to the new version".

**`einstellungen`** are the open slots. A plugin is meant to work on servers its author has
never seen, so it cannot carry role or channel numbers. It declares what it needs and the
admin fills a form in when adding it. Types: `text`, `mehrzeilig`, `zahl`, `rolle`, `kanal`,
`kategorie` — the last three render as a picker of that server's roles/channels/categories.

**Placeholders** are `{{name}}` and may appear in any text of the content. A placeholder the
plugin does not declare is rejected at upload — otherwise `{{name}}` would end up verbatim
in somebody's command.

**`quelle` and `homepage`** are optional and make the plugin updatable. `quelle` is the
address of the file's newest version — put it on GitHub and the bot can fetch updates from
there instead of you mailing a file to everyone. `homepage` is a link for humans, shown
next to the plugin.

### A plugin can also read data

Besides creating things, a plugin may declare what it would like to **read** — so somebody
who needs their own feed for a VRChat world builds a plugin and hooks it up themselves,
instead of a new endpoint going into the bot for every special case.

```json
"daten": [
  { "quelle": "profile", "felder": ["bio"], "zweck": "For the boards in the world" },
  { "quelle": "level",   "felder": ["level", "xp"],  "zweck": "For the ranking on the wall" }
]
```

A complete example that only reads and creates nothing is
[`tools/plugin-beispiele/plugin-beispiel-welt.json`](tools/plugin-beispiele/plugin-beispiel-welt.json).

| `quelle` | Fields |
|---|---|
| `profile` | `bio` |
| `level` | `level`, `xp`, `messages`, `voice_minutes`, `voice_level` |
| `vrchat` | `trust`, `verifiziert_18`, `supporter`, `gruppenmitglied` |

Leaving `felder` out means all of them. `zweck` is one sentence shown to the admin, saying
what it is for.

**A plugin only asks.** Whether it may is decided per server: a checkbox per view and a key
of its own, both off until somebody turns them on. Importing a plugin therefore gives it
access to nothing. Once released, the data is at:

```
GET https://your-dashboard/api/plugin/<kennung>?key=<KEY>
```

```json
{
  "gefunden": true,
  "plugin": "my-world-boards",
  "stand": "2026-11-18T17:40:12Z",
  "daten": {
    "profile": [{ "vrchat_name": "SomeUser", "bio": "…", "geaendert": "2026-11-17T20:11" }],
    "level":   [{ "vrchat_name": "SomeUser", "level": 9, "xp": 900 }]
  }
}
```

Everything comes in one answer, so a world loads once and searches it itself — no request
per visitor, which matters given VRChat's global cooldown between string downloads.

Three rules are built into this and cannot be configured away:

1. **Only released profiles.** A profile text appears exactly when the person pressed the
   button for it themselves. Writing something is not publishing it.
2. **No Discord ids.** Lookup goes by the VRChat name from the link; whoever has no link
   appears nowhere. Otherwise the answer would be a ready-made "VRChat name → Discord
   account" list, which nobody asked for.
3. **Only what is listed above.** No plugin can name a table or column nobody thought
   about here — email addresses, tokens and warnings are not "not released yet", they are
   unreachable.

Unticking every box switches fetching off entirely and clears the key. Changing the key
locks the old address out immediately. Requests are rate-limited per address.

> **A debug console for VRC-Link.** In a server's **VRC-Link** tab, the 🐞 icon (next to ℹ and
> ⚠) opens a small centered console with a few fixed commands: `data <name>` shows the exact
> fields a plugin would read from the `vrchat` source (`trust`, `verifiziert_18`, `supporter`,
> `gruppenmitglied`, confirmed links only); `status <name>` shows the full link status — even
> pending or unresolved ones — so you can spot problems; `live` streams this server's VRC-Link
> activity in real time until you type `stop`; `help` lists them. It is **not a shell**: it
> knows only these fixed commands and runs only fixed, parameterised lookups.

### Keeping a plugin up to date

With a `quelle` on the plugin, **Settings → Plugins** can ask the source whether something
newer is there: per plugin, or "check all of them" for the whole list. If a newer version is
found, it says so and offers a button — nothing is downloaded and installed behind your
back, and nothing on any server changes until somebody presses "move to the new version"
there.

Plugins can also be **added straight from a link** instead of a file. A normal GitHub page
link (`github.com/you/repo/blob/main/plugin.json`) is rewritten to the raw file address
automatically — the most common stumbling block, so it is handled rather than explained.

Versions are compared **as numbers**, not alphabetically: `1.10.0` is correctly newer than
`1.9.0`. "Newer" is strictly greater, so a plugin you edited locally is never quietly
overwritten by an older one at the source.

Two guards on this, both deliberate:

- **Only https, and only addresses on the open internet.** The bot would otherwise fetch an
  address a stranger wrote into a file — a request from inside your network. Private
  addresses (`127.*`, `10.*`, `192.168.*`, `::1` and the rest) are refused, including via a
  redirect: every hop is checked again rather than followed blindly.
- **The identifier has to match.** If a different plugin has appeared at that address, the
  update is refused and says so. Otherwise it would create a stranger's content on every
  server that uses the old one.

### What a plugin may create

| Key | Creates |
|---|---|
| `befehle` | custom commands (`trigger`, `response`) |
| `ticket_panels` | ticket panels, with their categories nested under `optionen` |
| `level_rollen` | level → role assignments (`level`, `role_id`) |
| `level_belohnungen` | level → reward text (`level`, `reward`) |
| `wortlisten` | auto-mod word lists (`label`, `words`) |

Anything else in `inhalt` is refused. Three things are deliberately not on the list:
reaction roles (they hang off the id of an existing message, which no package can bring
along), the per-server config keys (that is the server's master switch — a file should not
be able to turn features on), and anything holding people's data.

An imported ticket panel is created as a **draft** and is not published on its own:
publishing posts a message into a channel, and a human should trigger that, not a file
upload.

### Adding, changing, removing

Applying is **replacing**: whatever the plugin created on that server before is removed
first, then created fresh. So a change to the settings and an update to a new version are
the same operation, and a plugin never leaves two sets of commands side by side.

Every row a plugin creates is recorded. **Removing takes back exactly those rows** — never
something that looks similar. A command you wrote by hand survives a plugin that wanted to
create the same one (it is skipped at creation, so it is never recorded, so it is never
deleted). Changes somebody made to a plugin's own rows afterwards are lost on the next
apply, and the dashboard says so before you press it.

### Settings, exported separately

The plugin and a server's values for it are **two different files**. The plugin is what you
hand around; the values (role ids, channel ids, your own wording) are yours. Under
**Server → Plugins** each applied plugin can export its settings and import another
server's — the file fits that one plugin and is refused for any other.

### Build your own — step by step

You need a text editor. Nothing else.

**1. Start from the example.** Copy [`tools/plugin-beispiele/plugin-beispiel.json`](tools/plugin-beispiele/plugin-beispiel.json)
and save it under your own name, ending in `.json`.

**2. Fill in the head.**

```json
"kennung": "my-welcome-pack",
"name": "My welcome pack",
"version": "1.0.0",
"autor": "your name or handle",
"beschreibung": "One or two sentences: what does this do for a server?"
```

The `kennung` is the plugin's identity and never changes again — give it a name you can
live with. `name` and `beschreibung` are what people see in the list, so write them for
somebody who has never heard of your plugin.

**3. Decide what differs from server to server.** Every role, every channel and every
mention of a server's own name is something the next person has to be able to change. Each
of those becomes an entry in `einstellungen`:

```json
{ "name": "support_rolle", "art": "rolle", "titel": "Support role", "pflicht": true }
```

- `name` — how you refer to it in the content, letters/digits/underscore
- `art` — `rolle`, `kanal`, `kategorie` (pickers), or `text`, `mehrzeilig`, `zahl`
- `titel` — the label above the field. Write it as a question the admin can answer.
- `hinweis` — optional, a line under it explaining what it is used for
- `pflicht` — `true` if the plugin is broken without it
- `standard` — a prefilled value, for text fields

**4. Write the content.** Pick from the five keys in the table above and put your
placeholders where the values belong:

```json
"inhalt": {
  "befehle": [
    { "trigger": "!rules", "response": "Please read the pinned post, {{servername}}'s rules are short." },
    { "trigger": "!team",  "response": "Ask <@&{{support_rolle}}>." }
  ]
}
```

A role placeholder on its own is only a number — write `<@&{{support_rolle}}>` to make
Discord render it as a mention, and `<#{{kanal}}>` for a channel.

**5. Upload it.** **Settings → Plugins → choose a file**. If something is wrong with the
file, nothing is stored and the message says exactly what: an unknown content key, a
placeholder you forgot to declare, a missing required field. Fix it and upload again.

**6. Try it on a server.** Open a server, **Plugins**, fill in the form, apply. Check in
Discord whether it looks the way you meant it. Not right? Edit the file, raise the
`version`, upload again, then press "move to the new version" on the server.

**7. Hand it on.** **Settings → Plugins → Export** gives you the file back, exactly as the
bot has it. That file is the whole plugin — the other person imports it, fills in their own
roles and channels, and is done.

> **While you are still building**, keep applying it to one test server. Applying replaces
> what the plugin created before, so you can iterate as often as you like without leaving a
> mess behind — and "remove from this server" always gets you back to a clean state.

---

## Scheduled Messages

Under **Server → Scheduled Messages** you can schedule a message to be sent to any channel at a specific date and time. Useful for announcements, reminders or recurring events.

---

## Discord Events

Under **Server → Events** you can create native Discord scheduled events directly from the dashboard — either tied to a voice channel or as an "external" event (custom location, e.g. a game or an outside venue). Events can be edited as long as they haven't started yet; once Discord marks them active or completed, only deletion remains.

Optional extras when creating an event:
- **Announcement channel** — the bot posts a message there automatically once the event starts (and, if enabled, once it ends), including name, time, location and a link to the event
- **Reminders** — any number of custom messages posted a chosen number of minutes before the event starts
- **Recurrence** — optionally daily/weekly/monthly; since discord.py doesn't support Discord's native recurring events yet, the bot recreates a fresh single event each time it's due (carrying over reminder templates). A recurring series can be paused and resumed anytime without losing its reminders, or stopped for good.

---

## CrossVerification

Under **Server → CrossVerification** you can define "IF a member has/lacks certain roles, THEN add/remove roles" rules. By default they're evaluated **live**, the instant a member's roles change — an optional per-server interval switches this to a periodic full re-check of every member instead (0 minutes = live).

- **Condition** — has **any** / **all** / **none** of a chosen set of roles
- **Actions** — a rule can carry **several actions chained with AND**: "assign role A" *and* "remove role B" in one rule, each action with its own set of roles and its own target server. Actions aimed at the same server become a single role change, so giving and taking happen at once instead of as two edits that can overtake each other.
- **Target server** — each action can act on this server or on a **different one** (cross-server sync for a network of servers sharing the same bot token — only guilds reachable that way appear in the target dropdown)
- **Recreate missing roles** — when a rule is saved, the bot records name, colour and settings of the chosen action roles. If such a role is deleted later, it is recreated from that snapshot and the rule is pointed at the new one, instead of the rule quietly going inert. A role of the same name that already exists is reused rather than duplicated. Switchable off per server; needs **Manage Roles** on the target server. Rules that *remove* a role never create anything.
- **Priority** — rules run in order (lowest number first); if two rules affect the same role, the one applied last wins. The same holds inside a rule: the later action block wins.
- **Evaluation interval** — 0 means live, the instant roles change. **1 minute is recommended**: the periodic full pass also catches what the live evaluation never sees, such as a brief outage or a role changed directly on the target server. Below 1 is not possible, the check loop itself ticks once a minute.
- **Test sandbox** — simulate any role combination and see exactly what would happen, without touching a single real member
- **Debug view** — the bot's own step-by-step trace for this server, right on the tab, instead of digging through container logs

---


**Cooperations with other installations.** Two communities work together, each running their own Phobos: whoever was vetted over there should not have to go through the same check again here. Under *CrossVerification* you set up a **cooperation** — independently on each side, endable at any time.

Each side decides two things for itself: **what it gives** (which of its own roles count as "vetted" for the partner) and **what it accepts** (which roles somebody gets here when the partner says yes). When a new member joins, the bot asks the partner once; a no, a timeout or a partner that is briefly unreachable all mean the same — nothing happens. A role is never granted on an unclear answer.

**A cooperation is exactly as trustworthy as the partner.** Somebody who answers yes to everyone on their side hands everyone the role you grant for it — the only limits are that one role and the fact that you can end the cooperation at any moment. So pick roles whose misuse you could live with, not ones that lead to your moderation tools.

What travels is a single yes or no about one Discord ID. No names, no roles, no member lists, and a "no" says nothing about whether that person is even on the partner's server. The partner identifies itself with a key your side generates and can withdraw at any moment; it is stored as a checksum only, so it is shown exactly once. The interface is rate-limited, because "is this person one of yours" is an answer in itself and should not be askable a thousand times a minute. Internal addresses are refused, and cooperation keys stay out of backups.

**Existing members are caught up.** On join the bot asks straight away — but everybody already on the server when you set this up, which at first is everybody, is only reached by the sync. That comes as a button on each partner row (⟳) and as an interval in minutes you choose yourself (default 15, `0` = off). Only those who do not have the role yet are asked about; a limited number per pass, then it continues where it left off. If the connection drops mid-pass the skipped ones are not lost, and a partner that takes its time does not hold the bot up — after twenty seconds the pass ends and the rest follows next time.

The existing rules are untouched by all this — a rule works inside this installation, a cooperation reaches somebody you trust but do not administer.
## Polls

Under **Server → 🗳️ Polls** or `/poll-create` in Discord: single- or multiple-choice polls with live vote bars. Optional extras: an image and/or link per option (combined into one shared result image, with links listed as clickable text below it), a live-updating ranking of options by vote count, and either a fixed auto-end duration or a specific end date — a poll can even be scheduled to start at a future time, so it can be fully prepared in advance. Everything (question, options, images, links) stays editable after posting; edits update the live message in place.

---

## Ratings

Under **Server → ⭐ Ratings**: a persistent, always-open list — maps, servers, games, anything — that members rate 1–5 stars anytime with `/bewerten` (autocompletes existing entries). Unlike a poll, there's no end: a member's rating can be changed anytime and simply replaces their previous one, and the average updates live. `/bewertungen` posts the list to a channel with a built-in star-picker so members can rate without knowing the command exists. Admins can additionally mark individual entries as recommended, independent of their average — recommended entries always sort to the top.

---

## Gameserver (AMP)

Under **Server → 🎮 Gameserver**: control one or more [CubeCoders AMP](https://cubecoders.com/AMP)-hosted game server instances directly from Discord (`/gameserver-status` `/gameserver-start` `/gameserver-stop` `/gameserver-restart`) or the dashboard. Connect once with an AMP account's URL/username/password and every instance managed by it is detected automatically — no need to register each game server separately. Each instance can also get its own custom slash command names (e.g. `/palworld-start`) synced instantly, without a bot restart.

---

## Auto-Kick

Under **Server → 🚪 Auto-Kick**: automatically kicks members who still hold a designated "not yet verified" role after a configurable deadline since they joined — useful for verification flows where a role is assigned automatically on join and removed manually once a moderator approves someone. Any number of reminder DMs can be scheduled at different points before the deadline, each with its own custom message.

---

## Embed Messages

Under **Server → 📨 Embed Messages**: post fully custom, multi-block embed messages to any text or forum channel from the dashboard — each block becomes its own embed card in the same message. Supports an image, a footer, and (for forum channels) tags. Unlike a message typed directly in Discord, these stay editable afterwards from the dashboard — changes update the already-posted message in place instead of requiring a repost.

---

## Birthday System

Under **Server → Birthdays** you can configure a birthday channel and a custom message. Every day at 8 AM the bot automatically congratulates members whose birthday it is — each person only once per year.

**The command words are yours to choose.** By default members register with `!geburtstag DD.MM`, but the *Command words* field takes a comma-separated list, and all of them work side by side — so `birthday, geburtstag, cumpleaños` lets everyone on a mixed-language server use the word they expect. The words that clear a stored birthday again (`löschen, entfernen, delete, remove` by default) are configurable the same way. The tab shows which words are currently in effect, and an error message always quotes back the word the member actually typed.

**The bot's replies are yours too.** The three answers to the command — set, cleared, wrong format — are free text fields with placeholders: `{date}` for the stored date, `{user}` to mention the member, `{command}` for the word they actually typed, and `{delete}` for the first clear word. Left empty, each falls back to the suggested German text shown greyed out in the field. (The daily congratulation message has always been configurable and is separate from these.)

A birthday command word can't be the same as one of this server's Custom Commands — both handlers would answer the same message — so that combination is rejected on save.

---

## Working with lists

Lists in the dashboard — embed messages and ticket panels so far — can be handled in bulk
instead of one row at a time.

**Select and delete.** A checkbox per row, one in the header for all of them, and a button
that counts along: *Delete selected (3)*. The count is there on purpose — "delete selected"
alone leaves you guessing whether the header box really caught everything. Deleting an
embed message or a ticket panel removes the message it posted into the channel too, exactly
like deleting one on its own does.

**Open tickets** get two bulk actions instead of one: **close** (tidies up the channels, as
closing one does) and **take off the list** (leaves the channels alone). Each ticket runs on
its own — if one fails, missing permissions or a channel already gone, the rest still go
through and the result says how many made it.

**Reordering** works two ways. The **arrows** ↑ ↓ move a row one place; they are greyed out
at the top and bottom. Or **hold a row and drag it** — the new order saves on release and
the page reloads. The arrows stay because dragging does not exist on a touch device or from
the keyboard.

Two details worth knowing:

- Entries you never reordered all sit at position 0 and therefore keep the old
  newest-first order. The first drag or arrow press gives that server's list fixed places
  from 1 on.
- Cancelling a drag — Escape, or letting go outside the list — reloads the page. The
  preview you were looking at was never saved, and a list showing something other than what
  is stored is worse than no preview at all.

---

## Backup & Restore

Every user can export their own data (account, bot tokens, all server configurations) as a JSON file via their **profile page**. Admins can additionally:

- Download a backup for any individual user
- Download a **full backup** of the entire system (all users, tokens, configs)
- Download a **single server's backup** (its configuration only — no users, no tokens) from that server's own dashboard page, and restore it onto any server, including a completely different one
- **Restore** any backup via file upload — existing entries are updated, new ones are added, nothing is deleted

### The same backup, twice

Restoring **creates** entries; it does not reconcile them. Restore the same file three times and you have three sets of reaction roles, commands and panels — and you only notice afterwards.

So every exported file carries an **identifier** and a **running number**, and the number is in the filename: `backup_server_MyServer_nr0007_20261118_1430.json`. The number counts per server, so two files from the same server are told apart by something that means something — unlike the `(1)` a browser appends.

A file that has already been restored **onto this server** is refused, with the date, who did it and its number. If you really want it again, there is a checkbox next to the upload saying exactly what will happen. Restoring the same file **onto a different server** is not blocked — that is what the per-server backup is for, and nothing is duplicated there.

Older backups from before this have no identifier; for those the file's own fingerprint is used, so uploading the same old file twice is caught just the same.

### Handing a server over to someone else

The per-server backup is built for exactly that: it is tied to **no bot token and no user account**, so the file can be restored in a completely different Phobos installation, onto any server that admin chooses. Only admins can download or restore it.

What it contains: this one server's settings across all 22 configuration areas — reaction roles, commands, tickets, level roles and rewards, auto-mod categories, scheduled messages, recurring events including their reminder templates, embed posts, CrossVerification rules, ratings, auto-delete, auto-thread, temp voice, Twitch notifications, free-stuff channels, gameserver connection, birthdays, warnings — and the VRChat links of its members.

> Two things worth knowing. **The VRChat links are members' data**, not settings: names and account ids of real people travel with this file. **Plugins are not in it** — what a plugin created (commands, panels, rewards) comes along as ordinary settings, but the link back to the plugin does not, so on the target server those entries are plain hand-made entries nobody can remove through the plugin any more.

What it deliberately leaves out: dashboard users and their permissions, bot tokens, and all runtime/history data (level points, logs, open tickets, running giveaways and polls, counters).

**The AMP gameserver credentials (panel username and password) are left empty by default**, since this file is meant to be handed to somebody else. A checkbox next to the download button includes them — only tick it when moving a server between your *own* installations.

Passwords of existing accounts are never overwritten during a restore.

---

## Two-Factor Authentication

Every dashboard user can enable TOTP-based two-factor authentication under **Profile → Two-Factor Authentication** — compatible with Google Authenticator, Authy, Aegis and similar apps. After entering the confirmation code once, 8 one-time backup codes are shown (for account recovery if you lose your device); they can be regenerated anytime with your password. Login then requires the app code (or a backup code) after the password, and repeated failed codes temporarily lock the account.

The backup codes can be printed: the sheet carries the installation's name, the account, the dashboard address and the date, so two installations never produce two identical-looking sheets.

**Resetting a password on an account with 2FA** asks for the code *before* the mail goes out — from the app, or a backup code if the phone is gone. Without that step, access to the mailbox alone would be enough to take over the account: the reset link sets a new password, and nothing else stands in the way until then. Three wrong codes lock the reset path for an hour, counted separately from the login so neither can lock the other. Starting over at the address form does not clear it.

### Locked out completely

No password, no SMTP configured (so no reset mail), no second admin — then the way back is on the server itself:

```bash
docker exec -it Phobos-Bot python3 /repo/tools/passwort_setzen.py --liste
docker exec -it Phobos-Bot python3 /repo/tools/passwort_setzen.py --benutzer <name>
docker exec -it Phobos-Bot python3 /repo/tools/passwort_setzen.py --benutzer <name> --2fa-aus
```

The password is prompted for, never passed as an argument — otherwise it would sit in the shell history and the process list. Setting it ends all open sessions for that account. `--2fa-aus` additionally turns off two-factor and discards the backup codes, which is what you need when the phone is gone too. This opens nothing that was not already open: whoever has a shell on that machine can read and write the database anyway.

---

## Security

The dashboard is meant to sit on the open internet, so a few things are handled deliberately rather than left to chance.

**Login.** After 5 wrong passwords from the same address for the same account, that combination is locked for 15 minutes; a second, looser count per address stops one host from working through a list of usernames. An unknown username is checked against a dummy hash so the answer takes just as long — otherwise the response time alone tells an attacker which accounts exist.

**Sessions.** Every login gets its own handle, stored server-side. Signing out deletes it, so a copy of that cookie — taken from a shared machine, a backup, a proxy log — stops working at the same moment. Other devices of the same user keep their own sessions. The handle is stored hashed, as are password-reset tokens and invite codes: all three are only ever compared, never read back, so reading the database file gives you nothing usable.

**One cookie, and only for the dashboard.** `phobos_session`, `HttpOnly` and `SameSite=Lax` — the latter is also what stands in for CSRF protection. The member-facing VRC-Link pages set **no cookie at all**. A login cookie is technically necessary, so it needs no consent banner.

**Headers.** Every response carries `X-Frame-Options: SAMEORIGIN`, `Content-Security-Policy: frame-ancestors 'self'`, `X-Content-Type-Options: nosniff` and a `Referrer-Policy`. Deliberately no full CSP: the dashboard is built on inline scripts and styles, and a policy without `unsafe-inline` would break every page at once.

**Behind HTTPS**, set `PHOBOS_COOKIE_SECURE=1` in your docker-compose `environment:` block. That adds the `Secure` flag and sends HSTS. It is **off by default on purpose** — a Secure cookie is dropped by the browser over plain HTTP, so guessing this wrong would lock an already-running installation out of its own dashboard.

**Backups can be encrypted.** Every export — your own data, a single user, the full installation, a single server — takes an optional password. Enter one and the downloaded file leaves the server unreadable; leave it empty and you get the same plain JSON as before, so existing habits and older files keep working. Restoring asks for the password only when the file is actually encrypted. Forget it and only *that file* is lost — nothing on the server changes. Uses only Python's own standard library (scrypt + HMAC), because a compiled crypto package would break the Android and Termux builds.

**What is not protected:** the Discord bot token, the VRChat credentials, users' 2FA secrets and the SMTP/AMP passwords are stored in plain text *on the server*, because the bot needs them back. Whoever controls the machine can read them — no database encryption changes that, since the key has to live there too. What you can do is keep the copies safe: use an export password, and keep your `data/` backups encrypted. And change the default `admin` password on first login.

---

## Event Logging

Under **Server → Log** configure:

- **Log channel** — Discord channel where events are posted
- **Exclude channels** — channels whose messages are NOT logged (e.g. spam channels)

The 9 native categories below are always tracked. Each dashboard user can additionally set a **personal display filter** (which categories they see in the dashboard log view — the configured log channel always receives every native event regardless of anyone's personal filter):
- Member join / leave (with roles on leave)
- Role changes, nickname changes, timeouts
- Bans / unbans
- Message deleted — **including who deleted it** (requires "View Audit Log" permission)
- **Bulk message delete** (e.g. `/clear` command) with responsible moderator
- Message edited (before + after + jump link)
- Voice channel join / leave / switch
- Channel created / deleted / renamed
- Server boost changes

Beyond that, 7 **bot action categories** can be opted into per server (all off by default): polls posted/ended, tickets created/closed, giveaways started/ended, warnings (`/warn`), auto-mod actions (warn/timeout/kick/ban from the spam filter), scheduled messages sent, and birthday congratulations sent.

---

## Bug & Feature Reports

Admins can open **Settings → 📣 Report** to file a bug report or feature request. The form pre-fills a title, description (bot version and platform are attached automatically), and a bug/enhancement label, then opens GitHub's own "new issue" page in a new tab for the [public repository](https://github.com/LucyWolf/phobos-bot/issues) — the bot itself never stores a GitHub token or submits anything on its own; a free GitHub account is needed to actually confirm the submission there.

---

## Permission System

Phobos keeps this deliberately simple — just two base roles, no reusable custom permission sets to build and assign:

| Role | Access |
|---|---|
| **Admin** | Everything: global settings, user management, bot tokens, Streaming-API credentials, SMTP, updates, bot design, and every connected server |
| **Moderator** | Only the servers explicitly granted to them under **Users**, or inherited automatically from a bot token they've been assigned to. Can still view (but not change) some read-only pages like Bot Info |

The very first account (`admin` / `admin`, see Installation below) is always an Admin. There must always be at least one Admin — the dashboard blocks demoting or deleting the last remaining one.

A few finer controls exist on top of this:

- **New users** can be created directly by an admin, or self-register via a one-time **invite link** (Users page) that expires after 5 minutes
- A granted moderator's access to one server can be **narrowed to specific tabs** (e.g. only Tickets and Polls) instead of the whole server, right from that server's own Users tab
- Each server can independently **hide unused feature tabs** from its own sidebar for every viewer, purely to declutter navigation on servers that only use a handful of features — this doesn't restrict access, just what's shown
- Admins can **instantly invalidate every active session everywhere** (Users page) — useful if a device or session ever gets compromised

---

## Installation

### Requirements

- Docker & Docker Compose
- Nginx Proxy Manager (recommended) or another reverse proxy

> **Don't have Docker yet?** On Linux, the official install script sets up Docker Engine, the CLI and the Compose plugin (`docker compose`, used throughout this README) in one go:
> ```bash
> curl -fsSL https://get.docker.com | sh
> ```
> On Windows or macOS, install [Docker Desktop](https://www.docker.com/products/docker-desktop/) instead — it bundles the same Compose plugin.

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
>
> On a small machine like this, consider the two commented-out lines in `docker-compose.yml` (`mem_limit` / `pids_limit`): they cap a runaway container so one bad instance can't take the whole Pi down with it. They are off by default and don't slow normal operation — see **[Resource limits](#resource-limits-for-small-machines--step-by-step)** for the step-by-step.

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

### What the updater needs

The dashboard update runs `git` inside the container, in `/repo` — the project folder
mounted from the host. Your `docker-compose.yml` has to carry all three volume lines:

```yaml
    volumes:
      - ./app:/app
      - ./data:/app/data
      - .:/repo
```

Without the last one the update fails before it starts (from 1.19.38 it says so; older
versions just showed `exit 128`). **A restart does not fix this** — Docker only applies
mounts when a container is *created*, so after changing the file you need
`docker compose up -d`. The same goes for `./data:/app/data`: without it the database lives
inside the container and is gone the moment it is recreated. Check what you actually have
with:

```bash
docker inspect <container-name> --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```

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
│   ├── entrypoint.sh       # Drops root before starting the bot (see Security)
│   ├── main.py             # FastAPI routes + bot setup
│   ├── database.py         # SQLite schema + helpers
│   ├── i18n.py             # DE/EN translations
│   ├── totp.py             # TOTP secret/QR/backup-code logic for 2FA
│   ├── plugins.py          # Plugin format: validation, placeholders, apply/remove
│   ├── befehlstexte.py     # English names/descriptions for the slash commands
│   ├── vrchat.py           # VRChat API client (login, 2FA, profile lookups)
│   ├── backup_crypto.py    # Password-encrypted backup files
│   ├── logbuch.py          # Mirrors every print() into data/logs/phobos.log
│   ├── cogs/
│   │   ├── moderation.py
│   │   ├── leveling.py
│   │   ├── welcome.py      # Welcome card image generation
│   │   ├── automod.py      # Spam/link/word filtering
│   │   ├── reaction_roles.py
│   │   ├── logging_cog.py  # Event logging with audit log
│   │   ├── log_utils.py    # Shared "log this bot action" helper (not a cog)
│   │   ├── custom_commands.py
│   │   ├── tickets.py
│   │   ├── giveaways.py
│   │   ├── notifications.py  # Twitch live notifications
│   │   ├── freestuff.py      # Free stuff & deals
│   │   ├── auto_delete.py    # Auto-delete messages by channel
│   │   ├── auto_thread.py    # A thread per message in selected channels
│   │   ├── auto_kick.py      # Kick members still holding a "not verified" role
│   │   ├── temp_voice.py     # Join-to-Create temp voice channels
│   │   ├── scheduler.py      # Scheduled messages + recurring Discord events
│   │   ├── birthday.py       # Birthday congratulations
│   │   ├── polls.py          # Polls with images, ranking, scheduling
│   │   ├── ratings.py        # Persistent 1-5 star rating lists
│   │   ├── amp.py            # CubeCoders AMP gameserver control
│   │   ├── vrc_link.py       # VRChat account linking, group sync, instances
│   │   ├── profile.py        # Member profiles (/bio, /inspect, ...)
│   │   └── role_rules.py     # CrossVerification (role condition rules)
│   ├── templates/            # Jinja2 HTML templates
│   └── assets/               # Bundled welcome card overlay presets (PNG)
├── tools/                    # Helper scripts, checks run before each commit,
│                             # plus two example plugins to copy from
├── android/                  # Android Studio project - packages the bot as a real APK
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
| pyotp + qrcode | 2.9.0 / 7.4.2 |

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
- [Multi-Bot](#multi-bot-1)
- [Docker Compose](#docker-compose-1)
- [Ressourcengrenzen](#ressourcengrenzen-für-kleine-maschinen--schritt-für-schritt)
- [Leveling / XP](#leveling--xp-1)
- [Willkommenskarte](#willkommenskarte)
- [Temporäre Voice-Kanäle](#temporäre-voice-kanäle)
- [Spam-Schutz / Auto-Moderation](#spam-schutz--auto-moderation)
- [Auto-Delete](#auto-delete-1)
- [Auto-Thread](#auto-thread-1)
- [VRC-Link (VRChat)](#vrc-link-vrchat-1)
- [Profile](#profile)
- [Plugins](#plugins-1)
- [Geplante Nachrichten](#geplante-nachrichten)
- [Discord-Events](#discord-events-1)
- [CrossVerification](#crossverification-1)
- [Umfragen](#umfragen)
- [Bewertungen](#bewertungen)
- [Gameserver (AMP)](#gameserver-amp-1)
- [Auto-Kick](#auto-kick-1)
- [Embed-Nachrichten](#embed-nachrichten)
- [Geburtstags-System](#geburtstags-system)
- [Listen bedienen](#listen-bedienen)
- [Backup & Wiederherstellen](#backup--wiederherstellen)
- [Zwei-Faktor-Authentifizierung](#zwei-faktor-authentifizierung)
- [Sicherheit](#sicherheit)
- [Event-Logging](#event-logging-1)
- [Bug & Feature-Meldungen](#bug--feature-meldungen)
- [Berechtigungssystem](#berechtigungssystem)
- [Installation](#installation-1)
  - [Voraussetzungen](#voraussetzungen)
  - [Android (Termux) — ohne Docker](#android-termux--ohne-docker)
  - [Erster Start](#erster-start)
  - [Discord Developer Portal](#discord-developer-portal-1)
- [Updates](#updates-1)
  - [Automatisch (über Dashboard)](#automatisch-über-dashboard)
  - [Manuell (auf dem Server)](#manuell-auf-dem-server)
- [Twitch-Benachrichtigungen einrichten](#twitch-benachrichtigungen-einrichten)
- [Free Stuff & Deals einrichten](#free-stuff--deals-einrichten)
- [Nginx Proxy Manager](#nginx-proxy-manager-1)
- [Projektstruktur](#projektstruktur)
- [Technologie](#technologie)
- [Eine Anmerkung zu diesem Projekt](#eine-anmerkung-zu-diesem-projekt)

</details>

## Features

### Bot-Funktionen

*Stand 18. November 2026.* Die Kurzfassung — was der Bot kann. Alles unterhalb dieser Tabelle ist die lange: Einstellungen, Grenzen und die Gründe dahinter.

| Funktion | Was sie kann |
|---|---|
| **Moderation** | Kicken, bannen, timeouten, verwarnen — aus Discord oder dem Dashboard, mit einer Verwarnungs-Historie, die bleibt |
| **Leveling / XP** | Mitglieder sammeln XP fürs Schreiben und fürs Zusammensitzen im Voice, steigen Level auf und bekommen Rollen dafür |
| **Willkommen** | Begrüßt jeden Neuen mit einer selbst erzeugten Willkommenskarte — deine Farben, dein Hintergrund, deine Worte |
| **Auto-Moderation** | Fängt Spam, Links und Wörter ab, die du nicht lesen willst, und verwarnt, stummschaltet, kickt oder bannt von allein |
| **Reaction Roles** | Mitglieder holen sich ihre Rollen selbst — ein Klick auf ein Emoji genügt |
| **Event-Logging** | Schreibt mit, was auf dem Server passiert — und zeigt, wer eine Nachricht gelöscht hat |
| **Eigene Commands** | Deine eigenen Befehle, ohne eine Zeile Code |
| **Tickets** | Ein Knopf macht aus einer Frage einen privaten Ticket-Kanal — Support-Rolle, Kategorie, Archiv beim Schließen. Ein offenes Ticket je Kategorie, damit eine laufende Verifizierung keine Meldung blockiert |
| **Giveaways** | Verlosung mit einem Klick; der Bot zieht, verkündet und schreibt den Gewinnern eine DM |
| **Twitch-Benachrichtigungen** | Sagt deinem Kanal Bescheid, sobald einer deiner Streamer live geht |
| **Free Stuff & Deals** | Postet kostenlose Spiele und die Angebote, die dich interessieren — von selbst |
| **Auto-Delete** | Hält gewählte Kanäle sauber und räumt Nachrichten nach einer Zeit deiner Wahl weg |
| **Auto-Thread** | Gibt jeder Nachricht in einem Kanal ihren eigenen Thread, benannt wie du willst |
| **VRC-Link** | Mitglieder verknüpfen ihr VRChat-Konto, weisen nach, dass es wirklich ihres ist, und tragen ihren VRChat-Namen auf Discord |
| **VRChat-Gruppe** | Sieht, wer in deiner Gruppe ist, vergibt die passende Discord-Rolle und verschickt Einladungen auf Zuruf |
| **VRChat-Instanzen** | Erkennt jede Lobby, die deine Gruppe aufmacht, und meldet sie — mitlaufende Personenzahl, Beitritts-Knopf, deine Worte |
| **Temp Voice** | Einen Kanal betreten und den eigenen bekommen; er verschwindet, wenn der Letzte geht |
| **Geplante Nachrichten** | Jetzt schreiben, später posten lassen — in jedem Kanal |
| **Geburtstags-System** | Mitglieder werfen ihren Geburtstag in den Chat, der Bot gratuliert am Tag |
| **Discord-Events** | Plant echte Discord-Events aus dem Dashboard — Erinnerungen, Ankündigungen und auf Wunsch Wiederholungen |
| **CrossVerification** | Regeln nach dem Muster „hat diese Rolle → bekommt jene“, auch auf einen anderen Server — dazu Kooperationen mit Partner-Communitys, die einen eigenen Phobos betreiben: wen die geprüft haben, kommt hier automatisch durch |
| **Umfragen** | Umfragen mit Bildern, Live-Rangliste und Startzeit |
| **Bewertungen** | Eine Sterne-Liste, die deine Mitglieder immer weiter bewerten — Maps, Spiele, Server, was du willst |
| **Gameserver (AMP)** | Deine Gameserver starten, stoppen und im Blick behalten, ohne Discord zu verlassen |
| **Auto-Kick** | Zeigt weiterhin unverifizierten Mitgliedern nach einer Frist die Tür — vorher mit Erinnerungen |
| **Embed-Nachrichten** | Eine schön gesetzte Ankündigung im Dashboard bauen und überall posten |
| **Profile** | Mitglieder tragen selbst ein, was über sie bekannt sein soll — und eine VRChat-Welt kann lesen, was sie freigegeben haben |
| **Plugins** | Pakete aus Einstellungen — Befehle, Ticket-Panels, Belohnungen — einmal gebaut, exportiert und auf jedem Server einspielbar. Ein Plugin kann auch freigegebene Daten an eine VRChat-Welt liefern |

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
    image: phobos-bot:latest
    container_name: ${BOT_CONTAINER_NAME:-Phobos-Bot}
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./app:/app
      - ./data:/app/data
      - .:/repo
    environment:
      - TZ=Europe/Berlin
      - PYTHONUNBUFFERED=1
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - DAC_OVERRIDE
      - FOWNER
      - SETUID
      - SETGID
    security_opt:
      - no-new-privileges:true
    logging:
      driver: json-file
      options:
        max-size: "20m"
        max-file: "5"
```

Dann:

```bash
docker compose up -d --build
```

Das Dashboard liegt unter `http://<server>:8080`. Erste Anmeldung mit `admin` / `admin` — und das bitte sofort ändern.

`BOT_CONTAINER_NAME` braucht nur, wer mehrere Instanzen auf einem Server betreibt; ohne heißt der Container `Phobos-Bot`. Sonst ist serverseitig nichts einzustellen — der Discord-Token und alles Weitere kommt über das Dashboard hinein.

> Der `.:/repo`-Mount gibt dem Container Zugriff auf das Git-Repository selbst, damit das Update unter **Einstellungen → 🔄 Updates** den neuen Stand per `git fetch` + `git reset --hard` holen kann (kein normales `git pull` — das würde bei lokalen Abweichungen mit einem Konflikt stehen bleiben, der harte Reset überschreibt sie absichtlich). **Ohne ihn funktioniert das Update aus dem Dashboard überhaupt nicht** — verzichtbar ist er nur, wenn Updates von Hand über die Server-Shell laufen (`git pull` + `docker compose up -d --build`). Der Ordner, auf den er zeigt, muss ein echter `git clone` sein, keine Kopie der Dateien.
>
> Einen `/var/run/docker.sock`-Mount gibt es bewusst **nicht**. Den Docker-Socket in einen Container zu reichen heißt faktisch Root auf dem Wirt; das Update startet den Prozess stattdessen selbst neu, und `restart: unless-stopped` holt ihn zurück.

> **Der Bot läuft nicht als root.** Sein Container startet als Benutzer `1000`, gibt alle Linux-Fähigkeiten ab, die er nicht braucht (`cap_drop: ALL`), und kann sich keine zurückholen (`no-new-privileges`). Weil die eingehängten Ordner (`app/`, `data/`, das Repository) dem gehören, der sie auf dem Wirt angelegt hat, rückt das Startskript ihre Besitzrechte bei jedem Start zurecht, bevor es die Rechte abgibt — eine bestehende Installation läuft also weiter, ohne dass jemand von Hand eine Datei anfassen muss.
>
> `PUID`/`PGID` setzen, wenn die Dateien einer anderen Benutzernummer gehören. Lässt sich der Besitz gar nicht ändern (NFS, Docker Desktop, exFAT), schreibt das Startskript das ins Container-Protokoll und lässt den Bot wie bisher laufen, statt einen Container zu hinterlassen, der nicht hochkommt. `PHOBOS_ROOT=1` erzwingt das alte Verhalten.
>
> **Eine Sache danach:** Das Repository gehört jetzt dem Bot, nicht mehr root. Wer auf dem Server als root `git` darin benutzt, bekommt deshalb „detected dubious ownership" zu sehen — einmalig mit `git config --global --add safe.directory /pfad/zum/phobos-bot` erledigt, danach läuft `git pull` von Hand wie vorher. Wer dort als root Dateien anlegt (`git pull`, ein schneller Editiervorgang), hinterlässt wieder root-eigene Dateien; der nächste Start des Containers rückt das von selbst zurecht.
>
> Liegen im selben Verzeichnis die Datenordner **anderer** Instanzen (`data-xyz/`), bleiben die unangetastet: zurechtgerückt wird nur, was git kennt.
>
> Wirksam wird das beim **Neubauen** des Images (`docker compose up -d --build`). Ein Update über das Dashboard holt nur neuen Code und startet den Prozess neu — es baut das Image nicht neu, an einer laufenden Installation ändert sich also nichts, bis sie selbst neu gebaut wird.

> **Der `logging`-Block ist in der Praxis nicht freiwillig.** Ohne ihn schreibt Docker die Ausgabe des Bots in eine Datei, die nie kleiner wird. Am 02.11.2026 war eine davon auf 21 GB angewachsen und die Platte des Servers voll — der Bot lief dabei die ganze Zeit normal weiter, es fiel erst auf, als nichts mehr gespeichert werden konnte. 20 MB × 5 Dateien sind höchstens 100 MB je Container.
>
> Docker übernimmt das beim **Anlegen** des Containers. Wer es einer bestehenden Installation hinzufügt, braucht `docker compose up -d`, kein Neustart. Wer nach **Zeit** statt nach Größe begrenzen will, nimmt `tools/logrotate-phobos.conf` — Docker selbst kennt nur Größe und Anzahl.

### Ressourcengrenzen (für kleine Maschinen) — Schritt für Schritt

In der `docker-compose.yml` stehen drei Zeilen, die **standardmäßig auskommentiert** sind —
eine normale Installation ignoriert sie:

```yaml
    #mem_limit: 512m
    #pids_limit: 200
    #cpus: "1.0"
```

Auf einem gewöhnlichen Server braucht man sie nicht. Auf einem **Raspberry Pi 4/5** oder
jeder kleinen Maschine, auf der sich mehrere Container wenig RAM teilen, verhindern sie, dass
ein ausgebrochener Container die ganze Maschine mitnimmt. **`mem_limit` und `pids_limit` sind
ein Dach, keine Drossel** — der Bot nimmt sich darunter, was er braucht, und merkt die
Grenzen nie; sie greifen nur, wenn etwas ausbricht. **`cpus` ist anders: das drosselt
wirklich.** Nur setzen, wenn du den Bot bewusst zügeln willst.

**1 — Nachsehen, was der Bot wirklich zieht.** Auf dem Wirt:
```bash
docker stats --no-stream <container-name>
```
Die Spalte `MEM USAGE` zeigt es. Phobos liegt normal deutlich unter 300 MB.

**2 — Ein Speicher-Dach deutlich darüber wählen.** Grob das Doppelte des Verbrauchs,
mindestens 256–512 MB. Zu niedrig, und Docker schießt den Bot ab (siehe Schritt 6);
großzügig ist unproblematisch — das Dach zählt nur, wenn etwas ausbricht.

**3 — `docker-compose.yml` bearbeiten.** Das `#` vor den gewünschten Zeilen entfernen und die
Werte setzen. Für einen Pi sind Speicher und Prozesszahl die zwei nützlichen:
```yaml
    mem_limit: 512m
    pids_limit: 200
```
`cpus: "1.0"` (höchstens ein Kern) nur ergänzen, wenn du die CPU bewusst deckeln willst.

**4 — Anwenden.** Im Ordner mit der `docker-compose.yml`:
```bash
docker compose up -d
```
Das **erstellt den Container neu**. Ein bloßer Neustart übernimmt neue Grenzen **nicht** —
Docker liest sie nur beim Anlegen.

**5 — Prüfen, dass es gegriffen hat.**
```bash
docker inspect <container-name> --format 'mem={{.HostConfig.Memory}} pids={{.HostConfig.PidsLimit}}'
```
`mem` ist die Grenze in Bytes (`536870912` für 512 MB), `pids` die Prozessgrenze. Beide
ungleich null heißt: aktiv.

**6 — Startet der Bot ständig neu, ist die Grenze zu niedrig.** Dauernde Neustarts in
`docker ps` oder ein Exit-Code `137` heißen: Docker hat ihm den Speicher ausgehen lassen
(OOM). `mem_limit` erhöhen und noch einmal `docker compose up -d`.

**Grenzen wieder entfernen:** das `#` zurücksetzen und erneut `docker compose up -d`.

### Ohne Compose

Dasselbe als ein einzelner Befehl — praktisch, wenn man es nur ausprobieren will:

```bash
# einmalig, im geklonten Verzeichnis:
docker build -t phobos-bot:latest ./app

docker run -d \
  --name Phobos-Bot \
  --restart unless-stopped \
  -p 8080:8080 \
  -v "$PWD/app:/app" \
  -v "$PWD/data:/app/data" \
  -v "$PWD:/repo" \
  -e TZ=Europe/Berlin \
  -e PYTHONUNBUFFERED=1 \
  -e PUID=1000 -e PGID=1000 \
  --cap-drop ALL \
  --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
  --cap-add SETUID --cap-add SETGID \
  --security-opt no-new-privileges:true \
  --log-opt max-size=20m --log-opt max-file=5 \
  phobos-bot:latest
```

> Die zwei `--log-opt` lässt man gern weg, und genau die rächen sich: ohne sie schreibt Docker die Ausgabe in eine Datei, die nie kleiner wird. Siehe den Hinweis unter Docker Compose oben.

Ein Update heißt dann von Hand, was Compose sonst übernimmt:

```bash
git pull && docker build -t phobos-bot:latest ./app \
  && docker rm -f Phobos-Bot && docker run -d ...   # dieselbe Zeile wie oben
```

Für alles, was dauerhaft läuft, ist Compose der kürzere Weg — die `docker run`-Zeile steht hier, damit sichtbar ist, was dabei eigentlich passiert.

---

## Leveling / XP

Unter **Server → 🏆 Leveling** werden Text-Nachrichten und Zeit in Voice-Kanälen als zwei **unabhängige** Fortschritte erfasst — ein Mitglied hat sowohl ein Text-Level als auch ein Voice-Level, jeweils mit eigener XP-Kurve.

- **XP-Kurve** — die für ein Level benötigte XP-Menge folgt `quadratisch·Level² + linear·Level + Basis` (Standard: 5/50/100); alle drei Werte sind für Text und Voice getrennt einstellbar, damit sich das Tempo pro Server anpassen lässt
- **Kanal-Einschränkung** — optional festlegen, welche Kanäle für Text-XP zählen (leer = alle Kanäle)
- **Level-Rollen** — ab einem gewählten Level (beide Fortschritte) eine Rolle vergeben, entweder **stapelnd** (jede bisher erreichte Rolle bleibt) oder **ersetzend** (nur die zuletzt erreichte bleibt)
- **Level-Belohnungen** — ein optionaler eigener Text, der bei einem bestimmten Level in der Level-Up-Ankündigung erscheint, unabhängig von einer Rolle

---

## Willkommenskarte

Wenn ein Mitglied beitritt, kann der Bot statt einer Text-Nachricht eine **generierte Bildkarte** senden, mit Live-Vorschau im Dashboard während des Bearbeitens:

- **Avatar-Form** — Kreis, Hexagon, Achteck, Quadrat oder Raute, mit einstellbarer Rahmenfarbe
- **Layout** — Avatar links, rechts, oder mittig über dem Text
- **Text** — frei editierbare Überschrift und Unterzeile (nicht mehr fest auf "WELCOME"), unterstützt dieselben `{user}`/`{username}`/`{server}`/`{count}`-Platzhalter wie die normale Willkommensnachricht
- **Hintergrund** — ein eigenes hochgeladenes Bild, oder der Standard-Farbverlauf
- **Overlay** — ein optionales Bild über allem anderen (eigener Upload, oder eine von vier mitgelieferten Vorlagen: zersprungenes Glas, Herzen, Kneipe, Sommer/Tropisch)
- Alle Farben frei einstellbar unter **Server → Konfiguration**

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

## Auto-Thread

Unter **Server → Auto-Thread** wählst du die Kanäle, in denen **zu jeder Nachricht automatisch ein eigener Thread** geöffnet wird — gedacht für Vorstellungs-, Bewerbungs- oder Showcase-Kanäle, in denen jeder Beitrag seine eigene Diskussion bekommen soll, statt dass alles im Hauptkanal durcheinanderläuft.

Pro Kanal einstellbar:

- **Thread-Name** — eine Vorlage mit `{user}` (die Person), `{text}` (Anfang der Nachricht) und `{date}`. Bleibt ein Platzhalter leer, etwa bei einem Beitrag aus reinem Bild, fällt der Name auf den Namen der Person zurück, statt fehlzuschlagen.
- **Archivieren nach** — 1 Stunde, 24 Stunden, 3 Tage oder 7 Tage (Discords vier erlaubte Werte)
- **Startnachricht** — optionale erste Nachricht im neuen Thread, `{user}` erwähnt die Person
- **Bot-Nachrichten überspringen** (standardmäßig an) und **nur bei Nachrichten mit Anhang** (standardmäßig aus)

Der Bot braucht im Kanal die Berechtigung **Öffentliche Threads erstellen**. Bewusst übersprungen werden: Nachrichten, die schon in einem Thread stehen (auch Forenbeiträge, die technisch Threads sind), System-Meldungen wie Beitritte oder Pins, und Nachrichten, an denen bereits ein Thread hängt.

---

## VRC-Link (VRChat)

Verknüpft das **VRChat-Konto eines Mitglieds mit seinem Discord-Konto** und verbindet den Server von dort aus mit der VRChat-**Gruppe** und ihren **Lobbys**. Ein verknüpftes Mitglied bekommt dafür eine Rolle und trägt seinen VRChat-Namen als Discord-Spitznamen.

**Einmalig für den ganzen Bot:** Unter **Einstellungen → VRC Account Link** verbindest du das Konto, mit dem sich der Bot anmeldet — ein **eigenes Konto, nicht dein Hauptkonto**, denn VRChats Schnittstelle ist inoffiziell, und ein Konto, das sie strapaziert, kann gesperrt werden. Zwei-Faktor geht: Der Bot fragt einen Einmalcode ab und behält die Sitzung (etwa einen Monat), das Geheimnis muss also nie gespeichert werden. Die Seite zeigt die letzte Prüfung und den letzten Fehler, falls es einen gab.

Alles Weitere steht unter **Server → 🔗 VRC-Link**, in zwei Unterreitern.

### Verknüpfung

- **Rolle** für verknüpfte Mitglieder und eine **Spitznamen-Vorlage** (`{vrchatName}`, `{discordName}`) mit Live-Vorschau, gekappt auf Discords 32 Zeichen
- **Knopf zum Verknüpfen** — der Bot postet in einem Kanal deiner Wahl eine Nachricht mit Knopf; Überschrift, Text und Beschriftung schreibst du. `/vrc-link` tut dasselbe, und neue Mitglieder bekommen ihren Link auf Wunsch **per DM beim Beitritt**
- **Eigentum nachweisen** (standardmäßig an) — das Mitglied trägt einen kurzen Code wie `PHOBOS-K7M2QD` in seine **VRChat-Statusmeldung** ein. Ausgeschaltet genügt der eingetippte Name, und die Verknüpfung trägt kein „Eigentum bestätigt“
- **Automatisch freigeben** (standardmäßig aus) — sonst wartet jede Verknüpfung auf die Moderation
- **Gültigkeit der Links** in Minuten, 1 bis 1440, Standard 60
- **VRChat-Profil prüfen** — ein reines Nachschlagen: was VRChat zu einem Namen zurückgibt und welchen Text die Eigentumsprüfung liest. Damit sehen „der Code steht doch da“ und „der Bot sieht dieses Feld gar nicht“ nicht mehr gleich aus

**So verknüpft sich ein Mitglied:** Knopf oder `/vrc-link` → ein **persönlicher Link**, der nur für es gilt → es trägt seinen VRChat-Namen ein (der Bot übernimmt VRChats Schreibweise) → Code in die Statusmeldung, „Jetzt prüfen“ → Rolle und Spitzname folgen, sofort oder nach der Freigabe. Die Seite **setzt keine Cookies**: Der Schlüssel reist in den Formularen und nie in der Adresse, bleibt also aus Proxy-Logs, Verlauf und `Referer` heraus; ein Countdown zeigt, wie lange die Tür offen steht. Die Seite fragt **nie nach einem VRChat-Passwort** — wer das tut, betreibt Phishing, egal als wer er sich ausgibt. Nach der Verknüpfung zeigt sie die Abzeichen des Kontos (Eigentum bestätigt, 18+, VRChat+, Vertrauensrang) und bietet Auffrischen und Lösen an.

**VRChat-Gruppe (optional).** Trägst du eine **Gruppen-ID** (`grp_…`) ein, prüft der Bot nach jeder Bestätigung und jedem Auffrischen, ob das verknüpfte Konto in der Gruppe ist — auf Wunsch mit eigener Discord-Rolle dafür, die beim Austritt wieder wegfällt. Mitglieder können sich eine **Einladung** von ihrer Seite aus anfordern. Das Bot-Konto muss selbst in der Gruppe sein und dort das Einladungsrecht haben, und Rechte bekommt es erst, wenn es drin ist: *Status prüfen* und *Gruppe beitreten* erledigen das aus dem Dashboard (offene Gruppen nehmen es sofort, anfragebasierte stellen einen Antrag, reine Einladungsgruppen müssen es zuerst einladen). Geprüft wird nur, wenn ohnehin jemand wartet — nie auf einer Zeitschaltuhr.

**Discord-Rolle → VRChat-Gruppenrolle.** Ordne die eine der anderen zu: Wer die Discord-Rolle hat, bekommt die Gruppenrolle. Änderungen wirken sofort und in beide Richtungen — Rolle vergeben oder entzogen, Zuordnung angelegt oder gelöscht, Verknüpfung gelöst oder Server verlassen; das Intervall (`0` = nur beim Verknüpfen) ist ein Netz, nicht der Mechanismus. Der Abgleich vergleicht gegen den zuletzt gesetzten Stand: hat sich nichts geändert, gibt es auch keine VRChat-Anfrage. **Zwei Discord-Server auf einer Gruppe** — etwa NA und GER — kommen sich nicht in die Quere: keiner nimmt eine Rolle weg, die der andere noch hält. Das Bot-Konto braucht in der Gruppe das Recht, Rollen zu verwalten, und seine eigene Rolle über den vergebenen.

### Instanzen

Der Bot merkt von selbst, wenn die Gruppe eine Lobby aufmacht, und postet eine Karte in den gewählten Kanal: Weltname (anklickbar), Weltbild, Personenzahl, **Beitritts-Knopf**, optionaler Rollen-Ping und dein eigener Text (`{world}`, `{count}`, `{group}`, `{link}`, `{name}`). Die Zahl läuft mit, solange die Lobby offen ist. VRChat kennt drei Zustände, jeder mit eigener Überschrift und eigenem Text:

- **offen** — die Karte wie beschrieben
- **geschlossen** (keiner kommt mehr rein, die Drinnen bleiben) — nur mit **Genauer nachsehen** erkennbar, was eine zusätzliche VRChat-Anfrage je offener Lobby und Durchlauf kostet, höchstens fünf; die Karte wird orange und verliert den Beitritts-Knopf
- **beendet** — aus der Gruppenliste verschwunden: die Karte wird zum **Abschiedstext** (`{duration}`) und löscht sich auf Wunsch nach einer Frist deiner Wahl selbst

Beim ersten Durchlauf wird nur mitgeschrieben, damit beim Einschalten nicht jede laufende Lobby auf einmal in den Kanal fällt; jede Lobby wird genau einmal gemeldet. Ein Durchlauf kostet **eine** VRChat-Anfrage für den ganzen Server, mehr nur mit *Genauer nachsehen*. Fürs Löschen braucht der Bot „Nachrichten verwalten“.

**Debug-Bericht.** Ein Knopf gibt fertig zum Kopieren aus, was der Bot auf der VRChat-Seite sieht: die geltenden Einstellungen, das Bot-Konto (ohne Passwort, Geheimnis und Sitzungs-Keks), die Gruppe, ihre Rollen und deine Zuordnungen, jede offene Lobby roh, je Lobby eine eigene Abfrage mit herausgestellten Zustands- und Namensfeldern, den eigenen gespeicherten Stand und die Zahl der Verknüpfungen. Liest nur, ändert nichts.

Die Adresse für die Links nimmt der Bot von dort, wo du dieses Dashboard geöffnet hast — genau wie der Einladungslink in der Benutzerverwaltung, es ist also nichts einzurichten. Eine in den Einstellungen gesetzte **Basis-Adresse** hat Vorrang.

---

## Profile

Mitglieder tragen mit `/bio`, `/kinks`, `/triggers` und `/limits` selbst ein, was über sie
bekannt sein soll, und sehen mit `/inspect` die Angaben anderer. `/profil` zeigt das eigene,
`/profil-loeschen` räumt alles weg. Jede Antwort ist nur für die fragende Person sichtbar —
ein Profil landet nie in einem Kanal.

**18+ ist Pflicht** für kinks, triggers und limits, nicht für die Bio. Als Nachweis zählt die
VRChat-Altersbestätigung aus VRC-Link oder eine Rolle, die der Server dafür bestimmt. Wer
keinen Nachweis hat, darf trotzdem nachsehen — sieht dann aber nur die Bio, und zwar mit
derselben Antwort wie bei einem leeren Profil. So verrät die Antwort nicht, dass da etwas
verborgen ist.

Einschalten unter **Server → 🪪 Profile**; dort stehen auch die 18+-Rolle und wer `/inspect`
benutzen darf.

### Profile aus einer VRChat-Welt lesen

Eine Welt kann die Angaben über eine eigene Leseadresse holen. Dafür müssen drei Dinge
zusammenkommen, alle drei mit Absicht:

1. der Server hat **Anzeige in der VRChat-Welt** eingeschaltet,
2. die Anfrage trägt den **Schlüssel** dieses Servers (mindestens 20 Zeichen, auf derselben
   Seite),
3. die Person hat ihr Profil **selbst freigegeben** — der Knopf unter `/profil`.

Ohne Freigabe bekommt die Welt nichts, Schlüssel hin oder her. Eintragen heißt nicht
veröffentlichen.

```
GET  https://dein-dashboard/api/profil?key=<SCHLÜSSEL>&vrc=<VRCHAT-NAME ODER -KENNUNG>
```

`vrc` nimmt den VRChat-Namen oder die `usr_…`-Kennung. Gesucht wird über die
VRC-Link-Verknüpfung — wer sein VRChat-Konto nicht verknüpft hat, ist gar nicht auffindbar.

Die Antwort steht oben im englischen Teil. Die Felder kommen in fester Reihenfolge und nur,
soweit gefüllt. `gefunden: false` heißt: Name unbekannt, nichts geschrieben **oder** nichts
freigegeben — bewusst dieselbe Antwort für alle drei Fälle, damit sich über die Adresse nicht
herausfinden lässt, wer was hat. Status `400` fehlende Angaben, `403` falscher Schlüssel oder
Anzeige aus, `429` mehr als 60 Anfragen je Minute.

**Das Merkmal `erwachsen` muss die Welt selbst auswerten.** In Discord hängt an diesen Feldern
eine Altersprüfung; in einer VRChat-Welt gibt es so etwas nicht — was auf einer Tafel steht,
liest jeder, der davorsteht. Deshalb steht in jeder Antwort, welches Feld dahinter gehört.

### Was VRChat dabei vorgibt

- **Nicht vertraute Adressen.** VRChat lädt Zeichenketten nur von wenigen vertrauten Hosts
  (`*.github.io`, `gist.githubusercontent.com`, `pastebin.com`, `*.disbridge.com`,
  `*.vrcdn.cloud`, `assets.vrchat.com`). Ein selbst gehostetes Dashboard ist nicht dabei —
  jeder Besucher braucht also **„Allow Untrusted URLs"** in seinen Einstellungen, sonst sieht
  er nichts. In öffentlichen Instanzen muss die Adresse zusätzlich in der Hostliste der Welt
  auf vrchat.com stehen. Die Liste kann sich ändern; VRChat liefert sie selbst als
  `stringHostUrlList` aus.
- **Auf einen vertrauten Dienst spiegeln ist keine Lösung.** Pastebin oder ein Gist lüden
  ohne diese Einstellung — und legten die freigegebenen Profildaten auf eine öffentliche
  Adresse, von der nichts je wieder verschwindet. Genau dafür gibt es diese Leseadresse.
- **Ein Abruf nach dem anderen.** `VRCStringDownloader` hat eine welt-weite Sperre von rund
  fünf Sekunden zwischen zwei Abrufen. Einmal holen, wenn jemand in die Nähe kommt, und das
  Ergebnis behalten.
- **HTTPS.** Das Dashboard hinter einen Proxy mit Zertifikat; der Schlüssel steht in der
  Adresse.

---

## Plugins

Ein Plugin ist ein **Paket aus Einstellungen**, kein Programm. Eine JSON-Datei beschreibt,
was angelegt werden soll — Befehle, ein Ticket-Panel mit seinen Kategorien,
Level-Belohnungen, Wortlisten für den Spam-Schutz —, und der Bot legt es an. Die Datei lässt
sich exportieren, weitergeben und auf einem fremden Server einspielen.

> 📂 **Fertige Beispiele zum Abschreiben:** [`tools/plugin-beispiele/`](tools/plugin-beispiele/) — eine Datei hochladen, läuft. Jedes hat einen Datenpunkt-Teil und einen Hinweis, wie man ihn in der 🐞-Konsole prüft.

**Ein Plugin führt keinen Code aus.** Das ist Absicht und keine Einschränkung auf Zeit: Ein
Python-Plugin liefe im selben Prozess wie der Bot und käme an den Bot-Token, an die ganze
Datenbank (E-Mail-Adressen, Passwort-Hashes und 2FA-Geheimnisse der Dashboard-Konten) und an
die Dateien des Wirts. In Python gibt es keine Abschottung, die das zuverlässig verhindert —
wer ein Plugin hochladen dürfte, hätte den ganzen Bot. Eine Beschreibung kann das nicht: sie
wird gelesen, geprüft und in genau die Tabellen geschrieben, die unten stehen.

### Wo was liegt

| | |
|---|---|
| **Einstellungen → Plugins** | die Plugins der Installation: einspielen, exportieren, löschen, auf einen Server anlegen |
| **die Leiste eines Servers** | je laufendem Plugin ein Eintrag mit eigenem Icon und Namen |

Ein eingespieltes Plugin tut zunächst gar nichts. Unter **Einstellungen → Plugins** wählst
du dann einen Server dafür und füllst dessen Werte aus. Ab da erscheint das Plugin in der
Leiste dieses Servers unter seinem Namen (und `icon`, falls es eins angibt) — einen
generischen „Plugins"-Reiter gibt es nicht. Ein Klick öffnet die Einstellungen des Plugins;
dort entfernt heißt: wieder vom Server herunter und aus der Leiste.

### Das Dateiformat

```json
{
  "phobos_plugin": "1.0",
  "kennung": "support-basis",
  "name": "Support-Grundgerüst",
  "icon": "🎫",
  "version": "1.0.0",
  "autor": "du",
  "beschreibung": "Ein Ticket-Panel mit drei Kategorien und zwei Befehlen.",
  "quelle": "https://raw.githubusercontent.com/du/repo/main/plugin.json",
  "homepage": "https://github.com/du/repo",

  "einstellungen": [
    { "name": "support_rolle", "art": "rolle", "titel": "Support-Rolle", "pflicht": true },
    { "name": "gruss", "art": "text", "titel": "Begrüßung", "standard": "Moin!" }
  ],

  "inhalt": {
    "befehle": [
      { "trigger": "!team", "response": "Zuständig ist <@&{{support_rolle}}>." }
    ]
  }
}
```

Ein vollständiges Beispiel zum Abschreiben liegt in
[`tools/plugin-beispiele/plugin-beispiel.json`](tools/plugin-beispiele/plugin-beispiel.json).

**`kennung`** ist das, was ein Plugin über Versionen hinweg identifiziert — Kleinbuchstaben,
Ziffern, `-` und `_`. Dieselbe Kennung nochmal hochzuladen ist eine *neue Fassung*, kein
zweites Plugin. Server, die es benutzen, behalten die alte Fassung, bis dort jemand auf
„Auf die neue Fassung bringen" drückt.

**`einstellungen`** sind die offenen Stellen. Ein Plugin soll auf Servern laufen, die sein
Autor nie gesehen hat — Rollen- und Kanalnummern kann es deshalb nicht mitbringen. Es sagt,
was es braucht, und der Admin füllt beim Anlegen ein Formular aus. Arten: `text`,
`mehrzeilig`, `zahl`, `rolle`, `kanal`, `kategorie` — die letzten drei zeigen eine
Auswahlliste des jeweiligen Servers.

**Platzhalter** heißen `{{name}}` und dürfen in jedem Text des Inhalts stehen. Ein
Platzhalter, den das Plugin nicht erklärt, lässt die Datei beim Hochladen durchfallen —
sonst stünde am Ende `{{name}}` wörtlich in irgendeinem Befehl.

**`quelle` und `homepage`** sind freiwillig und machen das Plugin aktualisierbar. `quelle`
ist die Adresse der jeweils neuesten Fassung — liegt die auf GitHub, kann der Bot Updates
von dort holen, statt dass du allen eine Datei schicken musst. `homepage` ist ein Link für
Menschen und steht neben dem Plugin.

### Ein Plugin kann auch Daten lesen

Neben dem Anlegen darf ein Plugin erklären, was es **lesen** möchte — damit sich jemand,
der eine eigene Abfrage für eine VRChat-Welt braucht, ein Plugin baut und selbst einbindet,
statt dass für jeden Sonderfall eine neue Schnittstelle in den Bot muss.

```json
"daten": [
  { "quelle": "profile", "felder": ["bio"], "zweck": "Für die Tafeln in der Welt" },
  { "quelle": "level",   "felder": ["level", "xp"],  "zweck": "Für die Rangliste an der Wand" }
]
```

Ein vollständiges Beispiel, das nur liest und nichts anlegt, liegt in
[`tools/plugin-beispiele/plugin-beispiel-welt.json`](tools/plugin-beispiele/plugin-beispiel-welt.json).

| `quelle` | Felder |
|---|---|
| `profile` | `bio` |
| `level` | `level`, `xp`, `messages`, `voice_minutes`, `voice_level` |
| `vrchat` | `trust`, `verifiziert_18`, `supporter`, `gruppenmitglied` |

Lässt man `felder` weg, gelten alle. `zweck` ist ein Satz, der dem Admin angezeigt wird und
sagt, wofür das gebraucht wird.

**Ein Plugin fragt nur.** Ob es darf, entscheidet jeder Server selbst: ein Haken je Ansicht
und ein eigener Schlüssel, beides aus, bis jemand es einschaltet. Ein eingespieltes Plugin
kommt damit an gar nichts. Freigegeben liegen die Daten unter:

```
GET https://dein-dashboard/api/plugin/<kennung>?key=<SCHLÜSSEL>
```

```json
{
  "gefunden": true,
  "plugin": "meine-welt-tafeln",
  "stand": "2026-11-18T17:40:12Z",
  "daten": {
    "profile": [{ "vrchat_name": "Jemand", "bio": "…", "geaendert": "2026-11-17T20:11" }],
    "level":   [{ "vrchat_name": "Jemand", "level": 9, "xp": 900 }]
  }
}
```

Alles kommt in **einer** Antwort — eine Welt lädt einmal und sucht dann selbst darin, statt
pro Besucher eine Abfrage zu starten. Das ist bei VRChats Sperrzeit zwischen zwei
Ladevorgängen der Unterschied zwischen „geht" und „geht nicht".

Drei Regeln sind dabei fest eingebaut und nicht einstellbar:

1. **Nur freigegebene Profile.** Ein Profiltext erscheint genau dann, wenn die Person selbst
   den Knopf dafür gesetzt hat. Eintragen ist nicht Veröffentlichen.
2. **Keine Discord-Kennungen.** Gefunden wird über den VRChat-Namen aus der Verknüpfung; wer
   keine hat, steht nirgends. Sonst wäre die Antwort eine fertige Liste „VRChat-Name →
   Discord-Konto", und die hat niemand bestellt.
3. **Nur was oben steht.** Kein Plugin kann eine Tabelle oder Spalte nennen, an die hier
   niemand gedacht hat — E-Mail-Adressen, Tokens und Verwarnungen sind damit nicht „noch
   nicht freigegeben", sondern unerreichbar.

Alle Haken zu entfernen schaltet den Abruf ganz ab und löscht den Schlüssel. Ein geänderter
Schlüssel sperrt die alte Adresse sofort aus. Abrufe sind je Adresse gedrosselt.

> **Eine Debug-Konsole für VRC-Link.** Im **VRC-Link**-Reiter eines Servers öffnet das 🐞-Icon
> (neben ℹ und ⚠) ein kleines, zentriertes Konsolenfenster mit ein paar festen Befehlen:
> `data <name>` zeigt genau die Felder, die ein Plugin aus der Quelle `vrchat` läse (`trust`,
> `verifiziert_18`, `supporter`, `gruppenmitglied`, nur bestätigte Verknüpfungen);
> `status <name>` zeigt den vollen Verknüpfungs-Status — auch wartende und ungelöste — damit man
> Probleme sieht; `live` zeigt die VRC-Link-Vorgänge dieses Servers in Echtzeit, bis man `stop`
> tippt; `help` listet sie auf. Es ist **keine Shell**: Es kennt nur diese festen Befehle und
> führt nur feste, parametrisierte Abfragen aus.

### Ein Plugin aktuell halten

Nennt ein Plugin eine `quelle`, kann **Einstellungen → Plugins** dort nachfragen, ob es
etwas Neueres gibt — je Plugin oder mit „Bei allen nachsehen" für die ganze Liste. Findet
sich eine neuere Fassung, wird sie gemeldet und ein Knopf angeboten. Es wird nichts hinter
deinem Rücken geladen und eingespielt, und auf keinem Server ändert sich etwas, bis dort
jemand auf „Auf die neue Fassung bringen" drückt.

Plugins lassen sich auch **direkt über einen Link** einspielen statt über eine Datei. Ein
gewöhnlicher GitHub-Seitenlink (`github.com/du/repo/blob/main/plugin.json`) wird automatisch
in die Rohadresse umgeschrieben — das ist die häufigste Stolperstelle, also wird sie
erledigt statt erklärt.

Versionen werden **als Zahlen** verglichen, nicht alphabetisch: `1.10.0` ist richtig neuer
als `1.9.0`. „Neuer" heißt echt größer — ein Plugin, das du hier selbst bearbeitet hast,
wird also nie klammheimlich durch eine ältere Fassung von der Quelle überschrieben.

Zwei Sicherungen dabei, beide mit Absicht:

- **Nur https, und nur Adressen im offenen Netz.** Der Bot holt hier eine Adresse, die ein
  Fremder in eine Datei geschrieben hat — also eine Abfrage aus deinem Netz heraus. Private
  Adressen (`127.*`, `10.*`, `192.168.*`, `::1` und der Rest) werden abgelehnt, auch über
  eine Weiterleitung: jede Zwischenstation wird erneut geprüft statt blind verfolgt.
- **Die Kennung muss übereinstimmen.** Liegt unter der Adresse inzwischen ein anderes
  Plugin, wird das Update abgelehnt und sagt das auch. Sonst würde auf jedem Server, der das
  alte benutzt, fremder Inhalt angelegt.

### Was ein Plugin anlegen darf

| Schlüssel | Legt an |
|---|---|
| `befehle` | eigene Befehle (`trigger`, `response`) |
| `ticket_panels` | Ticket-Panels, Kategorien verschachtelt unter `optionen` |
| `level_rollen` | Level → Rolle (`level`, `role_id`) |
| `level_belohnungen` | Level → Belohnungstext (`level`, `reward`) |
| `wortlisten` | Wortlisten für den Spam-Schutz (`label`, `words`) |

Alles andere unter `inhalt` wird abgelehnt. Drei Dinge fehlen mit Absicht: Reaction Roles
(sie hängen an der Nummer einer bestehenden Nachricht, die kein Paket mitbringen kann), die
Server-Einstellungen selbst (das ist der Generalschlüssel — eine Datei soll keine Funktionen
anschalten können) und alles, worin Daten von Personen stehen.

Ein eingespieltes Ticket-Panel steht als **Entwurf** da und wird nicht von selbst
veröffentlicht: Veröffentlichen postet eine Nachricht in einen Kanal, und das soll ein
Mensch auslösen, kein Datei-Upload.

### Anlegen, ändern, entfernen

Anlegen ist **ersetzen**: Was das Plugin auf diesem Server vorher angelegt hatte, wird erst
entfernt und dann neu erzeugt. Eine geänderte Einstellung und ein Wechsel auf eine neue
Fassung sind damit derselbe Vorgang, und es stehen nie zwei Sätze Befehle nebeneinander.

Zu jeder angelegten Zeile wird mitgeschrieben, aus welchem Plugin sie stammt. **Entfernt
wird genau das — nie etwas, das nur ähnlich aussieht.** Ein Befehl, den jemand von Hand
geschrieben hat, überlebt ein Plugin, das denselben anlegen wollte: er wird beim Anlegen
übersprungen, also nicht mitgeschrieben, also auch nicht gelöscht. Änderungen, die jemand
nachträglich an den Zeilen des Plugins gemacht hat, gehen beim nächsten Anlegen verloren —
das steht auch im Dashboard, bevor man drückt.

### Einstellungen, getrennt exportierbar

Das Plugin und die Werte eines Servers sind **zwei verschiedene Dateien**. Das Plugin gibt
man weiter; die Werte (Rollennummern, Kanalnummern, eigene Formulierungen) sind die eigenen.
Unter **Server → Plugins** lassen sich die Einstellungen je Plugin exportieren und die eines
anderen Servers einspielen — die Datei passt nur zu genau diesem Plugin und wird für jedes
andere abgelehnt.

### Selber eins bauen — Schritt für Schritt

Gebraucht wird ein Texteditor. Sonst nichts.

**1. Vom Beispiel ausgehen.** [`tools/plugin-beispiele/plugin-beispiel.json`](tools/plugin-beispiele/plugin-beispiel.json)
kopieren und unter eigenem Namen speichern, Endung `.json`.

**2. Den Kopf ausfüllen.**

```json
"kennung": "mein-willkommenspaket",
"name": "Mein Willkommenspaket",
"version": "1.0.0",
"autor": "dein Name",
"beschreibung": "Ein, zwei Sätze: was bringt das einem Server?"
```

Die `kennung` ist die Identität des Plugins und ändert sich nie wieder — nimm einen Namen,
mit dem du leben kannst. `name` und `beschreibung` sieht man in der Liste; schreib sie für
jemanden, der von deinem Plugin noch nie gehört hat.

**3. Überlegen, was von Server zu Server anders ist.** Jede Rolle, jeder Kanal und jede
Stelle, an der ein Servername steht, muss der Nächste ändern können. Jedes davon wird ein
Eintrag unter `einstellungen`:

```json
{ "name": "support_rolle", "art": "rolle", "titel": "Support-Rolle", "pflicht": true }
```

- `name` — so heißt es im Inhalt, Buchstaben/Ziffern/Unterstrich
- `art` — `rolle`, `kanal`, `kategorie` (Auswahllisten) oder `text`, `mehrzeilig`, `zahl`
- `titel` — die Beschriftung über dem Feld. Formulier sie als Frage, die man beantworten kann.
- `hinweis` — freiwillig, eine Zeile darunter, wofür das gebraucht wird
- `pflicht` — `true`, wenn das Plugin ohne diesen Wert kaputt ist
- `standard` — ein vorausgefüllter Wert, bei Textfeldern

**4. Den Inhalt schreiben.** Aus den fünf Schlüsseln der Tabelle oben auswählen und die
Platzhalter dort einsetzen, wo die Werte hingehören:

```json
"inhalt": {
  "befehle": [
    { "trigger": "!regeln", "response": "Steht angepinnt — die Regeln von {{servername}} sind kurz." },
    { "trigger": "!team",   "response": "Zuständig ist <@&{{support_rolle}}>." }
  ]
}
```

Ein Rollen-Platzhalter allein ist nur eine Nummer — `<@&{{support_rolle}}>` macht daraus
eine echte Erwähnung, `<#{{kanal}}>` entsprechend einen Kanal.

**5. Hochladen.** **Einstellungen → Plugins → Datei auswählen**. Stimmt an der Datei etwas
nicht, wird nichts gespeichert und die Meldung sagt genau was: ein unbekannter Schlüssel im
Inhalt, ein Platzhalter, den du nicht erklärt hast, ein fehlendes Pflichtfeld. Ändern,
nochmal hochladen.

**6. Auf einem Server ausprobieren.** Server öffnen, **Plugins**, Formular ausfüllen,
anlegen. In Discord nachsehen, ob es so aussieht wie gedacht. Passt nicht? Datei ändern,
`version` hochsetzen, neu hochladen, auf dem Server auf „Auf die neue Fassung bringen"
drücken.

**7. Weitergeben.** **Einstellungen → Plugins → Exportieren** gibt die Datei zurück, genau
so wie der Bot sie hat. Diese Datei ist das ganze Plugin — der andere spielt sie ein, trägt
seine eigenen Rollen und Kanäle ein, fertig.

> **Solange du noch baust**, leg es immer wieder auf einem Testserver an. Anlegen ersetzt,
> was das Plugin vorher erzeugt hat — du kannst also beliebig oft probieren, ohne
> hinterherzuräumen, und „Vom Server entfernen" bringt dich jederzeit auf null zurück.

---

## Geplante Nachrichten

Unter **Server → Geplant** können Nachrichten für einen beliebigen Kanal zu einem bestimmten Datum und einer Uhrzeit eingeplant werden. Ideal für Ankündigungen, Erinnerungen oder regelmäßige Ereignisse.

---

## Discord-Events

Unter **Server → Events** lassen sich native Discord-Events direkt im Dashboard erstellen — entweder an einen Voice-Kanal gebunden oder als "externes" Event (freier Ort, z.B. ein Spiel oder eine Location außerhalb Discords). Events können bearbeitet werden, solange sie noch nicht gestartet sind; sobald Discord sie als aktiv oder beendet markiert, bleibt nur noch Löschen.

Optionale Extras beim Erstellen:
- **Ankündigungskanal** — der Bot postet dort automatisch eine Nachricht, sobald das Event startet (und optional, wenn es endet), mit Name, Zeit, Ort und einem Link zum Event
- **Erinnerungen** — beliebig viele eigene Nachrichten, die eine wählbare Anzahl Minuten vor Start gepostet werden
- **Wiederholung** — optional täglich/wöchentlich/monatlich; da discord.py Discords native Wiederhol-Events noch nicht unterstützt, legt der Bot bei Fälligkeit stattdessen automatisch ein frisches Einzel-Event an (Erinnerungs-Vorlagen werden dabei übernommen). Eine wiederholende Serie lässt sich jederzeit pausieren und fortsetzen, ohne die Erinnerungen zu verlieren, oder endgültig beenden.

---

## CrossVerification

Unter **Server → CrossVerification** lassen sich "Wenn ein Mitglied bestimmte Rollen hat/nicht hat, dann Rollen hinzufügen/entfernen"-Regeln definieren. Standardmäßig werden sie **live** ausgewertet, sofort bei jeder Rollenänderung eines Mitglieds — ein optionales, pro Server einstellbares Intervall schaltet stattdessen auf einen periodischen Voll-Durchlauf über alle Mitglieder um (0 Minuten = live).

- **Bedingung** — hat **mindestens eine** / **alle** / **keine** der gewählten Rollen
- **Aktionen** — eine Regel kann **mehrere per UND verkettete Aktionen** tragen: "Rolle A geben" *und* "Rolle B entfernen" in einer einzigen Regel, jede Aktion mit eigenem Rollen-Satz und eigenem Zielserver. Aktionen auf denselben Server werden zu einer einzigen Rollenänderung zusammengefasst — Geben und Nehmen passieren also gleichzeitig, statt als zwei Änderungen, die einander überholen können.
- **Zielserver** — jede Aktion kann auf diesem Server wirken oder auf einem **anderen** (Cross-Server-Sync für ein Netzwerk aus Servern, die denselben Bot-Token teilen — nur so erreichbare Server erscheinen im Zielserver-Dropdown)
- **Fehlende Rollen automatisch anlegen** — beim Speichern einer Regel merkt sich der Bot Name, Farbe und Einstellungen der gewählten Aktions-Rollen. Wird so eine Rolle später gelöscht, legt er sie aus diesem Schnappschuss neu an und verknüpft die Regel damit, statt die Regel stillschweigend wirkungslos werden zu lassen. Eine bereits vorhandene Rolle gleichen Namens wird übernommen, statt eine zweite anzulegen. Pro Server abschaltbar; der Bot braucht auf dem Zielserver **Rollen verwalten**. Regeln, die eine Rolle *entfernen*, legen nie etwas an.
- **Priorität** — Regeln laufen in Reihenfolge (niedrigste Zahl zuerst); betreffen zwei Regeln dieselbe Rolle, gewinnt die zuletzt angewendete. Innerhalb einer Regel gilt dasselbe: der spätere Aktionsblock gewinnt.
- **Auswertungs-Intervall** — 0 heißt live, sofort bei jeder Rollenänderung. **Empfohlen ist 1 Minute**: der periodische Voll-Durchlauf holt auch das nach, was die Live-Auswertung nie sieht — etwa einen kurzen Ausfall oder eine Rolle, die direkt auf dem Zielserver geändert wurde. Kleiner als 1 geht nicht, der Prüf-Durchlauf selbst tickt im Minutentakt.
- **Test-Sandbox** — simuliert eine beliebige Rollen-Kombination und zeigt, was passieren würde, ohne ein echtes Mitglied anzufassen
- **Debug-Ansicht** — die Schritt-für-Schritt-Spur des Bots für diesen Server direkt im Tab, statt in den Container-Logs zu wühlen

---


**Kooperationen mit anderen Installationen.** Zwei Communitys arbeiten zusammen, jede betreibt ihren eigenen Phobos: Wer drüben schon geprüft wurde, soll hier nicht noch einmal durch dieselbe Prüfung. Unter *CrossVerification* richtest du dafür eine **Kooperation** ein — jede Seite unabhängig, jederzeit kündbar.

Jede Seite legt zwei Dinge für sich fest: **was sie hergibt** (welche eigenen Rollen dem Partner als „geprüft“ gelten) und **was sie anerkennt** (welche Rollen jemand hier bekommt, wenn der Partner ja sagt). Kommt jemand neu dazu, fragt der Bot einmal beim Partner nach; ein Nein, ein Zeitablauf und ein Partner, der gerade nicht antwortet, bedeuten dasselbe — es passiert nichts. Auf eine unklare Antwort hin wird nie eine Rolle vergeben.

**Eine Kooperation ist genau so vertrauenswürdig wie der Partner.** Wer auf seiner Seite jedem ein Ja gibt, verschafft jedem die Rolle, die ihr dafür vergebt — begrenzt ist das nur durch diese eine Rolle und dadurch, dass ihr die Kooperation jederzeit beenden könnt. Nehmt also Rollen, deren Missbrauch ihr verkraften würdet, und keine, die auf eure Moderationswerkzeuge führen.

Übertragen wird ein einziges Ja oder Nein zu einer Discord-ID. Keine Namen, keine Rollen, keine Mitgliederlisten — und ein Nein sagt nicht einmal, ob die Person auf dem Partner-Server überhaupt ist. Der Partner weist sich mit einem Schlüssel aus, den deine Seite erzeugt und jederzeit zurückziehen kann; gespeichert ist nur seine Prüfsumme, angezeigt wird er genau einmal. Die Schnittstelle ist gebremst, denn „gehört dieser Mensch zu euch“ ist für sich schon eine Auskunft und soll nicht tausendmal pro Minute abfragbar sein. Interne Adressen werden abgelehnt, und Kooperations-Schlüssel landen in keinem Backup.

**Bestehende Mitglieder werden nachgeholt.** Beim Beitritt fragt der Bot sofort — aber wer beim Einrichten schon auf dem Server ist, und das sind anfangs alle, wird nur über den Abgleich erreicht. Den gibt es als Knopf in jeder Partner-Zeile (⟳) und als Takt in Minuten, den du selbst wählst (Standard 15, `0` = aus). Gefragt wird nur, wer die Rolle noch nicht hat; pro Durchgang eine begrenzte Zahl, danach wird dort weitergemacht, wo aufgehört wurde. Bricht die Verbindung mittendrin ab, gehen die Übersprungenen nicht verloren, und ein Partner, der lange braucht, hält den Bot nicht auf — nach zwanzig Sekunden ist Schluss und der Rest folgt beim nächsten Mal.

Die bestehenden Regeln bleiben davon unberührt — eine Regel wirkt innerhalb dieser Installation, eine Kooperation reicht zu jemandem, dem man vertraut, den man aber nicht verwaltet.
## Umfragen

Unter **Server → 🗳️ Umfragen** oder `/poll-create` in Discord: Umfragen mit Einzel- oder Mehrfachauswahl und live aktualisierten Stimmbalken. Optionale Extras: ein Bild und/oder Link pro Option (zu einem gemeinsamen Ergebnisbild zusammengefasst, Links darunter als klickbarer Text aufgelistet), eine live aktualisierte Rangliste der Optionen nach Stimmen, sowie entweder eine feste Auto-Ende-Dauer oder ein festes Enddatum — eine Umfrage kann sogar für einen zukünftigen Startzeitpunkt geplant werden, um sie komplett im Voraus vorzubereiten. Frage, Optionen, Bilder und Links bleiben nach dem Posten vollständig bearbeitbar; Änderungen aktualisieren die bereits gepostete Nachricht direkt.

---

## Bewertungen

Unter **Server → ⭐ Bewertungen**: eine dauerhafte, immer offene Liste — Maps, Server, Spiele, was auch immer — die Mitglieder jederzeit mit `/bewerten` (mit Autovervollständigung bestehender Einträge) mit 1 bis 5 Sternen bewerten können. Anders als bei einer Umfrage gibt es kein Ende: eine Bewertung lässt sich jederzeit ändern und ersetzt einfach die vorherige, der Durchschnitt aktualisiert sich live. `/bewertungen` postet die Liste in einen Kanal mit eingebauter Sternauswahl, damit Mitglieder bewerten können, ohne den Befehl zu kennen. Admins können einzelne Einträge zusätzlich unabhängig vom Durchschnitt als empfohlen markieren — empfohlene Einträge stehen immer ganz oben.

---

## Gameserver (AMP)

Unter **Server → 🎮 Gameserver**: eine oder mehrere von [CubeCoders AMP](https://cubecoders.com/AMP) gehostete Gameserver-Instanzen direkt aus Discord (`/gameserver-status` `/gameserver-start` `/gameserver-stop` `/gameserver-restart`) oder dem Dashboard steuern. Einmal mit URL/Nutzername/Passwort eines AMP-Accounts verbinden, jede von ihm verwaltete Instanz wird automatisch erkannt — kein einzelnes Registrieren jedes Gameservers nötig. Jede Instanz kann zusätzlich eigene Slash-Befehlsnamen bekommen (z.B. `/palworld-start`), sofort synchronisiert, ohne Bot-Neustart.

---

## Auto-Kick

Unter **Server → 🚪 Auto-Kick**: kickt automatisch Mitglieder, die nach einer einstellbaren Frist seit ihrem Beitritt noch eine dafür festgelegte "noch nicht verifiziert"-Rolle tragen — nützlich für Verifizierungs-Abläufe, bei denen eine Rolle automatisch beim Beitritt vergeben und erst manuell von einem Moderator entfernt wird, sobald jemand freigegeben ist. Beliebig viele Erinnerungs-DMs lassen sich zu unterschiedlichen Zeitpunkten vor der Frist einplanen, jede mit eigenem Text.

---

## Embed-Nachrichten

Unter **Server → 📨 Embed-Nachrichten**: komplett frei gestaltete, mehrteilige Embed-Nachrichten aus dem Dashboard in einen beliebigen Text- oder Forum-Kanal posten — jeder Block wird zu einer eigenen Embed-Karte in derselben Nachricht. Unterstützt ein Bild, einen Footer und (bei Forum-Kanälen) Tags. Anders als eine direkt in Discord getippte Nachricht bleiben diese danach aus dem Dashboard bearbeitbar — Änderungen aktualisieren die bereits gepostete Nachricht direkt, statt sie neu posten zu müssen.

---

## Geburtstags-System

Unter **Server → Geburtstage** können ein Geburtstags-Kanal und ein eigener Glückwunsch-Text konfiguriert werden. Jeden Tag um 8 Uhr morgens gratuliert der Bot automatisch — jede Person nur einmal pro Jahr.

**Die Befehlswörter bestimmst du selbst.** Standardmäßig trägt man seinen Geburtstag mit `!geburtstag TT.MM` ein, aber das Feld *Befehlswörter* nimmt eine kommagetrennte Liste, und alle funktionieren nebeneinander — mit `geburtstag, birthday, cumpleaños` benutzt auf einem mehrsprachigen Server jede Person das Wort, das sie erwartet. Die Wörter zum Löschen (standardmäßig `löschen, entfernen, delete, remove`) sind genauso einstellbar. Der Tab zeigt an, welche Wörter gerade wirken, und eine Fehlermeldung nennt immer das Wort, das die Person tatsächlich getippt hat.

**Die Antworten des Bots ebenfalls.** Die drei Antworten auf den Befehl — eingetragen, gelöscht, falsches Format — sind freie Textfelder mit Platzhaltern: `{date}` für das eingetragene Datum, `{user}` erwähnt die Person, `{command}` für das tatsächlich benutzte Befehlswort und `{delete}` für das erste Löschwort. Leer gelassen greift jeweils der vorgeschlagene Text, der grau im Feld steht. (Der tägliche Glückwunsch war schon immer einstellbar und ist davon getrennt.)

Ein Geburtstags-Befehlswort darf nicht gleichzeitig ein Custom Command dieses Servers sein — beide würden auf dieselbe Nachricht antworten —, diese Kombination wird beim Speichern abgelehnt.

---

## Listen bedienen

Listen im Dashboard — bisher Embed-Nachrichten und Ticket-Panels — lassen sich im Ganzen
bearbeiten statt Zeile für Zeile.

**Markieren und löschen.** Ein Kästchen je Zeile, eins in der Kopfzeile für alle, und ein
Knopf, der mitzählt: *Markierte löschen (3)*. Die Zahl steht da mit Absicht — „Markierte
löschen" allein lässt einen raten, ob das Kästchen oben wirklich alles erwischt hat. Beim
Löschen einer Embed-Nachricht oder eines Ticket-Panels verschwindet auch die Nachricht, die
im Kanal steht, genau wie beim einzelnen Löschen.

**Offene Tickets** haben statt einer zwei Sammelaktionen: **schließen** (räumt die Kanäle
auf, wie beim einzelnen Schließen) und **aus der Liste nehmen** (lässt die Kanäle stehen).
Jedes Ticket läuft für sich — klemmt eines, weil Rechte fehlen oder der Kanal schon weg ist,
laufen die anderen trotzdem durch, und am Ende steht da, wie viele es waren.

**Umsortieren** geht auf zwei Wegen. Die **Pfeile** ↑ ↓ schieben eine Zeile einen Platz; am
oberen und unteren Ende sind sie ausgegraut. Oder **Zeile festhalten und ziehen** — beim
Loslassen wird gespeichert und die Seite lädt neu. Die Pfeile bleiben, weil es Ziehen auf
einem Touchgerät nicht gibt und mit der Tastatur auch nicht.

Zwei Dinge, die man wissen sollte:

- Was nie umsortiert wurde, steht auf Platz 0 und behält damit die bisherige Reihenfolge,
  neueste zuerst. Beim ersten Ziehen oder Pfeildruck bekommt die Liste dieses Servers feste
  Plätze ab 1.
- Ein abgebrochener Zug — Escape, oder außerhalb der Liste losgelassen — lädt die Seite neu.
  Die Vorschau war nie gespeichert, und eine Liste, die etwas anderes zeigt als gespeichert
  ist, ist schlimmer als gar keine Vorschau.

---

## Backup & Wiederherstellen

Jeder Nutzer kann seine eigenen Daten (Konto, Bot-Tokens, alle Server-Konfigurationen) als JSON-Datei über die **Profilseite** exportieren. Admins können zusätzlich:

- Backup eines einzelnen Nutzers herunterladen
- **Komplett-Backup** des gesamten Systems (alle Nutzer, Tokens, Konfigurationen)
- **Backup eines einzelnen Servers** (nur dessen Konfiguration — keine Nutzer, keine Tokens) direkt über die Dashboard-Seite dieses Servers herunterladen und auf einen beliebigen anderen Server wiederherstellen
- Beliebiges Backup per Datei-Upload **wiederherstellen** — bestehende Einträge werden aktualisiert, neue hinzugefügt, nichts wird gelöscht

### Dasselbe Backup ein zweites Mal

Einspielen **legt an**, es gleicht nicht ab. Wer dieselbe Datei dreimal einspielt, hat danach dreimal dieselben Reaction Roles, Befehle und Panels — und merkt es erst hinterher.

Jede exportierte Datei trägt deshalb eine **Kennung** und eine **laufende Nummer**, und die Nummer steht im Dateinamen: `backup_server_MeinServer_nr0007_20261118_1430.json`. Gezählt wird je Server, damit zwei Dateien desselben Servers an etwas auseinanderzuhalten sind, das auch etwas bedeutet — anders als das `(1)`, das der Browser anhängt.

Eine Datei, die **auf diesem Server** schon eingespielt wurde, wird abgelehnt — mit Datum, wer es war und welche Nummer sie hatte. Wer es trotzdem will, setzt den Haken neben dem Upload, auf dem steht, was dann passiert. Dieselbe Datei auf einem **anderen** Server einzuspielen ist nicht gesperrt: genau dafür ist das Server-Backup da, und dort wird nichts doppelt.

Ältere Backups von vorher haben keine Kennung; für die springt der Fingerabdruck der Datei ein, sodass auch eine alte Datei zweimal hochgeladen auffällt.

### Einen Server an jemand anderen übergeben

Genau dafür ist das Server-Backup gebaut: Es hängt an **keinem Bot-Token und an keinem Benutzerkonto**, die Datei lässt sich also in einer völlig fremden Phobos-Installation auf einen beliebigen Server einspielen. Herunterladen und Einspielen dürfen nur Admins.

Enthalten sind die Einstellungen dieses einen Servers über alle 22 Konfigurationsbereiche: Reaction Roles, Commands, Tickets, Level-Rollen und -Belohnungen, Auto-Mod-Kategorien, geplante Nachrichten, wiederkehrende Events samt ihrer Erinnerungs-Vorlagen, Embed-Nachrichten, CrossVerification-Regeln, Bewertungen, Auto-Delete, Auto-Thread, Temp-Voice, Twitch-Benachrichtigungen, Free-Stuff-Kanäle, Gameserver-Anbindung, Geburtstage, Verwarnungen — und die VRChat-Verknüpfungen der Mitglieder.

> Zwei Dinge, die man wissen sollte. **Die VRChat-Verknüpfungen sind Daten von Personen**, keine Einstellungen: Namen und Konto-Kennungen echter Menschen wandern mit dieser Datei mit. **Plugins stecken nicht drin** — was ein Plugin angelegt hat (Befehle, Panels, Belohnungen), kommt als gewöhnliche Einstellung mit, die Verbindung zum Plugin aber nicht. Auf dem Zielserver sind das danach von Hand angelegte Einträge, die sich über das Plugin nicht mehr entfernen lassen.

Bewusst nicht enthalten: Dashboard-Nutzer und deren Berechtigungen, Bot-Tokens, sowie sämtliche Laufzeit- und Verlaufsdaten (Level-Punkte, Logs, offene Tickets, laufende Giveaways und Umfragen, Zähler).

**Die AMP-Zugangsdaten (Panel-Benutzer und -Passwort) bleiben standardmäßig leer**, weil diese Datei dafür gedacht ist, jemand anderem in die Hand gedrückt zu werden. Ein Haken neben dem Herunterladen-Knopf nimmt sie mit — setz ihn nur, wenn du einen Server zwischen deinen *eigenen* Installationen umziehst.

Passwörter bestehender Konten werden beim Einspielen nie überschrieben.

---

## Zwei-Faktor-Authentifizierung

Jeder Dashboard-Nutzer kann unter **Profil → Zwei-Faktor-Authentifizierung** TOTP-basierte 2FA aktivieren — kompatibel mit Google Authenticator, Authy, Aegis und ähnlichen Apps. Nach einmaliger Bestätigung mit dem Code aus der App werden 8 Backup-Codes angezeigt (für den Notfall, falls das Handy verloren geht); sie lassen sich jederzeit mit dem Passwort neu erstellen. Der Login verlangt danach zusätzlich zum Passwort den App-Code (oder einen Backup-Code); wiederholt falsche Codes sperren das Konto vorübergehend.

Die Backup-Codes lassen sich ausdrucken: auf dem Blatt stehen Name der Installation, Konto, Adresse des Dashboards und das Datum — sonst liegen bei zwei Installationen zwei nicht unterscheidbare Zettel herum.

**Passwort zurücksetzen bei einem Konto mit 2FA** verlangt den Code, *bevor* die Mail rausgeht — aus der App, oder einen Backup-Code, wenn das Handy weg ist. Ohne diesen Schritt würde der Zugriff auf das Postfach allein genügen, um das Konto zu übernehmen: der Link setzt ein neues Passwort, und bis dahin steht nichts weiter im Weg. Drei falsche Codes sperren den Weg für eine Stunde, getrennt vom Login gezählt, damit sich beide nicht gegenseitig sperren. Ein neuer Anlauf an der Adressmaske hebt die Sperre nicht auf.

### Ganz ausgesperrt

Kein Passwort, kein SMTP eingerichtet (also keine Mail zum Zurücksetzen), kein zweiter Admin — dann führt der Weg über den Server:

```bash
docker exec -it Phobos-Bot python3 /repo/tools/passwort_setzen.py --liste
docker exec -it Phobos-Bot python3 /repo/tools/passwort_setzen.py --benutzer <name>
docker exec -it Phobos-Bot python3 /repo/tools/passwort_setzen.py --benutzer <name> --2fa-aus
```

Das Passwort wird abgefragt, nicht als Argument übergeben — sonst stünde es in der Shell-Geschichte und in der Prozessliste. Beim Setzen werden alle offenen Anmeldungen dieses Kontos beendet. `--2fa-aus` schaltet zusätzlich die Zwei-Faktor-Anmeldung ab und verwirft die Backup-Codes; das braucht man, wenn auch das Handy weg ist. Damit geht nichts auf, was nicht ohnehin offen wäre: wer eine Shell auf der Maschine hat, kann die Datenbank sowieso lesen und schreiben.

---

## Sicherheit

Das Dashboard soll im offenen Internet stehen können, deshalb ist einiges bewusst geregelt statt dem Zufall überlassen.

**Anmeldung.** Nach 5 falschen Passwörtern von derselben Adresse auf dasselbe Konto ist diese Kombination 15 Minuten gesperrt; ein zweiter, lockerer Zähler je Adresse fängt das Durchprobieren vieler Benutzernamen ab. Ein unbekannter Benutzername wird gegen einen Dummy-Hash geprüft, damit die Antwort genauso lange braucht — sonst verrät allein die Antwortzeit, welche Konten es gibt.

**Sitzungen.** Jede Anmeldung bekommt ein eigenes Handle, das auf dem Server liegt. Abmelden löscht es, eine mitgeschnittene Kopie des Cookies ist im selben Moment wertlos — egal ob von einem geteilten Rechner, aus einem Backup oder einem Proxy-Protokoll. Andere Geräte desselben Nutzers bleiben angemeldet. Das Handle steht gehasht in der Datenbank, ebenso Passwort-Reset-Token und Einladungscodes: alle drei werden nur verglichen, nie zurückgelesen — wer die Datenbankdatei liest, kann damit nichts anfangen.

**Ein Cookie, und nur fürs Dashboard.** `phobos_session`, `HttpOnly` und `SameSite=Lax` — Letzteres stellt zugleich den CSRF-Schutz. Die Mitglieder-Seiten von VRC-Link setzen **gar kein Cookie**. Ein Anmelde-Cookie ist technisch notwendig und braucht daher kein Banner.

**Kopfzeilen.** Jede Antwort trägt `X-Frame-Options: SAMEORIGIN`, `Content-Security-Policy: frame-ancestors 'self'`, `X-Content-Type-Options: nosniff` und eine `Referrer-Policy`. Bewusst keine vollständige CSP: das Dashboard lebt von inline geschriebenem JavaScript, eine Richtlinie ohne `unsafe-inline` würde jede Seite auf einen Schlag lahmlegen.

**Hinter HTTPS** trägst du `PHOBOS_COOKIE_SECURE=1` in den `environment:`-Block deiner docker-compose ein. Das setzt das `Secure`-Flag und schickt HSTS. Standardmäßig ist es **absichtlich aus** — ein Secure-Cookie wird über einfaches HTTP vom Browser verworfen, einmal falsch geraten sperrt es eine laufende Installation aus ihrem eigenen Dashboard aus.

**Backups lassen sich verschlüsseln.** Jeder Export — eigene Daten, ein einzelner Nutzer, die ganze Installation, ein einzelner Server — nimmt ein optionales Passwort entgegen. Trägst du eins ein, verlässt die Datei den Server unlesbar; lässt du es leer, bekommst du dasselbe Klartext-JSON wie bisher, vorhandene Abläufe und ältere Dateien laufen also weiter. Beim Einspielen wird nur dann nach dem Passwort gefragt, wenn die Datei tatsächlich verschlüsselt ist. Vergisst du es, ist nur *diese Datei* verloren — auf dem Server ändert sich nichts. Gebaut allein mit Pythons Standardbibliothek (scrypt + HMAC), weil ein kompiliertes Krypto-Paket die Android- und Termux-Wege zerlegen würde.

**Nicht geschützt:** Discord-Token, VRChat-Zugangsdaten, die 2FA-Geheimnisse der Nutzer sowie SMTP- und AMP-Passwort liegen *auf dem Server* im Klartext, weil der Bot sie zurückbraucht. Wer die Maschine kontrolliert, kommt daran — daran ändert auch eine verschlüsselte Datenbank nichts, denn der Schlüssel müsste ebenfalls dort liegen. Was du tun kannst, ist die Kopien schützen: Export-Passwort nutzen und `data/`-Backups verschlüsselt aufbewahren. Und das Standard-Passwort `admin` bei der ersten Anmeldung ändern.

---

## Event-Logging

Unter **Server → Log** konfigurierbar:

- **Log-Kanal** — Discord-Kanal für die Ereignis-Meldungen
- **Kanäle ausschließen** — Kanäle, deren Nachrichten NICHT geloggt werden (z.B. Spam-Kanal)

Die 9 nativen Kategorien unten laufen immer mit. Jeder Dashboard-Nutzer kann sich zusätzlich einen **persönlichen Anzeige-Filter** setzen (welche Kategorien er selbst in der Dashboard-Log-Ansicht sieht — der konfigurierte Log-Kanal bekommt unabhängig vom persönlichen Filter immer jedes native Ereignis):
- Mitglied beigetreten / verlassen (mit Rollen beim Verlassen)
- Rollen-Änderungen, Nickname-Änderungen, Timeouts
- Bans / Entbannungen
- Nachricht gelöscht — **inkl. wer gelöscht hat** (benötigt „Audit-Log anzeigen"-Berechtigung)
- **Massenlöschung** (z.B. `/clear`-Befehl) mit verantwortlichem Moderator
- Nachricht bearbeitet (vorher + nachher + Sprung-Link)
- Voice-Kanal beigetreten / verlassen / gewechselt
- Kanal erstellt / gelöscht / umbenannt
- Server-Boost-Änderungen

Zusätzlich gibt es 7 **Bot-Aktions-Kategorien**, die pro Server einzeln zuschaltbar sind (standardmäßig alle aus): Umfragen gepostet/beendet, Tickets erstellt/geschlossen, Giveaways gestartet/beendet, Warnungen (`/warn`), Auto-Mod-Aktionen (Warn/Timeout/Kick/Ban durch den Spam-Schutz), gesendete geplante Nachrichten sowie versendete Geburtstags-Glückwünsche.

---

## Bug & Feature-Meldungen

Admins können unter **Einstellungen → 📣 Melden** einen Bug melden oder eine Erweiterung vorschlagen. Das Formular füllt Titel, Beschreibung (Bot-Version und Plattform werden automatisch angehängt) und ein Bug-/Erweiterung-Label vor, öffnet dann GitHubs eigene "New Issue"-Seite in einem neuen Tab für das [öffentliche Repository](https://github.com/LucyWolf/phobos-bot/issues) — der Bot selbst speichert nie einen GitHub-Token und schickt nichts von sich aus ab; zum tatsächlichen Absenden dort ist ein kostenloser GitHub-Account nötig.

---

## Berechtigungssystem

Bewusst einfach gehalten — nur zwei Basis-Rollen, keine wiederverwendbaren, konfigurierbaren Berechtigungssets:

| Rolle | Rechte |
|---|---|
| **Admin** | Alles: globale Einstellungen, Benutzerverwaltung, Bot-Tokens, Streaming-API-Zugangsdaten, SMTP, Updates, Bot-Design und jeder verbundene Server |
| **Moderator** | Nur die Server, die ihm unter **Benutzer** explizit freigegeben wurden, oder automatisch über einen zugewiesenen Bot-Token. Manche rein lesbaren Seiten (z.B. Bot-Info) bleiben trotzdem sichtbar |

Das allererste Konto (`admin` / `admin`, siehe Installation weiter unten) ist immer Admin. Es muss immer mindestens ein Admin existieren — das Dashboard verhindert das Herabstufen oder Löschen des letzten verbleibenden.

Ein paar feinere Stellschrauben gibt es trotzdem:

- **Neue Nutzer** können direkt von einem Admin angelegt werden, oder sich selbst über einen einmaligen **Einladungslink** (Benutzer-Seite) registrieren, der nach 5 Minuten abläuft
- Der Zugriff eines Moderators auf einen bereits freigegebenen Server lässt sich auf **bestimmte Reiter einschränken** (z.B. nur Tickets und Umfragen), direkt im 👥-Nutzer-Tab dieses Servers
- Jeder Server kann unabhängig **ungenutzte Funktions-Reiter aus seiner eigenen Seitenleiste ausblenden**, rein zum Aufräumen bei Servern die nur wenige Funktionen nutzen — das schränkt keinen Zugriff ein, blendet nur die Navigation aus
- Admins können **sofort jede aktive Sitzung überall beenden** (Benutzer-Seite) — nützlich falls ein Gerät oder eine Sitzung mal kompromittiert wurde

---

## Installation

### Voraussetzungen

- Docker & Docker Compose
- Nginx Proxy Manager (empfohlen) oder anderer Reverse-Proxy

> **Docker noch nicht installiert?** Unter Linux richtet das offizielle Installations-Skript Docker Engine, die CLI und das Compose-Plugin (`docker compose`, wird in dieser README durchgehend verwendet) in einem Rutsch ein:
> ```bash
> curl -fsSL https://get.docker.com | sh
> ```
> Unter Windows oder macOS stattdessen [Docker Desktop](https://www.docker.com/products/docker-desktop/) installieren — bringt dasselbe Compose-Plugin schon mit.

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
>
> Auf so einer kleinen Maschine lohnen sich die zwei auskommentierten Zeilen in der `docker-compose.yml` (`mem_limit` / `pids_limit`): sie decken einen ausgebrochenen Container ab, damit eine kaputte Instanz nicht den ganzen Pi mitreißt. Standardmäßig aus, bremsen den Normalbetrieb nicht — die Schrittanleitung steht unter **[Ressourcengrenzen](#ressourcengrenzen-für-kleine-maschinen--schritt-für-schritt)**.

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

### Was das Update braucht

Das Update aus dem Dashboard führt `git` im Container aus, und zwar in `/repo` — dem
Projektordner, der vom Wirt eingehängt wird. In der `docker-compose.yml` müssen alle drei
Zeilen stehen:

```yaml
    volumes:
      - ./app:/app
      - ./data:/app/data
      - .:/repo
```

Fehlt die letzte, scheitert das Update, bevor es anfängt (ab 1.19.38 sagt es das auch;
ältere Fassungen zeigten nur `exit 128`). **Ein Neustart behebt das nicht** — Docker
übernimmt Einhängepunkte nur beim *Neuerstellen*, nach einer Änderung an der Datei also
`docker compose up -d`. Dasselbe gilt für `./data:/app/data`: ohne diese Zeile liegt die
Datenbank im Container und ist weg, sobald er neu erstellt wird. Was tatsächlich eingehängt
ist, zeigt:

```bash
docker inspect <container-name> --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```

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
│   ├── entrypoint.sh         # Gibt root ab, bevor der Bot startet (siehe Sicherheit)
│   ├── main.py               # FastAPI-Routen + Bot-Setup
│   ├── database.py           # SQLite-Schema + Hilfsfunktionen
│   ├── i18n.py               # DE/EN Übersetzungen
│   ├── totp.py               # TOTP-Secret/QR/Backup-Code-Logik für 2FA
│   ├── plugins.py            # Plugin-Format: Prüfung, Platzhalter, Anlegen/Entfernen
│   ├── befehlstexte.py       # Englische Namen/Beschreibungen der Slash-Befehle
│   ├── vrchat.py             # VRChat-API-Client (Login, 2FA, Profilabfragen)
│   ├── backup_crypto.py      # Mit Passwort verschlüsselte Backup-Dateien
│   ├── logbuch.py            # Schreibt jedes print() zusätzlich nach data/logs/phobos.log
│   ├── cogs/
│   │   ├── moderation.py
│   │   ├── leveling.py
│   │   ├── welcome.py        # Willkommenskarte (Pillow-Bildgenerierung)
│   │   ├── automod.py        # Spam-/Link-/Wort-Filter
│   │   ├── reaction_roles.py
│   │   ├── logging_cog.py    # Event-Logging mit Audit-Log
│   │   ├── log_utils.py      # Geteilter "Bot-Aktion loggen"-Helfer (kein Cog)
│   │   ├── custom_commands.py
│   │   ├── tickets.py
│   │   ├── giveaways.py
│   │   ├── notifications.py  # Twitch Live-Benachrichtigungen
│   │   ├── freestuff.py      # Free Stuff & Deals
│   │   ├── auto_delete.py    # Automatisches Löschen nach Zeit
│   │   ├── auto_thread.py    # Ein Thread pro Nachricht in gewählten Kanälen
│   │   ├── auto_kick.py      # Kickt Mitglieder mit "nicht verifiziert"-Rolle
│   │   ├── temp_voice.py     # Join-to-Create Temp-Voice-Kanäle
│   │   ├── scheduler.py      # Geplante Nachrichten + wiederkehrende Events
│   │   ├── birthday.py       # Geburtstags-Glückwünsche
│   │   ├── polls.py          # Umfragen mit Bildern, Rangliste, Planung
│   │   ├── ratings.py        # Dauerhafte 1-5-Sterne-Bewertungslisten
│   │   ├── amp.py            # CubeCoders-AMP-Gameserver-Steuerung
│   │   ├── vrc_link.py       # VRChat-Verknüpfung, Gruppenabgleich, Instanzen
│   │   ├── profile.py        # Profile der Mitglieder (/bio, /inspect, ...)
│   │   └── role_rules.py     # CrossVerification (Rollen-Bedingungsregeln)
│   ├── templates/            # Jinja2 HTML-Templates
│   └── assets/               # Mitgelieferte Willkommenskarte-Overlay-Vorlagen (PNG)
├── tools/                    # Hilfsskripte, Prüfungen vor jedem Commit und
│                             # dazu zwei Beispiel-Plugins zum Abschreiben
├── android/                  # Android-Studio-Projekt - packt den Bot als echte APK
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
| pyotp + qrcode | 2.9.0 / 7.4.2 |

Bot und Web-Dashboard laufen im **selben asyncio-Prozess** — kein separater Web-Server nötig.

---

## Eine Anmerkung zu diesem Projekt

Dieser Code wurde von Claude AI erschaffen – und ich weiß, viele rümpfen bei diesen Worten die Nase. Trotzdem steht dieser Bot für einen einfachen Gedanken: für alle da zu sein, ohne Ausnahme. Eine KI ist kein Wundermittel, das jedes Problem von selbst löst – sie ist ein Werkzeug, das seine Kraft erst durch die Hände entfaltet, die es führen. Und weil dahinter keine bezahlte Arbeit steckt, sondern nur die Zeit, die ich gerne investiert habe, wird dieser Bot niemals etwas kosten. Alle Dateien liegen offen, für jeden frei zugänglich, frei verwendbar.

Ich will an dieser Stelle ehrlich sein: Das hier ist KI-generiert, und ich beanspruche nicht, es selbst geschrieben zu haben. Diese Ehre gebührt mir nicht. Der 3D-Drucker hat einst Hobby-Ingenieure entstehen lassen, die damit Probleme des Alltags lösten, für die ihnen früher Wissen oder Mittel fehlten. Genau das kann – und sollte – auch KI sein: kein Wundermittel, sondern ein Werkzeug, das unser Leben einfacher macht. Ein Werkzeug, mit dem auch Menschen ohne Informatik-Hintergrund die kleinen, nervigen Probleme angehen können, die uns allen begegnen. Nicht aus Anspruch auf Genialität, sondern aus dem einfachen Wunsch, etwas besser zu machen.

> *— lucy_wolf*
