"""
Recycle bin DOM probe — captures the exact HTML and tile IDs from the recycle bin.

Usage:
    source .venv/bin/activate
    python -m src.probe_recycle_bin
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from src.config import load_tenant_config
from src.auth import open_browser


async def _probe():
    cfg = load_tenant_config("eu10", "config/settings.yaml")
    base_url     = cfg["datasphere"]["base_url"].rstrip("/")
    session_file = cfg["datasphere"]["session_file"]
    space_mgmt   = base_url + cfg["datasphere"]["space_management_path"]
    output_dir   = Path(cfg["outputs"]["logs_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context(storage_state=session_file)
        page = await context.new_page()

        print("\n[probe] Navigating to Space Management...")
        await page.goto(space_mgmt, wait_until="domcontentloaded", timeout=30000)

        print("\n[probe] Ready.")
        print("=" * 60)
        print("In the browser:")
        print("  1. Click the Recycle Bin tab in the left panel")
        print("  2. Wait for tiles to load")
        print("  3. Come back here and press Enter")
        print("=" * 60)
        input("\nPress Enter once the recycle bin tiles are visible...")

        # Dump 1: full page HTML
        full_html = await page.content()
        html_path = output_dir / "recycle_bin_full_page.html"
        html_path.write_text(full_html, encoding="utf-8")
        print(f"\n[probe] Full page HTML saved to: {html_path}")

        # Dump 2: all elements matching the tile ID label selector
        tile_ids = await page.evaluate("""() => {
            return Array.from(
                document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]')
            ).map(el => ({
                id:   el.id,
                text: el.innerText.trim(),
            }));
        }""")
        print(f"\n[probe] Tile ID labels ([id$='spaceTileHeader-identifier-txt']) — {len(tile_ids)} found:")
        for t in tile_ids:
            print(f"  id={repr(t['id'][:100]):<105} text={repr(t['text'])}")

        # Dump 3: all text inside elements that look like space identifiers
        all_labels = await page.evaluate("""() => {
            const selectors = [
                '[id*="identifier"]',
                '[id*="TileHeader"]',
                '[id*="spaceId"]',
                '[id*="spaceName"]',
                '.sapMOTileHeader',
            ];
            const results = [];
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    const text = el.innerText.trim();
                    if (text) results.push({selector: sel, id: el.id.slice(0, 100), text: text.slice(0, 80)});
                });
            });
            return results;
        }""")
        print(f"\n[probe] Broader identifier-like elements — {len(all_labels)} found:")
        for a in all_labels:
            print(f"  sel={repr(a['selector']):<35} id={repr(a['id']):<80} text={repr(a['text'])}")

        # Dump 4: all checkboxes
        checkboxes = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll(
                'input[type="checkbox"], [role="checkbox"]'
            )).map(el => ({
                id:         el.id || '',
                aria_label: el.getAttribute('aria-label') || '',
                aria_checked: el.getAttribute('aria-checked') || '',
                classes:    el.className.toString().slice(0, 80),
            }));
        }""")
        print(f"\n[probe] Checkboxes — {len(checkboxes)} found:")
        for c in checkboxes:
            print(f"  id={repr(c['id'][:80]):<85} aria_label={repr(c['aria_label'][:50]):<55} checked={c['aria_checked']}")

        # Dump 5: visible toolbar buttons
        buttons = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button, [role="button"]'))
                .filter(el => el.getBoundingClientRect().width > 0)
                .map(el => ({
                    id:         el.id.slice(0, 100),
                    text:       el.innerText.trim().slice(0, 80),
                    aria_label: (el.getAttribute('aria-label') || '').slice(0, 80),
                }));
        }""")
        print(f"\n[probe] Visible buttons — {len(buttons)} found:")
        for b in buttons:
            print(f"  id={repr(b['id']):<105} text={repr(b['text']):<50} aria={repr(b['aria_label'])}")

        input("\nPress Enter to close the browser...")
        await browser.close()
        print(f"\n[probe] Done. Full DOM saved to {html_path}")


def main():
    asyncio.run(_probe())


if __name__ == "__main__":
    main()
