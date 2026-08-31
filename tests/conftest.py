import os
import pytest
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture(autouse=True)
def set_project_root(monkeypatch):
    """Ensure tests run from the project root so config paths resolve correctly."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.chdir(root)


def make_async_playwright_mocks():
    """Return (mock_pw_cm, mock_browser, mock_context, mock_page) for async_playwright patching.

    mock_pw_cm is an async context manager — patch it as the return value of async_playwright.
    mock_browser / context / page are AsyncMocks so all their methods can be awaited.
    """
    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_pw = AsyncMock()
    mock_pw.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_pw.__aexit__ = AsyncMock(return_value=False)
    mock_pw.chromium = AsyncMock()

    return mock_pw, mock_browser, mock_context, mock_page
