#!/bin/sh
# Build a minimal macOS .app bundle that wraps the calendar bridge so
# EventKit can prompt for permission with our usage description.
#
# Why we need this: a plain `python3 -m uvicorn ...` process has no
# Info.plist that macOS recognizes, so the EventKit permission request
# is silently denied and the process never even appears in
# System Settings → Privacy & Security → Calendars. A bundle with
# NSCalendarsFullAccessUsageDescription fixes both.
#
# Usage:
#   make calendar-bridge-app
#   open apps/macos/ReflectionsCalendarBridge.app
#
# The bundle re-execs `poetry run python -m uvicorn ...` from the
# project root that was current when this script was run.
set -eu

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
APP_DIR="${APP_DIR:-${PROJECT_ROOT}/apps/macos/ReflectionsCalendarBridge.app}"
BUNDLE_ID="${BUNDLE_ID:-com.reflections.calendar-bridge}"
APP_NAME="ReflectionsCalendarBridge"

if [ ! -f "${PROJECT_ROOT}/pyproject.toml" ]; then
  echo "ERROR: PROJECT_ROOT=${PROJECT_ROOT} does not look like the reflections root" >&2
  exit 2
fi

rm -rf "${APP_DIR}"
mkdir -p "${APP_DIR}/Contents/MacOS"

# Info.plist — the bare-minimum keys macOS needs to (a) treat this as a
# bundled app for TCC purposes and (b) show our usage description in the
# permission prompt.
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
  <string>Reflections Calendar Bridge</string>
  <key>CFBundleDisplayName</key>
  <string>Reflections Calendar Bridge</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSUIElement</key>
  <true/>
  <!-- macOS 14+ full-access (read+write). The string is shown to the
       user verbatim in the system prompt. -->
  <key>NSCalendarsFullAccessUsageDescription</key>
  <string>Reflections reads and writes your local Apple Calendar so the assistant can recall and schedule events for you. All data stays on this Mac.</string>
  <!-- Legacy key for pre-macOS 14. -->
  <key>NSCalendarsUsageDescription</key>
  <string>Reflections reads your local Apple Calendar so the assistant can recall events for you. All data stays on this Mac.</string>
</dict>
</plist>
PLIST

# Launcher — execs poetry from the project root so pyobjc + uvicorn
# resolve against the host venv we already set up.
cat > "${APP_DIR}/Contents/MacOS/${APP_NAME}" <<LAUNCH
#!/bin/sh
# Pull in user PATH (poetry, pyenv) so a double-clicked .app can find them.
[ -f "\$HOME/.zshrc" ] && . "\$HOME/.zshrc" >/dev/null 2>&1 || true
[ -f "\$HOME/.bash_profile" ] && . "\$HOME/.bash_profile" >/dev/null 2>&1 || true
export PATH="\$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:\$PATH"

cd "${PROJECT_ROOT}"
[ -f .env ] && set -a && . ./.env && set +a

LOG="${PROJECT_ROOT}/run/calendar-bridge.app.log"
mkdir -p "${PROJECT_ROOT}/run"
exec poetry run python -m uvicorn \\
  reflections.calendar_bridge.main:app \\
  --host 127.0.0.1 --port 9004 \\
  >>"\$LOG" 2>&1
LAUNCH

chmod +x "${APP_DIR}/Contents/MacOS/${APP_NAME}"

# Touch the bundle so Launch Services re-scans it; helps when rebuilding
# in-place. Harmless if it fails.
touch "${APP_DIR}" 2>/dev/null || true

echo "Built ${APP_DIR}"
echo
echo "Next:"
echo "  1. open ${APP_DIR}"
echo "  2. Grant Calendar access when prompted"
echo "     (or in System Settings → Privacy & Security → Calendars,"
echo "      look for 'Reflections Calendar Bridge')"
echo "  3. curl -s http://127.0.0.1:9004/health | jq ."
