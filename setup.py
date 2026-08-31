from setuptools import setup, find_packages

APP = ["src/app.py"]
DATA_FILES = [
    ("config", ["config/settings.yaml", "config/allowlist.txt"]),
]
OPTIONS = {
    "argv_emulation": False,
    "iconfile": None,
    "plist": {
        "CFBundleName": "Datasphere Cleanup",
        "CFBundleDisplayName": "Datasphere Cleanup",
        "CFBundleIdentifier": "com.sap.datasphere-cleanup",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
    },
    "packages": [
        "src",
        "PyQt5",
        "playwright",
        "yaml",
        "dotenv",
    ],
    "includes": [
        "threading",
        "queue",
        "json",
        "pathlib",
        "datetime",
        "re",
        "time",
    ],
    "excludes": ["pytest", "tests"],
}

setup(
    name="datasphere-cleanup",
    version="1.0.0",
    packages=find_packages(),
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
    entry_points={
        "console_scripts": [
            "datasphere-cleanup=src.main:main",
            "datasphere-cleanup-combined-demo=src.combined:main_demo",
            "datasphere-cleanup-eu10=src.eu10:main",
            "datasphere-cleanup-us10=src.us10:main",
            "datasphere-cleanup-ap11=src.ap11:main",
            "datasphere-cleanup-combined=src.combined:main",
            "datasphere-cleanup-ap11-2=src.ap11_2:main",
            "datasphere-cleanup-eu10-2=src.eu10_2:main",
            "datasphere-cleanup-us10-2=src.us10_2:main",
            "datasphere-cleanup-probe-date-filter=src.probes.probe_portal_date_filter:main",
        ],
    },
)
