import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from src.datasphere_client import DeleteResult
from src.logging_setup import get_logger

logger = get_logger("report")

_KNOWN_OUTCOMES = {"deleted", "not_found", "skipped_allowlist", "skipped_dry_run", "failed"}


def generate_report(
    results: List[DeleteResult],
    run_id: str,
    reports_dir: str,
    dry_run: bool
) -> str:
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    report_path = Path(reports_dir) / f"report_{run_id}.json"

    counts: dict = {k: 0 for k in _KNOWN_OUTCOMES}
    for r in results:
        if r.outcome not in _KNOWN_OUTCOMES:
            logger.warning(f"Unknown outcome '{r.outcome}' for {r.user_id}/{r.space_id}")
        counts[r.outcome] = counts.get(r.outcome, 0) + 1

    report = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "summary": {
            "total_users_processed": len({r.user_id for r in results}),
            "total_spaces_attempted": len(results),
            **counts,
        },
        "results": [
            {
                "user_id":  r.user_id,
                "space_id": r.space_id,
                "outcome":  r.outcome,
                "error":    r.error,
            }
            for r in results
        ],
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Report written to {report_path}")
    logger.info(
        f"Summary — users: {report['summary']['total_users_processed']}, "
        f"spaces attempted: {report['summary']['total_spaces_attempted']}, "
        f"deleted: {counts['deleted']}, not_found: {counts['not_found']}, "
        f"skipped_allowlist: {counts['skipped_allowlist']}, "
        f"skipped_dry_run: {counts['skipped_dry_run']}, "
        f"failed: {counts['failed']}"
    )
    return str(report_path)
