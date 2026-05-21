#!/bin/sh
# Build a minimal macOS .app bundle that wraps the catalog bridge.
#
# Why: the bridge needs to walk paths that may be outside the user's home
# tree (external drives mounted at /Volumes/X, archives at /usr/local/...,
# etc.). On macOS that requires Full Disk Access, which TCC only offers
# to *bundled* apps with a recognized identifier. A plain
# `python -m uvicorn ...` process can't even appear in System Settings →
# Privacy & Security → Full Disk Access.
#
# Usage:
#   make catalog-bridge-app
#   open apps/macos/ReflectionsCatalogBridge.app
#
# Then in System Settings → Privacy & Security → Full Disk Access,
# toggle on "Reflections Catalog Bridge" and re-open the bundle.

set -eu

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
APP_DIR="${APP_DIR:-${PROJECT_ROOT}/apps/macos/ReflectionsCatalogBridge.app}"
BUNDLE_ID="${BUNDLE_ID:-com.reflections.catalog-bridge}"
APP_NAME="ReflectionsCatalogBridge"

if [ ! -f "${PROJECT_ROOT}/pyproject.toml" ]; then
  echo "ERROR: PROJECT_ROOT=${PROJECT_ROOT} does not look like the reflections root" >&2
  exit 2
fi

rm -rf "${APP_DIR}"
mkdir -p "${APP_DIR}/Contents/MacOS"

cat > "${APP_DIR}/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key>
  <string>${BUNDLE_ID}</string>
  <key>CFBundleName</key>
  <string>Reflections Catalog Bridge</string>
  <key>CFBundleDisplayName</key>
  <string>Reflections Catalog Bridge</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSUIElement</key>
  <true/>
  <key>NSDesktopFolderUsageDescription</key>
  <string>Reflections catalogs files in your Desktop folder when you point it there. All data stays on this Mac.</string>
  <key>NSDocumentsFolderUsageDescription</key>
  <string>Reflections catalogs files in your Documents folder when you point it there. All data stays on this Mac.</string>
  <key>NSDownloadsFolderUsageDescription</key>
  <string>Reflections catalogs files in your Downloads folder when you point it there. All data stays on this Mac.</string>
  <key>NSRemovableVolumesUsageDescription</key>
  <string>Reflections catalogs files on connected drives so the assistant can recall them. Bytes never leave this Mac.</string>
  <key>NSNetworkVolumesUsageDescription</key>
  <string>Reflections catalogs files on network volumes so the assistant can recall them. Bytes never leave this Mac.</string>
</dict>
</plist>
PLIST

cat > "${APP_DIR}/Contents/MacOS/${APP_NAME}" <<LAUNCH
#!/bin/sh
[ -f "\$HOME/.zshrc" ] && . "\$HOME/.zshrc" >/dev/null 2>&1 || true
[ -f "\$HOME/.bash_profile" ] && . "\$HOME/.bash_profile" >/dev/null 2>&1 || true
export PATH="\$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:\$PATH"

cd "${PROJECT_ROOT}"
[ -f .env ] && set -a && . ./.env && set +a

LOG="${PROJECT_ROOT}/run/catalog-bridge.app.log"
mkdir -p "${PROJECT_ROOT}/run"
exec poetry run python -m uvicorn \\
  reflections.catalog_bridge.main:app \\
  --host 127.0.0.1 --port 9005 \\
  >>"\$LOG" 2>&1
LAUNCH

chmod +x "${APP_DIR}/Contents/MacOS/${APP_NAME}"
touch "${APP_DIR}" 2>/dev/null || true

echo "Built ${APP_DIR}"
echo
echo "Next:"
echo "  1. open ${APP_DIR}"
echo "  2. In System Settings → Privacy & Security → Full Disk Access,"
echo "     toggle on 'Reflections Catalog Bridge'. Then reopen the bundle."
echo "  3. curl -s http://127.0.0.1:9005/health | jq ."
