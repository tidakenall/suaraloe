#!/usr/bin/env bash
# build_dmg.sh — Build Suaraloe into a distributable .dmg installer.
#
# Output:  dist/Suaraloe-<version>.dmg
# Requires: Python 3 (framework build), py2app (auto-installed).
# Optional: brew install create-dmg  →  prettier installer window.

set -euo pipefail

APP_NAME="Suaraloe"
APP_VERSION="1.0.0"
DMG_NAME="${APP_NAME}-${APP_VERSION}"
VOLUME_NAME="${APP_NAME}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

# ── pick a framework-linked Python (same logic as run.sh) ─────────────────────
PYTHON=""
for PY in \
    /Library/Developer/CommandLineTools/usr/bin/python3 \
    /usr/bin/python3 \
    /opt/homebrew/bin/python3; do
    if [ -x "$PY" ]; then
        PYTHON="$PY"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "✗ no python3 found — install Xcode CLT: xcode-select --install" >&2
    exit 1
fi
echo "▸ python:  $PYTHON"

# ── install build-time + runtime deps ─────────────────────────────────────────
echo "▸ installing build dependencies…"
"$PYTHON" -m pip install --quiet --upgrade pip
"$PYTHON" -m pip install --quiet py2app
"$PYTHON" -m pip install --quiet -r requirements.txt

# ── clean previous artefacts ──────────────────────────────────────────────────
echo "▸ cleaning build/ and dist/…"
rm -rf build dist

# ── build the .app bundle ─────────────────────────────────────────────────────
echo "▸ building .app bundle with py2app…"
"$PYTHON" setup.py py2app

APP_BUNDLE="dist/${APP_NAME}.app"
if [ ! -d "$APP_BUNDLE" ]; then
    echo "✗ build failed — $APP_BUNDLE not produced" >&2
    exit 1
fi

# Sanity-check the copyright actually landed in the bundle.
COPYRIGHT_IN_PLIST="$(/usr/libexec/PlistBuddy -c 'Print :NSHumanReadableCopyright' "$APP_BUNDLE/Contents/Info.plist" 2>/dev/null || echo '')"
echo "▸ copyright in bundle: $COPYRIGHT_IN_PLIST"

# ── package into a .dmg ───────────────────────────────────────────────────────
DMG_OUT="dist/${DMG_NAME}.dmg"
echo "▸ creating ${DMG_OUT}…"

if command -v create-dmg >/dev/null 2>&1; then
    create-dmg \
        --volname "$VOLUME_NAME" \
        --window-pos 200 120 \
        --window-size 640 360 \
        --icon-size 110 \
        --icon "${APP_NAME}.app" 170 180 \
        --hide-extension "${APP_NAME}.app" \
        --app-drop-link 470 180 \
        --no-internet-enable \
        "$DMG_OUT" \
        "$APP_BUNDLE"
else
    echo "  (create-dmg not installed — using hdiutil; \`brew install create-dmg\` for a polished installer window)"
    STAGE="dist/_dmg_staging"
    rm -rf "$STAGE"
    mkdir -p "$STAGE"
    cp -R "$APP_BUNDLE" "$STAGE/"
    ln -s /Applications "$STAGE/Applications"
    hdiutil create \
        -volname "$VOLUME_NAME" \
        -srcfolder "$STAGE" \
        -ov -format UDZO \
        "$DMG_OUT"
    rm -rf "$STAGE"
fi

echo ""
echo "✓ done — $HERE/$DMG_OUT"
echo ""
echo "  Distribution notes:"
echo "  • The bundle is NOT code-signed or notarized. macOS Gatekeeper will warn"
echo "    on first launch; users right-click → Open to bypass."
echo "  • For App Store / public distribution, sign with a Developer ID:"
echo "      codesign --deep --force --options runtime \\"
echo "        --sign \"Developer ID Application: satusembilan (TEAMID)\" \\"
echo "        \"$APP_BUNDLE\""
echo "    then notarize with \`xcrun notarytool submit\`."
