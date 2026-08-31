"""
Datasphere workshop-ID bulk-delete probe (READ-ONLY up to the confirm dialog).

Captures the DOM the new workshop-sweep model needs:
  1. Result rows for a WORKSHOP-NUMBER search (headline + subheading per row)
  2. Per-row selection checkboxes
  3. The select-all control
  4. The bulk Delete button and the "type DELETE" confirm dialog

It does NOT click the final confirm — nothing is deleted. It pauses at each step
so you can inspect the live browser, and dumps HTML + a JSON summary to outputs/logs.

Usage:
    source .venv/bin/activate
    python -m src.probe_workshop_bulk --tenant ap11 --workshop 279401
"""
import asyncio
import argparse
import json
from pathlib import Path

from playwright.async_api import async_playwright

from src.config import load_tenant_config
from src.auth import open_browser


_SEARCHBOX = (
    "[id*='manageSpaces--filterSpacesInput-I'], "
    "[id*='spaceManagement'] [role='searchbox'], "
    "[id*='managespaces'] input[type='search']"
)


async def _probe(tenant: str, workshop: str):
    cfg = load_tenant_config(tenant, "config/settings.yaml")
    base_url     = cfg["datasphere"]["base_url"].rstrip("/")
    session_file = cfg["datasphere"]["session_file"]
    space_mgmt   = base_url + cfg["datasphere"]["space_management_path"]
    out_dir      = Path(cfg["outputs"]["logs_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context(storage_state=session_file)
        page = await context.new_page()

        print(f"\n[probe] Tenant: {tenant.upper()}  Workshop: {workshop}")
        print("[probe] Navigating to Space Management...")
        await page.goto(space_mgmt, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector(_SEARCHBOX, timeout=15000)

        searchbox = page.locator(_SEARCHBOX).first
        await searchbox.click()
        await searchbox.fill("")
        await asyncio.sleep(0.3)
        await searchbox.fill(workshop)
        await searchbox.press("End")
        await searchbox.press("Enter")
        print("[probe] Searched by workshop number. Waiting for results to settle...")
        await asyncio.sleep(3.0)

        # ── 1. Result rows: dump EVERY text element per card so we can locate the
        #      user ID (AC<workshop>Uxx). Renamed spaces show POOL_XA_* as headline;
        #      the user ID must appear somewhere in the card or the model can't validate.
        rows = await page.evaluate("""() => {
            const ids = document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]');
            const out = [];
            ids.forEach((idEl, i) => {
                let card = idEl;
                while (card && card.tagName !== 'BODY') {
                    if (card.className && card.className.toString().includes('sapFCard')) break;
                    card = card.parentElement;
                }
                // Collect every element in the card that has non-empty text, with its id suffix.
                const texts = [];
                if (card) {
                    card.querySelectorAll('[id]').forEach(el => {
                        const t = (el.innerText || '').trim();
                        if (t && t.length < 60 && el.children.length === 0) {
                            texts.push({ id_suffix: el.id.slice(-45), text: t });
                        }
                    });
                }
                const cb = card ? card.querySelector("[role='checkbox'], input[type='checkbox'], .sapMCb") : null;
                out.push({
                    index: i,
                    identifier_txt: idEl.innerText.trim(),
                    card_texts: texts,
                    has_checkbox: !!cb,
                    checkbox_id: cb ? (cb.id || '') : '',
                });
            });
            return out;
        }""")
        print(f"\n[probe] Result rows found: {len(rows)}")
        for r in rows[:5]:
            print(f"\n  --- row {r['index']}  identifier_txt={r['identifier_txt']!r}  checkbox={r['has_checkbox']}")
            for t in r['card_texts']:
                print(f"      {t['text']!r:34} id=...{t['id_suffix']}")
        if len(rows) > 5:
            print(f"  ... ({len(rows)-5} more rows; full detail in the summary JSON)")

        # ── pagination detection ──
        pager = await page.evaluate("""() => {
            const grab = (sel) => Array.from(document.querySelectorAll(sel)).slice(0,10).map(e => ({
                id: (e.id||'').slice(-45), text: (e.innerText||'').trim().slice(0,20),
                aria: e.getAttribute('aria-label')||'',
            }));
            return {
                page_buttons: grab("[id*='pagesSegmentedButton'] [role='option'], [id*='pagination'] button, [class*='sapMPaginator'] button"),
                count_text: grab("[id*='count'], [id*='Count'], [class*='sapMListInfoTBar']"),
            };
        }""")
        print(f"\n[probe] Pagination buttons: {pager['page_buttons']}")
        print(f"[probe] Count/info text:   {pager['count_text']}")

        # ── 2. Select-all control + toolbar delete button candidates ──
        controls = await page.evaluate("""() => {
            const grab = (sel) => Array.from(document.querySelectorAll(sel)).slice(0, 8).map(e => ({
                id: e.id || '', cls: (e.className||'').toString(), aria: e.getAttribute('aria-label')||'',
                text: (e.innerText||'').trim().slice(0,40),
            }));
            return {
                select_all: grab("th [role='checkbox'], .sapMListTblHeaderCell [role='checkbox'], [id*='selectAll'], [id*='SelectAll']"),
                checkboxes: grab("[role='checkbox'].sapMCb, input[type='checkbox']"),
                delete_btns: grab("[id*='deleteButton'], [id*='DeleteButton'], button[aria-label*='Delete'], [id*='physicalDeleteButton']"),
                toolbar: grab("[id*='overflowToolbar'] button, [id*='Toolbar'] button"),
            };
        }""")
        print("\n[probe] SELECT-ALL candidates:")
        for c in controls["select_all"]: print(f"  {c}")
        print("[probe] DELETE button candidates:")
        for c in controls["delete_btns"]: print(f"  {c}")
        print(f"[probe] (checkboxes seen: {len(controls['checkboxes'])}, toolbar btns: {len(controls['toolbar'])})")

        # Dump full page HTML for offline selector work
        (out_dir / f"workshop_bulk_probe_{tenant}_{workshop}_results.html").write_text(
            await page.content(), encoding="utf-8")
        (out_dir / f"workshop_bulk_probe_{tenant}_{workshop}_summary.json").write_text(
            json.dumps({"rows": rows, "controls": controls}, indent=2), encoding="utf-8")
        print(f"\n[probe] Results DOM + summary saved to {out_dir}")

        print("\n[probe] MANUAL STEP: in the browser, select all rows and click the bulk")
        print("        Delete button so the 'type DELETE' confirm dialog is OPEN.")
        print("        Do NOT confirm. Leave the dialog open.")
        input("        Press Enter here once the confirm dialog is visible...")

        dialog = await page.evaluate("""() => {
            const dlg = document.querySelector("[id*='DeleteConfirmationDialog'], [role='alertdialog'], .sapMDialog");
            if (!dlg) return null;
            const input = dlg.querySelector("input");
            const okBtn = dlg.querySelector("button[aria-label='OK'], [id*='ok'], [id*='confirm'], button.sapMDialogFooterButton");
            return {
                dialog_id: dlg.id || '',
                dialog_html: dlg.outerHTML.slice(0, 4000),
                input_id: input ? (input.id || '') : '',
                ok_id: okBtn ? (okBtn.id || '') : '',
                ok_text: okBtn ? (okBtn.innerText||'').trim() : '',
            };
        }""")
        print("\n[probe] CONFIRM DIALOG:")
        print(json.dumps(dialog, indent=2) if dialog else "  (no dialog captured)")
        if dialog:
            (out_dir / f"workshop_bulk_probe_{tenant}_{workshop}_dialog.html").write_text(
                dialog.get("dialog_html", ""), encoding="utf-8")

        input("\n[probe] Done capturing. Press Enter to CLOSE (nothing was deleted)...")
        await browser.close()
        print("[probe] Closed. No deletions performed.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="ap11", choices=["eu10", "us10", "ap11", "ap11_2", "eu10_2"])
    ap.add_argument("--workshop", required=True, help="Workshop number, e.g. 279401")
    args = ap.parse_args()
    asyncio.run(_probe(args.tenant, args.workshop))


if __name__ == "__main__":
    main()
