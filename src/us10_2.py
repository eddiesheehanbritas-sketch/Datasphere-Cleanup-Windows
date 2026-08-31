"""
US10(2) entry point — opens the GUI targeting the US10(2) tenant.
Invoked via:  datasphere-cleanup-us10-2
          or: python -m src.us10_2
"""
from src.app import main as _app_main


def main():
    _app_main(tenant="us10_2")
