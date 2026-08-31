import asyncio
import re
from dataclasses import dataclass
from typing import List, Optional
from playwright.async_api import Page
from src.logging_setup import get_logger
from src.retry import with_retry, backoff_from_cfg

logger = get_logger("datasphere_client")

SPACE_MGMT_PATH = "/dwaas-core/index.html#/spaceManagement"

_WAIT_TIMEOUT = 15000

_SPACE_MGMT_SEARCHBOX = (
    "[id*='manageSpaces--filterSpacesInput-I'], "
    "[id*='spaceManagement'] [role='searchbox'], "
    "[id*='managespaces'] input[type='search']"
)

# Toast SAP renders after a successful deletion — confirms auto-navigation is done
_SPACE_DELETED_TOAST = ".sapMMessageToast"


def space_mgmt_url(cfg: dict) -> str:
    path = cfg["datasphere"].get("space_management_path", SPACE_MGMT_PATH)
    return cfg["datasphere"]["base_url"].rstrip("/") + path


_SAP_ERROR_DIALOG_SELECTOR = (
    ".sapMMessageBox, "
    ".sapMDialog[role='alertdialog'], "
    "[id*='messageBox'], "
    "[id*='errorDialog']"
)

# Buttons that dismiss SAP error dialogs — checked in order
_SAP_ERROR_DISMISS_SELECTORS = [
    "button[id*='okBtn']",
    "button[id*='closeBtn']",
    ".sapMDialogFooter button",
    ".sapMMessageBoxButton",
    "[role='button'][id*='ok']",
]

# SAP SPA "page not found" screen — shown when the router can't resolve
# the space detail URL after the space has been deleted.
_SAP_NOT_FOUND_SELECTOR = "[class*='notFound'], [id*='notFound'], [class*='errorPage']"
_SAP_NOT_FOUND_BACK_SELECTORS = [
    "a:has-text('Return to previous page')",
    "button:has-text('Return to previous page')",
    "a:has-text('Go back')",
    "button:has-text('Go back')",
    ".sapMBtn:has-text('Return')",
]


async def _dismiss_any_sap_dialogs(page: Page) -> int:
    """
    Dismiss any SAP error dialogs or 'page not found' screens that are currently
    visible. Returns the number of dialogs dismissed.

    Two known post-deletion screens:
      1. SPA 404 — "Sorry, we can't find this page" — click 'Return to previous page'
      2. Error dialog — "The space details couldn't be loaded" — click OK/Close
    """
    dismissed = 0

    # Screen 1: SPA 404 / not-found page
    try:
        not_found = page.locator(_SAP_NOT_FOUND_SELECTOR).first
        if await not_found.is_visible():
            logger.warning("SAP 'page not found' screen detected — clicking back link")
            for sel in _SAP_NOT_FOUND_BACK_SELECTORS:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible():
                        await btn.click()
                        dismissed += 1
                        try:
                            await page.wait_for_selector(
                                _SPACE_MGMT_SEARCHBOX, state="attached", timeout=_WAIT_TIMEOUT
                            )
                        except Exception:
                            pass
                        break
                except Exception:
                    continue
    except Exception:
        pass

    # Screen 2: error dialog (e.g. "space details couldn't be loaded")
    try:
        dialog = page.locator(_SAP_ERROR_DIALOG_SELECTOR).first
        if await dialog.is_visible():
            logger.warning("SAP error dialog detected — auto-dismissing and continuing")
            for selector in _SAP_ERROR_DISMISS_SELECTORS:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible():
                        await btn.click()
                        try:
                            await page.wait_for_selector(
                                _SAP_ERROR_DIALOG_SELECTOR, state="hidden", timeout=5000
                            )
                        except Exception:
                            pass
                        dismissed += 1
                        break
                except Exception:
                    continue
            if dismissed == 0:
                try:
                    await page.keyboard.press("Escape")
                    dismissed += 1
                except Exception:
                    pass
    except Exception:
        pass

    return dismissed


async def _wait_for_sap_post_deletion_nav(page: Page, cfg: dict):
    """
    After clicking Delete confirm, SAP automatically navigates back to Space
    Management and shows a 'Space deleted' toast. Wait for that to happen rather
    than issuing our own goto/go_back — any redundant navigation is what triggers
    the 'page not found' and 'space details couldn't be loaded' dialogs.

    Waits up to post_delete_pause seconds for the toast, then confirms the Space
    Management searchbox is present. Falls back to a single goto only if SAP's
    auto-navigation does not complete in time.
    """
    post_delete_pause = cfg["datasphere"]["post_delete_pause"]

    # Wait for the 'Space deleted' toast — confirms SAP's auto-navigation landed
    try:
        await page.wait_for_selector(
            _SPACE_DELETED_TOAST,
            state="attached",
            timeout=int(post_delete_pause * 1000),
        )
        logger.debug("'Space deleted' toast detected — SAP auto-navigation complete")
    except Exception:
        logger.debug("'Space deleted' toast not seen within timeout — checking for searchbox directly")

    # Confirm the Space Management searchbox is present
    try:
        await page.wait_for_selector(_SPACE_MGMT_SEARCHBOX, timeout=5000)
        return
    except Exception:
        logger.warning("Space Management searchbox not found after deletion — falling back to goto")

    await page.goto(space_mgmt_url(cfg), wait_until="domcontentloaded", timeout=30000)
    await _dismiss_any_sap_dialogs(page)


async def wait_for_space_mgmt_ready(page: Page):
    """
    Wait until Space Management is fully interactive after a navigation.

    Sequence:
    1. Dismiss any SAP error dialogs or 404 screens from the navigation
    2. Wait for the searchbox to be in the DOM (structural readiness)
    3. Wait for any SAPUI5 busy overlay to clear (interaction readiness)
    4. Short networkidle wait so any in-flight XHRs from the previous
       deletion settle before we type a new search query
    5. Clear the searchbox so the SPA resets the tile container to empty —
       stale tiles from a previous workshop search persist until a new search
       replaces them.
    """
    await _dismiss_any_sap_dialogs(page)

    await page.wait_for_selector(_SPACE_MGMT_SEARCHBOX, timeout=_WAIT_TIMEOUT)

    # SAPUI5 busy indicator — present while the component is still loading/processing
    try:
        await page.wait_for_selector(
            ".sapUiLocalBusyIndicator, .sapUiBlockLayerTabbable",
            state="hidden",
            timeout=15000,
        )
    except Exception:
        pass  # no busy indicator visible — page is ready

    # Allow any post-deletion XHRs to settle before the next search fires
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass  # networkidle can hang on SPAs — structural readiness above is sufficient

    # Clear the searchbox so the SPA collapses the tile container back to empty.
    # Without this clear, stale tiles from a previous workshop search persist until
    # the next workshop search replaces them.
    try:
        searchbox = page.locator(_SPACE_MGMT_SEARCHBOX).first
        await searchbox.click()
        await searchbox.fill("")
    except Exception:
        pass  # searchbox not interactive — fine to proceed


@dataclass
class DeleteResult:
    user_id: str
    space_id: str
    outcome: str          # deleted | skipped_allowlist | skipped_dry_run | failed
    error: Optional[str] = None


async def navigate_to_space_management(page: Page, cfg: dict):
    backoff = backoff_from_cfg(cfg)

    @with_retry(backoff)
    async def _navigate():
        await page.goto(space_mgmt_url(cfg), wait_until="domcontentloaded", timeout=30000)
        await wait_for_space_mgmt_ready(page)
        logger.debug("Navigated to Space Management")

    await _navigate()



# ── Workshop bulk-sweep selectors (confirmed via probe_workshop_bulk on all 5 tenants) ──
# Each result card is spacesContainer-<N>; the header identifier is
# spacesContainer-<N>--spaceTileHeader-identifier-txt (renamed name on AP11/GE tenants),
# and the user ID (AC<workshop>U.. / bare GE<workshop>) is a sibling text node in the card.
_BULK_IDENTIFIER_TXT = '[id$="spaceTileHeader-identifier-txt"]'
_BULK_ROW_CHECKBOX   = ".sapMCb"
_BULK_DELETE_BTN     = "[id$='manageSpaces--toolbar--deleteButton']"
_BULK_CONFIRM_DIALOG = "[id*='DeleteConfirmationDialog--dialog']"
_BULK_CONFIRM_INPUT  = "[id*='DeleteConfirmationDialog--dialog--view--deleteInput-inner']"
_BULK_CONFIRM_OK     = "[id*='DeleteConfirmationDialog--dialog--view--ok']"


def _workshop_id_re(workshop: str) -> "re.Pattern":
    """Anchored validator for a result card's user ID: AC<workshop>U<digits>,
    GE<workshop>U<digits>, or bare GE<workshop>. Anchoring prevents a search
    over-match (e.g. workshop '284660' matching '1284660' or '2846601')."""
    return re.compile(rf'^(AC|GE){re.escape(workshop)}(U\d+)?$', re.IGNORECASE)


async def _current_tile_ids(page: Page) -> set:
    """Return the set of tile identifier-txt values currently rendered in the grid.

    Used to detect when a workshop-number search has actually re-rendered the tile grid
    to the filtered result set, versus still showing the stale pre-filter set."""
    try:
        return set(await page.evaluate(
            """() => Array.from(
                document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]')
            ).map(el => (el.innerText || '').trim()).filter(Boolean)"""
        ))
    except Exception:
        return set()


async def _visible_card_user_ids(page: Page) -> list:
    """Return, per visible tile, the list of leaf-text values inside its card.

    This mirrors the card-walk the card-READER uses (find_workshop_spaces' main evaluate):
    for each `spaceTileHeader-identifier-txt`, walk up to the enclosing `.sapFCard` and
    collect every leaf element's innerText. On RENAMED spaces the identifier-txt holds the
    renamed headline (e.g. `POOL_XA_00000978`) while the real AC/GE user ID lives in a
    sibling leaf text node (`AC279401U00`), so the settle check MUST look here, not at the
    identifier-txt, to recognise a renamed workshop's result as a valid match."""
    try:
        return await page.evaluate(
            """() => {
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
                    out.push(texts);
                });
                return out;
            }"""
        )
    except Exception:
        return []


async def _wait_for_search_settled(page: Page, workshop: str) -> bool:
    """Poll until the Space Management tile grid reaches a STABLE terminal state after a
    workshop-number search. Returns True once settled, False if it never settles within
    _WAIT_TIMEOUT.

    A state is "settled" when the visible tile-ID set is stable across two consecutive
    polls AND is a valid terminal state:
      - empty        -> the workshop genuinely has no spaces (a valid, common outcome;
                        confirmed live on AP11 for workshops 233717/234287), OR
      - matches      -> at least one visible CARD carries a user-ID text matching
                        ^(AC|GE)<workshop>(U\\d+)?$. This is read from the card's leaf text
                        nodes, NOT the identifier-txt headline — renamed spaces show a
                        `POOL_XA_*`/`SPACE_*` headline but carry the real AC/GE id in a
                        sibling text node (confirmed live on AP11 workshop 279401, 25
                        renamed POOL_XA_* tiles). Matching the headline here caused a false
                        "never settled" abort on exactly the renamed workshops the sweep
                        exists to clean.

    Why not the old "did the tile set CHANGE from a pre-search snapshot" test: SAPUI5
    filters the grid via an async OData query, so reading too early scrapes the STALE
    pre-filter set. The old guard detected the change, but could NOT recognise a valid
    empty result when the grid was already empty before the search (empty->empty never
    "changes") — it then failed closed and aborted the whole tenant run. This positive
    settle signal accepts a stable empty result while still refusing a stale non-matching
    grid: if tiles are present but NO card carries the searched workshop's id (e.g. the
    default 25-tile grid because the search silently didn't fire), it is NOT settled — keep
    polling, and fail closed on timeout rather than read the wrong workshop's spaces."""
    _asyncio = asyncio
    validator = _workshop_id_re(workshop)
    deadline_steps = int(_WAIT_TIMEOUT / 500)  # poll every 500ms up to _WAIT_TIMEOUT
    prev = None
    for _ in range(max(deadline_steps, 1)):
        current = await _current_tile_ids(page)
        stable = (prev is not None and current == prev)
        if stable:
            if not current:
                return True  # stable empty -> genuinely no spaces
            # Match against the CARD leaf texts (real user IDs), not the headline, so
            # renamed POOL_XA_*/SPACE_* tiles are recognised.
            card_texts = await _visible_card_user_ids(page)
            if any(validator.match(t) for texts in card_texts for t in texts):
                return True  # stable and at least one card matches this workshop
            # Stable but no card matches (stale default grid) -> not settled, keep waiting.
        prev = current
        await _asyncio.sleep(0.5)
    return False


async def find_workshop_spaces(page: Page, workshop: str, cfg: dict = None) -> List[dict]:
    """Search Datasphere by WORKSHOP NUMBER and return every space belonging to it.

    The workshop number appears in every space's user ID (the subheading/technical ID:
    AC<workshop>U.. on AC tenants, bare GE<workshop> on GE public tenants), so one search
    surfaces ALL of a workshop's spaces — including ones the content portal never listed.
    Renamed spaces (headline POOL_XA_*/SPACE_*) are still matched because the user ID is
    carried in a sibling text node in each card, not the (renamed) headline.

    Each returned dict: {"user_id": <AC/GE id>, "headline": <display name>, "container": <N>}.
    Only cards whose user ID matches ^(AC|GE)<workshop>(U\\d+)?$ are returned — this is the
    over-match guard: a substring search hit like '1284660' for workshop '284660' is dropped.
    """
    searchbox = page.locator(_SPACE_MGMT_SEARCHBOX).first
    await searchbox.wait_for(state="visible", timeout=_WAIT_TIMEOUT)
    await searchbox.click()
    await searchbox.fill("")
    # Type the workshop number and press Enter ONCE to search. The grid filters to the
    # workshop's spaces. The autocomplete dropdown is irrelevant and ignored — selection of
    # the found spaces happens later in delete_workshop_spaces.
    await searchbox.fill(workshop)
    await searchbox.press("Enter")

    # Wait for SAPUI5 busy overlay to clear and XHRs to settle.
    try:
        await page.wait_for_selector(
            ".sapUiLocalBusyIndicator, .sapUiBlockLayerTabbable",
            state="hidden",
            timeout=15000,
        )
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass

    # HARD CONFIRM the search reached a stable terminal state before reading. A stable
    # empty grid is a valid "no spaces" result; a stable grid with matching tiles is a
    # valid populated result. Fail CLOSED (raise) only if the grid never settles — e.g. it
    # persistently shows a non-matching (stale) set — rather than mis-attribute another
    # workshop's spaces to this one and mark this workshop wrongly swept.
    settled = await _wait_for_search_settled(page, workshop)
    if not settled:
        raise RuntimeError(
            f"workshop {workshop}: search grid never settled to a stable empty or "
            f"matching state within {_WAIT_TIMEOUT}ms — refusing to read stale tiles"
        )

    # Read every card: container index N, header identifier, and the user-ID text node.
    # The user ID is the card text that matches the AC/GE id shape; headline is the
    # identifier-txt (may be a renamed name). Mirrors the container-index evaluate
    # pattern used by the (per-user) tile scanner.
    raw = await page.evaluate("""() => {
        const ids = document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]');
        const out = [];
        ids.forEach(idEl => {
            const m = idEl.id.match(/spacesContainer-(\\d+)--spaceTileHeader/);
            if (!m) return;
            const n = m[1];
            let card = idEl;
            while (card && card.tagName !== 'BODY') {
                if (card.className && card.className.toString().includes('sapFCard')) break;
                card = card.parentElement;
            }
            // Collect candidate ID texts from leaf elements in the card.
            const texts = [];
            if (card) {
                card.querySelectorAll('[id]').forEach(el => {
                    if (el.children.length === 0) {
                        const t = (el.innerText || '').trim();
                        if (t) texts.push(t);
                    }
                });
            }
            out.push({ container: n, headline: idEl.innerText.trim(), texts: texts });
        });
        return out;
    }""")

    validator = _workshop_id_re(workshop)
    results = []
    for card in raw:
        # The user ID is whichever leaf text matches the anchored AC/GE workshop pattern.
        user_id = next((t for t in card["texts"] if validator.match(t)), None)
        if user_id is None:
            logger.debug(
                f"workshop {workshop}: card container {card['container']} "
                f"(headline={card['headline']!r}) has no matching user ID — skipping"
            )
            continue
        results.append({
            "user_id": user_id.upper(),
            "headline": card["headline"],
            "container": card["container"],
        })

    logger.info(f"workshop {workshop}: {len(results)} space(s) matched (from {len(raw)} card(s))")
    return results


async def delete_workshop_spaces(page: Page, workshop: str, cards: List[dict], cfg: dict,
                                 dry_run: bool, allowlist: set = None) -> List[DeleteResult]:
    """Bulk-delete the validated spaces of one workshop in a single operation.

    Selects each validated card's checkbox, then one Delete → type DELETE → OK. The
    committing OK click is fired exactly once and is NOT retried (prepare/commit split:
    only idempotent navigation is retried; the committing click fires once). Returns one
    DeleteResult per space.

    Safety: allowlisted user IDs are dropped (skipped_allowlist) BEFORE any selection;
    dry_run emits skipped_dry_run per card with no clicks; a mismatch between the number of
    boxes we ticked and the number we intended aborts the whole batch (all failed) rather
    than deleting an unexpected set.
    """
    allowlist = {a.upper() for a in (allowlist or set())}
    results: List[DeleteResult] = []

    to_delete = []
    for c in cards:
        if c["user_id"].upper() in allowlist:
            logger.warning(f"{c['user_id']}: on the allowlist — skipping")
            results.append(DeleteResult(user_id=c["user_id"], space_id=c["user_id"],
                                        outcome="skipped_allowlist"))
        else:
            to_delete.append(c)

    if not to_delete:
        return results

    if dry_run:
        for c in to_delete:
            logger.info(f"[DRY-RUN] Would delete space '{c['user_id']}' (workshop {workshop})")
            results.append(DeleteResult(user_id=c["user_id"], space_id=c["user_id"],
                                        outcome="skipped_dry_run"))
        return results

    backoff = backoff_from_cfg(cfg)

    async def _fail_all(err: str) -> List[DeleteResult]:
        logger.error(f"workshop {workshop}: bulk delete aborted — {err}")
        for c in to_delete:
            results.append(DeleteResult(user_id=c["user_id"], space_id=c["user_id"],
                                        outcome="failed", error=err))
        return results

    # Tick each validated card's checkbox by container index.
    ticked = 0
    for c in to_delete:
        cb = page.locator(f"[id*='spacesContainer-{c['container']}-'] {_BULK_ROW_CHECKBOX}").first
        try:
            await cb.click(timeout=_WAIT_TIMEOUT)
            ticked += 1
        except Exception as exc:
            return await _fail_all(f"could not select checkbox for {c['user_id']}: {exc}")

    # Guard: the number we ticked must equal the number we intended to delete.
    if ticked != len(to_delete):
        return await _fail_all(f"selected {ticked} but intended {len(to_delete)}")

    @with_retry(backoff)
    async def _prepare_bulk_delete():
        del_btn = page.locator(_BULK_DELETE_BTN).first
        await del_btn.wait_for(state="visible", timeout=_WAIT_TIMEOUT)
        await del_btn.click()
        await page.wait_for_selector(_BULK_CONFIRM_DIALOG, timeout=_WAIT_TIMEOUT, state="visible")
        confirm_input = page.locator(_BULK_CONFIRM_INPUT).first
        await confirm_input.wait_for(state="visible", timeout=_WAIT_TIMEOUT)
        await confirm_input.click()
        await confirm_input.fill("DELETE")

    async def _commit_bulk_delete():
        # Fired exactly once — NOT retried. This commits the bulk deletion.
        await page.locator(_BULK_CONFIRM_OK).first.click()

    try:
        await _prepare_bulk_delete()
        await _commit_bulk_delete()
        logger.info(f"workshop {workshop}: bulk-deleted {len(to_delete)} space(s)")
        for c in to_delete:
            results.append(DeleteResult(user_id=c["user_id"], space_id=c["user_id"],
                                        outcome="deleted"))
        await _wait_for_sap_post_deletion_nav(page, cfg)
        await wait_for_space_mgmt_ready(page)
        return results
    except Exception as exc:
        try:
            await wait_for_space_mgmt_ready(page)
        except Exception:
            pass
        return await _fail_all(str(exc))


async def search_and_verify_space(page: Page, user_id: str, space_id: str) -> Optional[str]:
    """
    Used by Stage 3 verification. Types user_id into the Space Management
    searchbox, reads the autocomplete suggestions, and checks whether space_id
    still appears. Returns space_id if still present, None if confirmed gone.

    Searching by user_id (the immutable technical ID) finds the space even when
    it has been renamed — the subheading in the autocomplete is always the
    original AC/GE user ID regardless of display name.
    """
    searchbox = page.locator(_SPACE_MGMT_SEARCHBOX).first
    await searchbox.wait_for(state="visible", timeout=_WAIT_TIMEOUT)
    await searchbox.click()
    await searchbox.fill("")
    await searchbox.fill(user_id)
    try:
        await searchbox.press("End")
        await searchbox.press("Enter")
    except Exception:
        pass
    try:
        await page.wait_for_selector(
            '[role="listbox"].sapMSelectList li',
            timeout=_WAIT_TIMEOUT,
            state="attached",
        )
    except Exception:
        await searchbox.press("Escape")
        return None

    suggestions = await page.evaluate("""() => {
        const list = document.querySelector('[role="listbox"].sapMSelectList');
        if (!list) return [];
        const results = [];
        list.querySelectorAll('li').forEach(li => {
            const text = li.innerText.trim();
            const match = text.match(/^(.+?)\\s+\\(([^)]+)\\)$/);
            if (!match) return;
            results.push({ headline: match[1].trim(), subheading: match[2].trim() });
        });
        return results;
    }""")
    await searchbox.press("Escape")

    for s in suggestions:
        if (s.get("subheading", "").upper() == space_id.upper()
                or s.get("headline", "").upper() == space_id.upper()):
            return space_id
    return None
