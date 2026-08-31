#!/usr/bin/env bash
# build.sh — produces "Datasphere Cleanup.app" in dist/
#
# Usage:
#   chmod +x build.sh   (first time only)
#   ./build.sh
#
# Output: dist/Datasphere Cleanup.app
# Share the .app by zipping: zip -r "Datasphere Cleanup.zip" "dist/Datasphere Cleanup.app"

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

echo ""
echo "Done. App is at: dist/Datasphere Cleanup.app"
echo "To distribute: zip -r \"Datasphere Cleanup.zip\" \"dist/Datasphere Cleanup.app\""
