import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from playwright.async_api import Page, async_playwright

from src.auth import open_browser
from src.datasphere_client import space_mgmt_url, wait_for_space_mgmt_ready
from src.logging_setup import get_logger
from src.retry import backoff_from_cfg, with_retry
from src.stage2_deletion import DELETED_LOG

logger = get_logger("stage4")

_WAIT_TIMEOUT = 15000

# Side-panel row that switches to the Recycle Bin view
_RECYCLE_BIN_ROW = (
    "[data-sap-ui*='deletedSpacesListItem'], "
    "[id*='deletedSpacesListItem']"
)

# Tile container in the recycle bin
_TILE_CONTAINER = (
    "[id*='manageSpacesLandingPage--spacesContainer'], "
    "[id*='spacesContainer']"
)

# Technical space ID label on each tile
_TILE_ID_LABEL = "[id$='spaceTileHeader-identifier-txt']"

# Checkbox (outer SAPUI5 div) on each tile
_TILE_CHECKBOX = "[role='checkbox'].sapMCb"

# Permanent delete button in the toolbar
_PHYSICAL_DELETE_BTN = (
    "[id*='toolbar--physicalDeleteButton'], "
    "button[title='Delete'].sapMBtn"
)

# Permanent delete confirmation dialog selectors (stable component-scoped IDs)
_DELETE_CONFIRM_DIALOG = "[id*='DeleteConfirmationDialog--dialog']"
_DELETE_CONFIRM_INPUT  = "[id*='DeleteConfirmationDialog--dialog--view--deleteInput-inner']"
_DELETE_CONFIRM_OK     = "[id*='DeleteConfirmationDialog--dialog--view--ok']"

# Pagination segment buttons
_PAGE_BUTTONS = "[id*='pagesSegmentedButton'] [role='option']"


@dataclass
class PurgeResult:
    space_id: str
    outcome: str          # purged | skipped_age | skipped_not_ours | skipped_dry_run | failed
    error: Optional[str] = None


def load_deleted_log(min_age_days: int = 7, cfg=None) -> Dict[str, date]:
    """
    Read deleted.txt and return a dict of {space_id: deletion_date} for entries
    that are at least min_age_days old, sorted oldest-first so callers that apply
    a max_purge limit naturally process the oldest spaces first.
    """
    if cfg is not None:
        from src.stage2_deletion import _deleted_path
        log_path = _deleted_path(cfg)
    else:
        log_path = DELETED_LOG
    path = Path(log_path)
    if not path.exists():
        return {}

    cutoff = datetime.now(timezone.utc).date()
    eligible: Dict[str, date] = {}

    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) != 2:
                continue
            space_id, date_str = parts[0], parts[1]
            try:
                deleted_on = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                logger.warning(f"Skipping malformed date in deleted.txt: {line.strip()!r}")
                continue
            age_days = (cutoff - deleted_on).days
            if age_days >= min_age_days:
                key = space_id.upper()
                if key not in eligible or deleted_on < eligible[key]:
                    eligible[key] = deleted_on

    # Sort oldest-first so a max_purge limit always targets the longest-waiting spaces
    eligible = dict(sorted(eligible.items(), key=lambda kv: kv[1]))

    logger.info(
        f"deleted.txt: {len(eligible)} space(s) eligible for purge "
        f"(age >= {min_age_days} days)"
    )
    return eligible


def load_still_exists_exclusions(cfg=None) -> Set[str]:
    """Return the set of space IDs (upper-cased) that any Stage 3 verification report
    marked as 'still_exists'.

    Stage 2 appends a space to deleted.txt the moment it records outcome='deleted' —
    BEFORE Stage 3 verifies the server-side deletion actually happened. If Stage 3 later
    finds the space still exists (the delete failed/rolled back), the deleted.txt entry is
    stale but is never removed automatically. Without this exclusion, Stage 4 would treat
    that space as eligible and could PERMANENTLY purge a space that was never actually
    deleted by this pipeline. We therefore cross-check every verification report and refuse
    to purge anything a verification flagged as still_exists. Fail-safe: any unreadable
    report is skipped with a warning (it cannot silently drop an exclusion — a missing
    report just means no exclusions from it, and the age/deleted.txt gates still apply)."""
    import json
    if cfg is not None:
        reports_dir = cfg.get("outputs", {}).get("reports_dir", "outputs/reports")
    else:
        reports_dir = "outputs/reports"
    d = Path(reports_dir)
    if not d.exists():
        return set()
    excluded: Set[str] = set()
    for report_file in d.glob("verification_*.json"):
        try:
            with open(report_file, encoding="utf-8") as f:
                data = json.load(f)
            for v in data.get("verifications", []):
                if v.get("verification") == "still_exists":
                    sid = (v.get("space_id") or "").strip().upper()
                    if sid:
                        excluded.add(sid)
        except Exception as exc:
            logger.warning(f"Could not read verification report {report_file}: {exc}")
    if excluded:
        logger.info(f"{len(excluded)} space(s) excluded from purge (Stage 3 marked still_exists)")
    return excluded


async def _navigate_to_recycle_bin(page: Page, cfg: dict):
    """Navigate to Space Management and click into the Recycle Bin tab."""
    backoff = backoff_from_cfg(cfg)

    @with_retry(backoff)
    async def _go():
        await page.goto(space_mgmt_url(cfg), wait_until="domcontentloaded", timeout=30000)
        await wait_for_space_mgmt_ready(page)

    await _go()

    await page.wait_for_selector(_RECYCLE_BIN_ROW, timeout=_WAIT_TIMEOUT)
    await page.locator(_RECYCLE_BIN_ROW).first.click()

    # Wait for tiles to appear — recycle bin may be empty, so treat timeout as
    # "no tiles" rather than a hard error (caller checks tile count)
    try:
        await page.wait_for_selector(_TILE_ID_LABEL, timeout=_WAIT_TIMEOUT)
    except Exception:
        pass
    logger.info("Navigated to Recycle Bin")


async def _get_page_count(page: Page) -> int:
    """Return the number of pagination buttons (1 if no paginator present)."""
    try:
        await page.wait_for_selector(_PAGE_BUTTONS, timeout=3000)
        return await page.locator(_PAGE_BUTTONS).count()
    except Exception:
        return 1


async def _go_to_page(page: Page, page_index: int):
    """Click the nth pagination button (0-indexed)."""
    btn = page.locator(_PAGE_BUTTONS).nth(page_index)
    await btn.click()
    await page.wait_for_selector(_TILE_ID_LABEL, timeout=_WAIT_TIMEOUT)
    await asyncio.sleep(0.5)  # allow SAPUI5 virtual scroll to settle


async def _collect_tile_ids(page: Page) -> List[str]:
    """Return technical space IDs for all tiles currently visible on the page."""
    ids = []
    for el in await page.locator(_TILE_ID_LABEL).all():
        text = (await el.inner_text()).strip().upper()
        if text:
            ids.append(text)
    return ids


async def _select_tile(page: Page, space_id: str):
    """Click the checkbox for the tile whose technical ID matches space_id.

    Uses Playwright's native click (real pointer events) rather than a JS
    .click() — SAPUI5 checkboxes only respond to real pointer events, not
    synthetic JS clicks, so JS-based selection leaves the toolbar Delete
    button disabled.
    """
    # Find the container index N from the identifier-txt element whose text matches
    container_n = await page.evaluate("""(spaceId) => {
        const labels = Array.from(
            document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]')
        );
        const label = labels.find(
            el => el.innerText.trim().toUpperCase() === spaceId.toUpperCase()
        );
        if (!label) return null;
        const m = label.id.match(/spacesContainer-(\\d+)--/);
        return m ? m[1] : null;
    }""", space_id)

    if container_n is None:
        raise RuntimeError(f"Could not find tile for space_id={space_id}")

    # Click the checkbox using Playwright's native pointer events
    cb = page.locator(f"[id*='spacesContainer-{container_n}-'] {_TILE_CHECKBOX}").first
    await cb.wait_for(state="visible", timeout=_WAIT_TIMEOUT)
    await cb.click()
    logger.debug(f"Selected tile: {space_id}")


async def _click_permanent_delete(page: Page, dry_run: bool) -> bool:
    """
    Click the physical delete button, type DELETE in the confirmation input,
    and click the OK button. Returns True on success, False if the dialog
    didn't appear or the confirmation failed.
    """
    if dry_run:
        logger.info("[DRY-RUN] Would click permanent delete button")
        return True

    delete_btn = page.locator(_PHYSICAL_DELETE_BTN).first
    await delete_btn.wait_for(state="visible", timeout=_WAIT_TIMEOUT)
    await delete_btn.click()

    try:
        await page.wait_for_selector(_DELETE_CONFIRM_DIALOG, state="visible", timeout=_WAIT_TIMEOUT)
    except Exception:
        logger.error("Confirmation dialog did not appear after clicking permanent delete")
        return False

    # Type DELETE in the confirmation input
    try:
        confirm_input = page.locator(_DELETE_CONFIRM_INPUT).first
        await confirm_input.wait_for(state="visible", timeout=_WAIT_TIMEOUT)
        await confirm_input.click()
        await confirm_input.fill("DELETE")
        logger.debug("Typed DELETE in confirmation input")
    except Exception as exc:
        logger.error(f"Could not find or fill DELETE confirmation input: {exc}")
        # Press Escape to dismiss the dialog rather than leaving it open
        await page.keyboard.press("Escape")
        return False

    # Click the OK / confirm button
    ok_btn = page.locator(_DELETE_CONFIRM_OK).first
    await ok_btn.wait_for(state="visible", timeout=_WAIT_TIMEOUT)
    await ok_btn.click()

    # Wait for dialog to close
    try:
        await page.wait_for_selector(_DELETE_CONFIRM_DIALOG, state="hidden", timeout=_WAIT_TIMEOUT)
    except Exception:
        pass

    # Wait for the tile list to re-render after the purge
    try:
        await page.wait_for_selector(_TILE_ID_LABEL, timeout=_WAIT_TIMEOUT)
    except Exception:
        pass  # recycle bin may now be empty — that's a valid state

    logger.info("Permanent delete confirmed")
    return True


async def _run_stage4_async(cfg: dict, dry_run: bool, run_id: str, min_age_days: int = 7, max_purge: int = 0, progress_callback: Optional[Callable[[str], None]] = None) -> List[PurgeResult]:
    eligible = load_deleted_log(min_age_days=min_age_days, cfg=cfg)
    # Cross-check Stage 3: never purge a space a verification flagged as still_exists
    # (its deleted.txt entry is stale — the delete didn't actually take).
    excluded = load_still_exists_exclusions(cfg=cfg)
    if excluded:
        before = len(eligible)
        eligible = {sid: d for sid, d in eligible.items() if sid not in excluded}
        removed = before - len(eligible)
        if removed:
            logger.warning(
                f"Excluded {removed} space(s) from purge because Stage 3 verification "
                f"reported them as still_exists (stale deleted.txt entries)"
            )
    if not eligible:
        logger.info(
            f"No eligible spaces to purge (min_age={min_age_days} days) — "
            "either deleted.txt is empty or all entries are too recent"
        )
        return []

    if max_purge > 0:
        logger.info(f"max_purge={max_purge} — will stop after {max_purge} space(s)")

    all_results: List[PurgeResult] = []

    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context(storage_state=cfg["datasphere"]["session_file"])
        page = await context.new_page()

        try:
            await _navigate_to_recycle_bin(page, cfg)

            purged_ids:  Set[str] = set()
            purge_count = 0

            while True:
                if max_purge > 0 and purge_count >= max_purge:
                    logger.info(f"max_purge limit ({max_purge}) reached — stopping")
                    break

                page_count = await _get_page_count(page)
                logger.info(f"Recycle bin has {page_count} page(s) of tiles")

                found_any = False

                for page_idx in range(page_count):
                    if max_purge > 0 and purge_count >= max_purge:
                        break

                    if page_idx > 0:
                        await _go_to_page(page, page_idx)

                    tile_ids = await _collect_tile_ids(page)
                    logger.info(f"Page {page_idx + 1}/{page_count}: {len(tile_ids)} tile(s) visible")

                    to_select = [
                        tid for tid in tile_ids
                        if tid not in purged_ids
                    ]

                    if max_purge > 0:
                        to_select = to_select[:max_purge - purge_count]

                    if not to_select:
                        logger.info(f"Page {page_idx + 1}: no matching spaces — skipping")
                        continue

                    logger.info(f"Page {page_idx + 1}: selecting {len(to_select)} space(s) for purge")

                    # Select tiles — collect failures separately to avoid mutating the list mid-iteration
                    failed_ids: Set[str] = set()
                    for space_id in to_select:
                        try:
                            await _select_tile(page, space_id)
                        except Exception as exc:
                            logger.error(f"Could not select tile {space_id}: {exc}")
                            all_results.append(PurgeResult(space_id=space_id, outcome="failed", error=str(exc)))
                            failed_ids.add(space_id)

                    confirmed = [s for s in to_select if s not in failed_ids]
                    if not confirmed:
                        continue

                    if dry_run:
                        for space_id in confirmed:
                            logger.info(f"[DRY-RUN] Would permanently delete: {space_id}")
                            all_results.append(PurgeResult(space_id=space_id, outcome="skipped_dry_run"))
                            purged_ids.add(space_id)
                            purge_count += 1
                        if progress_callback is not None:
                            dr = sum(1 for r in all_results if r.outcome == "skipped_dry_run")
                            fa = sum(1 for r in all_results if r.outcome == "failed")
                            progress_callback(
                                f"Stage 4: {purge_count} purged — {dr} would purge | {fa} failed"
                            )
                        found_any = True
                        # Deselect by re-navigating — always restart from page 0
                        await _navigate_to_recycle_bin(page, cfg)
                        break

                    success = await _click_permanent_delete(page, dry_run=False)

                    if success:
                        for space_id in confirmed:
                            logger.info(f"Permanently deleted: {space_id}")
                            all_results.append(PurgeResult(space_id=space_id, outcome="purged"))
                            purged_ids.add(space_id)
                            purge_count += 1
                        if progress_callback is not None:
                            pu = sum(1 for r in all_results if r.outcome == "purged")
                            fa = sum(1 for r in all_results if r.outcome == "failed")
                            progress_callback(
                                f"Stage 4: {purge_count} purged — {pu} purged | {fa} failed"
                            )
                        found_any = True
                        # Re-navigate to refresh tile list — always restart from page 0
                        await _navigate_to_recycle_bin(page, cfg)
                        break
                    else:
                        for space_id in confirmed:
                            all_results.append(PurgeResult(space_id=space_id, outcome="failed",
                                                            error="confirmation dialog missing"))

                # If we completed the full page loop without finding anything to purge, we're done
                if not found_any:
                    break

        finally:
            await browser.close()

    purged   = sum(1 for r in all_results if r.outcome == "purged")
    dry      = sum(1 for r in all_results if r.outcome == "skipped_dry_run")
    failed   = sum(1 for r in all_results if r.outcome == "failed")
    logger.info(
        f"Stage 4 complete — purged={purged}, dry_run={dry}, failed={failed}"
    )
    return all_results


def run_stage4(cfg: dict, dry_run: bool, run_id: str, min_age_days: int = 7, max_purge: int = 0, progress_callback: Optional[Callable[[str], None]] = None) -> List[PurgeResult]:
    return asyncio.run(_run_stage4_async(cfg, dry_run, run_id, min_age_days, max_purge, progress_callback))
