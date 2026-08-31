"""
Datasphere Space Management DOM probe.

Usage:
    source .venv/bin/activate
    python -m src.probe_datasphere [--tenant eu10|us10] [--user AC######U##]
"""
import asyncio
import argparse
from pathlib import Path

from playwright.async_api import async_playwright

from src.config import load_tenant_config
from src.auth import open_browser


async def _probe(tenant: str, test_user: str):
    cfg = load_tenant_config(tenant, "config/settings.yaml")
    base_url     = cfg["datasphere"]["base_url"].rstrip("/")
    session_file = cfg["datasphere"]["session_file"]
    space_mgmt   = base_url + cfg["datasphere"]["space_management_path"]
    output_dir   = Path(cfg["outputs"]["logs_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    searchbox_sel = (
        "[id*='manageSpaces--filterSpacesInput-I'], "
        "[id*='spaceManagement'] [role='searchbox'], "
        "[id*='managespaces'] input[type='search']"
    )

    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context(storage_state=session_file)
        page = await context.new_page()

        print(f"\n[probe] Tenant: {tenant.upper()}")
        print(f"[probe] Navigating to Space Management...")
        await page.goto(space_mgmt, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector(searchbox_sel, timeout=15000)
        print(f"[probe] Page loaded. Searching for {test_user}...")

        searchbox = page.locator(searchbox_sel).first
        await searchbox.click()
        await searchbox.fill("")
        await asyncio.sleep(0.5)

        # Type and wait for autocomplete
        await searchbox.fill(test_user)
        try:
            await page.wait_for_selector(
                '[role="listbox"].sapMSelectList li',
                timeout=5000, state="attached",
            )
            suggestions = await page.evaluate("""() => {
                const list = document.querySelector('[role="listbox"].sapMSelectList');
                if (!list) return [];
                return Array.from(list.querySelectorAll('li')).map(li => li.innerText.trim());
            }""")
            print(f"\n[probe] Autocomplete suggestions ({len(suggestions)}):")
            for s in suggestions:
                print(f"  {repr(s)}")
        except Exception:
            print("[probe] No autocomplete suggestions appeared")
            suggestions = []

        # Dismiss and submit
        await searchbox.press("Escape")
        await asyncio.sleep(0.3)
        await searchbox.click()
        await searchbox.fill("")
        await asyncio.sleep(0.3)
        await searchbox.fill(test_user)
        await searchbox.press("Enter")

        print(f"\n[probe] Waiting for tiles after Enter...")
        await asyncio.sleep(2.0)  # give the SPA time to settle

        # Read ALL open buttons — both visible and hidden
        tile_data = await page.evaluate("""() => {
            const buttons = Array.from(document.querySelectorAll(
                '[id*="spaceTileFragment"][id*="openSpaceButton"]'
            ));
            const results = [];
            buttons.forEach((btn, i) => {
                const r = btn.getBoundingClientRect();
                const style = window.getComputedStyle(btn);
                const visible = r.width > 0 && r.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';

                let card = btn;
                while (card && card.parentElement) {
                    card = card.parentElement;
                    if (card.className && card.className.toString().includes('sapFCard')) break;
                    if (card.tagName === 'BODY') { card = null; break; }
                }

                // Also find the identifier label near this tile
                let identifier = '';
                if (card) {
                    const idEl = card.querySelector('[id$="spaceTileHeader-identifier-txt"]');
                    if (idEl) identifier = idEl.innerText.trim();
                }

                results.push({
                    index:      i,
                    btn_id:     btn.id,
                    visible:    visible,
                    identifier: identifier,
                    card_text:  card ? card.innerText.trim().slice(0, 200) : '',
                    card_html:  card ? card.outerHTML : '',
                });
            });
            return results;
        }""")

        print(f"\n[probe] Total tile Open buttons in DOM: {len(tile_data)}")
        visible = [t for t in tile_data if t['visible']]
        hidden  = [t for t in tile_data if not t['visible']]
        print(f"  Visible: {len(visible)}")
        print(f"  Hidden:  {len(hidden)}")

        # Also read identifier-txt elements directly via evaluate (JS-rendered, not in static HTML)
        live_identifiers = await page.evaluate("""() => {
            const els = document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]');
            return Array.from(els).map(el => ({
                id:   el.id,
                text: el.innerText.trim(),
            }));
        }""")
        print(f"\n[probe] Live identifier-txt elements ({len(live_identifiers)}):")
        for item in live_identifiers[:10]:
            print(f"  text={repr(item['text'])}  id=...{item['id'][-60:]}")
        if len(live_identifiers) > 10:
            print(f"  ... ({len(live_identifiers) - 10} more)")

        for t in tile_data:
            print(f"\n{'='*60}")
            print(f"Index:      {t['index']}")
            print(f"Visible:    {t['visible']}")
            print(f"Identifier: {repr(t['identifier'])}")
            print(f"btn_id:     ...{t['btn_id'][-80:]}")
            print(f"Card text:  {repr(t['card_text'][:150])}")
            if t['card_html']:
                html_path = output_dir / f"tile_probe_{tenant}_{t['index']}.html"
                html_path.write_text(t['card_html'], encoding="utf-8")
                print(f"HTML saved: {html_path}")

        # Also dump the full page for inspection
        full_html = await page.content()
        full_path = output_dir / f"space_mgmt_probe_{tenant}.html"
        full_path.write_text(full_html, encoding="utf-8")
        print(f"\n[probe] Full page HTML: {full_path}")

        input("\nPress Enter to close the browser...")
        await browser.close()
        print("[probe] Done.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="eu10", choices=["eu10", "us10", "ap11"])
    parser.add_argument("--user", default="AC333150U04")
    args = parser.parse_args()
    asyncio.run(_probe(args.tenant, args.user))


if __name__ == "__main__":
    main()
