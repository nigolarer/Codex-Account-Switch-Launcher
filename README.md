# Codex Switcher

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh-CN.md">简体中文</a>
</p>

Codex Switcher is a lightweight macOS app for switching between multiple local Codex / ChatGPT Desktop launch profiles while keeping each profile's login state isolated.

It is designed for people who use more than one Codex account on the same Mac and want to switch profiles without repeatedly signing in and out, while continuing to work with the same local projects.

## Highlights

- Up to six local launchers (A–F); A remains the system-default launcher and B–F can be isolated.

- Native macOS AppKit + WKWebView app; no Electron runtime.
- Apple Silicon (`arm64`) support.
- The app starts and stops its own local backend automatically.
- Launcher A always uses the normal ChatGPT launch behavior.
- Additional launchers can use isolated `CODEX_HOME` and Desktop `user-data-dir` values.
- Multiple launchers can point to the same local workspaces.
- Local account aliases and membership labels.
- Up to 20 account mnemonics; add controls disable clearly at the limit.
- Weekly quota tracking and reset scheduling.
- 5-hour reset countdown and custom reset-time correction.
- Reset-card tracking and global reset actions.
- Read-only Workspace inspection.
- User-level Codex Skill inspection and safe copying between profiles.
- Light and dark modes.
- English and Simplified Chinese.
- First-launch Welcome panel with privacy and usage explanations.
- Custom Codex Switcher macOS app icon.
- Labs: safely reset Codex Desktop UI settings per launcher with automatic config backup and one-click restore.
- Animated current / suggested / preview launcher deck for smoother profile handoffs.
- Snap points on weekly quota sliders.
- Persistent **Next Codex Hand Off** scratchpad for carrying context between accounts.
- Editable 5-hour reset time directly from the current launcher panel.

## How it works

Codex Switcher separates **launch profiles** from **account labels**.

A launcher controls how ChatGPT / Codex Desktop starts:

- **Launcher A** uses the normal system/default ChatGPT launch.
- **Launchers B–F** can use isolated `CODEX_HOME` and Desktop `user-data-dir` locations.

Account aliases are local labels only. They are not verified OpenAI identities, so you can manually change which account label is associated with a launcher if you sign into a different account inside that profile.

## Installation

### GitHub Release

Download:

```text
Codex-Switcher-v0.21.2-macOS-arm64.zip
```

Then:

1. Extract the ZIP.
2. Move `Codex Switcher.app` into `/Applications`.
3. Open the app.

The Release build is self-contained. End users do **not** need Python, Xcode, Homebrew, or the source repository.

### Build from source

On an Apple Silicon Mac:

```bash
./scripts/build-release.sh
```

The build script:

- prefers `/Applications/Xcode-beta.app`, then stable Xcode;
- compiles the native AppKit/WKWebView shell for `arm64`;
- bundles the Python backend with PyInstaller;
- embeds all static web resources inside `Codex Switcher.app`;
- generates and embeds the macOS app icon;
- applies an ad-hoc signature;
- verifies the native shell and bundled backend are arm64;
- creates the GitHub Release asset under `release/`;
- keeps the PyInstaller build environment in a stable user Cache location, so renaming or moving the source checkout does not invalidate an old project-local virtualenv.

Output:

```text
release/Codex-Switcher-v0.21.2-macOS-arm64.zip
```

### Local development install

```bash
./scripts/install-app.sh
```

Installed app:

```text
~/Applications/Codex Switcher.app
```

Development mode:

```bash
./scripts/run.sh
```

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

The application database stores local launcher configuration, account aliases, quota notes, reset schedules, history, appearance, language, and related local state.

## Migration from older releases

If the current database does not exist, Codex Switcher can migrate data from the previous application location:

```text
~/Library/Application Support/com.ping.codex-account-switch-launcher/
```

Older project-local data can also be migrated from:

```text
data/launcher.sqlite3
```

Migration is copy-only. The previous database is left intact.

## First launch

On first launch, Codex Switcher displays a Welcome panel explaining:

- what launchers A/B/C represent;
- that account aliases are local labels rather than verified OpenAI identities;
- which quota and reset information is tracked locally;
- that passwords and authentication tokens are not read.

The Welcome panel is shown only once by default. You can reopen it at any time using the `?` button beside the app title.

## Local service port

Default port:

```text
17831
```

The port can be changed in Settings to a value from `1024` to `65535`.

Restart Codex Switcher after changing the port.

## Workspaces

`View Workspaces` is read-only.

It reads the selected launcher's `.codex-global-state.json` and displays entries from `local-projects`, including:

- project name;
- primary root directory;
- additional root directories.

Codex workspace state files are not modified.

## Skills

`View Skills` inspects user-level Skills under:

```text
$CODEX_HOME/skills
```

Only directories containing `SKILL.md` are shown. `.system` Skills are excluded.

`Copy Missing Skills`:

- copies only missing user Skill directories;
- copies the whole Skill folder, including scripts, references, and assets;
- never overwrites an existing same-name Skill;
- never copies authentication, workspace, thread, or account state.

## Privacy

Codex Switcher is designed around local-only state management.

It does **not** read your ChatGPT password or authentication tokens.

Do not commit files such as:

```text
auth.json
cookies
tokens
local databases
logs containing private information
```

The repository `.gitignore` excludes runtime databases, logs, Python caches, virtual environments, build artifacts, Release ZIPs, local environment files, and IDE-specific files.

## Uninstall

```bash
./scripts/uninstall-app.sh
```

This removes the app only.

User data is intentionally preserved under:

```text
~/Library/Application Support/com.nigolarer.codex-switcher/
```

## macOS Gatekeeper

The current public build is ad-hoc signed rather than Developer ID signed and notarized.

On first launch, macOS may require:

1. Right-click `Codex Switcher.app`.
2. Choose **Open**.
3. Confirm the launch.

A future Developer ID signed and notarized build can remove this extra step.

## Current release

Current public release:

```text
v0.21.2
```

Release asset:

```text
Codex-Switcher-v0.21.2-macOS-arm64.zip
```

### v0.21.2 stale backend fix

The native app now verifies both the backend version and the static UI before reusing an existing local service. If an older Codex Switcher backend is still listening after the source folder was renamed or moved, the app safely replaces that stale backend instead of attaching to it and showing a 404 page. Release builds also validate that `runtime/static/index.html` is present.
