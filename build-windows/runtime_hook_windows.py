"""
PyInstaller runtime hook for Datasphere Cleanup — Windows build.

Runs before any app code. Sets environment variables so Playwright finds
the driver and Chromium bundled inside the .exe distribution folder.
"""
import os
import sys
from pathlib import Path

if hasattr(sys, "_MEIPASS"):
    bundle = Path(sys._MEIPASS)

    # Windows: the Node driver binary is node.exe
    os.environ["PLAYWRIGHT_DRIVER_PATH"] = str(
        bundle / "playwright" / "driver" / "node.exe"
    )

    # Tell Playwright where to find the bundled Chromium.
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundle / "ms-playwright")
