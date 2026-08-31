"""
EU10(2) entry point — opens the GUI targeting the EU10(2) tenant.
Invoked via:  datasphere-cleanup-eu10-2
          or: python -m src.eu10_2
"""
from src.app import main as _app_main


def main():
    _app_main(tenant="eu10_2")
