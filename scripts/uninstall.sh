#!/bin/zsh
set -e
LABEL="local.codex-profile-launcher"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout gui/$(id -u) "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "LaunchAgent removed. Project data remains in the launcher project data/ directory."
