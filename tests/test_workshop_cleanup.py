import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, call

from src.portal_client import scrape_single_workshop
from src.stage1_discovery import run_workshop_scrape
from tests.conftest import make_async_playwright_mocks


def _make_cfg(tmp_path):
    return {
        "portal": {
            "base_url": "https://portal.example.com",
            "session_file": str(tmp_path / "session.json"),
            "search_term": "SAP Datasphere Overview",
            "scroll_pause": 0,
        },
        "outputs": {
            "user_lists_dir": str(tmp_path / "user_lists"),
            "processed_workshops_file": str(tmp_path / "processed_workshops.txt"),
        },
        "retry": {"backoff_seconds": []},
    }


# ── scrape_single_workshop ────────────────────────────────────────────────────

class TestScrapeSingleWorkshop:

    def test_calls_filtered_list_with_workshop_id(self, tmp_path):
        import asyncio
        page = MagicMock()
        cfg = _make_cfg(tmp_path)
        with patch("src.portal_client._go_to_filtered_list", new_callable=AsyncMock) as mock_filter, \
             patch("src.portal_client.mark_workshop_processed"):
            asyncio.run(scrape_single_workshop(page, cfg, "1234567"))
        mock_filter.assert_called_once_with(page, cfg["portal"]["base_url"], "1234567", dc_region="EU10", start_date_from=None, start_date_to=None, end_date_from=None, end_date_to=None, requests_tree_item="Internal request(s)", workshop_id_from=None, workshop_id_to=None)

    def test_returns_empty_list(self, tmp_path):
        import asyncio
        page = MagicMock()
        cfg = _make_cfg(tmp_path)
        with patch("src.portal_client._go_to_filtered_list", new_callable=AsyncMock), \
             patch("src.portal_client.append_pending_workshop") as mock_append, \
             patch("src.portal_client.mark_workshop_processed"):
            result = asyncio.run(scrape_single_workshop(page, cfg, "1234567"))
        assert result == []

    def test_appends_workshop_to_pending(self, tmp_path):
        import asyncio
        page = MagicMock()
        cfg = _make_cfg(tmp_path)
        with patch("src.portal_client._go_to_filtered_list", new_callable=AsyncMock), \
             patch("src.portal_client.append_pending_workshop") as mock_append, \
             patch("src.portal_client.mark_workshop_processed"):
            asyncio.run(scrape_single_workshop(page, cfg, "1234567"))
        mock_append.assert_called_once_with("1234567", cfg)

    def test_marks_workshop_processed(self, tmp_path):
        import asyncio
        page = MagicMock()
        cfg = _make_cfg(tmp_path)
        with patch("src.portal_client._go_to_filtered_list", new_callable=AsyncMock), \
             patch("src.portal_client.mark_workshop_processed") as mock_mark:
            asyncio.run(scrape_single_workshop(page, cfg, "9999999"))
        mock_mark.assert_called_once_with("9999999", cfg)

    def test_returns_empty_list_when_no_users(self, tmp_path):
        import asyncio
        page = MagicMock()
        cfg = _make_cfg(tmp_path)
        with patch("src.portal_client._go_to_filtered_list", new_callable=AsyncMock), \
             patch("src.portal_client.mark_workshop_processed"):
            result = asyncio.run(scrape_single_workshop(page, cfg, "1234567"))
        assert result == []


# ── run_workshop_scrape ───────────────────────────────────────────────────────

class TestRunWorkshopScrape:

    def test_queues_workshop_for_sweep(self, tmp_path):
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()
        cfg = _make_cfg(tmp_path)

        with patch("src.stage1_discovery.async_playwright", return_value=mock_pw), \
             patch("src.stage1_discovery.open_browser", return_value=mock_browser), \
             patch("src.stage1_discovery.scrape_single_workshop", new_callable=AsyncMock, return_value=[]) as mock_scrape:
            run_workshop_scrape(workshop_id="1234567", cfg=cfg, run_id="test_run")

        mock_scrape.assert_called_once()
        assert mock_scrape.call_args[0][2] == "1234567"

    def test_does_not_queue_already_pending_workshop(self, tmp_path):
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()
        cfg = _make_cfg(tmp_path)
        pending_ws = tmp_path / "pending_workshops.txt"
        pending_ws.write_text("1234567\n", encoding="utf-8")
        cfg["outputs"]["pending_workshops_file"] = str(pending_ws)

        with patch("src.stage1_discovery.async_playwright", return_value=mock_pw), \
             patch("src.stage1_discovery.open_browser", return_value=mock_browser), \
             patch("src.stage1_discovery.scrape_single_workshop", new_callable=AsyncMock, return_value=[]):
            run_workshop_scrape(workshop_id="1234567", cfg=cfg, run_id="test_run")

        assert pending_ws.read_text(encoding="utf-8").strip() == "1234567"

    def test_does_not_touch_pending_queue_for_already_processed_users(self, tmp_path):
        """If all scraped users are already processed, pending.txt must not be created."""
        mock_pw, mock_browser, _, _ = make_async_playwright_mocks()
        cfg = _make_cfg(tmp_path)
        pending = tmp_path / "pending.txt"

        async def fake_scrape(page, cfg, workshop_id):
            return ["AC000001U00", "AC000002U00"]

        with patch("src.stage1_discovery.async_playwright", return_value=mock_pw), \
             patch("src.stage1_discovery.open_browser", return_value=mock_browser), \
             patch("src.stage1_discovery.scrape_single_workshop", side_effect=fake_scrape):
            run_workshop_scrape(workshop_id="1234567", cfg=cfg, run_id="myrun")

        assert not pending.exists()


# ── Workshop queue UI logic ───────────────────────────────────────────────────
# Tests for _add_to_workshop_queue / _remove_from_workshop_queue / _run_workshop_scrape
# guard in both App (app.py) and CombinedApp (combined.py).
# We drive the methods directly without rendering a real Qt window.

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_app_instance(tmp_path, monkeypatch):
    """Return a minimally initialised App instance with Qt widgets."""
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "settings.yaml").write_text(
        "tenants:\n"
        "  eu10:\n"
        "    portal:\n"
        "      base_url: https://example.com\n"
        "      session_file: sessions/portal_eu10.json\n"
        "      search_term: SAP Datasphere Overview\n"
        "      scroll_pause: 0\n"
        "    datasphere:\n"
        "      base_url: https://example.com\n"
        "      session_file: sessions/ds_eu10.json\n"
        "      renamed_spaces: false\n"
        "    outputs:\n"
        "      user_lists_dir: outputs/user_lists\n"
        "      logs_dir: outputs/logs\n"
        "      reports_dir: outputs/reports\n"
        "      processed_workshops_file: outputs/user_lists/processed_workshops_eu10.txt\n"
        "    retry:\n"
        "      backoff_seconds: []\n",
        encoding="utf-8",
    )
    from PyQt5.QtWidgets import QApplication
    import sys
    app_qt = QApplication.instance() or QApplication(sys.argv)
    from src.app import App
    win = App(tenant="eu10")
    return win, app_qt


def _make_combined_instance(tmp_path, monkeypatch):
    """Return a minimally initialised CombinedApp instance."""
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "settings.yaml").write_text(
        "tenants:\n"
        "  eu10:\n"
        "    portal:\n"
        "      base_url: https://example.com\n"
        "      session_file: sessions/portal_eu10.json\n"
        "      search_term: SAP Datasphere Overview\n"
        "      scroll_pause: 0\n"
        "    datasphere:\n"
        "      base_url: https://example.com\n"
        "      session_file: sessions/ds_eu10.json\n"
        "      renamed_spaces: false\n"
        "    outputs:\n"
        "      user_lists_dir: outputs/user_lists\n"
        "      logs_dir: outputs/logs\n"
        "      reports_dir: outputs/reports\n"
        "      processed_workshops_file: outputs/user_lists/processed_workshops_eu10.txt\n"
        "    retry:\n"
        "      backoff_seconds: []\n",
        encoding="utf-8",
    )
    from PyQt5.QtWidgets import QApplication
    import sys
    app_qt = QApplication.instance() or QApplication(sys.argv)
    from src.combined import CombinedApp
    win = CombinedApp()
    return win, app_qt


class TestWorkshopQueueApp:
    """Queue UI logic in the single-tenant App."""

    def test_add_valid_id_appends_to_queue(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("123456")
        win._add_to_workshop_queue()
        assert win._workshop_queue == ["123456"]
        assert win._workshop_queue_widget.count() == 1
        assert win._workshop_queue_widget.item(0).text() == "123456"

    def test_add_clears_input_field(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("123456")
        win._add_to_workshop_queue()
        assert win._workshop_id_input.text() == ""

    def test_add_enables_launch_button(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        assert not win.btn_workshop_scrape.isEnabled()
        win._workshop_id_input.setText("123456")
        win._add_to_workshop_queue()
        assert win.btn_workshop_scrape.isEnabled()

    def test_launch_label_reflects_count(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("111111")
        win._add_to_workshop_queue()
        win._workshop_id_input.setText("222222")
        win._add_to_workshop_queue()
        assert "2" in win.btn_workshop_scrape.text()

    def test_add_rejects_non_digit(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("12abc7")
        with patch("src.app.QMessageBox.warning"):
            win._add_to_workshop_queue()
        assert win._workshop_queue == []

    def test_add_rejects_too_short(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("1234")
        with patch("src.app.QMessageBox.warning"):
            win._add_to_workshop_queue()
        assert win._workshop_queue == []

    def test_add_rejects_too_long(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("12345678")
        with patch("src.app.QMessageBox.warning"):
            win._add_to_workshop_queue()
        assert win._workshop_queue == []

    def test_add_rejects_duplicate(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("123456")
        win._add_to_workshop_queue()
        win._workshop_id_input.setText("123456")
        with patch("src.app.QMessageBox.information"):
            win._add_to_workshop_queue()
        assert win._workshop_queue.count("123456") == 1
        assert win._workshop_queue_widget.count() == 1

    def test_remove_selected_item(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("123456")
        win._add_to_workshop_queue()
        win._workshop_id_input.setText("654321")
        win._add_to_workshop_queue()
        win._workshop_queue_widget.setCurrentRow(0)
        win._remove_from_workshop_queue()
        assert "123456" not in win._workshop_queue
        assert win._workshop_queue == ["654321"]
        assert win._workshop_queue_widget.count() == 1

    def test_remove_last_item_disables_launch(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("123456")
        win._add_to_workshop_queue()
        win._workshop_queue_widget.setCurrentRow(0)
        win._remove_from_workshop_queue()
        assert not win.btn_workshop_scrape.isEnabled()
        assert "0" in win.btn_workshop_scrape.text()

    def test_remove_does_nothing_when_nothing_selected(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("123456")
        win._add_to_workshop_queue()
        win._workshop_queue_widget.clearSelection()
        win._remove_from_workshop_queue()
        assert win._workshop_queue == ["123456"]

    def test_launch_guard_empty_queue(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        logged = []
        win.log = lambda m: logged.append(m)
        win._run_workshop_scrape()
        assert any("empty" in m.lower() for m in logged)

    def test_launch_clears_queue_and_list_widget(self, tmp_path, monkeypatch):
        win, _ = _make_app_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("123456")
        win._add_to_workshop_queue()
        with patch.object(win, "_run_in_thread"):
            win._run_workshop_scrape()
        assert win._workshop_queue == []
        assert win._workshop_queue_widget.count() == 0
        assert not win.btn_workshop_scrape.isEnabled()


class TestWorkshopQueueCombined:
    """Queue UI logic in the combined CombinedApp — same behaviour, different class."""

    def test_add_valid_id_appends_to_queue(self, tmp_path, monkeypatch):
        win, _ = _make_combined_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("123456")
        win._add_to_workshop_queue()
        assert win._workshop_queue == ["123456"]
        assert win._workshop_queue_widget.count() == 1

    def test_add_rejects_invalid_id(self, tmp_path, monkeypatch):
        win, _ = _make_combined_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("abc")
        with patch("src.combined.QMessageBox.warning"):
            win._add_to_workshop_queue()
        assert win._workshop_queue == []

    def test_add_rejects_duplicate(self, tmp_path, monkeypatch):
        win, _ = _make_combined_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("123456")
        win._add_to_workshop_queue()
        win._workshop_id_input.setText("123456")
        with patch("src.combined.QMessageBox.information"):
            win._add_to_workshop_queue()
        assert win._workshop_queue.count("123456") == 1

    def test_remove_item(self, tmp_path, monkeypatch):
        win, _ = _make_combined_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("111111")
        win._add_to_workshop_queue()
        win._workshop_id_input.setText("222222")
        win._add_to_workshop_queue()
        win._workshop_queue_widget.setCurrentRow(0)
        win._remove_from_workshop_queue()
        assert "111111" not in win._workshop_queue
        assert win._workshop_queue_widget.count() == 1

    def test_launch_guard_empty_queue(self, tmp_path, monkeypatch):
        win, _ = _make_combined_instance(tmp_path, monkeypatch)
        logged = []
        win.log = lambda m: logged.append(m)
        win._run_workshop_scrape()
        assert any("empty" in m.lower() for m in logged)

    def test_launch_clears_queue_and_list_widget(self, tmp_path, monkeypatch):
        win, _ = _make_combined_instance(tmp_path, monkeypatch)
        win._workshop_id_input.setText("123456")
        win._add_to_workshop_queue()
        with patch.object(win, "_run_concurrent"):
            win._run_workshop_scrape()
        assert win._workshop_queue == []
        assert win._workshop_queue_widget.count() == 0
        assert not win.btn_workshop_scrape.isEnabled()
