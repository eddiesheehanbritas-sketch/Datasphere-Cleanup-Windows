# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Datasphere Cleanup — Windows build
#
# DO NOT use this spec on macOS — use datasphere-cleanup.spec instead.
#
# This spec is invoked by the GitHub Actions workflow at
# .github/workflows/build-windows.yml and produces:
#   dist\Datasphere Cleanup\Datasphere Cleanup.exe
#
# Chromium is copied in after the build by the workflow (same reason as the
# Mac build: PyInstaller would re-process its binaries and break them).

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # build-windows/ is one level below the project root

# Find the Playwright driver from the system Python (no venv on the CI runner).
# sys.path contains the site-packages directory for the active Python.
import site
_site = Path(site.getsitepackages()[0])
PLAYWRIGHT_DRIVER = _site / "playwright" / "driver"

# Windows Playwright cache: %LOCALAPPDATA%\ms-playwright\chromium-1223
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
CHROMIUM_DIR = LOCALAPPDATA / "ms-playwright" / "chromium-1223"

# ── Sanity checks ─────────────────────────────────────────────────────────────
if not PLAYWRIGHT_DRIVER.exists():
    raise FileNotFoundError(f"Playwright driver not found: {PLAYWRIGHT_DRIVER}")
if not CHROMIUM_DIR.exists():
    raise FileNotFoundError(
        f"Chromium not found: {CHROMIUM_DIR}\n"
        f"Run: .venv\\Scripts\\activate && playwright install chromium"
    )

# ── Data files bundled into the distribution ──────────────────────────────────
datas = [
    # App config
    (str(ROOT / "config" / "settings.yaml"), "config"),
    (str(ROOT / "config" / "allowlist.txt"), "config"),
    # SAP 72 fonts
    (str(ROOT / "assets" / "fonts"), "assets/fonts"),
    # SAP Datasphere theme QSS
    (str(ROOT / "theme" / "datasphere_theme.qss"), "theme"),
    # Playwright driver (node.exe + cli.js package)
    (str(PLAYWRIGHT_DRIVER), "playwright/driver"),
    # NOTE: Chromium is NOT listed here — copied in after the build by the
    # workflow to avoid PyInstaller reprocessing its binaries.
]

# ── Hidden imports ─────────────────────────────────────────────────────────────
hidden_imports = [
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
    "PyQt5",
    "PyQt5.QtWidgets",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.sip",
    "PyQt5.QtSvg",
    "asyncio",
    "asyncio.events",
    "asyncio.tasks",
    "asyncio.futures",
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
    "yaml",
    "dotenv",
    "dotenv.main",
]

# ── Analysis ───────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "src" / "combined.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "build-windows" / "runtime_hook_windows.py")],
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
    # icon="build-windows/icon.ico"  # add a .ico file here when available
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
