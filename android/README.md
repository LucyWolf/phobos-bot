# Phobos Bot — Android app (Chaquopy)

**Status: written blind, never built or run.** There is no Android SDK, emulator, or physical
device available in the environment this was written in — everything below is my best
understanding of how Chaquopy/Gradle/Android projects fit together, not something I could
verify. Expect to spend real debugging time on the first build. This document exists to make
that debugging faster, not to promise it'll just work.

## What this is

A minimal Android app that embeds a full Python interpreter (via [Chaquopy](https://chaquo.com/chaquopy/))
and runs the *exact same* `main.py` the Docker and Termux deployments run — see
`app/build.gradle`'s `python { srcDirs = ["../../app"] }`, which points Chaquopy directly at the
existing `../app` folder instead of copying the bot's source into the Android project. One
source of truth for the bot's Python code; this project is only a wrapper around it.

The bot runs inside a foreground `Service` (`PhobosService.kt`) so Android doesn't kill it in
the background. `MainActivity` just starts/stops that service and shows the phone's local IP so
you know where to point a browser.

## Prerequisites

- Android Studio (a recent version — this was written against roughly the Android
  Studio Hedgehog/Iguana era of tooling; if plugin versions below are too old/new for whatever
  you have installed, Android Studio will usually offer to upgrade them automatically on sync)
- JDK 17 (Android Studio normally bundles one)

## Opening the project

Open the `android/` folder (not the repo root) directly in Android Studio as an existing
project, and let it run Gradle sync.

## Chaquopy licensing

Chaquopy is free for local/personal use and open-source projects that aren't distributed via
Google Play; commercial Play Store distribution needs a paid license. Since the intent here is
side-loading onto your own phone, this should fall under the free tier — but licensing terms
change, so check [chaquo.com/chaquopy/license](https://chaquo.com/chaquopy/license/) yourself
before relying on that.

## Debugging order (most to least likely to fail)

1. **Gradle sync fails on plugin versions.** `build.gradle` (root) pins Android Gradle Plugin
   8.2.2, Kotlin 1.9.22, Chaquopy 15.0.1 — these three need to be mutually compatible, and I
   couldn't verify that combination against a real sync. If Android Studio complains, check
   [Chaquopy's own compatibility notes](https://chaquo.com/chaquopy/doc/current/versions.html)
   for which AGP version its current release actually supports, and adjust the Kotlin version to
   match whatever Android Studio suggests.

2. **`pip install` fails for a specific package in `requirements.txt`.** This is the biggest
   unknown. Chaquopy maintains its own repository of prebuilt wheels for common packages
   (pure-Python ones generally "just work"; some popular C-extension packages like `Pillow` are
   explicitly supported). The two I'd actually worry about:
   - **`bcrypt`** — uses a Rust extension. If Chaquopy doesn't have a prebuilt wheel for it and
     pip tries to compile from source, this will very likely fail (no Rust-for-Android
     toolchain is set up here). If it does, the fix isn't something to guess at blind — come
     back with the actual error and it can be scoped properly (options range from an
     alternate hashing library with better Android support to vendoring a prebuilt wheel).
   - **`psutil`** — C extension, same concern, slightly lower stakes since it's only used for
     the dashboard's system-stats display, not anything security-critical.
   Everything else in `requirements.txt` (`discord.py`, `fastapi`, `uvicorn`, `aiosqlite`,
   `jinja2`, `pyotp`, `qrcode`, etc.) is pure Python or has commonly-supported C extensions with
   pure-Python fallbacks, so these are lower risk.

3. **Foreground service type rejected at runtime.** `AndroidManifest.xml` declares
   `foregroundServiceType="dataSync"` for `PhobosService` — a reasonable-seeming fit for "runs a
   network server in the background", but Android 14 tightened enforcement of these types and I
   couldn't test whether `dataSync` is actually accepted for this use case. If the service
   crashes immediately with a `ForegroundServiceStartNotAllowedException` or similar, try
   `specialUse` instead (requires adding a `<property android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE" .../>`
   under the `<service>` tag — see Android's foreground service docs for the exact syntax, not
   reproduced here since it's a fairly recent, narrowly-scoped API I'd rather not guess at).

4. **App crashes on first launch after tapping "Start Bot".** Check Logcat, filter for
   `PhobosService` — any Python traceback from `main.py`'s startup (`init_db()`, admin user
   creation, etc.) will show up there via the `catch (e: Exception)` in `startPython()`.

## What's deliberately NOT done here

- **App icon** is a placeholder vector shape (`ic_launcher_foreground.xml`/`_background.xml`),
  not real artwork.
- **No release signing config** — this only really supports Android Studio's own debug-signed
  builds for now (`Run ▶` from Android Studio, or `Build > Build Bundle(s) / APK(s) > Build
  APK(s)`, then locate the APK under `app/build/outputs/apk/debug/`).
- **The Bot-Update dashboard page won't work** here any more than it does under Termux — it
  drives `docker compose`. Updating means pulling the latest code and rebuilding the app in
  Android Studio.
