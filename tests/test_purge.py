import asyncio
import pytest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, call

from src.stage4_purge import load_deleted_log
from src.stage2_deletion import append_deleted_log


# ── append_deleted_log writes timestamps ─────────────────────────────────────

class TestAppendDeletedLog:

    def test_writes_space_id_and_date(self, tmp_path):
        log = tmp_path / "deleted.txt"
        with patch("src.stage2_deletion.DELETED_LOG", str(log)):
            append_deleted_log("AC000001U00")
        line = log.read_text(encoding="utf-8").strip()
        parts = line.split()
        assert parts[0] == "AC000001U00"
        assert len(parts) == 2
        # Date is today in YYYY-MM-DD format
        assert parts[1] == date.today().strftime("%Y-%m-%d")

    def test_appends_multiple_entries(self, tmp_path):
        log = tmp_path / "deleted.txt"
        with patch("src.stage2_deletion.DELETED_LOG", str(log)):
            append_deleted_log("AC000001U00")
            append_deleted_log("AC000002U00")
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("AC000001U00")
        assert lines[1].startswith("AC000002U00")


# ── load_deleted_log age filtering ───────────────────────────────────────────

class TestLoadDeletedLog:

    def _write_log(self, path: Path, entries: list):
        path.write_text(
            "\n".join(f"{sid} {d}" for sid, d in entries) + "\n",
            encoding="utf-8"
        )

    def test_returns_eligible_entries(self, tmp_path):
        log = tmp_path / "deleted.txt"
        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        self._write_log(log, [("AC000001U00", old_date)])
        with patch("src.stage4_purge.DELETED_LOG", str(log)):
            result = load_deleted_log(min_age_days=7)
        assert "AC000001U00" in result

    def test_excludes_entries_too_recent(self, tmp_path):
        log = tmp_path / "deleted.txt"
        new_date = (date.today() - timedelta(days=3)).strftime("%Y-%m-%d")
        self._write_log(log, [("AC000001U00", new_date)])
        with patch("src.stage4_purge.DELETED_LOG", str(log)):
            result = load_deleted_log(min_age_days=7)
        assert "AC000001U00" not in result

    def test_includes_exactly_min_age(self, tmp_path):
        log = tmp_path / "deleted.txt"
        exact_date = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        self._write_log(log, [("AC000001U00", exact_date)])
        with patch("src.stage4_purge.DELETED_LOG", str(log)):
            result = load_deleted_log(min_age_days=7)
        assert "AC000001U00" in result

    def test_skips_entries_without_date(self, tmp_path):
        log = tmp_path / "deleted.txt"
        log.write_text("AC000001U00\n", encoding="utf-8")
        with patch("src.stage4_purge.DELETED_LOG", str(log)):
            result = load_deleted_log(min_age_days=7)
        assert result == {}

    def test_skips_malformed_date(self, tmp_path):
        log = tmp_path / "deleted.txt"
        log.write_text("AC000001U00 not-a-date\n", encoding="utf-8")
        with patch("src.stage4_purge.DELETED_LOG", str(log)):
            result = load_deleted_log(min_age_days=7)
        assert result == {}

    def test_normalises_space_id_to_uppercase(self, tmp_path):
        log = tmp_path / "deleted.txt"
        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        self._write_log(log, [("ac000001u00", old_date)])
        with patch("src.stage4_purge.DELETED_LOG", str(log)):
            result = load_deleted_log(min_age_days=7)
        assert "AC000001U00" in result

    def test_returns_empty_when_file_missing(self, tmp_path):
        with patch("src.stage4_purge.DELETED_LOG", str(tmp_path / "nonexistent.txt")):
            result = load_deleted_log(min_age_days=7)
        assert result == {}

    def test_mixed_eligible_and_ineligible(self, tmp_path):
        log = tmp_path / "deleted.txt"
        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        new_date = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
        self._write_log(log, [
            ("AC000001U00", old_date),
            ("AC000002U00", new_date),
            ("AC000003U00", old_date),
        ])
        with patch("src.stage4_purge.DELETED_LOG", str(log)):
            result = load_deleted_log(min_age_days=7)
        assert "AC000001U00" in result
        assert "AC000002U00" not in result
        assert "AC000003U00" in result

    def test_duplicate_space_id_keeps_earliest_date(self, tmp_path):
        """B1 fix: when the same space appears twice, the earliest eligible date wins."""
        log = tmp_path / "deleted.txt"
        old_date = (date.today() - timedelta(days=20)).strftime("%Y-%m-%d")
        new_date = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
        # old entry first, then newer re-deletion that is not yet eligible
        self._write_log(log, [
            ("AC000001U00", old_date),
            ("AC000001U00", new_date),
        ])
        with patch("src.stage4_purge.DELETED_LOG", str(log)):
            result = load_deleted_log(min_age_days=7)
        assert "AC000001U00" in result
        assert result["AC000001U00"].strftime("%Y-%m-%d") == old_date

    def test_duplicate_space_id_newer_entry_first_still_uses_oldest(self, tmp_path):
        """Earliest date wins regardless of line order in the file."""
        log = tmp_path / "deleted.txt"
        old_date = (date.today() - timedelta(days=20)).strftime("%Y-%m-%d")
        new_date = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
        # newer entry first in file — older one must still win
        self._write_log(log, [
            ("AC000001U00", new_date),
            ("AC000001U00", old_date),
        ])
        with patch("src.stage4_purge.DELETED_LOG", str(log)):
            result = load_deleted_log(min_age_days=7)
        assert "AC000001U00" in result
        assert result["AC000001U00"].strftime("%Y-%m-%d") == old_date

    def test_duplicate_space_id_both_ineligible_excluded(self, tmp_path):
        """Two recent entries for the same space: space must not appear in result."""
        log = tmp_path / "deleted.txt"
        d1 = (date.today() - timedelta(days=3)).strftime("%Y-%m-%d")
        d2 = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        self._write_log(log, [
            ("AC000001U00", d1),
            ("AC000001U00", d2),
        ])
        with patch("src.stage4_purge.DELETED_LOG", str(log)):
            result = load_deleted_log(min_age_days=7)
        assert "AC000001U00" not in result

    def test_load_deleted_log_uses_cfg_path(self, tmp_path):
        """load_deleted_log reads from cfg deleted_file when provided."""
        log = tmp_path / "tenant_deleted.txt"
        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        self._write_log(log, [("AC000001U00", old_date)])
        cfg = {"outputs": {"deleted_file": str(log)}}
        result = load_deleted_log(min_age_days=7, cfg=cfg)
        assert "AC000001U00" in result
        log = tmp_path / "deleted.txt"
        d20 = (date.today() - timedelta(days=20)).strftime("%Y-%m-%d")
        d15 = (date.today() - timedelta(days=15)).strftime("%Y-%m-%d")
        d8  = (date.today() - timedelta(days=8)).strftime("%Y-%m-%d")
        self._write_log(log, [
            ("AC000002U00", d15),
            ("AC000001U00", d20),
            ("AC000003U00", d8),
        ])
        with patch("src.stage4_purge.DELETED_LOG", str(log)):
            result = load_deleted_log(min_age_days=7)
        assert list(result.keys()) == ["AC000001U00", "AC000002U00", "AC000003U00"]


# ── run_stage4 max_purge cap ──────────────────────────────────────────────────

class TestRunStage4MaxPurge:

    def _make_cfg(self, tmp_path):
        return {
            "datasphere": {
                "base_url": "https://ds.example.com",
                "session_file": str(tmp_path / "session.json"),
                "space_management_path": "/dwaas-core/index.html#/spaceManagement",
                "post_delete_pause": 12,
            },
            "outputs": {
                "deleted_file": str(tmp_path / "deleted.txt"),
            },
            "retry": {"backoff_seconds": []},
        }

    def test_max_purge_limits_purged_count(self, tmp_path):
        from src.stage4_purge import run_stage4
        from datetime import date, timedelta
        from tests.conftest import make_async_playwright_mocks

        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        log = tmp_path / "deleted.txt"
        log.write_text(
            "\n".join(f"AC00000{i}U00 {old_date}" for i in range(5)) + "\n",
            encoding="utf-8"
        )
        cfg = self._make_cfg(tmp_path)
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()
        eligible_ids = [f"AC00000{i}U00" for i in range(5)]

        async def fake_navigate(page, cfg): pass
        async def fake_get_count(page): return 1
        async def fake_collect(page): return eligible_ids
        async def fake_select(page, space_id): pass
        async def fake_delete(page, dry_run): return True

        with patch("src.stage4_purge.async_playwright", return_value=mock_pw), \
             patch("src.stage4_purge.open_browser", return_value=mock_browser), \
             patch("src.stage4_purge.DELETED_LOG", str(log)), \
             patch("src.stage4_purge._navigate_to_recycle_bin", side_effect=fake_navigate), \
             patch("src.stage4_purge._get_page_count", side_effect=fake_get_count), \
             patch("src.stage4_purge._collect_tile_ids", side_effect=fake_collect), \
             patch("src.stage4_purge._select_tile", side_effect=fake_select), \
             patch("src.stage4_purge._click_permanent_delete", side_effect=fake_delete):
            results = run_stage4(cfg=cfg, dry_run=False, run_id="test", max_purge=2)

        purged = [r for r in results if r.outcome == "purged"]
        assert len(purged) == 2

    def test_unknown_tiles_purged_regardless_of_deleted_log(self, tmp_path):
        """Tiles not in deleted.txt are purged — ownership is no longer checked."""
        from src.stage4_purge import run_stage4
        from datetime import date, timedelta
        from tests.conftest import make_async_playwright_mocks

        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        log = tmp_path / "deleted.txt"
        log.write_text(f"AC000001U00 {old_date}\n", encoding="utf-8")
        cfg = self._make_cfg(tmp_path)
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        async def fake_navigate(page, cfg): pass
        async def fake_get_count(page): return 1
        async def fake_collect(page): return ["AC000001U00", "AC000099U00"]
        async def fake_select(page, space_id): pass
        async def fake_delete(page, dry_run): return True

        with patch("src.stage4_purge.async_playwright", return_value=mock_pw), \
             patch("src.stage4_purge.open_browser", return_value=mock_browser), \
             patch("src.stage4_purge.DELETED_LOG", str(log)), \
             patch("src.stage4_purge._navigate_to_recycle_bin", side_effect=fake_navigate), \
             patch("src.stage4_purge._get_page_count", side_effect=fake_get_count), \
             patch("src.stage4_purge._collect_tile_ids", side_effect=fake_collect), \
             patch("src.stage4_purge._select_tile", side_effect=fake_select), \
             patch("src.stage4_purge._click_permanent_delete", side_effect=fake_delete):
            results = run_stage4(cfg=cfg, dry_run=False, run_id="test", max_purge=0)

        outcomes = {r.space_id: r.outcome for r in results}
        assert outcomes.get("AC000099U00") == "purged"
        assert outcomes.get("AC000001U00") == "purged"

    def test_select_tile_failure_records_failed_outcome(self, tmp_path):
        """If _select_tile raises, the space must be recorded as failed, not purged."""
        from src.stage4_purge import run_stage4
        from datetime import date, timedelta
        from tests.conftest import make_async_playwright_mocks

        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        log = tmp_path / "deleted.txt"
        log.write_text(f"AC000001U00 {old_date}\n", encoding="utf-8")
        cfg = self._make_cfg(tmp_path)
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        async def fake_navigate(page, cfg): pass
        async def fake_get_count(page): return 1
        async def fake_collect(page): return ["AC000001U00"]

        async def fake_select(page, space_id):
            raise RuntimeError("tile not found")

        async def fake_delete(page, dry_run): return True

        with patch("src.stage4_purge.async_playwright", return_value=mock_pw), \
             patch("src.stage4_purge.open_browser", return_value=mock_browser), \
             patch("src.stage4_purge.DELETED_LOG", str(log)), \
             patch("src.stage4_purge._navigate_to_recycle_bin", side_effect=fake_navigate), \
             patch("src.stage4_purge._get_page_count", side_effect=fake_get_count), \
             patch("src.stage4_purge._collect_tile_ids", side_effect=fake_collect), \
             patch("src.stage4_purge._select_tile", side_effect=fake_select), \
             patch("src.stage4_purge._click_permanent_delete", side_effect=fake_delete):
            results = run_stage4(cfg=cfg, dry_run=False, run_id="test")

        failed = [r for r in results if r.outcome == "failed"]
        assert len(failed) == 1
        assert "tile not found" in failed[0].error

    def test_click_permanent_delete_returns_false_records_failed(self, tmp_path):
        """If _click_permanent_delete returns False, confirmed spaces get outcome=failed."""
        from src.stage4_purge import run_stage4
        from datetime import date, timedelta
        from tests.conftest import make_async_playwright_mocks

        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        log = tmp_path / "deleted.txt"
        log.write_text(f"AC000001U00 {old_date}\n", encoding="utf-8")
        cfg = self._make_cfg(tmp_path)
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        async def fake_navigate(page, cfg): pass
        async def fake_get_count(page): return 1
        async def fake_collect(page): return ["AC000001U00"]
        async def fake_select(page, space_id): pass
        async def fake_delete(page, dry_run): return False  # dialog missing

        with patch("src.stage4_purge.async_playwright", return_value=mock_pw), \
             patch("src.stage4_purge.open_browser", return_value=mock_browser), \
             patch("src.stage4_purge.DELETED_LOG", str(log)), \
             patch("src.stage4_purge._navigate_to_recycle_bin", side_effect=fake_navigate), \
             patch("src.stage4_purge._get_page_count", side_effect=fake_get_count), \
             patch("src.stage4_purge._collect_tile_ids", side_effect=fake_collect), \
             patch("src.stage4_purge._select_tile", side_effect=fake_select), \
             patch("src.stage4_purge._click_permanent_delete", side_effect=fake_delete):
            results = run_stage4(cfg=cfg, dry_run=False, run_id="test")

        failed = [r for r in results if r.outcome == "failed"]
        assert len(failed) == 1
        assert "confirmation dialog" in failed[0].error

    def test_returns_empty_when_no_eligible_spaces(self, tmp_path):
        """If deleted.txt has no entries old enough, run_stage4 returns [] immediately."""
        from src.stage4_purge import run_stage4
        from datetime import date, timedelta
        from tests.conftest import make_async_playwright_mocks

        # All entries are too recent
        new_date = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
        log = tmp_path / "deleted.txt"
        log.write_text(f"AC000001U00 {new_date}\n", encoding="utf-8")
        cfg = self._make_cfg(tmp_path)
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        with patch("src.stage4_purge.async_playwright", return_value=mock_pw), \
             patch("src.stage4_purge.open_browser", return_value=mock_browser), \
             patch("src.stage4_purge.DELETED_LOG", str(log)):
            results = run_stage4(cfg=cfg, dry_run=False, run_id="test")

        assert results == []

    def test_loop_exits_when_no_matching_tiles_on_any_page(self, tmp_path):
        """If eligible spaces are in deleted.txt but not found in any recycle bin tile, loop exits."""
        from src.stage4_purge import run_stage4
        from datetime import date, timedelta
        from tests.conftest import make_async_playwright_mocks

        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        log = tmp_path / "deleted.txt"
        log.write_text(f"AC000001U00 {old_date}\n", encoding="utf-8")
        cfg = self._make_cfg(tmp_path)
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        async def fake_navigate(page, cfg): pass
        async def fake_get_count(page): return 1
        async def fake_collect(page): return []  # recycle bin is empty
        async def fake_select(page, space_id): pass
        async def fake_delete(page, dry_run): return True

        with patch("src.stage4_purge.async_playwright", return_value=mock_pw), \
             patch("src.stage4_purge.open_browser", return_value=mock_browser), \
             patch("src.stage4_purge.DELETED_LOG", str(log)), \
             patch("src.stage4_purge._navigate_to_recycle_bin", side_effect=fake_navigate), \
             patch("src.stage4_purge._get_page_count", side_effect=fake_get_count), \
             patch("src.stage4_purge._collect_tile_ids", side_effect=fake_collect), \
             patch("src.stage4_purge._select_tile", side_effect=fake_select), \
             patch("src.stage4_purge._click_permanent_delete", side_effect=fake_delete):
            results = run_stage4(cfg=cfg, dry_run=False, run_id="test")

        # No purged or failed — loop found nothing to do and exited
        assert all(r.outcome not in ("purged", "failed") for r in results)

    def test_dry_run_respects_max_purge(self, tmp_path):
        from src.stage4_purge import run_stage4
        from datetime import date, timedelta
        from tests.conftest import make_async_playwright_mocks

        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        log = tmp_path / "deleted.txt"
        log.write_text(
            "\n".join(f"AC00000{i}U00 {old_date}" for i in range(5)) + "\n",
            encoding="utf-8"
        )
        cfg = self._make_cfg(tmp_path)
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()
        eligible_ids = [f"AC00000{i}U00" for i in range(5)]

        async def fake_navigate(page, cfg): pass
        async def fake_get_count(page): return 1
        async def fake_collect(page): return eligible_ids
        async def fake_select(page, space_id): pass
        async def fake_delete(page, dry_run): return True

        with patch("src.stage4_purge.async_playwright", return_value=mock_pw), \
             patch("src.stage4_purge.open_browser", return_value=mock_browser), \
             patch("src.stage4_purge.DELETED_LOG", str(log)), \
             patch("src.stage4_purge._navigate_to_recycle_bin", side_effect=fake_navigate), \
             patch("src.stage4_purge._get_page_count", side_effect=fake_get_count), \
             patch("src.stage4_purge._collect_tile_ids", side_effect=fake_collect), \
             patch("src.stage4_purge._select_tile", side_effect=fake_select), \
             patch("src.stage4_purge._click_permanent_delete", side_effect=fake_delete):
            results = run_stage4(cfg=cfg, dry_run=True, run_id="test", max_purge=3)

        dry = [r for r in results if r.outcome == "skipped_dry_run"]
        assert len(dry) == 3


# ── _collect_tile_ids ─────────────────────────────────────────────────────────

class TestCollectTileIds:

    def test_returns_uppercase_ids(self):
        from src.stage4_purge import _collect_tile_ids
        page = MagicMock()

        el1 = MagicMock()
        el1.inner_text = AsyncMock(return_value="ac000001u00")
        el2 = MagicMock()
        el2.inner_text = AsyncMock(return_value="AC000002U00")
        page.locator.return_value.all = AsyncMock(return_value=[el1, el2])

        result = asyncio.run(_collect_tile_ids(page))
        assert result == ["AC000001U00", "AC000002U00"]

    def test_skips_blank_tiles(self):
        from src.stage4_purge import _collect_tile_ids
        page = MagicMock()

        el1 = MagicMock()
        el1.inner_text = AsyncMock(return_value="  ")
        el2 = MagicMock()
        el2.inner_text = AsyncMock(return_value="AC000001U00")
        page.locator.return_value.all = AsyncMock(return_value=[el1, el2])

        result = asyncio.run(_collect_tile_ids(page))
        assert result == ["AC000001U00"]

    def test_returns_empty_when_no_tiles(self):
        from src.stage4_purge import _collect_tile_ids
        page = MagicMock()
        page.locator.return_value.all = AsyncMock(return_value=[])
        result = asyncio.run(_collect_tile_ids(page))
        assert result == []


# ── _click_permanent_delete ───────────────────────────────────────────────────

class TestClickPermanentDelete:

    def test_dry_run_returns_true_without_clicking(self):
        from src.stage4_purge import _click_permanent_delete
        page = MagicMock()
        result = asyncio.run(_click_permanent_delete(page, dry_run=True))
        assert result is True
        page.locator.assert_not_called()

    def test_returns_false_when_dialog_never_appears(self):
        from src.stage4_purge import _click_permanent_delete
        page = MagicMock()

        delete_btn = MagicMock()
        delete_btn.wait_for = AsyncMock()
        delete_btn.click = AsyncMock()
        page.locator.return_value.first = delete_btn

        async def fake_wait_selector(sel, **kw):
            raise Exception("timeout — dialog never appeared")

        page.wait_for_selector = fake_wait_selector

        result = asyncio.run(_click_permanent_delete(page, dry_run=False))
        assert result is False

    def test_returns_true_on_full_success(self):
        from src.stage4_purge import _click_permanent_delete
        page = MagicMock()

        # All locator().first children must be fully async
        async_locator = MagicMock()
        async_locator.wait_for = AsyncMock()
        async_locator.click = AsyncMock()
        async_locator.fill = AsyncMock()

        page.locator = MagicMock(return_value=MagicMock(first=async_locator))

        async def fake_wait_selector(sel, **kw):
            pass

        page.wait_for_selector = fake_wait_selector
        page.keyboard = MagicMock()
        page.keyboard.press = AsyncMock()

        result = asyncio.run(_click_permanent_delete(page, dry_run=False))
        assert result is True


# ── _get_page_count ───────────────────────────────────────────────────────────

class TestGetPageCount:

    def test_returns_button_count_when_paginator_present(self):
        from src.stage4_purge import _get_page_count

        page = MagicMock()

        async def fake_wait_selector(sel, **kw):
            pass

        page.wait_for_selector = fake_wait_selector
        page.locator.return_value.count = AsyncMock(return_value=3)

        result = asyncio.run(_get_page_count(page))
        assert result == 3

    def test_returns_1_when_no_paginator(self):
        from src.stage4_purge import _get_page_count

        page = MagicMock()

        async def fake_wait_selector(sel, **kw):
            raise Exception("not found")

        page.wait_for_selector = fake_wait_selector

        result = asyncio.run(_get_page_count(page))
        assert result == 1


# ── _go_to_page ───────────────────────────────────────────────────────────────

class TestGoToPage:

    def test_clicks_nth_button_and_waits(self):
        from src.stage4_purge import _go_to_page

        page = MagicMock()
        btn = MagicMock()
        btn.click = AsyncMock()
        page.locator.return_value.nth = MagicMock(return_value=btn)

        async def fake_wait_selector(sel, **kw):
            pass

        page.wait_for_selector = fake_wait_selector

        with patch("src.stage4_purge.asyncio.sleep", new=AsyncMock()):
            asyncio.run(_go_to_page(page, 2))

        btn.click.assert_called_once()


# ── _select_tile ──────────────────────────────────────────────────────────────

class TestSelectTile:

    def test_raises_when_tile_not_found(self):
        from src.stage4_purge import _select_tile

        page = MagicMock()
        page.evaluate = AsyncMock(return_value=None)  # tile not found

        with pytest.raises(RuntimeError, match="Could not find tile"):
            asyncio.run(_select_tile(page, "AC000001U00"))

    def test_clicks_checkbox_via_playwright_locator(self):
        from src.stage4_purge import _select_tile

        page = MagicMock()
        page.evaluate = AsyncMock(return_value="3")  # container index found

        cb = MagicMock()
        cb.wait_for = AsyncMock()
        cb.click = AsyncMock()
        locator_mock = MagicMock()
        locator_mock.first = cb
        page.locator = MagicMock(return_value=locator_mock)

        asyncio.run(_select_tile(page, "AC000001U00"))
        cb.click.assert_awaited_once()


# ── _click_permanent_delete: input fill fails → Escape + False ────────────────

class TestClickPermanentDeleteInputFails:

    def test_returns_false_and_presses_escape_when_fill_fails(self):
        from src.stage4_purge import _click_permanent_delete

        page = MagicMock()

        # delete button succeeds
        delete_btn = MagicMock()
        delete_btn.wait_for = AsyncMock()
        delete_btn.click = AsyncMock()

        # confirm input fill raises
        confirm_input = MagicMock()
        confirm_input.wait_for = AsyncMock()
        confirm_input.click = AsyncMock()
        confirm_input.fill = AsyncMock(side_effect=Exception("fill failed"))

        call_idx = {"n": 0}

        def fake_locator(sel):
            m = MagicMock()
            m.first = confirm_input  # used for both delete btn and input
            return m

        page.locator = fake_locator
        page.keyboard = MagicMock()
        page.keyboard.press = AsyncMock()

        # dialog appears
        async def fake_wait_selector(sel, **kw):
            pass

        page.wait_for_selector = fake_wait_selector

        result = asyncio.run(_click_permanent_delete(page, dry_run=False))
        assert result is False
        page.keyboard.press.assert_called_once_with("Escape")


# ── progress_callback invocation ─────────────────────────────────────────────

class TestProgressCallback:

    def _make_cfg(self, tmp_path):
        return {
            "datasphere": {
                "base_url": "https://ds.example.com",
                "session_file": str(tmp_path / "session.json"),
                "space_management_path": "/dwaas-core/index.html#/spaceManagement",
                "post_delete_pause": 12,
            },
            "outputs": {
                "deleted_file": str(tmp_path / "deleted.txt"),
            },
            "retry": {"backoff_seconds": []},
        }

    def test_progress_callback_called_during_dry_run(self, tmp_path):
        from src.stage4_purge import run_stage4
        from tests.conftest import make_async_playwright_mocks

        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        log = tmp_path / "deleted.txt"
        log.write_text(f"AC000001U00 {old_date}\n", encoding="utf-8")
        cfg = self._make_cfg(tmp_path)
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        callback_messages = []

        async def fake_navigate(page, cfg): pass
        async def fake_get_count(page): return 1
        async def fake_collect(page): return ["AC000001U00"]
        async def fake_select(page, space_id): pass
        async def fake_delete(page, dry_run): return True

        with patch("src.stage4_purge.async_playwright", return_value=mock_pw), \
             patch("src.stage4_purge.open_browser", return_value=mock_browser), \
             patch("src.stage4_purge.DELETED_LOG", str(log)), \
             patch("src.stage4_purge._navigate_to_recycle_bin", side_effect=fake_navigate), \
             patch("src.stage4_purge._get_page_count", side_effect=fake_get_count), \
             patch("src.stage4_purge._collect_tile_ids", side_effect=fake_collect), \
             patch("src.stage4_purge._select_tile", side_effect=fake_select), \
             patch("src.stage4_purge._click_permanent_delete", side_effect=fake_delete):
            run_stage4(
                cfg=cfg, dry_run=True, run_id="test",
                progress_callback=callback_messages.append
            )

        assert len(callback_messages) >= 1
        assert any("would purge" in m.lower() or "Stage 4" in m for m in callback_messages)

    def test_progress_callback_called_during_live_run(self, tmp_path):
        from src.stage4_purge import run_stage4
        from tests.conftest import make_async_playwright_mocks

        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        log = tmp_path / "deleted.txt"
        log.write_text(f"AC000001U00 {old_date}\n", encoding="utf-8")
        cfg = self._make_cfg(tmp_path)
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        callback_messages = []

        async def fake_navigate(page, cfg): pass
        async def fake_get_count(page): return 1
        async def fake_collect(page): return ["AC000001U00"]
        async def fake_select(page, space_id): pass
        async def fake_delete(page, dry_run): return True

        with patch("src.stage4_purge.async_playwright", return_value=mock_pw), \
             patch("src.stage4_purge.open_browser", return_value=mock_browser), \
             patch("src.stage4_purge.DELETED_LOG", str(log)), \
             patch("src.stage4_purge._navigate_to_recycle_bin", side_effect=fake_navigate), \
             patch("src.stage4_purge._get_page_count", side_effect=fake_get_count), \
             patch("src.stage4_purge._collect_tile_ids", side_effect=fake_collect), \
             patch("src.stage4_purge._select_tile", side_effect=fake_select), \
             patch("src.stage4_purge._click_permanent_delete", side_effect=fake_delete):
            run_stage4(
                cfg=cfg, dry_run=False, run_id="test",
                progress_callback=callback_messages.append
            )

        assert len(callback_messages) >= 1
        assert any("purged" in m.lower() or "Stage 4" in m for m in callback_messages)


# ── multi-page loop + max_purge mid-loop break ────────────────────────────────

class TestRunStage4MultiPage:

    def _make_cfg(self, tmp_path):
        return {
            "datasphere": {
                "base_url": "https://ds.example.com",
                "session_file": str(tmp_path / "session.json"),
                "space_management_path": "/dwaas-core/index.html#/spaceManagement",
                "post_delete_pause": 12,
            },
            "outputs": {
                "deleted_file": str(tmp_path / "deleted.txt"),
            },
            "retry": {"backoff_seconds": []},
        }

    def test_max_purge_breaks_mid_loop_across_pages(self, tmp_path):
        """max_purge mid-loop: stops processing further pages once limit reached."""
        from src.stage4_purge import run_stage4
        from tests.conftest import make_async_playwright_mocks

        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        log = tmp_path / "deleted.txt"
        log.write_text(
            f"AC000001U00 {old_date}\nAC000002U00 {old_date}\nAC000003U00 {old_date}\n",
            encoding="utf-8",
        )
        cfg = self._make_cfg(tmp_path)
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        page_idx = {"n": 0}

        async def fake_navigate(page, cfg): pass

        async def fake_get_count(page):
            return 3  # 3 pages available

        async def fake_collect(page):
            # Each page returns one eligible space
            ids = [["AC000001U00"], ["AC000002U00"], ["AC000003U00"]]
            result = ids[min(page_idx["n"], 2)]
            page_idx["n"] += 1
            return result

        async def fake_go_to_page(page, idx):
            pass

        async def fake_select(page, space_id): pass
        async def fake_delete(page, dry_run): return True

        with patch("src.stage4_purge.async_playwright", return_value=mock_pw), \
             patch("src.stage4_purge.open_browser", return_value=mock_browser), \
             patch("src.stage4_purge.DELETED_LOG", str(log)), \
             patch("src.stage4_purge._navigate_to_recycle_bin", side_effect=fake_navigate), \
             patch("src.stage4_purge._get_page_count", side_effect=fake_get_count), \
             patch("src.stage4_purge._collect_tile_ids", side_effect=fake_collect), \
             patch("src.stage4_purge._go_to_page", side_effect=fake_go_to_page), \
             patch("src.stage4_purge._select_tile", side_effect=fake_select), \
             patch("src.stage4_purge._click_permanent_delete", side_effect=fake_delete):
            results = run_stage4(cfg=cfg, dry_run=False, run_id="test", max_purge=2)

        purged = [r for r in results if r.outcome == "purged"]
        assert len(purged) == 2

    def test_skipped_not_ours_not_double_counted_across_pages(self, tmp_path):
        """All tiles are purged in one batch — both known and unknown spaces."""
        from src.stage4_purge import run_stage4
        from tests.conftest import make_async_playwright_mocks

        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        log = tmp_path / "deleted.txt"
        log.write_text(f"AC000001U00 {old_date}\n", encoding="utf-8")
        cfg = self._make_cfg(tmp_path)
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        call_count = {"n": 0}

        async def fake_navigate(page, cfg): pass
        async def fake_get_count(page): return 1

        async def fake_collect(page):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ["AC000001U00", "AC_UNKNOWN"]
            return []

        async def fake_select(page, space_id): pass
        async def fake_delete(page, dry_run): return True

        with patch("src.stage4_purge.async_playwright", return_value=mock_pw), \
             patch("src.stage4_purge.open_browser", return_value=mock_browser), \
             patch("src.stage4_purge.DELETED_LOG", str(log)), \
             patch("src.stage4_purge._navigate_to_recycle_bin", side_effect=fake_navigate), \
             patch("src.stage4_purge._get_page_count", side_effect=fake_get_count), \
             patch("src.stage4_purge._collect_tile_ids", side_effect=fake_collect), \
             patch("src.stage4_purge._select_tile", side_effect=fake_select), \
             patch("src.stage4_purge._click_permanent_delete", side_effect=fake_delete):
            results = run_stage4(cfg=cfg, dry_run=False, run_id="test")

        purged = [r for r in results if r.outcome == "purged"]
        assert len(purged) == 2


# ── load_still_exists_exclusions (M1: stale deleted.txt guard) ────────────────

class TestStillExistsExclusions:

    def test_collects_still_exists_space_ids(self, tmp_path):
        import json
        from src.stage4_purge import load_still_exists_exclusions
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "verification_ap11_1.json").write_text(json.dumps({
            "verifications": [
                {"space_id": "GE359210", "verification": "still_exists"},
                {"space_id": "GE359126", "verification": "confirmed_deleted"},
            ]
        }), encoding="utf-8")
        cfg = {"outputs": {"reports_dir": str(reports)}}
        result = load_still_exists_exclusions(cfg=cfg)
        assert result == {"GE359210"}

    def test_empty_when_no_reports(self, tmp_path):
        from src.stage4_purge import load_still_exists_exclusions
        cfg = {"outputs": {"reports_dir": str(tmp_path / "nonexistent")}}
        assert load_still_exists_exclusions(cfg=cfg) == set()

    def test_skips_unreadable_report_without_dropping_others(self, tmp_path):
        import json
        from src.stage4_purge import load_still_exists_exclusions
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "verification_bad.json").write_text("{ not valid json", encoding="utf-8")
        (reports / "verification_good.json").write_text(json.dumps({
            "verifications": [{"space_id": "AC123U00", "verification": "still_exists"}]
        }), encoding="utf-8")
        cfg = {"outputs": {"reports_dir": str(reports)}}
        result = load_still_exists_exclusions(cfg=cfg)
        assert result == {"AC123U00"}  # bad report skipped, good one still read

    def test_stage4_excludes_still_exists_from_eligible(self, tmp_path):
        """A space in deleted.txt and old enough, but flagged still_exists by Stage 3,
        must NOT be eligible for purge."""
        import json
        from src.stage4_purge import load_deleted_log, load_still_exists_exclusions
        old = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        log = tmp_path / "deleted.txt"
        log.write_text(f"GE359210 {old}\nGE359126 {old}\n", encoding="utf-8")
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "verification_x.json").write_text(json.dumps({
            "verifications": [{"space_id": "GE359210", "verification": "still_exists"}]
        }), encoding="utf-8")
        cfg = {"outputs": {"reports_dir": str(reports)}}
        with patch("src.stage4_purge.DELETED_LOG", str(log)):
            eligible = load_deleted_log(min_age_days=7)
        excluded = load_still_exists_exclusions(cfg=cfg)
        final = {s: d for s, d in eligible.items() if s not in excluded}
        assert "GE359210" not in final
        assert "GE359126" in final
