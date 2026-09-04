#!/bin/zsh
set -e
APP_DIR="$HOME/Applications/Codex Switcher.app"
/usr/bin/osascript -e 'tell application "Codex Switcher" to quit' >/dev/null 2>&1 || true
rm -rf "$APP_DIR"
echo "Removed: $APP_DIR"
