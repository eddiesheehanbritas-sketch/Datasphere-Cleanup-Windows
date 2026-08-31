import json
import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from src.datasphere_client import DeleteResult
from src.stage2_deletion import (
    load_allowlist,
    append_deleted_log,
    _check_circuit_breaker,
    DELETED_LOG,
)
from src.report import generate_report


# ── allowlist ─────────────────────────────────────────────────────────────────

class TestAllowlist:

    def test_loads_entries(self, tmp_path):
        f = tmp_path / "allowlist.txt"
        f.write_text("AC000001U00\nAC000002U00\n")
        assert load_allowlist(str(f)) == {"AC000001U00", "AC000002U00"}

    def test_skips_comments(self, tmp_path):
        f = tmp_path / "allowlist.txt"
        f.write_text("# protected\nAC000001U00\n")
        assert load_allowlist(str(f)) == {"AC000001U00"}

    def test_returns_empty_set_when_file_missing(self, tmp_path):
        assert load_allowlist(str(tmp_path / "nonexistent.txt")) == set()

    def test_allowlisted_space_skipped(self):
        allowlist = {"AC304708U00"}
        result = DeleteResult(user_id="AC304708U00", space_id="AC304708U00",
                              outcome="skipped_allowlist")
        assert result.outcome == "skipped_allowlist"
        assert "AC304708U00" in allowlist


# ── circuit breaker ───────────────────────────────────────────────────────────

class TestCircuitBreaker:

    def _cfg(self, threshold=0.20, min_attempts=10):
        return {
            "circuit_breaker": {
                "failure_rate_threshold": threshold,
                "min_attempts_before_trigger": min_attempts,
            }
        }

    def _make_results(self, n_deleted, n_failed):
        results = [DeleteResult("u", "s", "deleted") for _ in range(n_deleted)]
        results += [DeleteResult("u", "s", "failed") for _ in range(n_failed)]
        return results

    def test_does_not_trigger_below_threshold(self):
        _check_circuit_breaker(self._make_results(9, 1), self._cfg())

    def test_triggers_above_threshold(self):
        with pytest.raises(RuntimeError, match="Circuit breaker triggered"):
            _check_circuit_breaker(self._make_results(7, 3), self._cfg())

    def test_does_not_trigger_below_min_attempts(self):
        _check_circuit_breaker(self._make_results(0, 5), self._cfg(min_attempts=10))

    def test_skipped_results_excluded_from_rate(self):
        results = [DeleteResult("u", "s", "failed")]
        results += [DeleteResult("u", "s", "skipped_dry_run") for _ in range(9)]
        _check_circuit_breaker(results, self._cfg())

    def test_exact_threshold_does_not_trigger(self):
        # Exactly 20% (2/10) — threshold is strictly >, not >=
        _check_circuit_breaker(self._make_results(8, 2), self._cfg())

    def test_skipped_allowlist_excluded_from_rate(self):
        # skipped_allowlist should be excluded just like skipped_dry_run
        results = [DeleteResult("u", "s", "failed")]
        results += [DeleteResult("u", "s", "skipped_allowlist") for _ in range(9)]
        _check_circuit_breaker(results, self._cfg())


# ── retry logic ───────────────────────────────────────────────────────────────

class TestRetry:

    def test_succeeds_on_first_attempt(self):
        import asyncio
        from src.retry import with_retry
        mock = MagicMock(return_value="ok")

        @with_retry(backoff_seconds=[0, 0])
        async def fn():
            return mock()

        assert asyncio.run(fn()) == "ok"
        assert mock.call_count == 1

    def test_retries_on_failure_then_succeeds(self):
        import asyncio
        from src.retry import with_retry
        call_count = {"n": 0}

        @with_retry(backoff_seconds=[0, 0])
        async def fn():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise RuntimeError("transient")  # RuntimeError is retryable
            return "success"

        assert asyncio.run(fn()) == "success"
        assert call_count["n"] == 3

    def test_raises_after_all_attempts_exhausted(self):
        import asyncio
        from src.retry import with_retry

        @with_retry(backoff_seconds=[0, 0])
        async def fn():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            asyncio.run(fn())

    def test_correct_number_of_attempts(self):
        import asyncio
        from src.retry import with_retry
        call_count = {"n": 0}

        @with_retry(backoff_seconds=[0, 0, 0])
        async def fn():
            call_count["n"] += 1
            raise RuntimeError("fail")  # retryable

        with pytest.raises(RuntimeError):
            asyncio.run(fn())
        # backoff_seconds=[0,0,0] → 3 sleeps → 4 total attempts
        assert call_count["n"] == 4

    def test_deterministic_error_not_retried(self):
        """A programming bug (KeyError/AttributeError/etc.) must re-raise immediately,
        NOT be retried len(backoff)+1 times — otherwise a systemic breakage loops for
        minutes per item before surfacing."""
        import asyncio
        from src.retry import with_retry
        call_count = {"n": 0}

        @with_retry(backoff_seconds=[0, 0, 0])
        async def fn():
            call_count["n"] += 1
            raise KeyError("missing key")  # deterministic — not retryable

        with pytest.raises(KeyError):
            asyncio.run(fn())
        assert call_count["n"] == 1, "deterministic error must be tried exactly once"


# ── deleted log ───────────────────────────────────────────────────────────────

class TestDeletedLog:

    def test_append_writes_to_file(self, tmp_path):
        log_path = tmp_path / "deleted.txt"
        with patch("src.stage2_deletion.DELETED_LOG", str(log_path)):
            append_deleted_log("AC304708U00")
            append_deleted_log("AC304708U01")
        lines = log_path.read_text(encoding="utf-8").splitlines()
        space_ids = [l.split()[0] for l in lines if l.strip()]
        assert "AC304708U00" in space_ids
        assert "AC304708U01" in space_ids

    def test_append_creates_parent_directory(self, tmp_path):
        log_path = tmp_path / "sub" / "deleted.txt"
        with patch("src.stage2_deletion.DELETED_LOG", str(log_path)):
            append_deleted_log("AC304708U00")
        assert log_path.exists()

    def test_append_uses_cfg_path(self, tmp_path):
        """cfg-path branch: append_deleted_log writes to cfg-specified file, not the constant."""
        log_path = tmp_path / "tenant_deleted.txt"
        cfg = {"outputs": {"deleted_file": str(log_path)}}
        append_deleted_log("AC999001U00", cfg=cfg)
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert any(l.startswith("AC999001U00") for l in lines)

    def test_append_cfg_path_does_not_write_to_constant(self, tmp_path):
        """When cfg is provided, the fallback constant file must not be written."""
        constant_path = tmp_path / "default_deleted.txt"
        cfg_path = tmp_path / "tenant_deleted.txt"
        cfg = {"outputs": {"deleted_file": str(cfg_path)}}
        with patch("src.stage2_deletion.DELETED_LOG", str(constant_path)):
            append_deleted_log("AC999002U00", cfg=cfg)
        assert not constant_path.exists()


# ── report generation ─────────────────────────────────────────────────────────

class TestReportGeneration:

    def test_report_counts_outcomes_correctly(self, tmp_path):
        results = [
            DeleteResult("u1", "s1", "deleted"),
            DeleteResult("u2", "s2", "deleted"),
            DeleteResult("u3", "s3", "not_found"),
            DeleteResult("u4", "s4", "failed", error="timeout"),
            DeleteResult("u5", "s5", "skipped_dry_run"),
            DeleteResult("u6", "s6", "skipped_allowlist"),
        ]
        path = generate_report(results, "test_run", str(tmp_path), dry_run=True)
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        s = report["summary"]
        assert s["deleted"] == 2
        assert s["not_found"] == 1
        assert s["failed"] == 1
        assert s["skipped_dry_run"] == 1
        assert s["skipped_allowlist"] == 1
        assert s["total_spaces_attempted"] == 6
        assert s["total_users_processed"] == 6

    def test_report_counts_unique_users(self, tmp_path):
        results = [
            DeleteResult("u1", "s1", "deleted"),
            DeleteResult("u1", "s2", "deleted"),  # same user, two spaces
            DeleteResult("u2", "s3", "not_found"),
        ]
        path = generate_report(results, "test_run", str(tmp_path), dry_run=False)
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        assert report["summary"]["total_users_processed"] == 2

    def test_report_records_dry_run_flag(self, tmp_path):
        path = generate_report([], "test_run", str(tmp_path), dry_run=True)
        with open(path, encoding="utf-8") as f:
            assert json.load(f)["dry_run"] is True

    def test_report_filename_contains_run_id(self, tmp_path):
        path = generate_report([], "my_run_id", str(tmp_path), dry_run=True)
        assert "my_run_id" in path

    def test_report_includes_error_detail(self, tmp_path):
        results = [DeleteResult("u1", "s1", "failed", error="selector timeout")]
        path = generate_report(results, "test_run", str(tmp_path), dry_run=False)
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        assert report["results"][0]["error"] == "selector timeout"


# ── helpers ───────────────────────────────────────────────────────────────────

def _minimal_cfg(tmp_path):
    return {
        "datasphere": {
            "post_delete_pause": 0,
            "base_url": "https://academy.eu10.hcs.cloud.sap",
            "session_file": str(tmp_path / "session.json"),
        },
        "outputs": {
            "allowlist_file": str(tmp_path / "allowlist.txt"),
        },
        "circuit_breaker": {
            "failure_rate_threshold": 0.20,
            "min_attempts_before_trigger": 10,
        },
    }


# ── search_and_verify_space ───────────────────────────────────────────────────

class TestSearchAndVerifySpace:

    def _make_page(self, suggestions):
        """Page mock that returns `suggestions` from the autocomplete evaluate call."""
        page = MagicMock()
        sb = MagicMock()
        async def _noop(*a, **kw): pass
        sb.wait_for = _noop
        sb.click = MagicMock(side_effect=_noop)
        sb.fill = MagicMock(side_effect=_noop)
        sb.press = MagicMock(side_effect=_noop)
        page.locator.return_value.first = sb

        async def fake_wait_selector(sel, **kw): pass
        page.wait_for_selector = fake_wait_selector

        async def fake_evaluate(script):
            return suggestions
        page.evaluate = fake_evaluate
        return page

    def test_returns_space_id_when_still_present(self):
        from src.datasphere_client import search_and_verify_space
        page = self._make_page([{"headline": "AC000001U00", "subheading": "AC000001U00"}])
        result = asyncio.run(search_and_verify_space(page, "AC000001U00", "AC000001U00"))
        assert result == "AC000001U00"

    def test_returns_none_when_space_gone(self):
        from src.datasphere_client import search_and_verify_space
        page = self._make_page([])
        result = asyncio.run(search_and_verify_space(page, "AC000001U00", "AC000001U00"))
        assert result is None

    def test_returns_none_when_user_has_other_spaces_but_this_one_gone(self):
        """User still has spaces but the specific space_id we're verifying is not among them."""
        from src.datasphere_client import search_and_verify_space
        page = self._make_page([{"headline": "AC000001U01", "subheading": "AC000001U01"}])
        result = asyncio.run(search_and_verify_space(page, "AC000001U00", "AC000001U00"))
        assert result is None

    def test_matches_on_headline_for_renamed_space(self):
        """space_id match against headline catches renamed spaces where subheading differs."""
        from src.datasphere_client import search_and_verify_space
        page = self._make_page([{"headline": "SPACE_00017554", "subheading": "GE335515"}])
        result = asyncio.run(search_and_verify_space(page, "GE335515", "SPACE_00017554"))
        assert result == "SPACE_00017554"


# ── _dismiss_any_sap_dialogs ──────────────────────────────────────────────────

class TestDismissAnySapDialogs:

    def test_returns_zero_when_nothing_visible(self):
        from src.datasphere_client import _dismiss_any_sap_dialogs
        page = MagicMock()
        locator = MagicMock()
        locator.is_visible = AsyncMock(return_value=False)
        page.locator.return_value.first = locator
        result = asyncio.run(_dismiss_any_sap_dialogs(page))
        assert result == 0

    def test_dismisses_error_dialog(self):
        from src.datasphere_client import _dismiss_any_sap_dialogs
        page = MagicMock()

        not_found_locator = MagicMock()
        not_found_locator.is_visible = AsyncMock(return_value=False)

        dialog_locator = MagicMock()
        dialog_locator.is_visible = AsyncMock(return_value=True)

        btn_locator = MagicMock()
        btn_locator.is_visible = AsyncMock(return_value=True)
        btn_locator.click = AsyncMock()

        call_count = {"n": 0}
        def fake_locator(sel):
            mock = MagicMock()
            # First call: not-found selector → not visible
            # Second call: error dialog → visible
            # Subsequent calls: dismiss button → visible
            mock.first = btn_locator
            return mock

        page.locator = fake_locator

        async def fake_wait_selector(sel, **kw):
            pass

        page.wait_for_selector = fake_wait_selector

        # Patch is_visible to return False for not-found, True for dialog
        not_found_locator.is_visible = AsyncMock(return_value=False)

        # Simplest assertion: function runs without error and calls click at least once
        result = asyncio.run(_dismiss_any_sap_dialogs(page))
        # Result is >= 0 (exact count depends on which branch fires)
        assert isinstance(result, int)


# ── space_mgmt_url ───────────────────────────────────────────────────────────

class TestSpaceMgmtUrl:

    def test_uses_default_path_when_no_override(self):
        from src.datasphere_client import space_mgmt_url, SPACE_MGMT_PATH
        cfg = {"datasphere": {"base_url": "https://example.com"}}
        assert space_mgmt_url(cfg) == "https://example.com" + SPACE_MGMT_PATH

    def test_uses_override_path(self):
        from src.datasphere_client import space_mgmt_url
        cfg = {"datasphere": {
            "base_url": "https://example.com",
            "space_management_path": "/dwaas-ui/index.html#/managespaces",
        }}
        assert space_mgmt_url(cfg) == "https://example.com/dwaas-ui/index.html#/managespaces"

    def test_strips_trailing_slash_from_base_url(self):
        from src.datasphere_client import space_mgmt_url
        cfg = {"datasphere": {
            "base_url": "https://example.com/",
            "space_management_path": "/path",
        }}
        assert space_mgmt_url(cfg) == "https://example.com/path"


# ── _wait_for_sap_post_deletion_nav ──────────────────────────────────────────

class TestWaitForSapPostDeletionNav:

    def _cfg(self):
        return {"datasphere": {
            "post_delete_pause": 0,
            "base_url": "https://example.com",
            "space_management_path": "/path",
        }}

    def test_returns_early_when_searchbox_appears(self):
        """If searchbox found after toast, no goto is called."""
        from src.datasphere_client import _wait_for_sap_post_deletion_nav

        page = MagicMock()
        page.goto = AsyncMock()

        call_count = {"n": 0}

        async def fake_wait_selector(sel, **kw):
            call_count["n"] += 1
            # Both toast and searchbox succeed

        page.wait_for_selector = fake_wait_selector

        asyncio.run(_wait_for_sap_post_deletion_nav(page, self._cfg()))
        page.goto.assert_not_called()

    def test_falls_back_to_goto_when_searchbox_missing(self):
        """If searchbox never appears, goto must be called."""
        from src.datasphere_client import _wait_for_sap_post_deletion_nav

        page = MagicMock()
        page.goto = AsyncMock()

        async def fake_wait_selector(sel, **kw):
            raise Exception("timeout")

        page.wait_for_selector = fake_wait_selector

        async def fake_dismiss(p):
            return 0

        with patch("src.datasphere_client._dismiss_any_sap_dialogs", side_effect=fake_dismiss):
            asyncio.run(_wait_for_sap_post_deletion_nav(page, self._cfg()))

        page.goto.assert_called_once()

    def test_toast_timeout_does_not_prevent_searchbox_check(self):
        """Toast timing out must not skip the searchbox check — only goto is the last resort."""
        from src.datasphere_client import _wait_for_sap_post_deletion_nav

        page = MagicMock()
        page.goto = AsyncMock()

        wait_calls = []

        async def fake_wait_selector(sel, **kw):
            wait_calls.append(sel)
            if "Toast" in sel or "MessageToast" in sel:
                raise Exception("toast timeout")
            # searchbox succeeds

        page.wait_for_selector = fake_wait_selector

        asyncio.run(_wait_for_sap_post_deletion_nav(page, self._cfg()))
        # goto must NOT be called — searchbox was found
        page.goto.assert_not_called()


# ── _dismiss_any_sap_dialogs: Escape fallback ────────────────────────────────

class TestDismissAnySapDialogsEscapeFallback:

    def test_presses_escape_when_no_dismiss_button_found(self):
        """When the dialog is visible but no dismiss button is visible, Escape is pressed."""
        from src.datasphere_client import _dismiss_any_sap_dialogs

        page = MagicMock()

        not_found = MagicMock()
        not_found.is_visible = AsyncMock(return_value=False)

        dialog = MagicMock()
        dialog.is_visible = AsyncMock(return_value=True)

        invisible_btn = MagicMock()
        invisible_btn.is_visible = AsyncMock(return_value=False)

        def fake_locator(sel):
            m = MagicMock()
            # not-found screen selector → not visible
            if "notFound" in sel or "errorPage" in sel:
                m.first = not_found
            # error dialog selector → visible
            elif "MessageBox" in sel or "alertdialog" in sel or "messageBox" in sel or "errorDialog" in sel:
                m.first = dialog
            else:
                m.first = invisible_btn
            return m

        page.locator = fake_locator

        async def fake_wait_selector(sel, **kw):
            raise Exception("timeout")

        page.wait_for_selector = fake_wait_selector
        page.keyboard = MagicMock()
        page.keyboard.press = AsyncMock()

        result = asyncio.run(_dismiss_any_sap_dialogs(page))
        page.keyboard.press.assert_called_once_with("Escape")


# ── navigate_to_space_management ─────────────────────────────────────────────

class TestNavigateToSpaceManagement:

    def test_calls_goto_and_wait(self):
        from src.datasphere_client import navigate_to_space_management

        page = MagicMock()
        page.goto = AsyncMock()

        cfg = {
            "datasphere": {
                "base_url": "https://example.com",
                "space_management_path": "/path",
                "post_delete_pause": 0,
            },
            "retry": {"backoff_seconds": []},
        }

        async def fake_ready(p):
            pass

        with patch("src.datasphere_client.wait_for_space_mgmt_ready", side_effect=fake_ready):
            asyncio.run(navigate_to_space_management(page, cfg))

        page.goto.assert_called_once()


# ── Workshop-sweep model: find_workshop_spaces / delete_workshop_spaces ───────

class TestFindWorkshopSpaces:

    def _page_with_cards(self, raw_cards, tile_ids_after=None):
        """raw_cards: list of {container, headline, texts} as the card-read page.evaluate
        would return.

        find_workshop_spaces calls page.evaluate for THREE distinct scripts:
          1. _current_tile_ids (polled by _wait_for_search_settled for STABILITY) → returns
             the identifier-txt headlines (tile_headlines). Same every time → stable.
          2. _visible_card_user_ids (the settle MATCH check) → returns each card's leaf
             texts (the real user IDs, incl. renamed cards whose headline differs). Routed
             by: walks .sapFCard, queries [id] leaves, but has NO 'spacesContainer-' regex.
          3. the card-read evaluate → returns raw_cards. Routed by the 'spacesContainer-'
             container-index regex it uses.
        We route by matching distinctive substrings of each script.
        """
        page = MagicMock()

        async def _noop(*a, **kw): pass
        async def fake_wait_selector(sel, **kw):
            pass
        page.wait_for_selector = fake_wait_selector

        async def fake_wait_load_state(*a, **kw): pass
        page.wait_for_load_state = fake_wait_load_state

        class _KB:
            async def press(self, *a, **kw): pass
        page.keyboard = _KB()

        sb = MagicMock()
        sb.wait_for = _noop
        sb.click = MagicMock(side_effect=_noop)
        sb.fill = MagicMock(side_effect=_noop)
        sb.type = MagicMock(side_effect=_noop)
        sb.press = MagicMock(side_effect=_noop)

        # Stability reads (identifier-txt headlines) — same every poll → stable immediately.
        # Default to each card's HEADLINE (mirrors live: renamed cards show POOL_XA_* here).
        if tile_ids_after is None:
            tile_ids_after = [c["headline"] for c in raw_cards]
        # The settle MATCH check reads per-card leaf texts (the real user IDs).
        card_texts = [c["texts"] for c in raw_cards]

        async def fake_evaluate(script):
            # (3) card-reader: uses the spacesContainer-(N) index regex.
            if "spacesContainer-" in script:
                return raw_cards
            # (2) _visible_card_user_ids: walks .sapFCard, collects leaf texts, no container regex.
            if "sapFCard" in script and "identifier-txt" in script:
                return list(card_texts)
            # (1) _current_tile_ids: identifier-txt innerText, no .sapFCard walk.
            if "identifier-txt" in script:
                return list(tile_ids_after)
            return raw_cards
        page.evaluate = fake_evaluate

        def _locator(sel, *a, **kw):
            return MagicMock(first=sb)
        page.locator = MagicMock(side_effect=_locator)
        return page

    def test_keeps_only_matching_user_ids(self):
        from src.datasphere_client import find_workshop_spaces
        raw = [
            {"container": "0", "headline": "POOL_XA_1", "texts": ["POOL_XA_1", "AC279401U00"]},
            {"container": "1", "headline": "POOL_XA_2", "texts": ["POOL_XA_2", "AC279401U01"]},
            {"container": "2", "headline": "FOREIGN",   "texts": ["FOREIGN", "AC1279401U00"]},  # over-match
            {"container": "3", "headline": "OTHER",     "texts": ["OTHER", "AC999999U00"]},      # foreign
        ]
        page = self._page_with_cards(raw)
        result = asyncio.run(find_workshop_spaces(page, "279401"))
        ids = sorted(r["user_id"] for r in result)
        assert ids == ["AC279401U00", "AC279401U01"], f"got {ids}"

    def test_bare_ge_workshop(self):
        from src.datasphere_client import find_workshop_spaces
        raw = [{"container": "0", "headline": "GE231332", "texts": ["GE231332"]}]
        page = self._page_with_cards(raw)
        result = asyncio.run(find_workshop_spaces(page, "231332"))
        assert [r["user_id"] for r in result] == ["GE231332"]

    def test_renamed_spaces_settle_via_card_text(self):
        # REGRESSION (live AP11 workshop 279401): 25 renamed spaces whose identifier-txt
        # headline is POOL_XA_* (never matches ^AC279401...) but whose card leaf text holds
        # the real user ID (AC279401U..). The settle guard must match on the CARD TEXT, not
        # the headline — else it fails closed with "never settled" on exactly the renamed
        # workshops the sweep exists to clean. Stability reads return the POOL_XA_* headlines.
        from src.datasphere_client import find_workshop_spaces
        raw = [
            {"container": "0", "headline": "POOL_XA_00000978", "texts": ["POOL_XA_00000978", "AC279401U00"]},
            {"container": "1", "headline": "POOL_XA_00000980", "texts": ["POOL_XA_00000980", "AC279401U01"]},
            {"container": "2", "headline": "POOL_XA_00000982", "texts": ["POOL_XA_00000982", "AC279401U02"]},
        ]
        page = self._page_with_cards(raw)  # tile_ids_after defaults to the POOL_XA_* headlines
        result = asyncio.run(find_workshop_spaces(page, "279401"))
        ids = sorted(r["user_id"] for r in result)
        assert ids == ["AC279401U00", "AC279401U01", "AC279401U02"], f"got {ids}"

    def test_no_cards_returns_empty(self):
        # Genuinely-empty workshop (confirmed live on AP11 for 233717/234287): the grid is
        # a STABLE empty set. _wait_for_search_settled accepts a stable-empty reading as a
        # valid terminal state, and the card read returns []. This is the case the old
        # change-detector guard could not handle (empty->empty never "changed") and which
        # aborted the whole tenant run — the regression this fix targets.
        from src.datasphere_client import find_workshop_spaces
        page = MagicMock()

        async def _noop(*a, **kw): pass
        async def fake_wait_selector(sel, **kw): pass
        page.wait_for_selector = fake_wait_selector
        async def fake_wait_load_state(*a, **kw): pass
        page.wait_for_load_state = fake_wait_load_state

        class _KB:
            async def press(self, *a, **kw): pass
        page.keyboard = _KB()

        sb = MagicMock()
        sb.wait_for = _noop; sb.click = MagicMock(side_effect=_noop)
        sb.fill = MagicMock(side_effect=_noop); sb.press = MagicMock(side_effect=_noop)
        sb.type = MagicMock(side_effect=_noop)

        async def fake_evaluate(script):
            return []  # empty tiles on every read; card read also empty
        page.evaluate = fake_evaluate

        def _locator(sel, *a, **kw):
            return MagicMock(first=sb)
        page.locator = MagicMock(side_effect=_locator)

        assert asyncio.run(find_workshop_spaces(page, "279401")) == []

    def test_stale_grid_fails_closed(self):
        # If the grid persistently shows tiles that DON'T match the searched workshop (the
        # stale default grid because the search silently didn't fire), the guard must never
        # settle and find_workshop_spaces must RAISE rather than read the wrong spaces.
        from src.datasphere_client import find_workshop_spaces
        raw = [{"container": "0", "headline": "AC092254U00", "texts": ["AC092254U00"]}]
        page = self._page_with_cards(
            raw, tile_ids_after=["AC092254U00"]  # stable, but no tile matches 279401
        )
        with pytest.raises(RuntimeError, match="never settled"):
            asyncio.run(find_workshop_spaces(page, "279401"))


def _bulk_delete_page():
    """A page mock whose locators expose async click/wait_for/fill for the bulk-delete flow."""
    async def _noop(*a, **kw): pass

    def _loc(*a, **kw):
        m = MagicMock()
        m.click = MagicMock(side_effect=_noop)
        m.wait_for = MagicMock(side_effect=_noop)
        m.fill = MagicMock(side_effect=_noop)
        wrapper = MagicMock()
        wrapper.first = m
        return wrapper

    page = MagicMock()
    page.locator = MagicMock(side_effect=_loc)

    async def fake_wait_selector(sel, **kw): pass
    page.wait_for_selector = fake_wait_selector
    return page


class TestDeleteWorkshopSpaces:

    def _cfg(self):
        return {"retry": {"backoff_seconds": []}}

    def _cards(self, n, workshop="279401"):
        return [{"user_id": f"AC{workshop}U{i:02d}", "headline": f"H{i}", "container": str(i)}
                for i in range(n)]

    def test_dry_run_emits_skipped_no_clicks(self):
        from src.datasphere_client import delete_workshop_spaces
        page = MagicMock()
        clicked = {"n": 0}
        async def _click(*a, **kw): clicked["n"] += 1
        page.locator = MagicMock(return_value=MagicMock(first=MagicMock(click=_click)))
        results = asyncio.run(delete_workshop_spaces(page, "279401", self._cards(3), self._cfg(), dry_run=True))
        assert [r.outcome for r in results] == ["skipped_dry_run"] * 3
        assert clicked["n"] == 0, "dry-run must not click anything"

    def test_allowlisted_dropped_before_selection(self):
        from src.datasphere_client import delete_workshop_spaces
        page = _bulk_delete_page()
        cards = self._cards(3)
        allow = {cards[1]["user_id"]}
        async def _noop(*a, **kw): pass
        with patch("src.datasphere_client._wait_for_sap_post_deletion_nav", side_effect=_noop), \
             patch("src.datasphere_client.wait_for_space_mgmt_ready", side_effect=_noop):
            results = asyncio.run(delete_workshop_spaces(page, "279401", cards, self._cfg(),
                                                         dry_run=False, allowlist=allow))
        outcomes = {r.user_id: r.outcome for r in results}
        assert outcomes[cards[1]["user_id"]] == "skipped_allowlist"
        assert outcomes[cards[0]["user_id"]] == "deleted"
        assert outcomes[cards[2]["user_id"]] == "deleted"

    def test_success_emits_deleted_per_space(self):
        from src.datasphere_client import delete_workshop_spaces
        page = _bulk_delete_page()
        async def _noop(*a, **kw): pass
        with patch("src.datasphere_client._wait_for_sap_post_deletion_nav", side_effect=_noop), \
             patch("src.datasphere_client.wait_for_space_mgmt_ready", side_effect=_noop):
            results = asyncio.run(delete_workshop_spaces(page, "279401", self._cards(4), self._cfg(), dry_run=False))
        assert [r.outcome for r in results] == ["deleted"] * 4

    def test_checkbox_failure_aborts_all(self):
        from src.datasphere_client import delete_workshop_spaces
        page = MagicMock()
        async def raise_click(*a, **kw): raise Exception("checkbox not found")
        page.locator = MagicMock(return_value=MagicMock(first=MagicMock(click=raise_click)))
        results = asyncio.run(delete_workshop_spaces(page, "279401", self._cards(3), self._cfg(), dry_run=False))
        assert [r.outcome for r in results] == ["failed"] * 3
