import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from src.config import load_tenant_config
from src.logging_setup import setup_logging, get_logger


def parse_args():
    parser = argparse.ArgumentParser(
        description="SAP Datasphere Trial Cleanup Automation"
    )
    parser.add_argument("--stage1", action="store_true", help="Run Stage 1: portal discovery")
    parser.add_argument("--stage2", action="store_true", help="Run Stage 2: space deletion")
    parser.add_argument("--stage3", action="store_true", help="Run Stage 3: verification")
    parser.add_argument("--stage4", action="store_true", help="Run Stage 4: permanently purge recycle bin spaces deleted by this pipeline (>= 7 days old)")
    parser.add_argument("--max-purge", type=int, default=0, metavar="N", dest="max_purge", help="Stage 4: stop after N spaces purged (0 = no limit)")
    parser.add_argument("--all", action="store_true", help="Run all stages end-to-end")
    parser.add_argument("--report", type=str, help="Report file to verify (for Stage 3)")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Second safety gate: must be set alongside dry_run=false in config to perform real deletions"
    )
    parser.add_argument("--sign-in", action="store_true", dest="sign_in", help="Save portal session for codegen")
    parser.add_argument("--sign-in-datasphere", action="store_true", dest="sign_in_datasphere", help="Save Datasphere session for codegen")
    parser.add_argument("--workshop", type=str, metavar="ID", help="Scrape a single workshop by ID and add its users to the pending queue")
    parser.add_argument("--search-term", type=str, dest="search_term", choices=["overview", "integration", "basic_trial"],
                        help="Portal search term for Stage 1 / --workshop: 'overview' = SAP Datasphere Overview (config default), 'integration' = SAP Analytics Cloud Planning and Datasphere Integration, 'basic_trial' = Basic Trial - Introduction to SAP Analytics Cloud")
    parser.add_argument("--start-date-from", type=str, dest="start_date_from", metavar="YYYY-MM-DD",
                        help="Planned start workshop date range — From (applied only if --start-date-to is also set)")
    parser.add_argument("--start-date-to", type=str, dest="start_date_to", metavar="YYYY-MM-DD",
                        help="Planned start workshop date range — To (applied only if --start-date-from is also set)")
    parser.add_argument("--end-date-from", type=str, dest="end_date_from", metavar="YYYY-MM-DD",
                        help="Planned end workshop date range — From (applied only if --end-date-to is also set)")
    parser.add_argument("--end-date-to", type=str, dest="end_date_to", metavar="YYYY-MM-DD",
                        help="Planned end workshop date range — To (applied only if --end-date-from is also set)")
    parser.add_argument("--tenant", type=str, default="eu10", choices=["eu10", "us10", "ap11", "ap11_2", "eu10_2", "us10_2"],
                        help="Tenant to operate on (default: eu10)")
    parser.add_argument("--config", type=str, default="config/settings.yaml", help="Path to settings.yaml")
    return parser.parse_args()


def _wait_for_approval():
    approval_file = Path("outputs/APPROVE_DELETION")
    print("\n" + "="*60)
    print("Stage 1 complete. Review the user list before proceeding.")
    print(f"When ready, run:  touch {approval_file}")
    print("="*60)
    print("Waiting for approval file...", end="", flush=True)
    while not approval_file.exists():
        time.sleep(3)
        print(".", end="", flush=True)
    print(" approved.")
    approval_file.unlink()


def main():
    args = parse_args()
    run_id = f"{args.tenant}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    cfg = load_tenant_config(tenant=args.tenant, settings_path=args.config)
    logger = setup_logging(logs_dir=cfg["outputs"]["logs_dir"], run_id=run_id)

    if args.search_term:
        from src.portal_client import SEARCH_TERMS
        cfg["portal"]["search_term"] = SEARCH_TERMS[args.search_term]
        logger.info(f"Portal search term overridden — {args.search_term!r} → {cfg['portal']['search_term']!r}")

    # Date range overrides — Start date and End date are independent; each range is applied
    # by the portal scrape only when both its From and To are set (see _go_to_filtered_list).
    for _key in ("start_date_from", "start_date_to", "end_date_from", "end_date_to"):
        _val = getattr(args, _key, None)
        if _val:
            cfg["portal"][_key] = _val
            logger.info(f"Portal {_key} overridden — {_val!r}")

    dry_run = cfg.get("dry_run", True)
    live = not dry_run and args.execute

    if not dry_run and not args.execute:
        logger.warning("Config has dry_run=false but --execute was not passed — running as dry-run")

    logger.info(f"datasphere-cleanup starting — run_id={run_id}")
    logger.info(f"dry_run={dry_run}, --execute={args.execute}, live_deletions={live}")

    if not live:
        logger.info("DRY-RUN MODE: no deletions will be performed")

    # --- Sign-in ---
    if args.sign_in:
        import asyncio
        from src.auth import save_portal_session
        asyncio.run(save_portal_session(cfg))
        sys.exit(0)

    if args.sign_in_datasphere:
        import asyncio
        from src.auth import save_datasphere_session
        asyncio.run(save_datasphere_session(cfg))
        sys.exit(0)

    # --- Workshop Scrape ---
    if args.workshop:
        from src.stage1_discovery import run_workshop_scrape
        logger.info(f"Workshop scrape starting — workshop_id={args.workshop}")
        run_workshop_scrape(workshop_id=args.workshop, cfg=cfg, run_id=run_id)
        logger.info(f"Workshop {args.workshop} queued for sweep")

    # --- Stage 1 ---
    if args.stage1 or args.all:
        from src.stage1_discovery import run_stage1
        logger.info("Stage 1 starting — portal scrape")
        run_stage1(cfg=cfg, run_id=run_id)
        logger.info("Stage 1 complete")
        if args.all:
            _wait_for_approval()

    # --- Stage 2 ---
    stage2_report = None
    if args.stage2 or args.all:
        from src.report import generate_report
        from src.stage2_deletion import run_stage2_workshops
        logger.info(f"Stage 2 (workshop-sweep) starting — dry_run={dry_run}, live={live}")
        results = run_stage2_workshops(cfg=cfg, dry_run=not live, run_id=run_id)
        stage2_report = generate_report(
            results=results,
            run_id=run_id,
            reports_dir=cfg["outputs"]["reports_dir"],
            dry_run=not live,
        )
        logger.info(f"Stage 2 complete — report at {stage2_report}")

    # --- Stage 3 ---
    if args.stage3 or args.all:
        report_file = args.report or stage2_report
        if not report_file:
            logger.error("--stage3 requires --report <report_file> (or run after --stage2 / --all)")
            sys.exit(1)

        from src.stage3_verify import run_stage3
        logger.info(f"Stage 3 starting — verifying report: {report_file}")
        verification_path = run_stage3(report_path=report_file, cfg=cfg, run_id=run_id)
        logger.info(f"Stage 3 complete — verification report at {verification_path}")

    # --- Stage 4 ---
    if args.stage4:
        from src.stage4_purge import run_stage4
        logger.info("Stage 4 starting — recycle bin purge")
        results = run_stage4(cfg=cfg, dry_run=not live, run_id=run_id, max_purge=args.max_purge)
        purged  = sum(1 for r in results if r.outcome == "purged")
        failed  = sum(1 for r in results if r.outcome == "failed")
        logger.info(f"Stage 4 complete — {purged} purged, {failed} failed")

    if not any([args.stage1, args.stage2, args.stage3, args.stage4, args.all, args.workshop, args.sign_in, args.sign_in_datasphere]):
        logger.warning("No stage specified. Use --stage1, --stage2, --stage3, --stage4, --all, or --sign-in")
        sys.exit(1)


if __name__ == "__main__":
    main()
