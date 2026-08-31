"""
Portal date-filter probe — run this to discover the DOM selectors needed
for applying the End Date (workshop end date) filter in portal_client.py.

Usage:
    python -m src.probe_portal_date_filter

    Optional — probe a specific tenant (defaults to eu10):
    python -m src.probe_portal_date_filter eu10
    python -m src.probe_portal_date_filter us10

What it does:
    1. Opens a headed browser with your saved portal session
    2. Navigates to Internal Requests and applies the existing two filters
       (Environment=Cleaned, DC Region) exactly as the production code does
    3. Pauses at each step so you can open the date filter manually
    4. Dumps DOM + screenshot at each step to outputs/logs/

    At the end you will have HTML snapshots of:
    - The filter panel showing all available filter fields
    - The date sub-panel after clicking "End Date" (or equivalent)
    - The state after entering the start date
    - The state after entering the end date and clicking OK

    Copy the relevant selectors back into portal_client.py.
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
    html_path = base / f"probe_date_{label}_{ts}.html"
    png_path  = base / f"probe_date_{label}_{ts}.png"
    html_path.write_text(await page.content(), encoding="utf-8")
    await page.screenshot(path=str(png_path), full_page=True)
    print(f"  [dump] HTML  → {html_path}")
    print(f"  [dump] PNG   → {png_path}")


async def probe(tenant: str = "eu10"):
    cfg        = load_tenant_config(tenant, "config/settings.yaml")
    base_url   = cfg["portal"]["base_url"]
    session    = cfg["portal"]["session_file"]
    dc_region  = cfg["portal"].get("dc_region", tenant.upper())
    search     = cfg["portal"].get("search_term", "SAP Datasphere Overview")
    output_dir = cfg["outputs"]["logs_dir"]

    WAIT = 15_000  # ms — same as production _WAIT_TIMEOUT

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state=session)
        page    = await context.new_page()

        # ── Step 1: navigate to Internal Requests ─────────────────────────────
        print(f"\n[probe] Navigating to portal ({tenant.upper()})…")
        await page.goto(base_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_selector(
            "[aria-label^='Tree Item Internal request(s)']", timeout=WAIT
        )
        await page.locator("[aria-label^='Tree Item Internal request(s)']").click()
        await page.wait_for_selector(
            "a[href*='/academy-request/'], .sapMListNoData, [class*='noData']",
            timeout=WAIT, state="attached",
        )
        print("[probe] Step 1 — Internal Requests loaded.")
        await dump(page, "01_internal_requests", output_dir)

        # ── Step 2: search ────────────────────────────────────────────────────
        sb = page.get_by_role("searchbox")
        await sb.click()
        await sb.fill(search)
        await sb.press("Enter")
        await page.wait_for_selector(
            "a[href*='/academy-request/'], .sapMListNoData", timeout=WAIT, state="attached"
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
            "a[href*='/academy-request/'], .sapMListNoData", timeout=WAIT, state="attached"
        )
        print("[probe] Filter 1 applied.")
        await dump(page, "03_after_filter_env_cleaned", output_dir)

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
            "a[href*='/academy-request/'], .sapMListNoData", timeout=WAIT, state="attached"
        )
        print("[probe] Filter 2 applied.")
        await dump(page, "04_after_filter_dc_region", output_dir)

        # ── Step 5: Open filter panel — DUMP ALL AVAILABLE FILTER FIELDS ──────
        print("\n[probe] ── MANUAL STEPS BEGIN ──")
        print("Step 5: Now we need to see ALL available filter fields.")
        print("        In the browser: click the Settings (gear) button,")
        print("        then click 'Filter' to open the filter field list.")
        print("        Leave it OPEN — do not click any field yet.")
        input("        Press ENTER once the filter field list is visible…")
        await dump(page, "05_filter_field_list", output_dir)
        print("  [probe] Filter field list dumped.")
        print("  Look for a field related to 'End Date', 'Workshop End', 'Date', or similar.")

        # ── Step 6: Click the date field ──────────────────────────────────────
        print("\nStep 6: Click the date-related field (e.g. 'End Date') in the filter panel.")
        print("        Leave the date sub-panel OPEN — do not enter any value yet.")
        input("        Press ENTER once the date sub-panel is visible…")
        await dump(page, "06_date_filter_panel_open", output_dir)
        print("  [probe] Date filter panel dumped.")
        print("  Look for: input fields, date-picker buttons, 'from'/'to' or 'start'/'end' inputs.")

        # ── Step 7: Enter the FROM date ───────────────────────────────────────
        print("\nStep 7: Enter the FROM date (e.g. 01/01/2024 or 2024-01-01).")
        print("        Try both typing directly into the field and using a calendar picker.")
        print("        Leave the panel open after entering — do not click OK yet.")
        input("        Press ENTER once the FROM date is entered…")
        await dump(page, "07_date_from_entered", output_dir)
        print("  [probe] FROM date state dumped.")

        # ── Step 8: Enter the TO date ─────────────────────────────────────────
        print("\nStep 8: Enter the TO date (e.g. 01/01/2025 or 2025-01-01).")
        print("        Leave the panel open — do not click OK yet.")
        input("        Press ENTER once the TO date is entered…")
        await dump(page, "08_date_to_entered", output_dir)
        print("  [probe] TO date state dumped.")

        # ── Step 9: Click OK and verify the 'Filtered by' toolbar ────────────
        print("\nStep 9: Click OK to apply the date filter.")
        print("        After clicking OK, look at the 'Filtered by:' toolbar at the top.")
        print("        It should now show three filters — note the EXACT text for the date filter.")
        print("        e.g. 'End Date (01/01/2024 – 01/01/2025)'")
        input("        Press ENTER once the filter is applied and toolbar is visible…")
        await dump(page, "09_three_filters_applied", output_dir)
        print("  [probe] Three-filter state dumped.")

        # ── Step 10: Inspect filtered by toolbar ──────────────────────────────
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
                if "Filtered by" in text:
                    label_text = text
                    break
            if label_text:
                break

        if label_text:
            print(f"  [probe] Toolbar text: '{label_text}'")
            print("  Copy the date portion — this is what _verify_filters_active must check.")
        else:
            print("  [probe] WARNING: Could not read toolbar text automatically.")
            print("  Read it manually from the browser or the HTML dump.")

        input("\nPress ENTER to close the browser and finish…")
        await browser.close()

    print("\n[probe] Done. Review dumps in:", output_dir)
    print("        Then send the Playwright selectors to implement the date filter.")


def main():
    tenant = sys.argv[1] if len(sys.argv) > 1 else "eu10"
    import os
    os.chdir(Path(__file__).resolve().parent.parent)
    asyncio.run(probe(tenant))


if __name__ == "__main__":
    main()
