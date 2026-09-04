# Codex Switcher v0.19.3

Codex Switcher is a lightweight macOS app for switching between multiple local Codex / ChatGPT Desktop launch profiles while keeping each profile's login state isolated.

## v0.19.3 app icon integration

Codex Switcher now includes its own macOS app icon. The canonical source artwork is tracked at `assets/AppIcon.png`; both local installation and GitHub Release builds automatically convert it into a standard `AppIcon.icns` and embed it in the `.app` bundle. This release also retains the v0.19.2 native `alert()` / `confirm()` / `prompt()` WKWebView dialog fix.


## Highlights

- Native macOS AppKit + WKWebView shell; no Electron runtime.
- App starts its own local Python service and stops it when you quit the app.
- Launcher A always uses the normal ChatGPT launch. B/C can use isolated `CODEX_HOME` and Desktop `user-data-dir` values.
- Local account mnemonics, quota notes, weekly reset timers, reset cards, Workspace inspection, and user Skill inspection/copying.
- English is the default UI language; Simplified Chinese remains available in Settings.
- A first-launch Welcome panel explains the local-profile model and privacy boundary. Reopen it any time with the `?` button beside the title.

## Install

```bash
./scripts/install-app.sh
```

The installer prefers `/Applications/Xcode-beta.app` when available, otherwise it falls back to the regular Xcode toolchain. It explicitly builds with a macOS 13 deployment target.

Installed app:

```text
~/Applications/Codex Switcher.app
```

The installed app bundles its Python server and web UI, so the source checkout can be moved or deleted after installation.

## User data

Codex Switcher stores user data in the standard macOS Application Support location:

```text
~/Library/Application Support/com.nigolarer.codex-switcher/
├── launcher.sqlite3
└── backups/
```

Native app logs:

```text
~/Library/Logs/Codex Switcher/native-app.log
```

### Automatic migration from older releases

If the new database does not exist, v0.19.3 automatically copies data from the previous location:

```text
~/Library/Application Support/com.ping.codex-account-switch-launcher/
```

If that location is also empty, the installer can still migrate an older project-local `data/launcher.sqlite3`. Migration is copy-only; the previous database is left intact.

## First launch

On first launch, Codex Switcher shows a short Welcome panel explaining:

- what launchers A/B/C represent;
- that account mnemonics are local labels rather than verified OpenAI identities;
- which local quota/reset information is tracked;
- that passwords and authentication tokens are not read.

Dismissal is stored locally so the panel is not shown on every launch. The `?` icon beside the app title opens it again at any time.

## Port

Default local port: `17831`. It can be changed in Settings to any value from `1024` to `65535`; restart the app after changing it.

## Workspaces

`View workspaces` is read-only. It parses `local-projects` in the selected launcher's `.codex-global-state.json` and shows each project name plus its `rootPaths`. Codex state files are not modified.

## Skills

`View Skills` inspects user-level Skill directories under `$CODEX_HOME/skills` that contain `SKILL.md`, excluding `.system`. `Copy missing Skills` copies only missing user Skill directories and never overwrites an existing same-name Skill or copies auth/workspace/thread state.

## Development mode

```bash
./scripts/run.sh
```

Development mode uses the same Application Support database as the installed app.

## Uninstall

```bash
./scripts/uninstall-app.sh
```

This removes only the app. User data is intentionally preserved in Application Support.

## GitHub / privacy

`.gitignore` excludes runtime databases, logs, Python caches, local environment files, IDE settings, build artifacts, and ZIP releases. Never commit `auth.json`, cookies, tokens, or other authentication material.

## GitHub Release build (Apple Silicon)

For the first public release, Codex Switcher targets Apple Silicon Macs only (`arm64`).

Build the distributable App on an Apple Silicon Mac:

```bash
./scripts/build-release.sh
```

The script:

- prefers `/Applications/Xcode-beta.app`, then stable Xcode;
- compiles the native AppKit/WKWebView shell for `arm64`;
- bundles the Python backend with PyInstaller, so target Macs do **not** need Python;
- embeds all static web resources inside `Codex Switcher.app`;
- applies an ad-hoc signature;
- verifies the native shell and bundled backend are arm64;
- creates the GitHub asset under `release/`.

Output:

```text
release/Codex-Switcher-v0.19.3-macOS-arm64.zip
```

End users only need to unzip the archive and move `Codex Switcher.app` into `/Applications`.
They do not need Xcode, Python, Homebrew, or the source repository.

### Gatekeeper note

The first public build is ad-hoc signed rather than Developer ID signed/notarized. On first launch, macOS may require the user to right-click the App and choose **Open**. A future notarized release can remove this friction once a Developer ID certificate is configured.
