# `app/` — the bot itself

Everything that runs inside the container. One process serves both the Discord bot and the
web dashboard, so there is no separate backend to start.

| | |
|---|---|
| `main.py` | All HTTP routes and the dashboard logic — the biggest file by far |
| `database.py` | Schema, migrations and the shared query helpers |
| `i18n.py` | German and English texts for the dashboard, kept strictly in pairs |
| `cogs/` | One file per Discord feature: welcome, leveling, tickets, VRC-Link … |
| `templates/` | The Jinja pages of the dashboard |
| `assets/` | Images shipped with the bot, e.g. the welcome-card overlays |
| `totp.py` | Two-factor codes and backup codes |
| `vrchat.py` | Talking to VRChat's (unofficial) API |
| `backup_crypto.py` | Encrypting exports — standard library only, so the Android build keeps working |
| `Dockerfile` | How the image is built |
| `VERSION` | The running version; the updater compares it against GitHub |

`data/` is created at runtime and holds the SQLite database. It is not in the repository,
and it should never be: Discord tokens, VRChat credentials, 2FA secrets and SMTP passwords
are stored there in plain text, because the bot needs them back.

> **If you clone this and work on it:** add `data/` and `.env` to your own ignore list before
> the first `git add`. The repository does not carry a `.gitignore` for them.

---

# `app/` — der Bot selbst

Alles, was im Container läuft. Ein Prozess bedient sowohl den Discord-Bot als auch das
Web-Dashboard; ein getrenntes Backend gibt es nicht.

`main.py` enthält sämtliche Routen und die Logik des Dashboards, `database.py` das Schema
samt Migrationen, `i18n.py` die deutschen und englischen Texte (strikt paarig), `cogs/` je
eine Datei pro Discord-Funktion und `templates/` die Jinja-Seiten.

`data/` entsteht erst zur Laufzeit und enthält die SQLite-Datenbank. Sie gehört nicht ins
Repository und sollte es nie: Discord-Token, VRChat-Zugangsdaten, 2FA-Geheimnisse und
SMTP-Passwörter liegen dort im Klartext, weil der Bot sie zurücklesen muss.

> **Wer hier entwickelt:** `data/` und `.env` vor dem ersten `git add` in die eigene
> Ignorier-Liste eintragen — im Repository liegt dafür keine `.gitignore`.
