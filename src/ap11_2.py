"""
AP11(2) entry point — opens the GUI targeting the AP11(2) tenant.
Invoked via:  datasphere-cleanup-ap11-2
          or: python -m src.ap11_2
"""
from src.app import main as _app_main


def main():
    _app_main(tenant="ap11_2")
