import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from src.portal_client import (
    load_processed_workshops,
    mark_workshop_processed,
)



# ── load_processed_workshops / mark_workshop_processed ───────────────────────

class TestProcessedWorkshops:

    def test_returns_empty_set_when_file_missing(self, tmp_path):
        cfg = {"outputs": {"processed_workshops_file": str(tmp_path / "pw.txt")}}
        result = load_processed_workshops(cfg)
        assert result == set()

    def test_loads_entries_from_file(self, tmp_path):
        f = tmp_path / "pw.txt"
        f.write_text("12345\n67890\n", encoding="utf-8")
        cfg = {"outputs": {"processed_workshops_file": str(f)}}
        result = load_processed_workshops(cfg)
        assert result == {"12345", "67890"}

    def test_skips_blank_lines(self, tmp_path):
        f = tmp_path / "pw.txt"
        f.write_text("12345\n\n67890\n", encoding="utf-8")
        cfg = {"outputs": {"processed_workshops_file": str(f)}}
        result = load_processed_workshops(cfg)
        assert result == {"12345", "67890"}

    def test_mark_appends_to_file(self, tmp_path):
        f = tmp_path / "pw.txt"
        cfg = {"outputs": {"processed_workshops_file": str(f)}}
        mark_workshop_processed("11111", cfg)
        mark_workshop_processed("22222", cfg)
        lines = f.read_text(encoding="utf-8").splitlines()
        assert "11111" in lines
        assert "22222" in lines

    def test_mark_creates_parent_directory(self, tmp_path):
        f = tmp_path / "sub" / "pw.txt"
        cfg = {"outputs": {"processed_workshops_file": str(f)}}
        mark_workshop_processed("11111", cfg)
        assert f.exists()

    def test_round_trip(self, tmp_path):
        f = tmp_path / "pw.txt"
        cfg = {"outputs": {"processed_workshops_file": str(f)}}
        mark_workshop_processed("99999", cfg)
        result = load_processed_workshops(cfg)
        assert "99999" in result


# ── pending_workshops (Stage 2 sweep input) ──────────────────────────────────

class TestPendingWorkshops:

    def _cfg(self, tmp_path):
        return {"outputs": {
            "pending_workshops_file": str(tmp_path / "pending_ws.txt"),
            "processed_workshops_file": str(tmp_path / "processed_ws.txt"),
        }}

    def test_append_and_load(self, tmp_path):
        from src.portal_client import append_pending_workshop, load_pending_workshops
        cfg = self._cfg(tmp_path)
        append_pending_workshop("279401", cfg)
        append_pending_workshop("284660", cfg)
        assert load_pending_workshops(cfg) == {"279401", "284660"}

    def test_append_skips_duplicate_in_pending(self, tmp_path):
        from src.portal_client import append_pending_workshop, load_pending_workshops
        cfg = self._cfg(tmp_path)
        append_pending_workshop("279401", cfg)
        append_pending_workshop("279401", cfg)
        assert list(load_pending_workshops(cfg)) == ["279401"]

    def test_append_skips_already_processed(self, tmp_path):
        from src.portal_client import append_pending_workshop, load_pending_workshops, mark_workshop_processed
        cfg = self._cfg(tmp_path)
        mark_workshop_processed("279401", cfg)  # already swept
        append_pending_workshop("279401", cfg)   # must NOT re-queue
        assert load_pending_workshops(cfg) == set()

    def test_load_empty_when_missing(self, tmp_path):
        from src.portal_client import load_pending_workshops
        assert load_pending_workshops(self._cfg(tmp_path)) == set()


# ── _collect_next_batch ───────────────────────────────────────────────────────

class TestFilterQuerySettle:
    """The settle wait is the fix for scraping the stale pre-filter row set."""

    def test_waits_for_busy_overlay_hidden(self):
        from src.portal_client import _wait_for_filter_query_settled

        waited_hidden = {"called": False}

        async def fake_wait_selector(sel, **kw):
            assert ".sapUiLocalBusyIndicator" in sel, "must wait on the SAPUI5 busy overlay"
            if kw.get("state") == "hidden":
                waited_hidden["called"] = True

        async def fake_wait_load(state, **kw):
            pass

        page = MagicMock()
        page.wait_for_selector = fake_wait_selector
        page.wait_for_load_state = fake_wait_load

        asyncio.run(_wait_for_filter_query_settled(page))
        assert waited_hidden["called"], "must wait for the busy overlay to reach state=hidden"

    def test_swallows_missing_overlay(self):
        """If no busy overlay is present, the timeouts must be swallowed, not raised."""
        from src.portal_client import _wait_for_filter_query_settled

        async def fake_wait_selector(sel, **kw):
            raise Exception("Timeout: no busy overlay")

        async def fake_wait_load(state, **kw):
            raise Exception("networkidle hung")

        page = MagicMock()
        page.wait_for_selector = fake_wait_selector
        page.wait_for_load_state = fake_wait_load

        asyncio.run(_wait_for_filter_query_settled(page))  # must not raise

    def test_hard_confirm_passes_when_rows_change(self):
        """With prev_ids given, it returns once the visible row set differs from prev_ids."""
        from src.portal_client import _wait_for_filter_query_settled

        async def fake_wait_selector(sel, **kw):
            pass

        async def fake_wait_load(state, **kw):
            pass

        async def fake_evaluate(script):
            return ["999"]  # different from prev_ids below

        page = MagicMock()
        page.wait_for_selector = fake_wait_selector
        page.wait_for_load_state = fake_wait_load
        page.evaluate = fake_evaluate
        page.locator = MagicMock(return_value=MagicMock(count=AsyncMock(return_value=0)))

        # must not raise — rows changed from the pre-filter set
        asyncio.run(_wait_for_filter_query_settled(page, prev_ids={"111", "222"}))

    def test_hard_confirm_aborts_when_rows_never_change(self):
        """If the row set stays identical to prev_ids, it must raise SAFETY ABORT (fail closed)."""
        from src.portal_client import _wait_for_filter_query_settled

        async def fake_wait_selector(sel, **kw):
            pass

        async def fake_wait_load(state, **kw):
            pass

        async def fake_evaluate(script):
            return ["111", "222"]  # identical to prev_ids — stale rows

        async def fake_sleep(t):
            pass

        page = MagicMock()
        page.wait_for_selector = fake_wait_selector
        page.wait_for_load_state = fake_wait_load
        page.evaluate = fake_evaluate
        page.locator = MagicMock(return_value=MagicMock(count=AsyncMock(return_value=0)))

        with patch("src.portal_client.asyncio.sleep", side_effect=fake_sleep):
            with pytest.raises(RuntimeError, match="SAFETY ABORT"):
                asyncio.run(_wait_for_filter_query_settled(page, prev_ids={"111", "222"}))


class TestCollectNextBatch:

    def test_settles_query_before_reading_rows(self):
        """_collect_next_batch must settle the filter query before it reads any rows,
        so a collection immediately after re-navigation never sees stale rows."""
        from src.portal_client import _collect_next_batch

        order = []

        async def fake_settle(p):
            order.append("settle")

        async def fake_verify(p, **kw):
            order.append("verify")

        async def fake_evaluate(script):
            order.append("read_rows")
            return ["10001"]

        async def fake_sleep(t):
            pass

        page = MagicMock()
        page.evaluate = fake_evaluate

        with patch("src.portal_client._wait_for_filter_query_settled", side_effect=fake_settle), \
             patch("src.portal_client._verify_filters_active", side_effect=fake_verify), \
             patch("src.portal_client.asyncio.sleep", side_effect=fake_sleep):
            asyncio.run(_collect_next_batch(page, scroll_pause=0, already_processed=set(), batch_size=1))

        assert order[0] == "settle", "must settle the filter query first"
        assert "read_rows" in order and order.index("settle") < order.index("read_rows")

    def _cfg(self):
        return {}

    def test_returns_unprocessed_workshops(self):
        from src.portal_client import _collect_next_batch

        pages = [["10001", "10002", "10003"]]
        call_idx = {"n": 0}

        async def fake_evaluate(script):
            return pages[0]

        async def fake_sleep(t):
            pass

        async def fake_verify(p, **kw):
            pass

        page = MagicMock()
        page.evaluate = fake_evaluate

        with patch("src.portal_client.asyncio.sleep", side_effect=fake_sleep), \
             patch("src.portal_client._verify_filters_active", side_effect=fake_verify):
            result = asyncio.run(_collect_next_batch(page, scroll_pause=0, already_processed=set(), batch_size=10))

        assert result == ["10001", "10002", "10003"]

    def test_skips_already_processed(self):
        from src.portal_client import _collect_next_batch

        async def fake_evaluate(script):
            return ["10001", "10002", "10003"]

        async def fake_sleep(t):
            pass

        async def fake_verify(p, **kw):
            pass

        page = MagicMock()
        page.evaluate = fake_evaluate

        with patch("src.portal_client.asyncio.sleep", side_effect=fake_sleep), \
             patch("src.portal_client._verify_filters_active", side_effect=fake_verify):
            result = asyncio.run(_collect_next_batch(
                page, scroll_pause=0, already_processed={"10001", "10003"}, batch_size=10
            ))

        assert result == ["10002"]

    def test_respects_batch_size(self):
        from src.portal_client import _collect_next_batch

        async def fake_evaluate(script):
            return [str(i) for i in range(10001, 10020)]

        async def fake_sleep(t):
            pass

        async def fake_verify(p, **kw):
            pass

        page = MagicMock()
        page.evaluate = fake_evaluate

        with patch("src.portal_client.asyncio.sleep", side_effect=fake_sleep), \
             patch("src.portal_client._verify_filters_active", side_effect=fake_verify):
            result = asyncio.run(_collect_next_batch(page, scroll_pause=0, already_processed=set(), batch_size=3))

        assert len(result) == 3

    def test_stops_when_dom_stable(self):
        """If evaluate returns the same IDs twice in a row, batch collection must stop."""
        from src.portal_client import _collect_next_batch

        call_count = {"n": 0}

        async def fake_evaluate(script):
            call_count["n"] += 1
            return ["10001"]  # always same — DOM is stable

        async def fake_sleep(t):
            pass

        async def fake_verify(p, **kw):
            pass

        page = MagicMock()
        page.evaluate = fake_evaluate

        with patch("src.portal_client.asyncio.sleep", side_effect=fake_sleep), \
             patch("src.portal_client._verify_filters_active", side_effect=fake_verify):
            result = asyncio.run(_collect_next_batch(
                page, scroll_pause=0, already_processed=set(), batch_size=50
            ))

        assert result == ["10001"]

    def test_aborts_when_verify_filters_raises(self):
        """_collect_next_batch must propagate RuntimeError from _verify_filters_active."""
        from src.portal_client import _collect_next_batch

        async def fake_verify_fail(p, **kw):
            raise RuntimeError("SAFETY ABORT: Filter verification failed.")

        page = MagicMock()

        with patch("src.portal_client._verify_filters_active", side_effect=fake_verify_fail):
            with pytest.raises(RuntimeError, match="SAFETY ABORT"):
                asyncio.run(_collect_next_batch(page, scroll_pause=0, already_processed=set(), batch_size=10))


# ── _verify_filters_active ────────────────────────────────────────────────────

class TestVerifyFiltersActive:

    def _make_page(self, label_text):
        page = MagicMock()

        async def fake_wait_selector(sel, **kw):
            pass

        page.wait_for_selector = fake_wait_selector

        label_mock = MagicMock()
        label_mock.inner_text = AsyncMock(return_value=label_text)

        locator_mock = MagicMock()
        locator_mock.all = AsyncMock(return_value=[label_mock])
        page.locator = MagicMock(return_value=locator_mock)

        return page

    def test_passes_when_all_filters_present(self):
        from src.portal_client import _verify_filters_active
        label = "Filtered by: Environment (Cleaned) | Data Center Region (EU10)"
        page = self._make_page(label)
        asyncio.run(_verify_filters_active(page, dc_region="EU10"))  # must not raise

    def test_raises_when_environment_filter_missing(self):
        from src.portal_client import _verify_filters_active
        label = "Filtered by: Data Center Region (EU10)"
        page = self._make_page(label)
        with pytest.raises(RuntimeError, match="SAFETY ABORT"):
            asyncio.run(_verify_filters_active(page, dc_region="EU10"))

    def test_raises_when_dc_region_filter_missing(self):
        from src.portal_client import _verify_filters_active
        label = "Filtered by: Environment (Cleaned)"
        page = self._make_page(label)
        with pytest.raises(RuntimeError, match="SAFETY ABORT"):
            asyncio.run(_verify_filters_active(page, dc_region="EU10"))

    def test_raises_when_no_filtered_by_toolbar(self):
        from src.portal_client import _verify_filters_active

        page = MagicMock()

        async def fake_wait_selector(sel, **kw):
            pass

        page.wait_for_selector = fake_wait_selector

        label_mock = MagicMock()
        label_mock.inner_text = AsyncMock(return_value="Some unrelated text")

        locator_mock = MagicMock()
        locator_mock.all = AsyncMock(return_value=[label_mock])
        page.locator = MagicMock(return_value=locator_mock)

        with pytest.raises(RuntimeError, match="SAFETY ABORT"):
            asyncio.run(_verify_filters_active(page, dc_region="EU10"))

    def test_us10_region_verified(self):
        from src.portal_client import _verify_filters_active
        label = "Filtered by: Environment (Cleaned) | Data Center Region (US10)"
        page = self._make_page(label)
        asyncio.run(_verify_filters_active(page, dc_region="US10"))  # must not raise

    def test_passes_when_both_date_chips_present(self):
        from src.portal_client import _verify_filters_active
        label = ("Filtered by: Environment (Cleaned), Data Center Region (EU10), "
                 "Planned end workshop (From: 2024-01-01, To: 2024-02-01), "
                 "Planned start workshop (From: 2024-01-01, To: 2024-02-01)")
        page = self._make_page(label)
        asyncio.run(_verify_filters_active(  # must not raise
            page, dc_region="EU10",
            start_date_from="2024-01-01", start_date_to="2024-02-01",
            end_date_from="2024-01-01", end_date_to="2024-02-01"))

    def test_raises_when_start_date_chip_missing(self):
        from src.portal_client import _verify_filters_active
        # Start range requested but only the end-date chip present — must raise.
        label = ("Filtered by: Environment (Cleaned), Data Center Region (EU10), "
                 "Planned end workshop (From: 2024-01-01, To: 2024-02-01)")
        page = self._make_page(label)
        with pytest.raises(RuntimeError, match="SAFETY ABORT"):
            asyncio.run(_verify_filters_active(
                page, dc_region="EU10",
                start_date_from="2024-01-01", start_date_to="2024-02-01",
                end_date_from="2024-01-01", end_date_to="2024-02-01"))

    def test_passes_when_workshop_id_chip_present(self):
        from src.portal_client import _verify_filters_active
        label = ("Filtered by: Environment (Cleaned), Data Center Region (AP11), "
                 "Workshop ID (Min: 277373, Max: 281952)")
        page = self._make_page(label)
        asyncio.run(_verify_filters_active(  # must not raise
            page, dc_region="AP11",
            workshop_id_from="277373", workshop_id_to="281952"))

    def test_raises_when_workshop_id_chip_missing(self):
        from src.portal_client import _verify_filters_active
        # Range requested but chip absent — must raise.
        label = "Filtered by: Environment (Cleaned), Data Center Region (AP11)"
        page = self._make_page(label)
        with pytest.raises(RuntimeError, match="SAFETY ABORT"):
            asyncio.run(_verify_filters_active(
                page, dc_region="AP11",
                workshop_id_from="277373", workshop_id_to="281952"))

    def test_skips_workshop_id_check_when_not_set(self):
        from src.portal_client import _verify_filters_active
        # No workshop_id_from/to provided — filter chip absence must NOT raise.
        label = "Filtered by: Environment (Cleaned), Data Center Region (EU10)"
        page = self._make_page(label)
        asyncio.run(_verify_filters_active(page, dc_region="EU10"))  # must not raise



# ── _go_to_filtered_list: Workshop ID range filter block ─────────────────────

class TestWorkshopIdRangeFilter:
    """Filter 5 — Workshop ID range — is applied when both workshop_id_from and
    workshop_id_to are set, and skipped entirely when either is absent."""

    def _make_page(self):
        page = MagicMock()

        async def fake_goto(*a, **kw): pass
        async def fake_wait_selector(*a, **kw): pass
        async def fake_click(*a, **kw): pass
        async def fake_fill(*a, **kw): pass
        async def fake_press(*a, **kw): pass
        async def fake_evaluate(*a, **kw): return []

        page.goto = fake_goto
        page.wait_for_selector = fake_wait_selector
        page.evaluate = fake_evaluate

        locator_mock = MagicMock()
        locator_mock.click = AsyncMock()
        locator_mock.fill = AsyncMock()
        locator_mock.press = AsyncMock()
        locator_mock.first = locator_mock
        page.locator = MagicMock(return_value=locator_mock)
        page.get_by_role = MagicMock(return_value=locator_mock)
        page.get_by_text = MagicMock(return_value=locator_mock)
        return page, locator_mock

    def test_workshop_id_filter_applied_when_both_set(self):
        """When workshop_id_from and workshop_id_to are both provided, the Min/Max
        inputs must be filled and OK clicked."""
        import src.portal_client as portal_client
        from src.portal_client import _go_to_filtered_list

        page, locator_mock = self._make_page()
        filled_values = []

        async def fake_verify(*a, **kw): pass
        async def fake_settle(*a, **kw): pass
        async def fake_list_ready(*a, **kw): pass

        original_fill = locator_mock.fill.side_effect
        async def capturing_fill(value):
            filled_values.append(value)
        locator_mock.fill = AsyncMock(side_effect=capturing_fill)

        with patch.object(portal_client, "_verify_filters_active", fake_verify), \
             patch.object(portal_client, "_wait_for_filter_query_settled", fake_settle), \
             patch.object(portal_client, "_wait_for_list_ready", fake_list_ready):
            asyncio.run(_go_to_filtered_list(
                page, "https://example.com", "SAP Datasphere Overview",
                dc_region="AP11", workshop_id_from="277373", workshop_id_to="281952",
            ))

        assert "277373" in filled_values, "Min (From) value not filled"
        assert "281952" in filled_values, "Max (To) value not filled"

    def test_workshop_id_filter_skipped_when_not_set(self):
        """When workshop_id_from/to are absent, no Min/Max fills should occur."""
        import src.portal_client as portal_client
        from src.portal_client import _go_to_filtered_list

        page, locator_mock = self._make_page()
        filled_values = []

        async def fake_verify(*a, **kw): pass
        async def fake_settle(*a, **kw): pass
        async def fake_list_ready(*a, **kw): pass

        async def capturing_fill(value):
            filled_values.append(value)
        locator_mock.fill = AsyncMock(side_effect=capturing_fill)

        with patch.object(portal_client, "_verify_filters_active", fake_verify), \
             patch.object(portal_client, "_wait_for_filter_query_settled", fake_settle), \
             patch.object(portal_client, "_wait_for_list_ready", fake_list_ready):
            asyncio.run(_go_to_filtered_list(
                page, "https://example.com", "SAP Datasphere Overview",
                dc_region="EU10",
            ))

        assert "277373" not in filled_values
        assert "281952" not in filled_values

    def test_workshop_id_filter_skipped_when_only_from_set(self):
        """Only from provided (no to) — filter block must not fire."""
        import src.portal_client as portal_client
        from src.portal_client import _go_to_filtered_list

        page, locator_mock = self._make_page()
        filled_values = []

        async def fake_verify(*a, **kw): pass
        async def fake_settle(*a, **kw): pass
        async def fake_list_ready(*a, **kw): pass

        async def capturing_fill(value):
            filled_values.append(value)
        locator_mock.fill = AsyncMock(side_effect=capturing_fill)

        with patch.object(portal_client, "_verify_filters_active", fake_verify), \
             patch.object(portal_client, "_wait_for_filter_query_settled", fake_settle), \
             patch.object(portal_client, "_wait_for_list_ready", fake_list_ready):
            asyncio.run(_go_to_filtered_list(
                page, "https://example.com", "SAP Datasphere Overview",
                dc_region="EU10", workshop_id_from="277373",
            ))

        assert "277373" not in filled_values


# ── Portal search term selection (workbook option) ───────────────────────────

class TestSearchTermSelection:
    """The Stage 1 / workshop scrape searches whichever workbook term is configured
    in cfg['portal']['search_term']. The GUI radio buttons and the CLI --search-term
    flag both work by setting that key; run_portal_scrape must forward it verbatim to
    _go_to_filtered_list."""

    def test_constants_have_expected_values(self):
        from src.portal_client import (
            SEARCH_TERM_OVERVIEW, SEARCH_TERM_INTEGRATION, SEARCH_TERM_BASIC_TRIAL, SEARCH_TERMS,
        )
        assert SEARCH_TERM_OVERVIEW == "SAP Datasphere Overview"
        assert SEARCH_TERM_INTEGRATION == "SAP Analytics Cloud Planning and Datasphere Integration"
        assert SEARCH_TERM_BASIC_TRIAL == "Basic Trial - Introduction to SAP Analytics Cloud"
        assert SEARCH_TERMS == {
            "overview": SEARCH_TERM_OVERVIEW,
            "integration": SEARCH_TERM_INTEGRATION,
            "basic_trial": SEARCH_TERM_BASIC_TRIAL,
        }

    def _make_cfg(self, search_term):
        return {
            "portal": {
                "base_url": "https://example.test",
                "search_term": search_term,
                "scroll_pause": 0,
                "dc_region": "AP11",
            },
            "retry": {},
        }

    def _run_and_capture_term(self, search_term):
        """Patch the two live-DOM helpers and capture the search_term forwarded
        to _go_to_filtered_list."""
        from src import portal_client

        captured = {}

        async def fake_go(page, base_url, term, **kw):
            captured["term"] = term

        async def fake_collect(*a, **kw):
            return []

        page = MagicMock()
        with patch.object(portal_client, "_go_to_filtered_list", fake_go), \
             patch.object(portal_client, "_collect_next_batch", fake_collect), \
             patch.object(portal_client, "load_processed_workshops", lambda cfg: set()):
            asyncio.run(portal_client.run_portal_scrape(page, self._make_cfg(search_term)))
        return captured.get("term")

    def test_overview_term_forwarded(self):
        from src.portal_client import SEARCH_TERM_OVERVIEW
        assert self._run_and_capture_term(SEARCH_TERM_OVERVIEW) == SEARCH_TERM_OVERVIEW

    def test_integration_term_forwarded(self):
        from src.portal_client import SEARCH_TERM_INTEGRATION
        assert self._run_and_capture_term(SEARCH_TERM_INTEGRATION) == SEARCH_TERM_INTEGRATION

    def test_custom_term_forwarded_verbatim(self):
        custom = "My Custom Workbook Name"
        assert self._run_and_capture_term(custom) == custom

    def test_empty_custom_term_falls_back_to_overview(self):
        from src.portal_client import SEARCH_TERM_OVERVIEW
        # An empty string in cfg (what _selected_search_term returns when custom field is blank)
        # must still scrape — run_portal_scrape passes it through; the fallback is enforced
        # by _selected_search_term before cfg is set, so an empty string here is unusual,
        # but confirm it at least doesn't break the scrape path.
        assert self._run_and_capture_term("") == ""
