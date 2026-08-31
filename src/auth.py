import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from src.logging_setup import get_logger

logger = get_logger("auth")


class SessionExpired(Exception):
    pass


async def open_browser(playwright, headless: bool = False):
    return await playwright.chromium.launch(headless=headless)


async def save_portal_session(cfg: dict, wait_callback=None):
    """
    Open a headed browser, wait for manual login, then save the portal session.
    wait_callback: callable invoked after the browser opens (GUI use).
    Defaults to input() for terminal use.
    """
    session_file = cfg["portal"]["session_file"]
    base_url     = cfg["portal"]["base_url"]

    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(base_url, wait_until="domcontentloaded")

        if wait_callback:
            wait_callback()
        else:
            input("Press ENTER once fully logged in to the portal...")

        await context.storage_state(path=session_file)
        logger.info(f"Portal session saved to {session_file}")
        await browser.close()


async def save_datasphere_session(cfg: dict, wait_callback=None):
    """
    Open a headed browser, wait for manual login to Datasphere, then save the session.
    wait_callback: callable invoked after the browser opens (GUI use).
    Defaults to input() for terminal use.
    """
    session_file = cfg["datasphere"]["session_file"]
    base_url     = cfg["datasphere"]["base_url"].rstrip("/")
    sign_in_path = cfg["datasphere"].get("sign_in_path", "/dwaas-core/index.html#/spaceManagement")
    target_url   = base_url + sign_in_path

    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(target_url, wait_until="domcontentloaded")

        if wait_callback:
            wait_callback()
        else:
            input("Press ENTER once fully logged in to Datasphere...")

        await context.storage_state(path=session_file)
        logger.info(f"Datasphere session saved to {session_file}")
        await browser.close()
