"""
INTERACTIVE read-only session on AP11 Space Management.

Opens the tile grid with your saved session, then hands the browser to YOU. Type / click /
watch the dropdown by hand. Each time you press Enter in the terminal, it prints a snapshot:
the search-box value, the grid tile count, and how many tiles carry AC279401.. ids. Type 'q'
then Enter to quit. Does NO deletions.

Usage:
    source .venv/bin/activate
    python -m src.probe_interactive --tenant ap11
"""
import asyncio
import argparse

from playwright.async_api import async_playwright

from src.config import load_tenant_config
from src.auth import open_browser
from src.datasphere_client import (
    navigate_to_space_management,
    _SPACE_MGMT_SEARCHBOX,
    _WAIT_TIMEOUT,
)


async def _snapshot(page, workshop):
    sb = page.locator(_SPACE_MGMT_SEARCHBOX).first
    try:
        box_val = await sb.input_value()
    except Exception as exc:
        box_val = f"<no searchbox: {exc}>"
    ids = await page.evaluate("""() => Array.from(
        document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]')
    ).map(el => (el.innerText || '').trim())""")
    cards = await page.evaluate("""() => {
        const els = document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]');
        const out = [];
        els.forEach(idEl => {
            let card = idEl;
            while (card && card.tagName !== 'BODY') {
                if (card.className && card.className.toString().includes('sapFCard')) break;
                card = card.parentElement;
            }
            const texts = [];
            if (card) card.querySelectorAll('[id]').forEach(el => {
                if (el.children.length === 0) { const t=(el.innerText||'').trim(); if(t) texts.push(t); }
            });
            out.push(texts);
        });
        return out;
    }""")
    matched = sum(1 for texts in cards for t in texts if t.startswith("AC" + workshop))
    # Is the autocomplete dropdown currently open?
    try:
        dd = await page.locator('[role="listbox"].sapMSelectList').count()
    except Exception:
        dd = "?"
    print(f"    search box value : {box_val!r}")
    print(f"    grid tile count  : {len(ids)}")
    print(f"    tiles matching AC{workshop}.. : {matched}")
    print(f"    autocomplete dropdown open? : {dd}")
    print(f"    first few tile ids: {ids[:6]}")


async def _run(tenant, workshop):
    cfg = load_tenant_config(tenant, "config/settings.yaml")
    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context(storage_state=cfg["datasphere"]["session_file"])
        page = await context.new_page()
        print(f"\n[interactive] Tenant: {tenant.upper()} — READ ONLY. Navigating...")
        await navigate_to_space_management(page, cfg)
        print(f"[interactive] Ready. Interact with the browser by hand.")
        print(f"[interactive] Suggested test: click the search box, type {workshop!r}, and")
        print(f"               WITHOUT pressing anything else, come here and press Enter to")
        print(f"               snapshot the grid. Then try clicking a tile / dropdown row and")
        print(f"               snapshot again. Type 'q' + Enter to quit.\n")
        loop = asyncio.get_event_loop()
        while True:
            cmd = await loop.run_in_executor(None, input, "[snapshot] Enter=snapshot, q=quit: ")
            if cmd.strip().lower() == "q":
                break
            print(f"\n  --- snapshot ---")
            await _snapshot(page, workshop)
            print()
        await browser.close()
        print("[interactive] Done.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="ap11")
    parser.add_argument("--workshop", default="279401")
    args = parser.parse_args()
    asyncio.run(_run(args.tenant, args.workshop))


if __name__ == "__main__":
    main()
