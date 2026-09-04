#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$HOME/Applications/Codex Switcher.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
RUNTIME="$RESOURCES/runtime"
APP_SUPPORT="$HOME/Library/Application Support/com.nigolarer.codex-switcher"
OLD_APP_SUPPORT="$HOME/Library/Application Support/com.ping.codex-account-switch-launcher"
OLD_PROJECT_DATA="$ROOT/data"
OLD_APP_DIR="$HOME/Applications/Codex账号切换启动器.app"
LABEL="local.codex-profile-launcher"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

# Gracefully quit a previously installed native App before replacing its bundle.
/usr/bin/osascript -e 'tell application "Codex Switcher" to quit' >/dev/null 2>&1 || true
/usr/bin/osascript -e 'tell application "Codex账号切换启动器" to quit' >/dev/null 2>&1 || true
/bin/sleep 0.5

# v0.16+ owns the service lifecycle inside the native App. Remove the old resident LaunchAgent.
/bin/launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST"

# Stop old project-based server processes before replacing the App.
PIDS="$(pgrep -f "$ROOT/app/server.py" 2>/dev/null || true)"
if [[ -n "$PIDS" ]]; then
  echo "$PIDS" | xargs kill >/dev/null 2>&1 || true
  /bin/sleep 0.4
fi

PYTHON_BIN="$(command -v python3 || true)"
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "python3 not found. Install Python 3 first."
  exit 1
fi

# Migrate old project-local data once, without deleting the original copy.
mkdir -p "$APP_SUPPORT"
if [[ ! -f "$APP_SUPPORT/launcher.sqlite3" && -f "$OLD_APP_SUPPORT/launcher.sqlite3" ]]; then
  echo "Migrating existing Codex Switcher data from the previous Application Support location..."
  cp -p "$OLD_APP_SUPPORT/launcher.sqlite3" "$APP_SUPPORT/launcher.sqlite3"
  if [[ -d "$OLD_APP_SUPPORT/backups" && ! -d "$APP_SUPPORT/backups" ]]; then
    cp -R "$OLD_APP_SUPPORT/backups" "$APP_SUPPORT/backups"
  fi
  echo "Previous data was preserved at: $OLD_APP_SUPPORT"
elif [[ ! -f "$APP_SUPPORT/launcher.sqlite3" && -f "$OLD_PROJECT_DATA/launcher.sqlite3" ]]; then
  echo "Migrating existing project-local launcher data to Codex Switcher Application Support..."
  cp -p "$OLD_PROJECT_DATA/launcher.sqlite3" "$APP_SUPPORT/launcher.sqlite3"
  if [[ -d "$OLD_PROJECT_DATA/backups" && ! -d "$APP_SUPPORT/backups" ]]; then
    cp -R "$OLD_PROJECT_DATA/backups" "$APP_SUPPORT/backups"
  fi
  echo "Old project data was preserved at: $OLD_PROJECT_DATA"
fi

# Prefer the newest Xcode Beta when available.
if [[ -d "/Applications/Xcode-beta.app/Contents/Developer" ]]; then
  DEVELOPER_DIR_PATH="/Applications/Xcode-beta.app/Contents/Developer"
elif [[ -d "/Applications/Xcode.app/Contents/Developer" ]]; then
  DEVELOPER_DIR_PATH="/Applications/Xcode.app/Contents/Developer"
else
  DEVELOPER_DIR_PATH="$(xcode-select -p 2>/dev/null || true)"
fi

if [[ -z "$DEVELOPER_DIR_PATH" || ! -d "$DEVELOPER_DIR_PATH" ]]; then
  echo "No usable Xcode developer directory was found."
  echo "Install Xcode or Xcode Beta first."
  exit 1
fi

SDK_PATH="$(DEVELOPER_DIR="$DEVELOPER_DIR_PATH" xcrun --sdk macosx --show-sdk-path 2>/dev/null || true)"
SWIFTC="$(DEVELOPER_DIR="$DEVELOPER_DIR_PATH" xcrun --find swiftc 2>/dev/null || true)"

if [[ -z "$SDK_PATH" || ! -d "$SDK_PATH" ]]; then
  echo "Unable to locate a usable macOS SDK in: $DEVELOPER_DIR_PATH"
  exit 1
fi
if [[ -z "$SWIFTC" || ! -x "$SWIFTC" ]]; then
  echo "Swift compiler not found in: $DEVELOPER_DIR_PATH"
  exit 1
fi

ARCH="$(uname -m)"
case "$ARCH" in
  arm64) TARGET_TRIPLE="arm64-apple-macos13.0" ;;
  x86_64) TARGET_TRIPLE="x86_64-apple-macos13.0" ;;
  *)
    echo "Unsupported architecture: $ARCH"
    exit 1
    ;;
esac

echo "Build developer dir: $DEVELOPER_DIR_PATH"
echo "Build SDK: $SDK_PATH"
echo "Deployment target: $TARGET_TRIPLE"

rm -rf "$APP_DIR"
mkdir -p "$MACOS" "$RESOURCES" "$RUNTIME/app" "$RUNTIME/static"

cat > "$CONTENTS/Info.plist" <<'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Codex Switcher</string>
  <key>CFBundleDisplayName</key><string>Codex Switcher</string>
  <key>CFBundleIdentifier</key><string>com.nigolarer.codex-switcher</string>
  <key>CFBundleVersion</key><string>0.18.0</string>
  <key>CFBundleShortVersionString</key><string>0.18.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>CodexAccountSwitcher</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST_EOF

# Bundle all runtime code and web assets so the installed App does not depend on the source tree.
cp -p "$ROOT/app/server.py" "$RUNTIME/app/server.py"
cp -R "$ROOT/static/." "$RUNTIME/static/"
printf '%s\n' "$PYTHON_BIN" > "$RESOURCES/python-path.txt"

DEVELOPER_DIR="$DEVELOPER_DIR_PATH" "$SWIFTC" \
  "$ROOT/macos/App.swift" \
  -sdk "$SDK_PATH" \
  -target "$TARGET_TRIPLE" \
  -framework Cocoa \
  -framework WebKit \
  -o "$MACOS/CodexAccountSwitcher"

/usr/bin/codesign --force --deep --sign - "$APP_DIR" >/dev/null 2>&1 || true
/usr/bin/touch "$APP_DIR"

if [[ -d "$OLD_APP_DIR" && "$OLD_APP_DIR" != "$APP_DIR" ]]; then
  rm -rf "$OLD_APP_DIR"
fi

echo "Installed standalone native Codex Switcher App: $APP_DIR"
echo "User data: $APP_SUPPORT"
echo "The source project can now be moved or deleted after installation."
echo "Open the App from Finder/Spotlight or drag it to the Dock."
