"""
READ-ONLY probe to diagnose the workshop-sweep "filtered tile set did not change"
safety abort on no-result searches.

Does NO deletions. Only navigates, searches by WORKSHOP NUMBER, and reports what the
guard (_wait_for_tile_set_changed) actually sees: the no-data selector count and the
visible tile-ID set, before and after each search.

It reproduces the exact failing sequence:
  1. fresh nav baseline
  2. search a workshop that swept OK (233717)  -> re-navigate
  3. search the workshop that FAILED (234287)   -> DO NOT re-navigate
  4. search 234287 AGAIN (empty -> empty)        -> the trigger case

Usage:
    source .venv/bin/activate
    python -m src.probe_workshop_nodata --tenant ap11
    python -m src.probe_workshop_nodata --tenant ap11 --workshops 233717 234287
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
    _current_tile_ids,
)

# The exact selector the guard uses to detect a valid empty-result state.
_NO_DATA_SEL = ".sapMListNoData, [class*='noData']"


async def _report(page, label):
    """Print what the guard would see right now: no-data count + tile-ID set."""
    try:
        no_data = await page.locator(_NO_DATA_SEL).count()
    except Exception as exc:
        no_data = f"<error: {exc}>"
    tiles = await _current_tile_ids(page)
    print(f"\n  [{label}]")
    print(f"    no-data count ('{_NO_DATA_SEL}'): {no_data}")
    print(f"    visible tile IDs ({len(tiles)}): {sorted(tiles)[:10]}"
          + (" ..." if len(tiles) > 10 else ""))
    return no_data, tiles


async def _search(page, workshop):
    """Mirror find_workshop_spaces' search steps exactly (no reading/deleting)."""
    searchbox = page.locator(_SPACE_MGMT_SEARCHBOX).first
    await searchbox.wait_for(state="visible", timeout=_WAIT_TIMEOUT)
    await searchbox.click()
    await searchbox.fill("")
    await searchbox.fill(workshop)
    await searchbox.press("End")
    await searchbox.press("Enter")
    await page.keyboard.press("Escape")
    try:
        await page.wait_for_selector(
            ".sapUiLocalBusyIndicator, .sapUiBlockLayerTabbable",
            state="hidden", timeout=15000,
        )
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass


async def _dump_nodata_html(page, tag, output_dir):
    """Capture what AP11 actually renders on a no-result search.

    Prior selector guesses (.sapMListNoData / [class*='noData']) matched nothing, so this
    instead (a) finds the real tile-area container by walking up from a known tile-area
    anchor, and (b) scans EVERY element for visible 'no results'-type text and reports the
    tag/class/text/id of each match. That reveals the true no-data element + selector."""
    info = await page.evaluate("""() => {
        // (a) The real tile area lives under the manageSpaces IconTabBar page content.
        // Find the tab page, then its content container (not the invisible header span).
        let area = document.querySelector('[id*="manageSpacesIconTabsPage"]');
        // Walk to a container that actually holds rendered content.
        let areaHtml = area ? area.outerHTML : '<no tab page found>';

        // (b) Scan for any VISIBLE element whose direct text looks like a no-result message.
        const NEEDLE = /(no (spaces|results|data|items)|not found|no matching|couldn't find|no entries)/i;
        const hits = [];
        const all = document.querySelectorAll('body *');
        for (const el of all) {
            const r = el.getBoundingClientRect();
            const st = window.getComputedStyle(el);
            const visible = r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden';
            if (!visible) continue;
            // Only leaf-ish elements: skip if a child holds the same text (avoid dup ancestors).
            const txt = (el.innerText || '').trim();
            if (!txt || txt.length > 120) continue;
            if (NEEDLE.test(txt)) {
                hits.push({
                    tag: el.tagName.toLowerCase(),
                    cls: (el.className && el.className.toString()) || '',
                    id: el.id || '',
                    text: txt,
                });
            }
        }
        // Dedup by (tag,cls,text) and prefer the innermost (shortest text) matches.
        const seen = new Set();
        const uniq = [];
        for (const h of hits.sort((a,b) => a.text.length - b.text.length)) {
            const k = h.tag + '|' + h.cls + '|' + h.text;
            if (!seen.has(k)) { seen.add(k); uniq.push(h); }
        }
        return {area_len: areaHtml.length, area_html: areaHtml.slice(0, 8000), hits: uniq.slice(0, 8)};
    }""")
    print(f"    no-result text matches found: {len(info['hits'])}")
    for h in info['hits']:
        print(f"      <{h['tag']}> class={repr(h['cls'])[:70]}")
        print(f"           id={repr(h['id'])[:70]}")
        print(f"           text={repr(h['text'])}")
    path = output_dir / f"nodata_probe_{tag}.html"
    path.write_text(info['area_html'], encoding="utf-8")
    print(f"    tab-page HTML ({info['area_len']} bytes total) saved: {path}")


async def _probe(tenant, workshops):
    from pathlib import Path
    cfg = load_tenant_config(tenant, "config/settings.yaml")
    output_dir = Path(cfg["outputs"]["logs_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    ok_ws, fail_ws = workshops[0], workshops[1]

    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context(storage_state=cfg["datasphere"]["session_file"])
        page = await context.new_page()

        print(f"\n[probe] Tenant: {tenant.upper()} — READ ONLY, no deletions")

        # --- 1. fresh nav baseline ---
        print("\n[STEP 1] Fresh navigation to Space Management (baseline)")
        await navigate_to_space_management(page, cfg)
        await _report(page, "after fresh nav")

        # --- 2. search the workshop that swept OK ---
        print(f"\n[STEP 2] Search '{ok_ws}' (this one swept OK in the live run)")
        await _search(page, ok_ws)
        await _report(page, f"after search {ok_ws}")
        await _dump_nodata_html(page, f"{tenant}_{ok_ws}", output_dir)

        # --- 3. re-navigate, then search the workshop that FAILED ---
        print(f"\n[STEP 3] Re-navigate, then search '{fail_ws}' (this one raised the abort)")
        await navigate_to_space_management(page, cfg)
        base_no_data, base_tiles = await _report(page, "after re-nav (this is prev_ids for step 3)")
        await _search(page, fail_ws)
        after_no_data, after_tiles = await _report(page, f"after search {fail_ws}")
        changed = (after_no_data if isinstance(after_no_data, int) else 0) > 0 or after_tiles != base_tiles
        print(f"    >>> guard condition (no_data>0 OR tiles changed): {changed}")
        await _dump_nodata_html(page, f"{tenant}_{fail_ws}_step3", output_dir)

        # --- 4. THE TRIGGER: search the same no-result workshop AGAIN, no re-nav ---
        print(f"\n[STEP 4] WITHOUT re-navigating, search '{fail_ws}' AGAIN (empty -> empty case)")
        prev_no_data, prev_tiles = await _report(page, "prev_ids captured for step 4")
        await _search(page, fail_ws)
        now_no_data, now_tiles = await _report(page, f"after 2nd search {fail_ws}")
        changed4 = (now_no_data if isinstance(now_no_data, int) else 0) > 0 or now_tiles != prev_tiles
        print(f"    >>> guard condition (no_data>0 OR tiles changed): {changed4}")
        print("    >>> if this is False, that is the bug: empty->empty cannot satisfy the guard")
        await _dump_nodata_html(page, f"{tenant}_{fail_ws}_step4", output_dir)

        # --- 5. CONTROL: search a workshop KNOWN to have spaces ---
        # Disambiguates "genuinely empty" from "_current_tile_ids selector misses results".
        # If this returns tiles, the tile-reading is trustworthy and empties above are real.
        # If this returns 0, the search-result grid is rendered differently than the default
        # grid and the sweep would silently skip populated workshops — a completeness failure.
        pop_ws = "99557"
        print(f"\n[STEP 5] CONTROL: re-navigate, then search '{pop_ws}' (KNOWN to have spaces)")
        await navigate_to_space_management(page, cfg)
        await _report(page, "after re-nav (baseline)")
        await _search(page, pop_ws)
        await _report(page, f"after search {pop_ws} — EXPECT tiles if reading is correct")
        # Read the raw tile identifiers directly, exactly as the sweep does.
        raw = await page.evaluate("""() => Array.from(
            document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]')
        ).map(el => (el.innerText || '').trim())""")
        print(f"    raw spaceTileHeader-identifier-txt values ({len(raw)}): {raw[:15]}"
              + (" ..." if len(raw) > 15 else ""))
        await _dump_nodata_html(page, f"{tenant}_{pop_ws}_step5", output_dir)

        # --- 6. RENAMED-SPACE workshop: 279401 (~25 POOL_XA_* renamed spaces) ---
        # This workshop fail-closed the sweep with "never settled". Two possible causes:
        #   (a) TIMING: ~25 tiles stream in over >15s, so two consecutive _current_tile_ids
        #       reads are never equal (set keeps growing) -> never settles.
        #   (b) MATCH FAILURE: identifier-txt holds the RENAMED headline (POOL_XA_*), which
        #       does NOT match ^(AC|GE)279401..., so the "at least one tile matches" settle
        #       condition is never satisfied even though the spaces are present.
        # We distinguish by dumping BOTH what _current_tile_ids sees (identifier-txt) AND the
        # per-card texts the card-reader uses (where the real AC/GE user ID lives), plus a
        # stability trace over ~15s so we can see whether the count is still growing.
        rn_ws = "279401"
        print(f"\n[STEP 6] RENAMED-SPACE workshop '{rn_ws}' (fail-closed in the live sweep)")
        await navigate_to_space_management(page, cfg)
        await _report(page, "after re-nav (baseline)")
        await _search(page, rn_ws)

        # Stability trace: read identifier-txt every 1s for 16s, show if the set is growing.
        print("    stability trace (identifier-txt count per second):")
        prev = None
        for sec in range(16):
            ids = await page.evaluate("""() => Array.from(
                document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]')
            ).map(el => (el.innerText || '').trim()).filter(Boolean)""")
            marker = "  (stable vs prev)" if prev is not None and set(ids) == set(prev) else ""
            print(f"      t+{sec:2d}s: {len(ids)} tiles{marker}")
            prev = ids
            await asyncio.sleep(1.0)

        # Final snapshot: identifier-txt values AND the per-card texts (real user IDs).
        final_ids = await page.evaluate("""() => Array.from(
            document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]')
        ).map(el => (el.innerText || '').trim())""")
        print(f"\n    identifier-txt values ({len(final_ids)}) — what _current_tile_ids/guard sees:")
        for v in final_ids[:30]:
            print(f"      {repr(v)}")

        card_texts = await page.evaluate("""() => {
            const ids = document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]');
            const out = [];
            ids.forEach(idEl => {
                let card = idEl;
                while (card && card.tagName !== 'BODY') {
                    if (card.className && card.className.toString().includes('sapFCard')) break;
                    card = card.parentElement;
                }
                const texts = [];
                if (card) {
                    card.querySelectorAll('[id]').forEach(el => {
                        if (el.children.length === 0) {
                            const t = (el.innerText || '').trim();
                            if (t) texts.push(t);
                        }
                    });
                }
                out.push({headline: idEl.innerText.trim(), texts: texts});
            });
            return out;
        }""")
        print(f"\n    per-card real texts ({len(card_texts)}) — where the AC/GE user ID lives:")
        for c in card_texts[:8]:
            print(f"      headline={repr(c['headline'])}  texts={c['texts']}")
        if len(card_texts) > 8:
            print(f"      ... ({len(card_texts) - 8} more cards)")

        # --- 7. NO-ENTER search test on 279401 ---
        # Confirmed live: with the current fill->End->Enter->Escape sequence, ENTER selects
        # the highlighted autocomplete item (e.g. 'AC250761U00') instead of submitting the
        # raw workshop number — the picked item sits in the search box and the grid never
        # settles. Hypothesis: SAP LIVE-FILTERS the grid as you type, so Enter is unnecessary
        # and harmful. This step types the workshop, presses ONLY Escape (no Enter), and
        # reports (a) the search box value and (b) whether the grid filtered to this
        # workshop's cards. If it did, removing Enter is the fix.
        print(f"\n[STEP 7] NO-ENTER test on '{rn_ws}' (type -> Escape only, no Enter)")
        await navigate_to_space_management(page, cfg)
        sb = page.locator(_SPACE_MGMT_SEARCHBOX).first
        await sb.wait_for(state="visible", timeout=_WAIT_TIMEOUT)
        await sb.click()
        await sb.fill("")
        await sb.fill(rn_ws)
        await sb.press("End")
        # NO Enter. Just dismiss the autocomplete overlay.
        await page.keyboard.press("Escape")
        # Give the live filter time to apply, then wait for busy overlay to clear.
        try:
            await page.wait_for_selector(
                ".sapUiLocalBusyIndicator, .sapUiBlockLayerTabbable",
                state="hidden", timeout=15000,
            )
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(2.0)  # let live-filter settle

        box_val = await sb.input_value()
        print(f"    search box value after type+Escape (no Enter): {repr(box_val)}")
        print(f"    (expect {repr(rn_ws)}; if it's a space ID the dropdown was still hijacked)")
        ne_ids = await page.evaluate("""() => Array.from(
            document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]')
        ).map(el => (el.innerText || '').trim())""")
        ne_cards = await page.evaluate("""() => {
            const ids = document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]');
            const out = [];
            ids.forEach(idEl => {
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
        matched = sum(1 for texts in ne_cards for t in texts if t.startswith("AC" + rn_ws) or t == "GE" + rn_ws)
        print(f"    grid tiles after no-Enter search: {len(ne_ids)}")
        print(f"    cards carrying AC{rn_ws}.. user IDs: {matched}")
        print(f"    >>> if grid shows ~25 tiles and matched>0, removing Enter is the fix")
        print(f"    >>> if grid shows the default 25 unrelated tiles (matched==0), typing alone")
        print(f"        does NOT filter and a different submit mechanism is needed")

        input("\nPress Enter to close the browser...")
        await browser.close()
        print("[probe] Done.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="ap11")
    parser.add_argument("--workshops", nargs=2, default=["233717", "234287"],
                        metavar=("OK_WORKSHOP", "FAILED_WORKSHOP"))
    args = parser.parse_args()
    asyncio.run(_probe(args.tenant, args.workshops))


if __name__ == "__main__":
    main()
