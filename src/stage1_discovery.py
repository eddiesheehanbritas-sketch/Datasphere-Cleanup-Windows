import asyncio
from typing import Callable, Optional
from playwright.async_api import async_playwright

from src.auth import open_browser
from src.portal_client import run_portal_scrape, scrape_single_workshop, load_pending_workshops
from src.logging_setup import get_logger

logger = get_logger("stage1")


async def _run_stage1_async(cfg: dict, run_id: str, max_workshops: int = None, progress_callback: Optional[Callable[[str], None]] = None) -> None:
    session_file = cfg["portal"]["session_file"]
    base_url     = cfg["portal"]["base_url"]

    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context(storage_state=session_file)
        page = await context.new_page()
        await page.goto(base_url, wait_until="domcontentloaded")

        cfg_max_raw = cfg.get("batch", {}).get("max_workshops")
        cfg_max = cfg_max_raw if cfg_max_raw else None
        effective_max = max_workshops if max_workshops is not None else cfg_max
        try:
            await run_portal_scrape(page, cfg, max_workshops=effective_max)
        finally:
            await browser.close()

    pending_total = len(load_pending_workshops(cfg))
    logger.info(f"Stage 1 complete — {pending_total} workshop(s) pending sweep")

    if progress_callback is not None:
        progress_callback(f"Stage 1 complete — {pending_total} workshop(s) pending sweep")


def run_stage1(cfg: dict, run_id: str, max_workshops: int = None, progress_callback: Optional[Callable[[str], None]] = None) -> None:
    """Scrape the portal for Cleaned workshops and append them to the pending-workshops queue."""
    asyncio.run(_run_stage1_async(cfg, run_id, max_workshops, progress_callback))


async def _run_workshop_scrape_async(workshop_id: str, cfg: dict, run_id: str, progress_callback: Optional[Callable[[str], None]] = None) -> None:
    session_file = cfg["portal"]["session_file"]
    base_url     = cfg["portal"]["base_url"]

    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context(storage_state=session_file)
        page = await context.new_page()
        await page.goto(base_url, wait_until="domcontentloaded")
        try:
            await scrape_single_workshop(page, cfg, workshop_id)
        finally:
            await browser.close()

    pending_total = len(load_pending_workshops(cfg))
    logger.info(f"Workshop {workshop_id} queued — {pending_total} workshop(s) pending sweep")

    if progress_callback is not None:
        progress_callback(f"Workshop {workshop_id} queued — {pending_total} pending sweep")


def run_workshop_scrape(workshop_id: str, cfg: dict, run_id: str, progress_callback: Optional[Callable[[str], None]] = None) -> None:
    """Scrape a single workshop by ID and append it to the pending-workshops queue."""
    asyncio.run(_run_workshop_scrape_async(workshop_id, cfg, run_id, progress_callback))
