#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="0.22.5"
PRODUCT="Codex Switcher"
APP_NAME="$PRODUCT.app"
BUILD_ROOT="$ROOT/build/release"
APP_DIR="$BUILD_ROOT/$APP_NAME"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
RUNTIME="$RESOURCES/runtime"
DIST_DIR="$ROOT/dist"
RELEASE_DIR="$ROOT/release"
ZIP_NAME="Codex-Switcher-v${VERSION}-macOS-arm64.zip"

ICON_SOURCE="$ROOT/assets/AppIcon.png"
ICONSET_DIR="$BUILD_ROOT/AppIcon.iconset"
ICON_FILE="$RESOURCES/AppIcon.icns"


generate_app_icon() {
  if [[ ! -f "$ICON_SOURCE" ]]; then
    echo "App icon source is missing: $ICON_SOURCE"
    exit 1
  fi
  if [[ ! -x /usr/bin/sips || ! -x /usr/bin/iconutil ]]; then
    echo "sips/iconutil are required to build the macOS app icon."
    exit 1
  fi

  rm -rf "$ICONSET_DIR"
  mkdir -p "$ICONSET_DIR"
  /usr/bin/sips -z 16 16 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
  /usr/bin/sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
  /usr/bin/sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
  /usr/bin/sips -z 64 64 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
  /usr/bin/sips -z 128 128 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
  /usr/bin/sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
  /usr/bin/sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
  /usr/bin/sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
  /usr/bin/sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
  /usr/bin/sips -z 1024 1024 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null
  /usr/bin/iconutil -c icns "$ICONSET_DIR" -o "$ICON_FILE"
  rm -rf "$ICONSET_DIR"
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Release builds must run on macOS."
  exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This release target is Apple Silicon only (arm64)."
  exit 1
fi

# Prefer Xcode Beta on newer macOS betas, then stable Xcode.
if [[ -d "/Applications/Xcode-beta.app/Contents/Developer" ]]; then
  DEVELOPER_DIR_PATH="/Applications/Xcode-beta.app/Contents/Developer"
elif [[ -d "/Applications/Xcode.app/Contents/Developer" ]]; then
  DEVELOPER_DIR_PATH="/Applications/Xcode.app/Contents/Developer"
else
  DEVELOPER_DIR_PATH="$(xcode-select -p 2>/dev/null || true)"
fi
if [[ -z "$DEVELOPER_DIR_PATH" || ! -d "$DEVELOPER_DIR_PATH" ]]; then
  echo "No usable Xcode developer directory found."
  exit 1
fi

SDK_PATH="$(DEVELOPER_DIR="$DEVELOPER_DIR_PATH" xcrun --sdk macosx --show-sdk-path 2>/dev/null || true)"
SWIFTC="$(DEVELOPER_DIR="$DEVELOPER_DIR_PATH" xcrun --find swiftc 2>/dev/null || true)"
if [[ -z "$SDK_PATH" || ! -d "$SDK_PATH" || -z "$SWIFTC" || ! -x "$SWIFTC" ]]; then
  echo "Unable to locate a usable macOS SDK / Swift compiler in $DEVELOPER_DIR_PATH"
  exit 1
fi

# Select an arm64 Python only on the BUILD machine. It will be bundled into the release.
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "Python 3 is required only to build the release."
  exit 1
fi
PY_ARCH="$($PYTHON_BIN -c 'import platform; print(platform.machine())')"
if [[ "$PY_ARCH" != "arm64" ]]; then
  echo "Release Python must be arm64, got: $PY_ARCH ($PYTHON_BIN)"
  exit 1
fi

# Keep the release build environment outside the source checkout. Python console
# scripts inside a venv embed their venv path in the shebang, so a project-local
# venv can break when the repository folder is renamed or moved.
BUILD_CACHE_ROOT="${CODEX_SWITCHER_BUILD_CACHE:-$HOME/Library/Caches/com.nigolarer.codex-switcher/build}"
VENV="$BUILD_CACHE_ROOT/release-venv"
mkdir -p "$BUILD_CACHE_ROOT"

if [[ ! -x "$VENV/bin/python" ]] \
  || ! "$VENV/bin/python" -c 'import sys; print(sys.prefix)' >/dev/null 2>&1 \
  || [[ "$("$VENV/bin/python" -c 'import platform; print(platform.machine())' 2>/dev/null || true)" != "arm64" ]]; then
  echo "Creating release build environment..."
  rm -rf "$VENV"
  "$PYTHON_BIN" -m venv "$VENV"
fi

if ! "$VENV/bin/python" -c 'import PyInstaller' >/dev/null 2>&1; then
  echo "Installing PyInstaller into the release build environment..."
  "$VENV/bin/python" -m pip install --upgrade pip pyinstaller
fi

echo "Build developer dir: $DEVELOPER_DIR_PATH"
echo "Build SDK: $SDK_PATH"
echo "Build Python: $PYTHON_BIN"
echo "Target: Apple Silicon (arm64)"

echo "Cleaning previous release output..."
rm -rf "$BUILD_ROOT" "$DIST_DIR/CodexSwitcherServer" "$ROOT/build/CodexSwitcherServer" "$RELEASE_DIR/$ZIP_NAME"
mkdir -p "$MACOS" "$RESOURCES" "$RUNTIME/static" "$RELEASE_DIR"

# Bundle the backend as a self-contained arm64 executable directory.
echo "Bundling local backend runtime..."
MACOSX_DEPLOYMENT_TARGET=13.0 "$VENV/bin/python" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name CodexSwitcherServer \
  --target-architecture arm64 \
  --distpath "$DIST_DIR" \
  --workpath "$ROOT/build/CodexSwitcherServer" \
  --specpath "$ROOT/build" \
  "$ROOT/app/server.py"

cp -R "$DIST_DIR/CodexSwitcherServer" "$RUNTIME/server"
cp -R "$ROOT/static/." "$RUNTIME/static/"
generate_app_icon

cat > "$CONTENTS/Info.plist" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Codex Switcher</string>
  <key>CFBundleDisplayName</key><string>Codex Switcher</string>
  <key>CFBundleIdentifier</key><string>com.nigolarer.codex-switcher</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>CodexSwitcher</string>
  <key>CFBundleIconFile</key><string>AppIcon.icns</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST_EOF

echo "Building native macOS shell..."
DEVELOPER_DIR="$DEVELOPER_DIR_PATH" "$SWIFTC" \
  "$ROOT/macos/App.swift" \
  -sdk "$SDK_PATH" \
  -target arm64-apple-macos13.0 \
  -framework Cocoa \
  -framework WebKit \
  -o "$MACOS/CodexSwitcher"

# Ad-hoc sign the complete bundle. A future Developer ID/notarized build can replace this step.
echo "Applying ad-hoc signature..."
/usr/bin/codesign --force --deep --sign - "$APP_DIR"

# Sanity checks: release App must not depend on project Python or source server.py.
if [[ -e "$RESOURCES/python-path.txt" || -e "$RUNTIME/app/server.py" ]]; then
  echo "Release validation failed: development Python/source artifacts are present."
  exit 1
fi
if [[ ! -f "$ICON_FILE" ]]; then
  echo "Release validation failed: AppIcon.icns is missing."
  exit 1
fi
if [[ ! -x "$RUNTIME/server/CodexSwitcherServer" ]]; then
  echo "Release validation failed: bundled backend executable is missing."
  exit 1
fi
if [[ ! -f "$RUNTIME/static/index.html" ]]; then
  echo "Release validation failed: runtime/static/index.html is missing."
  exit 1
fi

MAIN_ARCH="$(/usr/bin/file "$MACOS/CodexSwitcher")"
SERVER_ARCH="$(/usr/bin/file "$RUNTIME/server/CodexSwitcherServer")"
echo "$MAIN_ARCH"
echo "$SERVER_ARCH"
if [[ "$MAIN_ARCH" != *"arm64"* || "$SERVER_ARCH" != *"arm64"* ]]; then
  echo "Release validation failed: a binary is not arm64."
  exit 1
fi

# Preserve the .app structure/resource forks using ditto.
echo "Creating GitHub Release asset..."
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP_DIR" "$RELEASE_DIR/$ZIP_NAME"

SHA256="$(/usr/bin/shasum -a 256 "$RELEASE_DIR/$ZIP_NAME" | awk '{print $1}')"
echo
echo "Release ready:"
echo "  $RELEASE_DIR/$ZIP_NAME"
echo "SHA-256: $SHA256"
echo
echo "End users only need to unzip and move Codex Switcher.app to /Applications."
echo "No Python, Xcode, Homebrew, or source checkout is required on the target Mac."
echo "This build is ad-hoc signed, not Apple-notarized. Gatekeeper may require right-click > Open on first launch."
