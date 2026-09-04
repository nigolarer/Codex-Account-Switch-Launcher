#!/bin/zsh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export CODEX_LAUNCHER_LEGACY_PROJECT_DB="$ROOT/data/launcher.sqlite3"
LABEL="local.codex-profile-launcher"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NOW="$(id -u)"
PYTHON_BIN="$(command -v python3)"
PORT="$($PYTHON_BIN "$ROOT/app/server.py" --print-port)"

if [[ -f "$PLIST" ]]; then
  launchctl bootout "gui/$UID_NOW" "$PLIST" 2>/dev/null || true
  sleep 0.5
  launchctl bootstrap "gui/$UID_NOW" "$PLIST"
  launchctl enable "gui/$UID_NOW/$LABEL" 2>/dev/null || true
  sleep 0.5
  open "http://127.0.0.1:$PORT/?v=$(date +%s)"
  echo "Restarted installed Codex Account Switch Launcher on port $PORT."
  exit 0
fi

PIDS=$(pgrep -f "$ROOT/app/server.py" 2>/dev/null || true)
if [[ -n "$PIDS" ]]; then
  echo "$PIDS" | xargs kill 2>/dev/null || true
  sleep 0.8
fi
exec python3 "$ROOT/app/server.py" --open
