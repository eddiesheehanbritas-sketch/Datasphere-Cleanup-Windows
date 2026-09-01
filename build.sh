#!/usr/bin/env bash
# build.sh — produces "Datasphere Cleanup.app" and a compressed .dmg in dist/
#
# Usage:
#   chmod +x build.sh   (first time only)
#   ./build.sh
#
# Output:
#   dist/Datasphere Cleanup.app   — the app bundle
#   dist/Datasphere Cleanup.dmg   — compressed disk image to distribute to the team

set -euo pipefail

cd "$(dirname "$0")"

echo "Activating venv..."
source .venv/bin/activate

echo "Cleaning previous build..."
rm -rf build/Datasphere\ Cleanup dist/Datasphere\ Cleanup* dist/Datasphere\ Cleanup.app

echo "Building .app..."
pyinstaller datasphere-cleanup.spec

# Chromium cannot go through PyInstaller's binary processing (it re-signs
# the browser binaries and breaks them). Copy it in as-is after the build.
CHROMIUM_SRC="$HOME/Library/Caches/ms-playwright/chromium-1223"
CHROMIUM_DST="dist/Datasphere Cleanup.app/Contents/Frameworks/ms-playwright/chromium-1223"
echo "Copying Chromium into .app..."
mkdir -p "$CHROMIUM_DST"
cp -R "$CHROMIUM_SRC/" "$CHROMIUM_DST/"

# Ad-hoc sign the whole bundle (including the Chromium we just copied in) so it is
# internally consistent. We have no Apple Developer cert, so "-" is an ad-hoc
# signature — this does NOT get past Gatekeeper on its own, but it turns the fatal
# "app is damaged, move to Trash" error into the ordinary "unidentified developer"
# prompt that a user clears once with right-click -> Open. --deep signs the nested
# Chromium binaries; --force replaces any stale signatures left by the copy.
echo "Ad-hoc signing the bundle..."
codesign --force --deep --sign - "dist/Datasphere Cleanup.app"

# Package into a compressed disk image (UDZO = zlib-compressed).
# This preserves the bundle exactly (permissions, symlinks, signing) while
# compressing far better than zip, since hdiutil compresses the whole filesystem.
echo "Building compressed .dmg..."
rm -f "dist/Datasphere Cleanup.dmg"
hdiutil create \
    -volname "Datasphere Cleanup" \
    -srcfolder "dist/Datasphere Cleanup.app" \
    -ov -format UDZO -imagekey zlib-level=9 \
    "dist/Datasphere Cleanup.dmg"

echo ""
echo "Done."
echo "  App: dist/Datasphere Cleanup.app"
echo "  Distribute: dist/Datasphere Cleanup.dmg"
