# `tools/` — helpers that run outside the bot

Small scripts for things that have no place in the dashboard. None of them is needed in
normal operation.

### `passwort_setzen.py` — the way back in

For the case where nothing else works: password forgotten, no SMTP configured (so no reset
mail), no second admin — or the phone with the 2FA app is gone. Runs on the server against
the database directly.

```bash
docker exec -it Phobos-Bot python3 /repo/tools/passwort_setzen.py --liste
docker exec -it Phobos-Bot python3 /repo/tools/passwort_setzen.py --benutzer <name>
docker exec -it Phobos-Bot python3 /repo/tools/passwort_setzen.py --benutzer <name> --2fa-aus
```

The password is prompted for, never passed as an argument — otherwise it would sit in the
shell history and the process list. Setting it ends all open sessions of that account.
`--2fa-aus` additionally switches two-factor off, which is what you need when the phone is
gone too. This opens nothing that was not already open: whoever has a shell on that machine
can read and write the database anyway.

### `vorlagen_pruefen.py` — bracket check for the templates

Walks every Jinja template and reports blocks that do not close. Hooked up as
`.git/hooks/pre-commit`, so a broken template cannot be committed. It only counts brackets —
it cannot see what ends up inside what at runtime, which is why the test suite renders the
pages as well.

### `rechte_pruefen.py` — does the container still drop root?

Reads `app/Dockerfile`, `app/entrypoint.sh` and `docker-compose.yml` and fails if the bot
would come up as root again — a missing `ENTRYPOINT`, a start script that no longer hands
over, a reinstated `docker.sock` mount, a dropped `cap_drop`. Hooked up as `pre-commit`
alongside the template check. Nobody has to write "run as root" for this to come back:
Docker does that by default, so the absence of a line is enough. Whether it works in
practice is a separate question — `test_rechte.sh` answers that against the real image.

### `apk_pruefen.py` — do APK, version.txt and release note agree?

Checks that the published Android build, its version file and the release note describe the
same version. Only relevant when publishing an APK.

---

# `tools/` — Helfer außerhalb des Bots

Kleine Skripte für Dinge, die im Dashboard nichts verloren haben. Im laufenden Betrieb
braucht man keines davon.

**`passwort_setzen.py`** ist der Notausgang: Passwort vergessen, kein SMTP eingerichtet,
kein zweiter Admin — oder das Telefon mit der 2FA-App ist weg. Läuft auf dem Server direkt
gegen die Datenbank. Das Passwort wird abgefragt statt als Argument übergeben, sonst stünde
es in der Shell-Geschichte und in der Prozessliste. Mit `--2fa-aus` fällt zusätzlich die
Zwei-Faktor-Anmeldung weg.

**`vorlagen_pruefen.py`** zählt die Klammern in allen Jinja-Vorlagen und hängt als
`pre-commit`-Haken davor. Es sieht nur die Klammern, nicht was zur Laufzeit worin steckt —
deshalb rendern die Tests die Seiten zusätzlich.

**`rechte_pruefen.py`** schlägt an, wenn der Container wieder als root hochkäme — fehlender
`ENTRYPOINT`, ein Startskript, das nicht mehr übergibt, ein wieder eingehängter
`docker.sock`, ein verschwundenes `cap_drop`. Hängt ebenfalls als `pre-commit`-Haken davor.
Niemand muss dafür „als root" schreiben: Docker nimmt root von sich aus, es genügt also,
dass eine Zeile fehlt. Ob es im Betrieb wirklich klappt, prüft `test_rechte.sh` am echten
Image.

**`apk_pruefen.py`** prüft vor einer Android-Veröffentlichung, ob APK, `version.txt` und
Release-Notiz dieselbe Version meinen.
