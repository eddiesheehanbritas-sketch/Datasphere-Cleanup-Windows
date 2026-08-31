"""
EU10 entry point — opens the GUI targeting the EU10 tenant.
Invoked via:  datasphere-cleanup-eu10
          or: python -m src.eu10
"""
from src.app import main as _app_main


def main():
    _app_main(tenant="eu10")
