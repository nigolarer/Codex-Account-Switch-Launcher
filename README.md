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
- Automatically primes bound accounts' 5-hour windows without switching or interrupting the foreground ChatGPT app.

## Inspection mode

Enable **Inspection mode** in Settings; the preference saves automatically. The current launcher stays on the left, while compact rows on the right show the other launchers, suggested first. Each row retains its launcher color, account name, weekly remaining quota, weekly reset time, 5-hour remaining quota, 5-hour reset time, reset count, and a Launch button.

Wide windows fit up to five rows beside the current card, moving overflow into the Launchers section below. That section hides when empty. Narrow windows stack the panels and wrap metrics. Sync all can refresh bound accounts even when some accounts are still unbound.

For daily use, switch account logins inside A. A row's Launch button opens the corresponding launcher for binding or maintenance; inspection mode does not transfer login credentials into A. Turn the mode off to restore full cards and recent switch history.

## How it works

Codex Switcher separates **launch profiles** from **account labels**.

A launcher controls how ChatGPT / Codex Desktop starts:

- **Launcher A** uses the normal system/default ChatGPT launch.
- **Launchers B–F** can use isolated `CODEX_HOME` and Desktop `user-data-dir` locations.

Account aliases are local labels only. They are not verified OpenAI identities, so you can manually change which account label is associated with a launcher if you sign into a different account inside that profile.

## Automatic 5-Hour Window Priming

Auto-prime is enabled by default for bound accounts. Codex Switcher performs one unified full sync of all bound accounts every hour, and a verified `prime_next_at` also serves as the durable next 5H reset job. One background loop runs every five minutes and batches every due reset, delayed verification, and verification retry. When a new window is needed and the account is inside its configured active hours, it runs a temporary read-only Codex CLI session with that launcher's `CODEX_HOME` and sends a random two-digit addition problem whose operands and result are at most 100 using the low-usage model. The first reset timestamp is only a candidate: quota is synced again after at least five minutes, and success requires the absolute timestamp to drift by no more than five seconds while its remaining countdown has fallen below 4 hours 59 minutes. Network or validation failures retry only the quota read in a later five-minute task, never the prompt.

- Active hours default to 24 hours and can be configured per account, including overnight ranges.
- Auto-prime can be disabled independently for each account.
- Priming pauses when weekly remaining usage is below 5%.
- macOS sleep naturally pauses checks; a wake notification triggers an immediate catch-up check.
- Codex runs with `--ephemeral`, so no Session is persisted or shown in normal task history and no archive step is needed. It does not quit, switch, or focus ChatGPT Desktop.
- Codex Switcher must remain running; fully quitting the app also stops background checks.

## Installation

### GitHub Release

Download:

```text
Codex-Switcher-v1.1.0-macOS-arm64.zip
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
release/Codex-Switcher-v1.1.0-macOS-arm64.zip
```

### Local development install

```bash
./scripts/install-app.sh
```

Installed app:

```text
/Applications/Codex Switcher.app
```

The installer closes running Codex Switcher instances before building, creates
the release ZIP for distribution, moves the freshly built app directly from
`build/release/` into `/Applications`, removes duplicate personal-Applications
copies, and starts the installed app. It never extracts the ZIP for local use,
and no app bundle remains under `build/` after a successful installation.

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
- that passwords are never read; OAuth tokens are only read locally during an explicit Bind/Sync action and are never stored or displayed by Codex Switcher.

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

It does **not** read your ChatGPT password. For the optional real-account **Bind / Sync now** feature, it reads the active launcher’s local `auth.json` OAuth token only long enough to query live Codex quota data; the token is never stored or displayed by Codex Switcher.

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
v1.1.0
```

Release asset:

```text
Codex-Switcher-v1.1.0-macOS-arm64.zip
```

### v0.21.2 stale backend fix

The native app now verifies both the backend version and the static UI before reusing an existing local service. If an older Codex Switcher backend is still listening after the source folder was renamed or moved, the app safely replaces that stale backend instead of attaching to it and showing a 404 page. Release builds also validate that `runtime/static/index.html` is present.

## Release notes

### v1.0.3 Bound quota read-only polish

- Bound accounts now treat reset-count data as read-only: the edit pencil and **Increase reset count** action are hidden, account settings disable the field, and backend endpoints reject manual changes. Global reset-card actions skip bound accounts.
- When a bound account has 100% remaining in the 5-hour window, the countdown is always `—` and the UI explicitly shows **Next reset: Not started** in Current, Suggested next, and launcher cards.
- Unified the spacing between **Bound** and the membership badge across the top summary cards and lower launcher cards.

### v0.22.4 official sync age + bound-account interaction polish

- Bound accounts now show relative official-sync age: “Just synced” for the first 5 minutes, then 5/30 minutes ago, N hours ago, or N days ago.
- The same line now shows the next scheduled official sync as HH:MM only.
- Bound accounts are automatically refreshed from the official quota endpoint every 30 minutes; failed background syncs retry after 5 minutes.
- For a bound account in Current launcher, the manual Start / Restart 5H countdown button is hidden and only **Sync now** remains, avoiding conflicting local/manual timing with official quota data.

### v0.22.1 binding persistence + attention-state UI

- Renames quota **Danger** badges to the softer **Attention** label and places each label directly beside the metric that triggered it (weekly and/or 5-hour remaining).
- Restores **Bind account** on the actual active launcher in both the Current launcher summary and the launcher list.
- Persists real-account binding metadata in the stable SQLite database under Application Support so rebuilding/upgrading the app no longer drops the binding. Raw OAuth tokens are never persisted.
- After binding, a compact **Bound** badge appears immediately before the membership badge in Current, Suggested next, and launcher cards. Hover the badge to see the saved account ID, detected plan, source CODEX_HOME, and last sync time.
- Renames the current-launcher live quota action to **Sync now**. It reads the launcher’s local Codex OAuth credential on demand and updates 5-hour/weekly remaining plus reset timestamps from the live Codex usage endpoint.
- Keeps the quota-aware recommendation rules from v0.22.0: configurable 15% 5-hour and 10% Plus weekly attention thresholds.


### v1.0.3 Bound-account reset controls

- Bound accounts can no longer edit weekly reset timestamps, restart the local 5-hour countdown, or set a custom 5-hour reset time.
- Bound launcher cards show **Sync now** instead of local reset controls, keeping official quota/reset data authoritative.
- Added backend guards so bound reset timestamps cannot be modified by bypassing the UI.

### v1.0.0 UI polish and Hand Off presets

- Added a localized **Preset info** action to Next Codex Hand Off. The Chinese and English interfaces insert different fixed continuation instructions, and existing text is protected by a replace confirmation.
- Promoted the project version to **1.0.0** across the backend, release build, app bundle metadata, and documentation.
- Matched the **Sync now** button height to **Switch & Launch** while keeping each button width content-driven.


### v1.0.7 Sync cadence settings restored

- Restores a dedicated **Sync settings** section in Settings.
- Active-launcher official quota sync cadence can be set to **5 minutes / 30 minutes / 1 hour / 3 hours** (default: 30 minutes).
- Restores the separate **Global sync** cycle. It refreshes all distinct bound accounts and defaults to **6 hours**. Its interval is independently configurable from 1 to 168 hours.
- The “Next sync” time under a bound account now follows the earlier of its active-launcher sync and the next global sync.
- Both sync settings are persisted in the existing SQLite state and survive app upgrades.


### v1.0.7 Inline sync feedback

- **Sync now** no longer opens a confirmation/success dialog.
- While a manual sync is running, the button becomes **Syncing** with an inline CSS loading spinner.
- Manual sync is guarded against repeated clicks for 5 seconds.
- After success, the relative **Just synced** text briefly rises in and turns green, then settles back to the normal secondary color.
- The same behavior is used by Sync now controls in both the current launcher and lower launcher cards.


### v1.0.7 Bound-account global sync mode

- When every local account mnemonic is bound to an official account, the top-level **Global quota reset** and **Global reset card** actions are hidden.
- They are replaced by **Sync all now**, which manually triggers the same all-bound-account synchronization used by the configured global sync cycle (6 hours by default).
- Manual global sync uses inline loading feedback, prevents repeated clicks for at least 5 seconds, updates the global-sync timestamp, and refreshes all successfully synchronized account cards.
- If any local account is unbound again, the two local reset actions return automatically and the global sync button is hidden.


### v1.0.7 Quota warning emphasis

- Weekly and 5-hour remaining labels now turn into a soft red at the same threshold that shows the Attention badge.
- The red emphasis gradually strengthens as remaining quota approaches 0%.
- Below 5%, the Attention badge changes to **Low quota**.


### v1.0.8 Automatic bound-account remapping on sync

- If **Sync now** discovers that a launcher is currently signed in to a different real Codex account than the mnemonic assigned in Codex Switcher, it now looks for that real account among existing local bound accounts.
- When a matching bound account is found, the launcher is automatically reassigned to that account mnemonic and synchronization continues normally without showing an account-mismatch error.
- The mismatch error is shown only when the signed-in real account has no matching bound account in the local database.
- This is especially useful after signing out and signing in to another account directly inside Codex without first updating the launcher mapping in Codex Switcher.


### v1.1.0 Quota warning and sync UI refinements

- Quota labels stay in their normal text color; only the Attention badge changes from muted yellow to orange-red as quota falls, then becomes the softer Low quota badge below 5%.
- Removed the duplicate Sync now action from launcher tool groups; bound launchers keep the Sync now control in the 5-hour section.
- Next official sync is now shown as a relative countdown using 1-minute granularity under 5 minutes and 5-minute granularity afterwards.
