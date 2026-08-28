# Phobos Bot — Android app (Chaquopy)

**Status: confirmed working on real hardware.** Builds via `./gradlew assembleDebug` (JDK 17,
Android SDK, Gradle 8.4, Chaquopy 15.0.1) into an installable `app-debug.apk` (~30 MB), and has
been running end-to-end on an actual old Android 6 phone: the bot starts, connects to Discord,
serves the dashboard, survives the screen being locked, shows live CPU/RAM stats, and can update
itself in-place from a new APK triggered straight from the dashboard's Bot-Update page (see
"Real-device findings" below). This has only been exercised on that one specific device/API
level so far, not the full API 21–34 range this project targets.

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

**Requires Android 5.0 (API 21) or newer** — the documented minimum for the specific Chaquopy
version this project pins (15.0.1; see `app/build.gradle`'s `minSdk` comment - the *current*
Chaquopy release actually requires API 24, that floor was only introduced in a later version).
Anything from roughly 2014 onward should be fine, covering the vast majority of "spare phone in
a drawer" hardware.

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
   the Bot-Info dashboard page's CPU/RAM display — `app/main.py` does
   `try: import psutil / except ImportError: psutil = None`. Rather than just falling back to
   `0`, `get_system_stats()` has a `_proc_stats()` fallback that reads `/proc/meminfo`,
   `/proc/stat` and `/proc/self/status` directly (the same files psutil itself reads on Linux
   under the hood) - real numbers, not a placeholder, confirmed against the real device. This
   change is in the shared `app/` code but is a no-op for Docker/Termux, where psutil installs
   fine and takes priority when present.

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

## Real-device findings

Getting from "builds" to "actually runs" on a real (old, low-end) phone surfaced a string of
issues invisible from the build machine alone - worth knowing before touching this project
again, since several of them would silently reappear if undone:

- **Chaquopy bundles its own Python 3.8**, independent of `buildPython` (which only affects
  build-machine tooling). Any code using Python 3.9+ syntax breaks at runtime, not build time:
  builtin generic type hints (`dict[str, int]`, `list[str]`, `tuple[...]` etc., PEP 585) and the
  `X | Y` union syntax (PEP 604) both raise `TypeError: 'type' object is not subscriptable` the
  moment the module is imported. Fixed with `from __future__ import annotations` throughout the
  shared `app/` code (defers all annotations to strings, never evaluated) - except a couple of
  FastAPI route parameters whose types FastAPI actually inspects at runtime (`Form(...)` list
  fields), which needed real `typing.List`/`typing.Optional` instead. `str.removeprefix()`
  (3.9+) needed a manual replacement too.
- **A pip version old enough to predate PEP 668-era cross-platform-install safeguards is bundled
  by Chaquopy 15.0.1.** It silently drops transitive dependencies of anything installed via
  `requirements-android.txt` instead of erroring - `discord.py` needed `aiohttp` (and aiohttp's
  own dependency chain: `multidict`, `yarl`, `frozenlist`, `aiosignal`, `attrs`,
  `async-timeout`, `charset-normalizer`, `idna`) spelled out explicitly, `starlette` needed
  `anyio`/`sniffio`/`exceptiongroup`, `uvicorn` needed `click`/`h11`, `bcrypt` needed
  `six`/`cffi`/`chaquopy-libffi`/`pycparser`, `Pillow` needed `chaquopy-libjpeg`/
  `chaquopy-freetype`, `qrcode` needed `pypng` (its `PyPNGImage` fallback is only ever *used*
  when Pillow is missing, but the *import* is unconditional - conditional use isn't the same as
  conditional import). All now listed explicitly in `requirements-android.txt`, with comments
  explaining why each one is there.
- **`pydantic` resolving to its 2.x line pulls in `pydantic-core`, a Rust extension with no
  prebuilt Android wheel and no toolchain here to build it.** Pinned to `pydantic==1.10.13`
  instead (still pure Python, still has a universal wheel) - safe since Phobos Bot's own code
  never imports pydantic directly.
- **`Jinja2Templates(directory="templates")` (a relative path) silently broke under Chaquopy** -
  the app's working directory isn't the same as under Docker, where it happened to coincidentally
  match. Fixed with an absolute `Path(__file__).parent / "templates"` - a real, general
  robustness fix, not an Android-only workaround.
- **`versionCode` has to actually increase between builds**, or Android's installer treats a
  newer APK as nothing to install - it'll show the install dialog but not really replace
  anything. Now derived from `app/VERSION` at build time (see `app/build.gradle`) instead of
  being a hand-maintained constant, so it's not possible to forget.
- **`getExternalFilesDir(null)`/`filesDir` (private app storage) is invisible over USB (MTP)
  since Android 11, and unreadable by *other* apps (like the system installer) on any Android
  version** - two different restrictions, easy to conflate. Files meant to be picked up outside
  the app (crash logs, the downloaded update APK before installing it) need the public Downloads
  folder or `getExternalFilesDir()` respectively.
- **A held `PowerManager.WakeLock` alone doesn't keep the WiFi radio at full power** - without an
  additional `WifiManager.WifiLock`, the dashboard can become unreachable from other devices
  once the screen locks even though the bot process itself is fine. Also added a prompt for
  Doze/battery-optimization exemption (`ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`) - some
  budget/OEM-skinned Android builds kill foreground services on screen-lock regardless of either
  of the above, which is outside what any app can fix from code; that needs a
  manufacturer-specific "protected apps"/"autostart" setting found manually on the device.
- **A full silent self-update (zero user interaction) isn't possible for a normal, non-system
  app** - Android requires explicit confirmation to install anything from outside its own
  package manager, by design, regardless of permissions requested. The one remaining manual step
  in the in-app updater is that confirmation tap; going further would require Device Owner mode
  (a real, more invasive setup: one-time ADB provisioning, generally requires no Google account
  on the device, turns the phone into a "managed device") - not implemented, since it's a much
  bigger commitment than what's needed to make this usable.
- **Chaquopy licensing** for your specific use case (see below) — check yourself, terms change.

## Chaquopy licensing

Chaquopy is free for local/personal use and open-source projects that aren't distributed via
Google Play; commercial Play Store distribution needs a paid license. Since the intent here is
side-loading onto your own phone, this should fall under the free tier — but licensing terms
change, so check [chaquo.com/chaquopy/license](https://chaquo.com/chaquopy/license/) yourself
before relying on that.

## Installing the built APK

Don't want to build it yourself? A pre-built APK is published under
[GitHub Releases](https://github.com/LucyWolf/phobos-bot/releases), tag `android-v1.6.16-debug`
- the tag name itself is intentionally not tied to a bot version (kept fixed), since the asset
underneath it gets replaced on every Android-related commit; the release notes describe its
actual current state.

Otherwise, `app/build/outputs/apk/debug/app-debug.apk` is a debug-signed build — installable
directly via `adb install app-debug.apk`, or by copying it to the phone and opening it (Android
will prompt to allow installs from that source). No Play Store involved.

## Updating

Unlike Termux (which needs a manual `git pull` + restart), the dashboard's **Bot-Update** page
works here too - it just does something different under the hood than the Docker/Termux `git`-
based flow. On Android it downloads the latest `phobos-bot.apk` from this repo's Releases
straight to the phone and hands off to Android's own install prompt; confirming that one dialog
is the only manual step (see "Real-device findings" above for why a fully silent update isn't
possible without a much bigger Device Owner setup). `main.py` tells the two update paths apart
via a `PHOBOS_PLATFORM=android` env var that `PhobosService.kt` sets before starting Python.

## What's deliberately NOT done here

- **App icon** is a placeholder vector shape (`ic_launcher_foreground.xml`/`_background.xml`),
  not real artwork.
- **No release signing config** — this only produces Android Studio's own debug-signed builds
  for now.
