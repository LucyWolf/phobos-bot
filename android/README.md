# Phobos Bot — Android app (Chaquopy)

**Status: builds successfully into a working APK.** Verified with a real `./gradlew
assembleDebug` run (JDK 17, Android SDK, Gradle 8.4, Chaquopy 15.0.1) — the build completes and
produces an installable `app-debug.apk` (~39 MB) containing the bot's actual Python code. What
is **not** yet verified: installing and actually running it on a real device or emulator. If
that turns up problems, they'll be Android-runtime issues (permissions, the foreground service,
first-launch behavior), not build/packaging issues — those are now sorted out.

## What this is

A minimal Android app that embeds a full Python interpreter (via [Chaquopy](https://chaquo.com/chaquopy/))
and runs the *exact same* `main.py` the Docker and Termux deployments run — see
`app/build.gradle`'s `sourceSets { main { python { srcDirs = ["../../app"] } } }`, which points
Chaquopy directly at the existing `../app` folder instead of copying the bot's source into the
Android project. One source of truth for the bot's Python code; this project is only a wrapper
around it.

The bot runs inside a foreground `Service` (`PhobosService.kt`) so Android doesn't kill it in
the background. `MainActivity` just starts/stops that service and shows the phone's local IP so
you know where to point a browser.

**Requires Android 7.0 (API 24) or newer** — Chaquopy's own documented minimum, not a limit
chosen for this app specifically (see `app/build.gradle`'s `minSdk` comment). Older "spare
phone in a drawer" hardware than that isn't supported; anything from roughly 2016 onward should
be fine, covering most of what people actually have lying around.

## Prerequisites

- Android Studio (a recent version), **or** just a JDK 17 + the Android SDK command-line tools
  if you'd rather build from a terminal — Android Studio isn't actually required, `./gradlew
  assembleDebug` is all the build needs.
- No Rust or C toolchain needed despite what an earlier version of this doc warned about — see
  below.

## Opening / building the project

Open the `android/` folder (not the repo root) directly in Android Studio as an existing
project and let it sync, or from a terminal:

```bash
cd android
./gradlew assembleDebug
```

The APK ends up at `app/build/outputs/apk/debug/app-debug.apk`.

## What actually went wrong on the first real build attempt, and how it was fixed

Written up in detail because the fixes are non-obvious and someone bumping a dependency version
later will likely hit variations of the same issues.

1. **`srcDirs` in the wrong block.** Chaquopy source directories go under
   `android.sourceSets.main.python`, not inside `defaultConfig.python` (that block is only for
   `buildPython`/`pip`). Gradle's error (`Could not set unknown property 'srcDirs'`) made this
   easy to diagnose — see `app/build.gradle`.

2. **`buildPython "python3"` resolved to Python 3.13 on the build machine, and Chaquopy's
   bundled pip doesn't work on 3.13** (`ModuleNotFoundError: No module named 'cgi'` — the `cgi`
   stdlib module was removed in 3.13, and the pip version Chaquopy vendors still imports it).
   Fix: use a Python **3.11** interpreter as `buildPython` instead — this only affects the
   *build machine's* tooling, not the Android runtime interpreter (which is Chaquopy's own
   bundled Python 3.8, unrelated). If your `python3` isn't already 3.11, either install one, or
   grab a portable build (e.g. from
   [astral-sh/python-build-standalone](https://github.com/astral-sh/python-build-standalone))
   and put it first on `PATH` before running Gradle — no system-wide changes needed.

3. **`fastapi==0.111.0` unconditionally requires `orjson`, `ujson`, `fastapi-cli`, `httpx` and
   `email_validator`** (confirmed by inspecting its wheel metadata directly — these aren't
   behind an `extra`, plain `pip install fastapi==0.111.0` pulls all of them in). `orjson` is a
   Rust extension with no prebuilt Android wheel on Chaquopy's package index and no Rust-for-
   Android cross-compilation toolchain set up here. None of these five packages are actually
   imported by Phobos Bot's code. Fixed by installing `fastapi` with `--no-deps` (via
   Chaquopy's `pip { options "--no-deps"; install "fastapi==0.111.0"; options() }` — note the
   empty `options()` afterwards to clear the flag before the next `install` call, otherwise it
   silently applies to everything installed after it too) and listing fastapi's two dependencies
   Phobos Bot's code actually needs (`starlette`, `pydantic`) explicitly in
   `requirements-android.txt` instead.

4. **`psutil==5.9.8` has no prebuilt Android wheel and needs `gcc` to build from source**,
   which isn't available under Chaquopy's build environment either. `psutil` is only used for
   the Bot-Info dashboard page's CPU/RAM display — `app/main.py` now does
   `try: import psutil / except ImportError: psutil = None`, and `get_system_stats()` falls
   back to `0` for the psutil-derived fields when it's unavailable (not `None` — the template
   does numeric comparisons like `{% if stats.cpu > 80 %}` that would raise on `None`). This
   change is in the shared `app/` code but is a no-op for Docker/Termux, where psutil installs
   fine.

5. **`bcrypt==4.2.1` and `Pillow==10.4.0` also have no prebuilt Android wheels** for those exact
   versions (bcrypt rewrote its native extension in Rust starting at 4.0; Pillow's wheel-build
   pipeline on Chaquopy's index hadn't caught up to 10.4.0). Both *do* have prebuilt wheels for
   older versions, checked directly against Chaquopy's package index
   (`https://chaquo.com/pypi-13.1/<package>/`): `bcrypt==3.1.7` and `Pillow==9.2.0`, both pinned
   for Android only in `requirements-android.txt`. Safe substitutions: bcrypt's hash format
   (`hashpw`/`checkpw`/`gensalt`) has been stable across every version — a hash created by 3.1.7
   verifies fine against 4.2.1 and vice versa, so this doesn't create any compatibility issue
   with password hashes from a Docker/Termux install. The subset of Pillow's API this project
   uses (`Image.open`/`new`, drawing, `save`) hasn't changed between 9.2.0 and 10.4.0 either.

`requirements-android.txt` documents all of this inline too, next to the actual version pins.

## If a future dependency bump breaks the build again

The general debugging move that worked repeatedly here: query Chaquopy's package index directly
for the package in question — `https://chaquo.com/pypi-13.1/<package-name-lowercase>/` — to see
which exact versions have a prebuilt Android wheel before assuming a rebuild-from-source (with
all the toolchain problems that implies) is the only option.

## What's still genuinely unverified

- **Never installed on a real device or emulator.** The APK builds and looks structurally
  correct (contains `AndroidManifest.xml`, `classes.dex`, native libs for all three target
  ABIs, and the bundled Python/bot source), but nothing has confirmed it actually launches,
  that the foreground service survives backgrounding, or that the bot successfully connects to
  Discord and serves the dashboard from a phone.
- **`foregroundServiceType="dataSync"`** — still an educated guess for Android 14's stricter
  enforcement, not confirmed against a real device.
- **Chaquopy licensing** for your specific use case (see below) — check yourself, terms change.

## Chaquopy licensing

Chaquopy is free for local/personal use and open-source projects that aren't distributed via
Google Play; commercial Play Store distribution needs a paid license. Since the intent here is
side-loading onto your own phone, this should fall under the free tier — but licensing terms
change, so check [chaquo.com/chaquopy/license](https://chaquo.com/chaquopy/license/) yourself
before relying on that.

## Installing the built APK

Don't want to build it yourself? Pre-built APKs get published under
[GitHub Releases](https://github.com/LucyWolf/phobos-bot/releases) (tagged `android-v<bot
version>-debug`) — download `phobos-bot-debug.apk` from there.

Otherwise, `app/build/outputs/apk/debug/app-debug.apk` is a debug-signed build — installable
directly via `adb install app-debug.apk`, or by copying it to the phone and opening it (Android
will prompt to allow installs from that source). No Play Store involved.

## What's deliberately NOT done here

- **App icon** is a placeholder vector shape (`ic_launcher_foreground.xml`/`_background.xml`),
  not real artwork.
- **No release signing config** — this only produces Android Studio's own debug-signed builds
  for now.
- **The Bot-Update dashboard page won't work** here any more than it does under Termux — it
  drives `docker compose`. Updating means pulling the latest code and rebuilding the app.
