# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Datasphere Cleanup
# Produces: "Datasphere Cleanup.app" (macOS, arm64)
#
# Build with:
#   source .venv/bin/activate
#   pyinstaller datasphere-cleanup.spec
#
# The resulting .app is in dist/Datasphere Cleanup.app
# Chromium and the Playwright driver are bundled inside — no internet required.

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
VENV_SITE = ROOT / ".venv" / "lib" / "python3.9" / "site-packages"
PLAYWRIGHT_DRIVER = VENV_SITE / "playwright" / "driver"
CHROMIUM_DIR = Path.home() / "Library" / "Caches" / "ms-playwright" / "chromium-1223"

# ── Sanity checks ────────────────────────────────────────────────────────────
if not PLAYWRIGHT_DRIVER.exists():
    raise FileNotFoundError(f"Playwright driver not found: {PLAYWRIGHT_DRIVER}")
if not CHROMIUM_DIR.exists():
    raise FileNotFoundError(
        f"Chromium not found: {CHROMIUM_DIR}\n"
        f"Run: source .venv/bin/activate && playwright install chromium"
    )

# ── Data files bundled into the .app ─────────────────────────────────────────
# Format: (source_path, dest_folder_inside_bundle)
datas = [
    # App config
    (str(ROOT / "config" / "settings.yaml"), "config"),
    (str(ROOT / "config" / "allowlist.txt"), "config"),
    # SAP 72 fonts
    (str(ROOT / "assets" / "fonts"), "assets/fonts"),
    # SAP Datasphere theme QSS (icons are compiled into src/resources_rc.py)
    (str(ROOT / "theme" / "datasphere_theme.qss"), "theme"),
    # Playwright driver (node binary + cli.js package)
    (str(PLAYWRIGHT_DRIVER), "playwright/driver"),
    # NOTE: Chromium is NOT listed here — PyInstaller would try to re-sign its
    # binaries and break it. It is copied in as-is by build.sh after the build.
]

# ── Hidden imports ────────────────────────────────────────────────────────────
# Playwright and PyQt5 use dynamic imports that PyInstaller can't auto-detect.
hidden_imports = [
    # Playwright async internals
    "playwright",
    "playwright.async_api",
    "playwright._impl._api_types",
    "playwright._impl._browser",
    "playwright._impl._browser_context",
    "playwright._impl._browser_type",
    "playwright._impl._cdp_session",
    "playwright._impl._connection",
    "playwright._impl._dialog",
    "playwright._impl._download",
    "playwright._impl._element_handle",
    "playwright._impl._errors",
    "playwright._impl._event_context_manager",
    "playwright._impl._file_chooser",
    "playwright._impl._frame",
    "playwright._impl._helper",
    "playwright._impl._input",
    "playwright._impl._js_handle",
    "playwright._impl._keyboard",
    "playwright._impl._locator",
    "playwright._impl._mouse",
    "playwright._impl._network",
    "playwright._impl._page",
    "playwright._impl._playwright",
    "playwright._impl._selectors",
    "playwright._impl._transport",
    "playwright._impl._driver",
    # PyQt5
    "PyQt5",
    "PyQt5.QtWidgets",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.sip",
    # Stdlib async
    "asyncio",
    "asyncio.events",
    "asyncio.tasks",
    "asyncio.futures",
    # App modules
    "src",
    "src.app",
    "src.auth",
    "src.combined",
    "src.config",
    "src.datasphere_client",
    "src.logging_setup",
    "src.portal_client",
    "src.report",
    "src.retry",
    "src.stage1_discovery",
    "src.stage2_deletion",
    "src.stage3_verify",
    "src.stage4_purge",
    "src.theme_apply",
    "src.resources_rc",
    # PyQt5 SVG (SAP logo + nav icons)
    "PyQt5.QtSvg",
    # Dependencies
    "yaml",
    "dotenv",
    "dotenv.main",
]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "src" / "combined.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "build" / "runtime_hook.py")],
    excludes=["pytest", "tests", "_pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Datasphere Cleanup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    # Icon can be added later: icon="build/icon.icns"
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Datasphere Cleanup",
)

app = BUNDLE(
    coll,
    name="Datasphere Cleanup.app",
    icon=None,
    bundle_identifier="com.sap.datasphere-cleanup",
    version="1.0.0",
    info_plist={
        "CFBundleName": "Datasphere Cleanup",
        "CFBundleDisplayName": "Datasphere Cleanup",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        # Required for Playwright to open a headed browser from inside a .app
        "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
    },
)
