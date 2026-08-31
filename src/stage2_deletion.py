import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Set
from playwright.async_api import async_playwright

from src.auth import open_browser
from src.datasphere_client import (
    navigate_to_space_management,
    find_workshop_spaces,
    delete_workshop_spaces,
    DeleteResult,
)
from src.portal_client import (
    load_pending_workshops,
    mark_workshop_processed,
    _pending_workshops_path,
)
from src.logging_setup import get_logger

logger = get_logger("stage2")

DELETED_LOG = "outputs/user_lists/deleted.txt"


def _deleted_path(cfg):
    return cfg.get("outputs", {}).get("deleted_file", DELETED_LOG)


def _batch_remove_from_pending_workshops(workshop_ids: set, cfg=None):
    """Remove swept workshop IDs from pending_workshops_<tenant>.txt in one pass."""
    if not workshop_ids:
        return
    path = Path(_pending_workshops_path(cfg))
    if not path.exists():
        return
    ids = {w.strip() for w in workshop_ids}
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_content = "".join(l for l in lines if l.strip() not in ids)
    tmp = path.with_suffix(".ws_tmp")
    tmp.write_text(new_content, encoding="utf-8")
    os.replace(tmp, path)


def load_allowlist(allowlist_file: str) -> Set[str]:
    path = Path(allowlist_file)
    if not path.exists():
        return set()
    entries = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            entry = line.strip()
            if entry and not entry.startswith("#"):
                entries.add(entry)
    logger.info(f"Allowlist loaded: {len(entries)} protected space(s)")
    return entries


def append_deleted_log(space_id: str, cfg=None):
    p = Path(_deleted_path(cfg) if (cfg is not None and cfg.get("outputs", {}).get("deleted_file")) else DELETED_LOG)
    p.parent.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{space_id} {date_str}\n")


def _check_circuit_breaker(results: List[DeleteResult], cfg: dict):
    cb = cfg["circuit_breaker"]
    min_attempts = cb["min_attempts_before_trigger"]
    threshold    = cb["failure_rate_threshold"]

    attempted = [r for r in results
                 if r.outcome not in ("skipped_dry_run", "skipped_allowlist", "not_found")]
    if len(attempted) < min_attempts:
        return

    failures = sum(1 for r in attempted if r.outcome == "failed")
    rate = failures / len(attempted)
    if rate > threshold:
        raise RuntimeError(
            f"Circuit breaker triggered: failure rate {rate:.0%} exceeds threshold "
            f"{threshold:.0%} ({failures}/{len(attempted)} attempts failed)"
        )


async def _run_stage2_workshops_async(cfg: dict, dry_run: bool, run_id: str, progress_callback: Optional[Callable[[str], None]] = None) -> List[DeleteResult]:
    """Workshop-sweep Stage 2: iterate the pending-workshops queue, and for each workshop
    search Datasphere by workshop number, validate + bulk-delete ALL its spaces in one pass.

    Safety: allowlist enforced per space, per-space logging to deleted.txt,
    per-workshop circuit breaker, dedup against already-swept workshops.
    dry_run is honored end-to-end (no clicks)."""
    workshops = sorted(load_pending_workshops(cfg))
    if not workshops:
        logger.info("Pending-workshops queue is empty — nothing to sweep. Run Stage 1 first.")
        return []
    logger.info(f"Loaded {len(workshops)} workshop(s) from pending-workshops queue")

    max_deletions = cfg.get("limits", {}).get("max_deletions", 0)
    allowlist          = load_allowlist(cfg["outputs"]["allowlist_file"])

    all_results: List[DeleteResult] = []
    deletion_count = 0
    swept_to_remove: Set[str] = set()

    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context(storage_state=cfg["datasphere"]["session_file"])
        page    = await context.new_page()

        try:
            await navigate_to_space_management(page, cfg)
            circuit_tripped = False

            for i, workshop in enumerate(workshops, start=1):
                if max_deletions and max_deletions > 0 and deletion_count >= max_deletions:
                    logger.info(f"max_deletions limit ({max_deletions}) reached — stopping run")
                    break

                logger.info(f"Sweeping workshop {i}/{len(workshops)}: {workshop}")

                cards = await find_workshop_spaces(page, workshop, cfg=cfg)

                if not cards:
                    logger.info(f"workshop {workshop}: no spaces found — marking swept")
                    mark_workshop_processed(workshop, cfg)
                    swept_to_remove.add(workshop)
                    # Re-navigate so the next workshop search starts clean.
                    await navigate_to_space_management(page, cfg)
                    continue

                results = await delete_workshop_spaces(page, workshop, cards, cfg, dry_run, allowlist=allowlist)
                all_results.extend(results)

                any_deleted = any(r.outcome == "deleted" for r in results)
                all_done    = all(r.outcome in ("deleted", "skipped_dry_run", "skipped_allowlist") for r in results)

                if all_done:
                    if any_deleted:
                        deletion_count += sum(1 for r in results if r.outcome == "deleted")
                        for r in results:
                            if r.outcome == "deleted":
                                append_deleted_log(r.space_id, cfg)
                    # Mark swept on success (deleted or fully dry-run/allowlist).
                    # dry-run: leave in queue so the live run sweeps it for real.
                    if not dry_run:
                        mark_workshop_processed(workshop, cfg)
                        swept_to_remove.add(workshop)
                else:
                    logger.warning(
                        f"workshop {workshop}: {sum(1 for r in results if r.outcome == 'failed')} "
                        f"space(s) failed — will retry next run"
                    )
                try:
                    _check_circuit_breaker(all_results, cfg)
                except RuntimeError as exc:
                    logger.error(str(exc))
                    circuit_tripped = True
                    break

                # Re-navigate to a clean Space Management before the next workshop search.
                await navigate_to_space_management(page, cfg)

                if progress_callback is not None:
                    d  = sum(1 for r in all_results if r.outcome == "deleted")
                    fa = sum(1 for r in all_results if r.outcome == "failed")
                    sk = sum(1 for r in all_results if r.outcome == "skipped_dry_run")
                    progress_callback(
                        f"Stage 2: workshop {i}/{len(workshops)} — "
                        + (f"{sk} would delete | {fa} failed" if dry_run
                           else f"{d} deleted | {fa} failed")
                    )

        finally:
            await browser.close()
            if swept_to_remove:
                _batch_remove_from_pending_workshops(swept_to_remove, cfg)
                logger.debug(f"Removed {len(swept_to_remove)} workshop(s) from pending-workshops queue")

    if circuit_tripped:
        logger.warning("Run terminated early by circuit breaker")

    return all_results


def run_stage2_workshops(cfg: dict, dry_run: bool, run_id: str, progress_callback: Optional[Callable[[str], None]] = None) -> List[DeleteResult]:
    """Workshop-sweep Stage 2 (primary model). Sweeps every workshop in the
    pending-workshops queue: one search + one bulk delete per workshop."""
    return asyncio.run(_run_stage2_workshops_async(cfg, dry_run, run_id, progress_callback))
