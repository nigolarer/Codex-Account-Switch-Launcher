# Codex Switcher v0.18.0

Codex Switcher is a lightweight macOS app for switching between multiple local Codex / ChatGPT Desktop launch profiles while keeping each profile's login state isolated.

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

If the new database does not exist, v0.18.0 automatically copies data from the previous location:

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
