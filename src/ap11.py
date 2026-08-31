"""
AP11 entry point — opens the GUI targeting the AP11 tenant.
Invoked via:  datasphere-cleanup-ap11
          or: python -m src.ap11
"""
from src.app import main as _app_main


def main():
    _app_main(tenant="ap11")
