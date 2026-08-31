import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
from playwright.async_api import async_playwright

from src.auth import open_browser
from src.datasphere_client import navigate_to_space_management, search_and_verify_space
from src.logging_setup import get_logger

logger = get_logger("stage3")


def load_report(report_path: str) -> dict:
    path = Path(report_path)
    if not path.exists():
        raise FileNotFoundError(f"Report file not found: {report_path}")
    with open(path, encoding="utf-8") as f:
        report = json.load(f)
    if "results" not in report:
        raise ValueError(f"Report is missing 'results' key: {report_path}")
    return report


async def _run_stage3_async(report_path: str, cfg: dict, run_id: str, progress_callback: Optional[Callable[[str], None]] = None) -> str:
    report = load_report(report_path)
    deleted_results = [r for r in report["results"] if r["outcome"] == "deleted"]

    if not deleted_results:
        logger.info("No spaces marked as deleted in the report — nothing to verify")
        return _write_verification_report([], report_path, run_id, cfg)

    logger.info(f"Verifying {len(deleted_results)} deleted space(s)...")

    session_file = cfg["datasphere"]["session_file"]
    verifications = []

    async with async_playwright() as p:
        browser = await open_browser(p, headless=False)
        context = await browser.new_context(storage_state=session_file)
        page = await context.new_page()

        try:
            await navigate_to_space_management(page, cfg)

            for i, entry in enumerate(deleted_results, start=1):
                user_id  = entry["user_id"]
                space_id = entry["space_id"]

                try:
                    result = await search_and_verify_space(page, user_id, space_id)
                    still_exists = result is not None
                except Exception as exc:
                    logger.error(f"Verification check failed for {space_id} ({user_id}): {exc}")
                    try:
                        await navigate_to_space_management(page, cfg)
                    except Exception:
                        pass
                    verifications.append({
                        "user_id": user_id, "space_id": space_id,
                        "verification": "check_failed", "error": str(exc),
                    })
                    if progress_callback is not None:
                        confirmed  = sum(1 for v in verifications if v["verification"] == "confirmed_deleted")
                        still_ex   = sum(1 for v in verifications if v["verification"] == "still_exists")
                        chk_failed = sum(1 for v in verifications if v["verification"] == "check_failed")
                        progress_callback(
                            f"Stage 3: {i}/{len(deleted_results)} — "
                            f"{confirmed} confirmed | {still_ex} still exist | {chk_failed} check failed"
                        )
                    continue

                if still_exists:
                    logger.warning(f"DISCREPANCY: space {space_id} ({user_id}) still exists after reported deletion")
                    verifications.append({
                        "user_id": user_id, "space_id": space_id,
                        "verification": "still_exists", "error": None,
                    })
                else:
                    logger.info(f"Confirmed deleted: {space_id} ({user_id})")
                    verifications.append({
                        "user_id": user_id, "space_id": space_id,
                        "verification": "confirmed_deleted", "error": None,
                    })

                if progress_callback is not None:
                    confirmed  = sum(1 for v in verifications if v["verification"] == "confirmed_deleted")
                    still_ex   = sum(1 for v in verifications if v["verification"] == "still_exists")
                    chk_failed = sum(1 for v in verifications if v["verification"] == "check_failed")
                    progress_callback(
                        f"Stage 3: {i}/{len(deleted_results)} — "
                        f"{confirmed} confirmed | {still_ex} still exist | {chk_failed} check failed"
                    )
        finally:
            await browser.close()

    return _write_verification_report(verifications, report_path, run_id, cfg)


def run_stage3(report_path: str, cfg: dict, run_id: str, progress_callback: Optional[Callable[[str], None]] = None) -> str:
    return asyncio.run(_run_stage3_async(report_path, cfg, run_id, progress_callback))


def _write_verification_report(verifications: List[Dict], source_report: str, run_id: str, cfg: dict) -> str:
    reports_dir = cfg["outputs"]["reports_dir"]
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(reports_dir) / f"verification_{run_id}.json"

    counts = Counter(v["verification"] for v in verifications)
    confirmed     = counts["confirmed_deleted"]
    discrepancies = counts["still_exists"]
    check_failed  = counts["check_failed"]

    report = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_report": source_report,
        "summary": {
            "total_verified": len(verifications),
            "confirmed_deleted": confirmed,
            "still_exists": discrepancies,
            "check_failed": check_failed,
        },
        "verifications": verifications,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Verification report written to {out_path}")
    logger.info(
        f"Verification summary — confirmed: {confirmed}, "
        f"still_exists: {discrepancies}, check_failed: {check_failed}"
    )

    if discrepancies:
        logger.warning(
            f"{discrepancies} space(s) still exist after reported deletion — "
            f"review {out_path} and re-run Stage 2 for affected users"
        )

    return str(out_path)
