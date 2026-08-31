"""
Portal Workshop ID range filter probe — run this to discover the DOM selectors
needed for applying the Workshop ID from/to filter in portal_client.py.

Usage:
    python -m src.probes.probe_workshop_id_filter
    python -m src.probes.probe_workshop_id_filter ap11_2
    python -m src.probes.probe_workshop_id_filter eu10

What it does:
    1. Opens a headed browser with your saved portal session
    2. Navigates to the requests list and applies Environment=Cleaned + DC Region
       exactly as the production code does
    3. Pauses at each manual step so you can interact with the Workshop ID filter
    4. Dumps HTML + PNG at each step to outputs/logs/

    At the end you will have snapshots of:
    - The filter field list (to find the exact label for the Workshop ID field)
    - The Workshop ID sub-panel open (to find the From/To input selectors)
    - After entering the From value
    - After entering the To value
    - After clicking OK (to capture the toolbar chip text)
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from src.config import load_tenant_config


async def dump(page, label: str, output_dir: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    html_path = base / f"probe_wid_{label}_{ts}.html"
    png_path  = base / f"probe_wid_{label}_{ts}.png"
    html_path.write_text(await page.content(), encoding="utf-8")
    await page.screenshot(path=str(png_path), full_page=True)
    print(f"  [dump] HTML  → {html_path}")
    print(f"  [dump] PNG   → {png_path}")


async def probe(tenant: str = "ap11_2"):
    cfg        = load_tenant_config(tenant, "config/settings.yaml")
    base_url   = cfg["portal"]["base_url"]
    session    = cfg["portal"]["session_file"]
    dc_region  = cfg["portal"].get("dc_region", tenant.upper())
    search     = cfg["portal"].get("search_term", "SAP Datasphere Overview")
    requests_tree_item = cfg["portal"].get("requests_tree_item", "Internal request(s)")
    output_dir = cfg["outputs"]["logs_dir"]

    WAIT = 15_000  # ms — same as production _WAIT_TIMEOUT

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state=session)
        page    = await context.new_page()

        # ── Step 1: navigate to requests list ────────────────────────────────
        print(f"\n[probe] Navigating to portal ({tenant.upper()})…")
        await page.goto(base_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_selector(
            f"[aria-label^='Tree Item {requests_tree_item}']", timeout=WAIT
        )
        await page.locator(f"[aria-label^='Tree Item {requests_tree_item}']").click()
        await page.wait_for_selector(
            "a[href*='/academy-request/'], a[href*='/ge-request/'], "
            ".sapMListNoData, [class*='noData']",
            timeout=WAIT, state="attached",
        )
        print("[probe] Step 1 — Requests list loaded.")
        await dump(page, "01_requests_loaded", output_dir)

        # ── Step 2: search ────────────────────────────────────────────────────
        print(f"[probe] Searching for '{search}'…")
        try:
            sb = page.locator("[role='searchbox']")
            await sb.wait_for(timeout=5_000)
        except Exception:
            sb = page.locator("input[type='search'].fdp-search-field__input")
        await sb.click()
        await sb.fill(search)
        await sb.press("Enter")
        await page.wait_for_selector(
            "a[href*='/academy-request/'], a[href*='/ge-request/'], .sapMListNoData",
            timeout=WAIT, state="attached",
        )
        print("[probe] Step 2 — Search results loaded.")
        await dump(page, "02_search_results", output_dir)

        # ── Step 3: Filter 1 — Environment: Cleaned ───────────────────────────
        print("[probe] Applying Filter 1: Environment = Cleaned…")
        await page.get_by_role("button", name="Settings").click()
        await page.wait_for_selector("[role='option'][aria-label='Filter']", timeout=WAIT)
        await page.locator("[role='option'][aria-label='Filter']").click()
        await page.wait_for_selector(
            "li[role='listitem'] span.fd-list__title:text-is('Environment')", timeout=WAIT
        )
        await page.locator(
            "li[role='listitem'] span.fd-list__title:text-is('Environment')"
        ).click()
        await page.wait_for_selector("li[role='option']:has-text('Cleaned')", timeout=WAIT)
        await page.locator("li[role='option']:has-text('Cleaned')").click()
        await page.get_by_role("button", name="OK").click()
        await page.wait_for_selector(
            "a[href*='/academy-request/'], a[href*='/ge-request/'], .sapMListNoData",
            timeout=WAIT, state="attached",
        )
        print("[probe] Filter 1 applied.")
        await dump(page, "03_after_env_cleaned", output_dir)

        # ── Step 4: Filter 2 — DC Region ─────────────────────────────────────
        print(f"[probe] Applying Filter 2: DC Region = {dc_region}…")
        await page.get_by_role("button", name="Settings").click()
        await page.wait_for_selector("[role='option'][aria-label='Filter']", timeout=WAIT)
        await page.locator("[role='option'][aria-label='Filter']").click()
        await page.wait_for_selector("text=DC Region", timeout=WAIT)
        await page.get_by_text("DC Region").click()
        await page.wait_for_selector(f"text={dc_region}", timeout=WAIT)
        await page.get_by_text(dc_region).click()
        await page.get_by_role("button", name="OK").click()
        await page.wait_for_selector(
            "a[href*='/academy-request/'], a[href*='/ge-request/'], .sapMListNoData",
            timeout=WAIT, state="attached",
        )
        print("[probe] Filter 2 applied.")
        await dump(page, "04_after_dc_region", output_dir)

        # ── Step 5: Open filter panel — dump ALL available filter fields ──────
        print("\n[probe] ── MANUAL STEPS BEGIN ──")
        print("Step 5: We need to see ALL available filter fields.")
        print("        In the browser: click the Settings (gear) button,")
        print("        then click 'Filter' to open the filter field list.")
        print("        Leave the list OPEN — do not click any field yet.")
        input("        Press ENTER once the filter field list is visible…")
        await dump(page, "05_filter_field_list", output_dir)
        print("  [probe] Filter field list dumped.")
        print("  Look for a field related to 'Workshop', 'Request', 'ID', or 'Number'.")

        # ── Step 6: Click the Workshop ID field ───────────────────────────────
        print("\nStep 6: Click the Workshop ID range field in the filter panel.")
        print("        Leave the sub-panel OPEN — do not enter any value yet.")
        input("        Press ENTER once the Workshop ID sub-panel is visible…")
        await dump(page, "06_workshop_id_panel_open", output_dir)
        print("  [probe] Workshop ID filter panel dumped.")
        print("  Look for: input fields, 'From'/'To' or 'Start'/'End' or numeric inputs.")

        # ── Step 7: Enter the FROM value ──────────────────────────────────────
        print("\nStep 7: Enter the FROM workshop ID (e.g. 277373).")
        print("        Leave the panel open — do not click OK yet.")
        input("        Press ENTER once the FROM value is entered…")
        await dump(page, "07_workshop_id_from_entered", output_dir)
        print("  [probe] FROM value state dumped.")

        # ── Step 8: Enter the TO value ────────────────────────────────────────
        print("\nStep 8: Enter the TO workshop ID (e.g. 281952).")
        print("        Leave the panel open — do not click OK yet.")
        input("        Press ENTER once the TO value is entered…")
        await dump(page, "08_workshop_id_to_entered", output_dir)
        print("  [probe] TO value state dumped.")

        # ── Step 9: Click OK and capture the toolbar chip ─────────────────────
        print("\nStep 9: Click OK to apply the Workshop ID filter.")
        print("        After clicking OK, look at the 'Filtered by:' toolbar at the top.")
        print("        It should now show three filters — note the EXACT chip text,")
        print("        e.g. 'Workshop ID (277373 – 281952)'")
        input("        Press ENTER once the filter is applied and toolbar is visible…")
        await dump(page, "09_three_filters_applied", output_dir)
        print("  [probe] Three-filter state dumped.")

        # ── Step 10: Read the toolbar chip text automatically ─────────────────
        print("\nStep 10: Inspecting 'Filtered by:' toolbar text…")
        label_text = ""
        for selector in [
            "fd-toolbar[fdtype='info'] label",
            "[class*='applied-filters-toolbar'] label",
            "fd-label[fd-toolbar-label]",
            "label[fd-toolbar-label]",
        ]:
            els = await page.locator(selector).all()
            for el in els:
                text = (await el.inner_text()).strip()
                if "Filtered by" in text or "Workshop" in text or "ID" in text:
                    label_text = text
                    break
            if label_text:
                break

        if label_text:
            print(f"  [probe] Toolbar text: '{label_text}'")
            print("  Copy the Workshop ID portion — this is what _verify_filters_active must check.")
        else:
            print("  [probe] WARNING: Could not read toolbar text automatically.")
            print("  Read it manually from the browser or the HTML dump in outputs/logs/.")

        # ── Step 11: Dump all fd-list__title items from a fresh filter open ───
        print("\nStep 11: Open the filter panel one more time so we can dump all field labels.")
        print("         Click Settings → Filter, leave the list open.")
        input("         Press ENTER once the filter field list is visible…")
        titles = await page.locator("li[role='listitem'] span.fd-list__title").all()
        print(f"  [probe] Found {len(titles)} filter field labels:")
        for t in titles:
            print(f"    • '{(await t.inner_text()).strip()}'")
        await dump(page, "10_filter_fields_final", output_dir)

        input("\nPress ENTER to close the browser and finish…")
        await browser.close()

    print("\n[probe] Done. Review dumps in:", output_dir)
    print("        Send the HTML snapshots and field label list to implement the filter.")


def main():
    tenant = sys.argv[1] if len(sys.argv) > 1 else "ap11_2"
    import os
    os.chdir(Path(__file__).resolve().parent.parent.parent)
    asyncio.run(probe(tenant))


if __name__ == "__main__":
    main()
