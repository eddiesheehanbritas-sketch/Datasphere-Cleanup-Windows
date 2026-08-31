import asyncio
import re
from pathlib import Path
from typing import List, Set
from playwright.async_api import Page
from src.logging_setup import get_logger
from src.retry import with_retry, backoff_from_cfg

logger = get_logger("portal_client")

PROCESSED_WORKSHOPS_LOG = "outputs/user_lists/processed_workshops.txt"
PENDING_WORKSHOPS_LOG = "outputs/user_lists/pending_workshops.txt"
BATCH_SIZE = 50

# Portal search terms — the value typed into the content-portal search bar in
# _go_to_filtered_list before the Environment/DC-Region/date filters are applied.
# "overview" is the historical default (config settings.yaml:portal.search_term);
# "integration" and "basic_trial" are alternatives selectable in the GUI / via --search-term.
SEARCH_TERM_OVERVIEW = "SAP Datasphere Overview"
SEARCH_TERM_INTEGRATION = "SAP Analytics Cloud Planning and Datasphere Integration"
SEARCH_TERM_BASIC_TRIAL = "Basic Trial - Introduction to SAP Analytics Cloud"
SEARCH_TERMS = {
    "overview": SEARCH_TERM_OVERVIEW,
    "integration": SEARCH_TERM_INTEGRATION,
    "basic_trial": SEARCH_TERM_BASIC_TRIAL,
}

_WAIT_TIMEOUT = 15000


def _workshops_path(cfg):
    return cfg.get("outputs", {}).get("processed_workshops_file", PROCESSED_WORKSHOPS_LOG)


def _pending_workshops_path(cfg):
    return cfg.get("outputs", {}).get("pending_workshops_file", PENDING_WORKSHOPS_LOG)


_SCROLL_JS = """() => {
    const el = document.querySelector('.fdp-table__body.fd-scrollbar');
    if (el) { el.scrollTop = el.scrollHeight; return el.scrollHeight; }
    return 0;
}"""

_WORKSHOP_IDS_JS = """() => {
    const links = document.querySelectorAll('a[href*="/academy-request/"], a[href*="/ge-request/"]');
    const ids = [];
    links.forEach(a => {
        const m = a.href.match(/\\/(?:academy-request|ge-request)\\/(\\d{5,7})$/);
        if (m) ids.push(m[1]);
    });
    return ids;
}"""


def load_processed_workshops(cfg=None) -> Set[str]:
    path = Path(_workshops_path(cfg) if cfg is not None else PROCESSED_WORKSHOPS_LOG)
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def mark_workshop_processed(workshop_id: str, cfg=None):
    p = _workshops_path(cfg) if cfg is not None else PROCESSED_WORKSHOPS_LOG
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{workshop_id}\n")


def load_pending_workshops(cfg=None) -> Set[str]:
    path = Path(_pending_workshops_path(cfg) if cfg is not None else PENDING_WORKSHOPS_LOG)
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip() and not line.strip().startswith("#")}


def append_pending_workshop(workshop_id: str, cfg=None,
                            _pending: Set[str] = None, _processed: Set[str] = None):
    """Append a Cleaned workshop ID to the pending-workshops queue, skipping duplicates.

    Pass _pending and _processed as pre-loaded sets to avoid re-reading both files on
    every call inside a tight loop (run_portal_scrape calls this for each scraped workshop).
    When omitted the sets are loaded from disk — safe but O(n) per call.
    """
    p = _pending_workshops_path(cfg) if cfg is not None else PENDING_WORKSHOPS_LOG
    pending   = _pending   if _pending   is not None else load_pending_workshops(cfg)
    processed = _processed if _processed is not None else load_processed_workshops(cfg)
    if workshop_id in pending or workshop_id in processed:
        return
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{workshop_id}\n")


async def _wait_for_list_ready(page: Page):
    """Wait until the requests list has rendered rows or a no-data indicator.
    Internal requests rows use /academy-request/ hrefs; Public requests use /ge-request/."""
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass  # networkidle can hang on the portal — domcontentloaded is the hard guarantee
    await page.wait_for_selector(
        "a[href*='/academy-request/'], a[href*='/ge-request/'], .sapMListNoData, [class*='noData']",
        timeout=_WAIT_TIMEOUT,
        state="attached",
    )


async def _wait_for_filter_query_settled(page: Page, prev_ids: "set" = None):
    """Block until a just-applied filter's OData query has actually returned and the
    list has re-rendered — NOT just until the toolbar chip updates.

    The SAPUI5 toolbar 'Filtered by:' chip updates synchronously when OK is clicked,
    but the row set only updates when the background query returns. Reading rows (or
    verifying filters via the chip) before the query settles scrapes the STALE
    pre-filter result set — the root cause of active workshops being scraped despite
    the chip showing 'Cleaned'.

    Two layers:
    1. Best-effort: wait for the SAPUI5 busy overlay to appear then clear, then
       networkidle. Mirrors the proven post-navigation wait in datasphere_client.py.
    2. HARD confirmation (only when prev_ids is provided): after the best-effort waits,
       poll until the visible workshop-ID set actually DIFFERS from prev_ids (the
       pre-filter set) or a no-data indicator is shown. Applying an Environment/region
       filter always changes the result set, so if the ids are still identical the query
       has NOT returned yet. This does not trust overlay timing or class names — it
       observes the rows themselves. Raises RuntimeError (SAFETY ABORT) if the rows never
       change within the timeout, so we fail CLOSED rather than scrape stale rows."""
    # Best-effort overlay + networkidle. A busy overlay may take a beat to appear after
    # the OK click; give it a moment so we don't race past it.
    try:
        await page.wait_for_selector(
            ".sapUiLocalBusyIndicator, .sapUiBlockLayerTabbable",
            state="visible",
            timeout=2000,
        )
    except Exception:
        pass  # overlay may be too fast to catch, or already gone — fall through

    try:
        await page.wait_for_selector(
            ".sapUiLocalBusyIndicator, .sapUiBlockLayerTabbable",
            state="hidden",
            timeout=_WAIT_TIMEOUT,
        )
    except Exception:
        pass  # no busy overlay present — query likely already settled

    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass  # networkidle can hang on the SPA

    if prev_ids is None:
        return

    # HARD confirmation: the rows must actually have changed from the pre-filter set.
    _asyncio = asyncio
    deadline_steps = int(_WAIT_TIMEOUT / 500)  # poll every 500ms up to _WAIT_TIMEOUT
    for _ in range(max(deadline_steps, 1)):
        # A no-data indicator is a valid settled state (filter matched nothing).
        try:
            no_data = await page.locator(".sapMListNoData, [class*='noData']").count()
        except Exception:
            no_data = 0
        current = set(await page.evaluate(_WORKSHOP_IDS_JS))
        if no_data > 0 or current != prev_ids:
            return  # rows re-rendered — filtered query has returned
        await _asyncio.sleep(0.5)

    raise RuntimeError(
        "SAFETY ABORT: filtered result set did not change after applying the filter — "
        "the portal may still be showing the pre-filter (unfiltered) rows. Scraping halted "
        "to prevent processing active workshops."
    )


async def _verify_filters_active(page: Page, dc_region: str = "EU10", start_date_from: str = None, start_date_to: str = None, end_date_from: str = None, end_date_to: str = None, workshop_id_from: str = None, workshop_id_to: str = None):
    """
    Confirm the portal's own 'Filtered by:' toolbar shows all required filters.
    Raises RuntimeError if any is missing — callers must not proceed without this.
    The toolbar label is the portal's authoritative confirmation that filters took effect;
    checking it prevents scraping unfiltered results if a filter click silently failed.
    The Start date and End date ranges are independent — each is only required in the toolbar
    when both its From and To are set.
    """
    required = ["Environment (Cleaned)", f"Data Center Region ({dc_region})"]
    if end_date_from and end_date_to:
        required.append(f"Planned end workshop (From: {end_date_from}, To: {end_date_to})")
    if start_date_from and start_date_to:
        required.append(f"Planned start workshop (From: {start_date_from}, To: {start_date_to})")
    if workshop_id_from and workshop_id_to:
        required.append(f"Workshop ID (Min: {workshop_id_from}, Max: {workshop_id_to})")
    try:
        await page.wait_for_selector(
            "fd-toolbar[fdtype='info'] fd-label, fd-toolbar--info fd-label, "
            "[class*='applied-filters'] label, [class*='applied-filters-toolbar'] label",
            timeout=_WAIT_TIMEOUT,
        )
    except Exception:
        pass  # element may have a different selector — we check text content below regardless

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

    if not label_text:
        raise RuntimeError(
            "SAFETY ABORT: Could not find 'Filtered by:' toolbar after applying filters. "
            "The portal may be showing unfiltered results. Scraping halted to prevent "
            "processing active workshops."
        )

    missing = [f for f in required if f not in label_text]
    if missing:
        raise RuntimeError(
            f"SAFETY ABORT: Filter verification failed. "
            f"Expected filters not confirmed in toolbar: {missing}. "
            f"Toolbar text was: '{label_text}'. "
            f"Scraping halted to prevent processing active workshops."
        )

    logger.info(f"Filter verification passed: '{label_text}'")


async def _go_to_filtered_list(page: Page, base_url: str, search_term: str, dc_region: str = "EU10", start_date_from: str = None, start_date_to: str = None, end_date_from: str = None, end_date_to: str = None, requests_tree_item: str = "Internal request(s)", workshop_id_from: str = None, workshop_id_to: str = None):
    """Navigate to the requests list, search, and apply Environment: Cleaned + DC Region filter,
    and optionally independent Planned start workshop and Planned end workshop date range filters,
    and an optional Workshop ID range filter (each applied only when both its From and To are set).
    requests_tree_item controls which sidebar entry is clicked — "Internal request(s)" for all
    standard tenants, "Public request(s)" for AP11(2)."""
    await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_selector(
        f"[aria-label^='Tree Item {requests_tree_item}']",
        timeout=_WAIT_TIMEOUT,
    )
    await page.locator(f"[aria-label^='Tree Item {requests_tree_item}']").click()
    await _wait_for_list_ready(page)

    await page.wait_for_selector(
        "[role='searchbox'], input[type='search'].fdp-search-field__input",
        timeout=_WAIT_TIMEOUT,
    )
    searchbox = page.locator("[role='searchbox'], input[type='search'].fdp-search-field__input").first
    await searchbox.click()
    await searchbox.fill(search_term)
    await searchbox.press("Enter")
    await _wait_for_list_ready(page)

    # Filter 1 — Environment: Cleaned
    await page.get_by_role("button", name="Settings").click()
    await page.wait_for_selector("[role='option'][aria-label='Filter']", timeout=_WAIT_TIMEOUT)
    await page.locator("[role='option'][aria-label='Filter']").click()
    # Select the Environment row by its text — stable across SAPUI5 re-renders.
    # Never use positional #fd-list-item-N IDs here: they shift whenever SAP adds/removes
    # columns and will silently select the wrong filter or nothing at all.
    await page.wait_for_selector("li[role='listitem'] span.fd-list__title:text-is('Environment')", timeout=_WAIT_TIMEOUT)
    await page.locator("li[role='listitem'] span.fd-list__title:text-is('Environment')").click()
    # Select the Cleaned option by its text and role — stable for the same reason.
    await page.wait_for_selector("li[role='option']:has-text('Cleaned')", timeout=_WAIT_TIMEOUT)
    await page.locator("li[role='option']:has-text('Cleaned')").click()
    # Capture the pre-filter row set so _wait_for_filter_query_settled can HARD-confirm
    # the rows actually changed after the Cleaned filter applies (fail-closed if not).
    _pre_cleaned_ids = set(await page.evaluate(_WORKSHOP_IDS_JS))
    await page.get_by_role("button", name="OK").click()
    await _wait_for_filter_query_settled(page, prev_ids=_pre_cleaned_ids)
    await _wait_for_list_ready(page)

    # Filter 2 — DC Region
    await page.get_by_role("button", name="Settings").click()
    await page.wait_for_selector("[role='option'][aria-label='Filter']", timeout=_WAIT_TIMEOUT)
    await page.locator("[role='option'][aria-label='Filter']").click()
    await page.wait_for_selector("text=DC Region", timeout=_WAIT_TIMEOUT)
    await page.get_by_text("DC Region").click()
    await page.wait_for_selector(f"text={dc_region}", timeout=_WAIT_TIMEOUT)
    await page.get_by_text(dc_region).click()
    await page.get_by_role("button", name="OK").click()
    await _wait_for_filter_query_settled(page)
    await _wait_for_list_ready(page)

    logger.info(f"Applied filters: Environment=Cleaned, DC Region={dc_region}")

    # Filter 3 — End date range (optional; applied only when both ends are set)
    if end_date_from and end_date_to:
        await page.get_by_role("button", name="Settings").click()
        await page.wait_for_selector("[role='option'][aria-label='Filter']", timeout=_WAIT_TIMEOUT)
        await page.locator("[role='option'][aria-label='Filter']").click()
        await page.wait_for_selector("li[role='listitem'] span.fd-list__title:text-is('End date')", timeout=_WAIT_TIMEOUT)
        await page.locator("li[role='listitem'] span.fd-list__title:text-is('End date')").click()
        await page.wait_for_selector("fd-dialog.fd-dialog--active input[name='From'][type='date']", timeout=_WAIT_TIMEOUT)
        await page.locator("fd-dialog.fd-dialog--active input[name='From'][type='date']").fill(end_date_from)
        await page.locator("fd-dialog.fd-dialog--active input[name='To'][type='date']").fill(end_date_to)
        await page.locator("fd-dialog.fd-dialog--active button[aria-label='OK'].fd-dialog__decisive-button").click()
        await _wait_for_filter_query_settled(page)
        await _wait_for_list_ready(page)
        logger.info(f"Applied filter: End date From={end_date_from} To={end_date_to}")

    # Filter 4 — Start date range (optional; independent of the end date range)
    if start_date_from and start_date_to:
        await page.get_by_role("button", name="Settings").click()
        await page.wait_for_selector("[role='option'][aria-label='Filter']", timeout=_WAIT_TIMEOUT)
        await page.locator("[role='option'][aria-label='Filter']").click()
        await page.wait_for_selector("li[role='listitem'] span.fd-list__title:text-is('Start date')", timeout=_WAIT_TIMEOUT)
        await page.locator("li[role='listitem'] span.fd-list__title:text-is('Start date')").click()
        await page.wait_for_selector("fd-dialog.fd-dialog--active input[name='From'][type='date']", timeout=_WAIT_TIMEOUT)
        await page.locator("fd-dialog.fd-dialog--active input[name='From'][type='date']").fill(start_date_from)
        await page.locator("fd-dialog.fd-dialog--active input[name='To'][type='date']").fill(start_date_to)
        await page.locator("fd-dialog.fd-dialog--active button[aria-label='OK'].fd-dialog__decisive-button").click()
        await _wait_for_filter_query_settled(page)
        await _wait_for_list_ready(page)
        logger.info(f"Applied filter: Start date From={start_date_from} To={start_date_to}")

    # Filter 5 — Workshop ID range (optional; applied only when both ends are set)
    if workshop_id_from and workshop_id_to:
        await page.get_by_role("button", name="Settings").click()
        await page.wait_for_selector("[role='option'][aria-label='Filter']", timeout=_WAIT_TIMEOUT)
        await page.locator("[role='option'][aria-label='Filter']").click()
        await page.wait_for_selector("li[role='listitem'] span.fd-list__title:text-is('Workshop ID')", timeout=_WAIT_TIMEOUT)
        await page.locator("li[role='listitem'] span.fd-list__title:text-is('Workshop ID')").click()
        await page.wait_for_selector("fd-dialog.fd-dialog--active input[name='Min']", timeout=_WAIT_TIMEOUT)
        await page.locator("fd-dialog.fd-dialog--active input[name='Min']").fill(str(workshop_id_from))
        await page.locator("fd-dialog.fd-dialog--active input[name='Max']").fill(str(workshop_id_to))
        await page.locator("fd-dialog.fd-dialog--active button[aria-label='OK'].fd-dialog__decisive-button").click()
        await _wait_for_filter_query_settled(page)
        await _wait_for_list_ready(page)
        logger.info(f"Applied filter: Workshop ID From={workshop_id_from} To={workshop_id_to}")

    # Hard safety check — verify the portal's own 'Filtered by:' toolbar confirms all
    # filters are active before any scraping begins. Raises RuntimeError if not confirmed.
    # By this point the filtered query has settled (_wait_for_filter_query_settled above),
    # so the toolbar chip and the rendered rows agree.
    await _verify_filters_active(page, dc_region=dc_region, start_date_from=start_date_from, start_date_to=start_date_to, end_date_from=end_date_from, end_date_to=end_date_to, workshop_id_from=workshop_id_from, workshop_id_to=workshop_id_to)


async def _collect_next_batch(page: Page, scroll_pause: float, already_processed: Set[str], batch_size: int = BATCH_SIZE, dc_region: str = "EU10", start_date_from: str = None, start_date_to: str = None, end_date_from: str = None, end_date_to: str = None, workshop_id_from: str = None, workshop_id_to: str = None) -> None:
    """
    Scroll through the workshop list and collect the next batch_size unprocessed
    workshops. Stops as soon as the batch is full or the DOM stops growing.
    Verifies filters are active before collecting any IDs — raises RuntimeError
    (SAFETY ABORT) if the Cleaned filter is not confirmed in the portal toolbar.
    """
    # Belt-and-braces: settle any in-flight filter query before reading rows, so a
    # collection that runs immediately after _go_to_filtered_list (batch-of-1 loop)
    # never reads the stale pre-filter row set.
    await _wait_for_filter_query_settled(page)
    await _verify_filters_active(page, dc_region=dc_region, start_date_from=start_date_from, start_date_to=start_date_to, end_date_from=end_date_from, end_date_to=end_date_to, workshop_id_from=workshop_id_from, workshop_id_to=workshop_id_to)
    logger.info(f"Collecting next batch of up to {batch_size} unprocessed workshops...")

    batch: List[str] = []
    seen:  Set[str]  = set()
    prev_total = 0

    while len(batch) < batch_size:
        ids = await page.evaluate(_WORKSHOP_IDS_JS)

        for wid in ids:
            if wid not in seen and wid not in already_processed:
                seen.add(wid)
                batch.append(wid)
                if len(batch) >= batch_size:
                    break

        if len(batch) >= batch_size:
            break

        total_visible = len(ids)
        await page.evaluate(_SCROLL_JS)
        if total_visible == prev_total:
            # No new rows yet — give SAPUI5 extra time to render before giving up
            await asyncio.sleep(scroll_pause * 3)
            ids_recheck = await page.evaluate(_WORKSHOP_IDS_JS)
            if len(ids_recheck) == total_visible:
                logger.info("Reached end of workshop list")
                break
            prev_total = len(ids_recheck)
        else:
            prev_total = total_visible
            # Short sleep is intentional — SAPUI5 virtual scroll renders rows
            # asynchronously and fires no XHR, so networkidle won't help.
            await asyncio.sleep(scroll_pause)

    logger.info(f"Collected {len(batch)} new workshops to process")
    return batch


async def run_portal_scrape(page: Page, cfg: dict, max_workshops: int = None) -> None:
    base_url          = cfg["portal"]["base_url"]
    search_term       = cfg["portal"]["search_term"]
    scroll_pause      = cfg["portal"]["scroll_pause"]
    dc_region         = cfg["portal"].get("dc_region", "EU10")
    start_date_from   = cfg["portal"].get("start_date_from") or None
    start_date_to     = cfg["portal"].get("start_date_to") or None
    end_date_from     = cfg["portal"].get("end_date_from") or None
    end_date_to       = cfg["portal"].get("end_date_to") or None
    workshop_id_from  = cfg["portal"].get("workshop_id_from") or None
    workshop_id_to    = cfg["portal"].get("workshop_id_to") or None
    requests_tree_item = cfg["portal"].get("requests_tree_item", "Internal request(s)")
    backoff           = backoff_from_cfg(cfg)

    already_processed = load_processed_workshops(cfg)
    already_pending   = load_pending_workshops(cfg)
    logger.info(f"{len(already_processed)} workshops already processed in previous runs")
    if max_workshops is not None:
        logger.info(f"max_workshops={max_workshops} — scrape will stop after this many workshops")

    @with_retry(backoff)
    async def _navigate():
        await _go_to_filtered_list(page, base_url, search_term, dc_region=dc_region, start_date_from=start_date_from, start_date_to=start_date_to, end_date_from=end_date_from, end_date_to=end_date_to, requests_tree_item=requests_tree_item, workshop_id_from=workshop_id_from, workshop_id_to=workshop_id_to)

    await _navigate()

    # Single-sweep collection. Now that the scrape only records workshop NUMBERS (no
    # click-into-workshop user extraction), the filters are never destroyed mid-scrape,
    # so there is no need to re-navigate per workshop. Apply the filters once, then scroll
    # the filtered list in ONE pass collecting every unprocessed workshop ID.
    # _collect_next_batch already skips `already_processed` and stops when the list stops
    # growing ("Reached end of workshop list"), so a large batch_size sweeps everything;
    # a set max_workshops caps the sweep at that many unprocessed workshops.
    sweep_size = max_workshops if max_workshops is not None else 10**9
    workshop_ids = await _collect_next_batch(
        page, scroll_pause, already_processed, batch_size=sweep_size,
        dc_region=dc_region, start_date_from=start_date_from, start_date_to=start_date_to, end_date_from=end_date_from, end_date_to=end_date_to, workshop_id_from=workshop_id_from, workshop_id_to=workshop_id_to,
    )

    total_workshops = 0
    for wid in workshop_ids:
        logger.info(f"Queuing workshop {total_workshops + 1}: {wid}")
        append_pending_workshop(wid, cfg, _pending=already_pending, _processed=already_processed)
        mark_workshop_processed(wid, cfg)
        already_processed.add(wid)
        already_pending.add(wid)
        total_workshops += 1

    logger.info(f"Scrape complete — {total_workshops} workshop(s) queued for sweep")
    return []


async def scrape_single_workshop(page: Page, cfg: dict, workshop_id: str) -> None:
    """Navigate to the filtered portal list, queue workshop_id for the Stage 2 sweep,
    and mark it processed. User extraction is no longer performed."""
    base_url           = cfg["portal"]["base_url"]
    dc_region          = cfg["portal"].get("dc_region", "EU10")
    start_date_from    = cfg["portal"].get("start_date_from") or None
    start_date_to      = cfg["portal"].get("start_date_to") or None
    end_date_from      = cfg["portal"].get("end_date_from") or None
    end_date_to        = cfg["portal"].get("end_date_to") or None
    workshop_id_from   = cfg["portal"].get("workshop_id_from") or None
    workshop_id_to     = cfg["portal"].get("workshop_id_to") or None
    requests_tree_item = cfg["portal"].get("requests_tree_item", "Internal request(s)")
    backoff            = backoff_from_cfg(cfg)

    @with_retry(backoff)
    async def _navigate():
        await _go_to_filtered_list(page, base_url, workshop_id, dc_region=dc_region, start_date_from=start_date_from, start_date_to=start_date_to, end_date_from=end_date_from, end_date_to=end_date_to, requests_tree_item=requests_tree_item, workshop_id_from=workshop_id_from, workshop_id_to=workshop_id_to)

    await _navigate()
    append_pending_workshop(workshop_id, cfg)
    mark_workshop_processed(workshop_id, cfg)
    return []
