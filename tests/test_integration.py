"""
Integration tests for the three stage orchestrators.

All browser calls are mocked — these tests exercise the queue mechanics,
state-file transitions, and logic flow of run_stage1, run_stage2, run_stage3
without launching Playwright.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from src.datasphere_client import DeleteResult
from tests.conftest import make_async_playwright_mocks


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _stage2_cfg(tmp_path):
    return {
        "datasphere": {
            "base_url": "https://academy.eu10.hcs.cloud.sap",
            "session_file": str(tmp_path / "ds_session.json"),
            "space_management_path": "/dwaas-core/index.html#/spaceManagement",
            "post_delete_pause": 0,
        },
        "outputs": {
            "allowlist_file": str(tmp_path / "allowlist.txt"),
            "reports_dir": str(tmp_path / "reports"),
        },
        "circuit_breaker": {
            "failure_rate_threshold": 0.20,
            "min_attempts_before_trigger": 10,
        },
        "limits": {"max_deletions": 0},
        "retry": {"backoff_seconds": []},
    }


# ─────────────────────────────────────────────────────────────────────────────
# run_stage1 — orchestration
# ─────────────────────────────────────────────────────────────────────────────

class TestRunStage1:

    def _cfg(self, tmp_path):
        return {
            "portal": {
                "base_url": "https://portal.example.com",
                "session_file": str(tmp_path / "portal_session.json"),
                "search_term": "SAP Datasphere Overview",
                "scroll_pause": 0,
            },
            "outputs": {},
            "retry": {"backoff_seconds": []},
        }

    def test_run_stage1_calls_portal_scrape(self, tmp_path):
        from src.stage1_discovery import run_stage1
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        with patch("src.stage1_discovery.async_playwright", return_value=mock_pw), \
             patch("src.stage1_discovery.open_browser",    return_value=mock_browser), \
             patch("src.stage1_discovery.run_portal_scrape", return_value=[]) as mock_scrape:
            run_stage1(cfg=self._cfg(tmp_path), run_id="test_run")

        mock_scrape.assert_called_once()

    def test_already_processed_users_not_re_queued(self, tmp_path):
        from src.stage1_discovery import run_stage1
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()
        pending_path = tmp_path / "pending.txt"

        with patch("src.stage1_discovery.async_playwright", return_value=mock_pw), \
             patch("src.stage1_discovery.open_browser",    return_value=mock_browser), \
             patch("src.stage1_discovery.run_portal_scrape", return_value=[]):
            run_stage1(cfg=self._cfg(tmp_path), run_id="test_run")

        assert not pending_path.exists()

    def test_empty_scrape_does_not_modify_pending(self, tmp_path):
        from src.stage1_discovery import run_stage1
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()
        pending_path = tmp_path / "pending.txt"
        pending_path.write_text("AC000001U00\n", encoding="utf-8")

        with patch("src.stage1_discovery.async_playwright", return_value=mock_pw), \
             patch("src.stage1_discovery.open_browser",    return_value=mock_browser), \
             patch("src.stage1_discovery.run_portal_scrape", return_value=[]):
            run_stage1(cfg=self._cfg(tmp_path), run_id="test_run")

        assert "AC000001U00" in pending_path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# run_stage3 — verification counting
# ─────────────────────────────────────────────────────────────────────────────

class TestRunStage3:

    def _cfg(self, tmp_path):
        return {
            "datasphere": {
                "base_url": "https://academy.eu10.hcs.cloud.sap",
                "session_file": str(tmp_path / "ds_session.json"),
                "space_management_path": "/dwaas-core/index.html#/spaceManagement",
                "post_delete_pause": 0,
            },
            "outputs": {
                "reports_dir": str(tmp_path / "reports"),
            },
            "retry": {"backoff_seconds": []},
        }

    def _write_report(self, tmp_path, results):
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir(exist_ok=True)
        report = {
            "run_id": "source_run",
            "results": [
                {"user_id": r["user_id"], "space_id": r["space_id"], "outcome": r["outcome"]}
                for r in results
            ],
        }
        p = reports_dir / "report_source_run.json"
        p.write_text(json.dumps(report), encoding="utf-8")
        return str(p)

    def _run(self, tmp_path, report_results, space_still_exists_set):
        report_path = self._write_report(tmp_path, report_results)
        cfg = self._cfg(tmp_path)

        async def fake_verify(page, user_id, space_id, cfg=None):
            return space_id if space_id in space_still_exists_set else None

        async def fake_navigate(page, cfg):
            pass

        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        from src.stage3_verify import run_stage3

        with patch("src.stage3_verify.async_playwright",          return_value=mock_pw), \
             patch("src.stage3_verify.open_browser",              return_value=mock_browser), \
             patch("src.stage3_verify.navigate_to_space_management", side_effect=fake_navigate), \
             patch("src.stage3_verify.search_and_verify_space",   side_effect=fake_verify):
            verification_path = run_stage3(report_path=report_path, cfg=cfg, run_id="test_run")

        with open(verification_path, encoding="utf-8") as f:
            return json.load(f)

    def test_all_confirmed_deleted(self, tmp_path):
        results = [
            {"user_id": "AC000001U00", "space_id": "AC000001U00", "outcome": "deleted"},
            {"user_id": "AC000002U00", "space_id": "AC000002U00", "outcome": "deleted"},
        ]
        report = self._run(tmp_path, results, space_still_exists_set=set())
        assert report["summary"]["confirmed_deleted"] == 2
        assert report["summary"]["still_exists"] == 0

    def test_still_exists_counted_correctly(self, tmp_path):
        results = [
            {"user_id": "AC000001U00", "space_id": "AC000001U00", "outcome": "deleted"},
            {"user_id": "AC000002U00", "space_id": "AC000002U00", "outcome": "deleted"},
        ]
        report = self._run(tmp_path, results, space_still_exists_set={"AC000002U00"})
        assert report["summary"]["confirmed_deleted"] == 1
        assert report["summary"]["still_exists"] == 1

    def test_empty_report_produces_zero_counts(self, tmp_path):
        report_path = self._write_report(tmp_path, [])
        cfg = self._cfg(tmp_path)
        from src.stage3_verify import run_stage3
        verification_path = run_stage3(report_path=report_path, cfg=cfg, run_id="test_run")
        with open(verification_path, encoding="utf-8") as f:
            report = json.load(f)
        assert report["summary"]["total_verified"] == 0

    def test_non_deleted_outcomes_skipped(self, tmp_path):
        results = [
            {"user_id": "AC000001U00", "space_id": "AC000001U00", "outcome": "not_found"},
            {"user_id": "AC000002U00", "space_id": "AC000002U00", "outcome": "deleted"},
        ]
        report = self._run(tmp_path, results, space_still_exists_set=set())
        assert report["summary"]["total_verified"] == 1
        assert report["summary"]["confirmed_deleted"] == 1

    def test_progress_callback_on_normal_path(self, tmp_path):
        """Lines 89-92: progress_callback fires on confirmed_deleted and still_exists."""
        results = [
            {"user_id": "AC000001U00", "space_id": "AC000001U00", "outcome": "deleted"},
            {"user_id": "AC000002U00", "space_id": "AC000002U00", "outcome": "deleted"},
        ]
        report_path = self._write_report(tmp_path, results)
        cfg = self._cfg(tmp_path)

        async def fake_verify(page, user_id, space_id, cfg=None):
            return space_id if user_id == "AC000002U00" else None

        async def fake_navigate(page, cfg):
            pass

        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()
        progress_messages = []

        from src.stage3_verify import run_stage3

        with patch("src.stage3_verify.async_playwright",             return_value=mock_pw), \
             patch("src.stage3_verify.open_browser",                 return_value=mock_browser), \
             patch("src.stage3_verify.navigate_to_space_management", side_effect=fake_navigate), \
             patch("src.stage3_verify.search_and_verify_space",      side_effect=fake_verify):
            run_stage3(report_path=report_path, cfg=cfg, run_id="test_run",
                       progress_callback=progress_messages.append)

        assert len(progress_messages) == 2
        assert any("1 confirmed" in m for m in progress_messages)
        assert any("1 still exist" in m for m in progress_messages)

    def test_check_failed_counted_on_exception(self, tmp_path):
        results = [
            {"user_id": "AC000001U00", "space_id": "AC000001U00", "outcome": "deleted"},
        ]
        report_path = self._write_report(tmp_path, results)
        cfg = self._cfg(tmp_path)

        async def fake_navigate(page, cfg):
            pass

        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        from src.stage3_verify import run_stage3

        with patch("src.stage3_verify.async_playwright",          return_value=mock_pw), \
             patch("src.stage3_verify.open_browser",              return_value=mock_browser), \
             patch("src.stage3_verify.navigate_to_space_management", side_effect=fake_navigate), \
             patch("src.stage3_verify.search_and_verify_space",
                   side_effect=Exception("selector timeout")):
            verification_path = run_stage3(report_path=report_path, cfg=cfg, run_id="test_run")

        with open(verification_path, encoding="utf-8") as f:
            report = json.load(f)
        assert report["summary"]["check_failed"] == 1

    def test_check_failed_fires_progress_callback(self, tmp_path):
        """Lines 65-69: progress_callback receives a message when check_failed occurs."""
        results = [
            {"user_id": "AC000001U00", "space_id": "AC000001U00", "outcome": "deleted"},
        ]
        report_path = self._write_report(tmp_path, results)
        cfg = self._cfg(tmp_path)

        async def fake_navigate(page, cfg):
            pass

        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()
        progress_messages = []

        from src.stage3_verify import run_stage3

        with patch("src.stage3_verify.async_playwright",             return_value=mock_pw), \
             patch("src.stage3_verify.open_browser",                 return_value=mock_browser), \
             patch("src.stage3_verify.navigate_to_space_management", side_effect=fake_navigate), \
             patch("src.stage3_verify.search_and_verify_space",
                   side_effect=Exception("timeout")):
            run_stage3(report_path=report_path, cfg=cfg, run_id="test_run",
                       progress_callback=progress_messages.append)

        assert any("check failed" in m.lower() for m in progress_messages)

    def test_check_failed_renavigation_failure_is_swallowed(self, tmp_path):
        """Lines 58-60: if navigate_to_space_management raises during error recovery,
        the exception is swallowed and check_failed is still recorded."""
        results = [
            {"user_id": "AC000001U00", "space_id": "AC000001U00", "outcome": "deleted"},
            {"user_id": "AC000002U00", "space_id": "AC000002U00", "outcome": "deleted"},
        ]
        report_path = self._write_report(tmp_path, results)
        cfg = self._cfg(tmp_path)

        nav_calls = []

        async def fake_navigate(page, cfg):
            nav_calls.append("nav")
            if len(nav_calls) > 1:
                raise RuntimeError("nav failed during recovery")

        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()

        from src.stage3_verify import run_stage3

        with patch("src.stage3_verify.async_playwright",             return_value=mock_pw), \
             patch("src.stage3_verify.open_browser",                 return_value=mock_browser), \
             patch("src.stage3_verify.navigate_to_space_management", side_effect=fake_navigate), \
             patch("src.stage3_verify.search_and_verify_space",
                   side_effect=Exception("selector timeout")):
            verification_path = run_stage3(report_path=report_path, cfg=cfg, run_id="test_run")

        with open(verification_path, encoding="utf-8") as f:
            report = json.load(f)
        assert report["summary"]["check_failed"] == 2
        assert report["summary"]["confirmed_deleted"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# run_stage2_workshops — workshop-sweep mechanics
# ─────────────────────────────────────────────────────────────────────────────

class TestRunStage2WorkshopSweep:

    def _cfg(self, tmp_path):
        cfg = _stage2_cfg(tmp_path)
        cfg["outputs"]["pending_workshops_file"]   = str(tmp_path / "pending_ws.txt")
        cfg["outputs"]["processed_workshops_file"] = str(tmp_path / "processed_ws.txt")
        cfg["outputs"]["deleted_file"]             = str(tmp_path / "deleted.txt")
        return cfg

    def _run(self, tmp_path, pending_workshops, cards_by_workshop, dry_run=False):
        cfg = self._cfg(tmp_path)
        (tmp_path / "pending_ws.txt").write_text("\n".join(pending_workshops) + "\n", encoding="utf-8")

        async def fake_find(page, workshop, cfg=None):
            return cards_by_workshop.get(workshop, [])

        async def fake_delete(page, workshop, cards, cfg, dry_run, allowlist=None):
            if dry_run:
                return [DeleteResult(c["user_id"], c["user_id"], "skipped_dry_run") for c in cards]
            return [DeleteResult(c["user_id"], c["user_id"], "deleted") for c in cards]

        async def fake_navigate(page, cfg):
            pass

        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()
        from src.stage2_deletion import run_stage2_workshops

        with patch("src.stage2_deletion.async_playwright", return_value=mock_pw), \
             patch("src.stage2_deletion.open_browser", return_value=mock_browser), \
             patch("src.stage2_deletion.navigate_to_space_management", side_effect=fake_navigate), \
             patch("src.stage2_deletion.find_workshop_spaces", side_effect=fake_find), \
             patch("src.stage2_deletion.delete_workshop_spaces", side_effect=fake_delete):
            results = run_stage2_workshops(cfg=cfg, dry_run=dry_run, run_id="test_run")
        return results, cfg

    def _card(self, workshop, i):
        return {"user_id": f"AC{workshop}U{i:02d}", "headline": f"H{i}", "container": str(i)}

    def test_empty_queue_returns_nothing(self, tmp_path):
        results, _ = self._run(tmp_path, [], {})
        assert results == []

    def test_sweep_deletes_all_spaces_and_logs_each(self, tmp_path):
        cards = [self._card("279401", i) for i in range(3)]
        results, cfg = self._run(tmp_path, ["279401"], {"279401": cards})
        assert [r.outcome for r in results] == ["deleted"] * 3
        # each space logged to deleted.txt
        logged = Path(cfg["outputs"]["deleted_file"]).read_text().split()
        for c in cards:
            assert c["user_id"] in logged
        # workshop removed from pending, added to processed
        assert Path(cfg["outputs"]["pending_workshops_file"]).read_text().strip() == ""
        assert "279401" in Path(cfg["outputs"]["processed_workshops_file"]).read_text()

    def test_no_spaces_workshop_marked_swept(self, tmp_path):
        results, cfg = self._run(tmp_path, ["279401"], {"279401": []})
        assert results == []  # nothing deleted
        assert "279401" in Path(cfg["outputs"]["processed_workshops_file"]).read_text()
        assert Path(cfg["outputs"]["pending_workshops_file"]).read_text().strip() == ""

    def test_dry_run_leaves_workshop_in_queue(self, tmp_path):
        cards = [self._card("279401", 0)]
        results, cfg = self._run(tmp_path, ["279401"], {"279401": cards}, dry_run=True)
        assert [r.outcome for r in results] == ["skipped_dry_run"]
        # dry-run must NOT mark swept or remove from queue, and must not log deletions
        assert "279401" in Path(cfg["outputs"]["pending_workshops_file"]).read_text()
        assert not Path(cfg["outputs"]["processed_workshops_file"]).exists() \
            or "279401" not in Path(cfg["outputs"]["processed_workshops_file"]).read_text()
        assert not Path(cfg["outputs"]["deleted_file"]).exists() \
            or Path(cfg["outputs"]["deleted_file"]).read_text().strip() == ""
