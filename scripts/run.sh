#!/bin/zsh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export CODEX_LAUNCHER_LEGACY_PROJECT_DB="$ROOT/data/launcher.sqlite3"
exec python3 "$ROOT/app/server.py" --open
