"""
US10 entry point — opens the GUI targeting the US10 tenant.
Invoked via:  datasphere-cleanup-us10
          or: python -m src.us10
"""
from src.app import main as _app_main


def main():
    _app_main(tenant="us10")
