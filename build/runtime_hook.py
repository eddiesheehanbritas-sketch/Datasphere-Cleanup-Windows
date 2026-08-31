"""
PyInstaller runtime hook for Datasphere Cleanup.

Runs before any app code. Sets environment variables so Playwright finds
the driver and Chromium that are bundled inside the .app.

CWD and app home setup is handled by src.config.setup_app_home() which
is called at the start of main() in combined.py and app.py.
"""
import os
import sys
from pathlib import Path

if hasattr(sys, "_MEIPASS"):
    bundle = Path(sys._MEIPASS)

    # Tell Playwright where the Node driver lives inside the bundle.
    os.environ["PLAYWRIGHT_DRIVER_PATH"] = str(
        bundle / "playwright" / "driver" / "node"
    )

    # Tell Playwright where to find the bundled Chromium.
    # _MEIPASS resolves to Contents/Frameworks in a PyInstaller .app bundle.
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundle / "ms-playwright")
