#!/bin/zsh
set -e
APP_DIR="$HOME/Applications/Codex账号切换启动器.app"
/usr/bin/osascript -e 'tell application "Codex账号切换启动器" to quit' >/dev/null 2>&1 || true
rm -rf "$APP_DIR"
echo "Removed: $APP_DIR"
