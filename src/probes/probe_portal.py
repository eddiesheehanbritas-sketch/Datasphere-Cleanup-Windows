"""
Portal DOM probe — run this BEFORE editing portal_client.py selectors.

Usage:
    python -m src.probes.probe_portal

What it does:
    1. Opens a headed browser with your saved portal session
    2. Navigates to Internal Requests
    3. Pauses and dumps the visible DOM to stdout and to outputs/logs/probe_portal_<ts>.html
    4. After each step, waits for you to press ENTER so you can inspect the browser

This is your ground truth. Update portal_client.py selectors based on what
you see here — never guess.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

from src.config import load_config
from src.auth import open_browser


async def dump_dom(page, label: str, output_dir: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(output_dir) / f"probe_portal_{label}_{ts}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = await page.content()
    path.write_text(content, encoding="utf-8")
    screenshot_path = Path(output_dir) / f"probe_portal_{label}_{ts}.png"
    await page.screenshot(path=str(screenshot_path), full_page=True)
    print(f"\n[probe] DOM saved to: {path}")
    print(f"[probe] Screenshot saved to: {screenshot_path}")


async def probe():
    cfg = load_config()
    base_url = cfg["portal"]["base_url"]
    session_file = cfg["portal"]["session_file"]
    output_dir = cfg["outputs"]["logs_dir"]

    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context(storage_state=session_file)
        page = await context.new_page()

        print(f"\n[probe] Navigating to portal: {base_url}")
        await page.goto(base_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        await dump_dom(page, "01_home", output_dir)
        print("\n[probe] Step 1: Portal home loaded.")
        print("        Inspect the browser. Look for the sidebar 'Internal Requests' item.")
        print("        Note the exact element tag, class, and text.")
        input("        Press ENTER to continue to next step...")

        print("\n[probe] Attempting to click Internal Requests sidebar item...")
        print("        Trying selectors — watch the browser to see if it works.")
        candidates = [
            "a:has-text('Internal')",
            "li:has-text('Internal Requests')",
            "[role='menuitem']:has-text('Internal')",
            "span:has-text('Internal Requests')",
            "button:has-text('Internal')",
        ]
        clicked = False
        for sel in candidates:
            try:
                el = page.locator(sel)
                if await el.count() > 0:
                    await el.first.click()
                    print(f"        [probe] Clicked using selector: {sel}")
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            print("        [probe] WARNING: Could not click Internal Requests.")
            print("        Update the '[aria-label^=\\'Tree Item Internal request(s)\\']' locator")
            print("        in _go_to_filtered_list() in portal_client.py")

        await asyncio.sleep(2)
        await dump_dom(page, "02_internal_requests", output_dir)
        print("\n[probe] Step 2: After clicking Internal Requests.")
        print("        Look for: search input, filter dropdowns, workshop rows.")
        input("        Press ENTER to continue...")

        print("\n[probe] Attempting search for 'SAP Datasphere Overview'...")
        search_candidates = [
            "input[placeholder*='Search']",
            "input[type='search']",
            "input[placeholder*='search']",
            "input[placeholder*='Filter']",
        ]
        searched = False
        for sel in search_candidates:
            try:
                el = page.locator(sel)
                if await el.count() > 0:
                    await el.first.fill("SAP Datasphere Overview")
                    await page.keyboard.press("Enter")
                    print(f"        [probe] Searched using selector: {sel}")
                    searched = True
                    break
            except Exception:
                continue
        if not searched:
            print("        [probe] WARNING: Could not find search input.")
            print("        Update the searchbox locator in _go_to_filtered_list()")
            print("        in portal_client.py (currently uses get_by_role('searchbox'))")

        await asyncio.sleep(2)
        await dump_dom(page, "03_search_results", output_dir)
        print("\n[probe] Step 3: After searching.")
        print("        Look for: workshop rows, their HTML structure, how workshop IDs appear.")
        print("        Also look for the Environment filter element.")
        input("        Press ENTER to continue to filter dialog probe...")

        print("\n[probe] Step 4: Settings menu — MANUAL STEP")
        print("        In the browser: click the Settings (gear) button in the toolbar.")
        print("        Leave the menu OPEN — do not click anything else yet.")
        input("        Press ENTER once the Settings menu is open to dump DOM...")
        await asyncio.sleep(0.5)
        await dump_dom(page, "04_settings_menu_open", output_dir)
        print("        [probe] Settings menu DOM dumped.")

        print("\n[probe] Step 5: Filter panel — MANUAL STEP")
        print("        In the browser: click the 'Filter' option in the Settings menu.")
        print("        Leave the Filter panel OPEN — do not click anything yet.")
        input("        Press ENTER once the Filter panel is open to dump DOM...")
        await asyncio.sleep(0.5)
        await dump_dom(page, "05_filter_panel_open", output_dir)
        print("        [probe] Filter panel DOM dumped.")
        print("        IMPORTANT: note how 'Environment' and 'DC Region' items are identified.")

        print("\n[probe] Step 6: Environment values — MANUAL STEP")
        print("        In the browser: click the 'Environment' row in the filter panel.")
        print("        Leave the value list OPEN so 'Cleaned', 'Active', etc. are visible.")
        input("        Press ENTER once the Environment values are visible to dump DOM...")
        await asyncio.sleep(0.5)
        await dump_dom(page, "06_environment_values_open", output_dir)
        print("        [probe] Environment values DOM dumped.")
        print("        IMPORTANT: note how 'Cleaned' is identified — role, aria-label, id, text.")
        input("        Press ENTER to finish probe...")

        await browser.close()

    print("\n[probe] Done. Review the HTML dumps and screenshots in:", output_dir)
    print("        Then update selectors in src/portal_client.py accordingly.")


def main():
    asyncio.run(probe())


if __name__ == "__main__":
    main()
