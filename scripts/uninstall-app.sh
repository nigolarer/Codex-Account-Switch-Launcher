#!/bin/zsh
set -euo pipefail
installed_app="/Applications/Codex Switcher.app"
personal_app="$HOME/Applications/Codex Switcher.app"
/usr/bin/osascript -e 'tell application id "com.nigolarer.codex-switcher" to quit' >/dev/null 2>&1 || true
/bin/sleep 0.5
for app_path in "$installed_app" "$personal_app"; do
  if [[ -e "$app_path" ]]; then
    location_label="system"
    [[ "$app_path" == "$personal_app" ]] && location_label="personal"
    backup_path="$HOME/.Trash/Codex Switcher uninstalled $location_label $(date +%Y%m%d-%H%M%S).app"
    /bin/mv "$app_path" "$backup_path"
    echo "Moved to Trash: $app_path"
  fi
done
