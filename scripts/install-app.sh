#!/bin/zsh
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
product_name="Codex Switcher"
bundle_name="$product_name.app"
built_app="$repo_root/build/release/$bundle_name"
installed_app="/Applications/$bundle_name"
personal_app="$HOME/Applications/$bundle_name"
legacy_app="$HOME/Applications/Codex账号切换启动器.app"
app_support="$HOME/Library/Application Support/com.nigolarer.codex-switcher"
old_app_support="$HOME/Library/Application Support/com.ping.codex-account-switch-launcher"
old_project_data="$repo_root/data"
legacy_agent_label="local.codex-profile-launcher"
legacy_agent_plist="$HOME/Library/LaunchAgents/$legacy_agent_label.plist"
app_process_pattern='/Codex Switcher\.app/Contents/(MacOS/(CodexSwitcher|CodexAccountSwitcher)|Resources/runtime/server/CodexSwitcherServer)'

wait_for_app_exit() {
  local attempt
  for attempt in {1..10}; do
    if ! /usr/bin/pgrep -f "$app_process_pattern" >/dev/null 2>&1; then
      return 0
    fi
    /bin/sleep 0.5
  done
  return 1
}

close_running_app() {
  echo "Closing running $product_name instances..."
  /usr/bin/osascript -e 'tell application id "com.nigolarer.codex-switcher" to quit' >/dev/null 2>&1 || true
  if wait_for_app_exit; then
    return
  fi

  /usr/bin/pkill -TERM -f "$app_process_pattern" >/dev/null 2>&1 || true
  if wait_for_app_exit; then
    return
  fi

  echo "A stale $product_name process did not exit; stopping that process now."
  /usr/bin/pkill -KILL -f "$app_process_pattern" >/dev/null 2>&1 || true
  wait_for_app_exit || {
    echo "Unable to stop the running $product_name process."
    exit 1
  }
}

backup_app() {
  local source_path="$1"
  local backup_label="$2"
  if [[ ! -e "$source_path" ]]; then
    return
  fi
  local backup_path="$HOME/.Trash/$backup_label $(date +%Y%m%d-%H%M%S).app"
  echo "Moving existing app to Trash: $source_path"
  /bin/mv "$source_path" "$backup_path"
}

close_running_app

# v0.16+ owns its service lifecycle. Remove the obsolete resident LaunchAgent.
/bin/launchctl bootout "gui/$(id -u)/$legacy_agent_label" >/dev/null 2>&1 || true
/bin/rm -f "$legacy_agent_plist"

# Preserve the previous data migrations from the legacy source installer.
/bin/mkdir -p "$app_support"
if [[ ! -f "$app_support/launcher.sqlite3" && -f "$old_app_support/launcher.sqlite3" ]]; then
  echo "Migrating existing data from the previous Application Support location..."
  /bin/cp -p "$old_app_support/launcher.sqlite3" "$app_support/launcher.sqlite3"
  if [[ -d "$old_app_support/backups" && ! -d "$app_support/backups" ]]; then
    /bin/cp -R "$old_app_support/backups" "$app_support/backups"
  fi
elif [[ ! -f "$app_support/launcher.sqlite3" && -f "$old_project_data/launcher.sqlite3" ]]; then
  echo "Migrating existing project-local data to Application Support..."
  /bin/cp -p "$old_project_data/launcher.sqlite3" "$app_support/launcher.sqlite3"
  if [[ -d "$old_project_data/backups" && ! -d "$app_support/backups" ]]; then
    /bin/cp -R "$old_project_data/backups" "$app_support/backups"
  fi
fi

echo "Building the release app..."
"$repo_root/scripts/build-release.sh"

if [[ ! -d "$built_app" ]]; then
  echo "Release build did not produce: $built_app"
  exit 1
fi

# Keep only one Spotlight-visible installation. Existing copies remain
# recoverable in Trash, while the new app is moved (not copied) from build.
backup_app "$installed_app" "$product_name replaced"
backup_app "$personal_app" "$product_name personal duplicate"
backup_app "$legacy_app" "Codex账号切换启动器 replaced"

echo "Moving the built app into /Applications..."
/bin/mv "$built_app" "$installed_app"

if [[ -e "$built_app" ]]; then
  echo "Installation validation failed: the app still exists under build/."
  exit 1
fi
/usr/bin/codesign --verify --deep --strict "$installed_app"
if [[ ! -x "$installed_app/Contents/MacOS/CodexSwitcher" ]]; then
  echo "Installation validation failed: native executable is missing."
  exit 1
fi
if [[ ! -f "$installed_app/Contents/Resources/runtime/static/index.html" ]]; then
  echo "Installation validation failed: bundled UI is missing."
  exit 1
fi

echo "Starting $installed_app..."
/usr/bin/open "$installed_app"

echo
echo "Installed and started: $installed_app"
echo "The release ZIP remains under release/ for distribution only."
echo "No app bundle remains under build/release/."
