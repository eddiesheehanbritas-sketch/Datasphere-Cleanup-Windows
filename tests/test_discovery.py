import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from src.portal_client import _verify_filters_active



# ── Filter verification ───────────────────────────────────────────────────────

class TestVerifyFiltersActive:

    def _make_page(self, label_text):
        """Return a mock Page whose label locator returns the given text."""
        from unittest.mock import AsyncMock
        page = MagicMock()
        mock_el = AsyncMock()
        mock_el.inner_text = AsyncMock(return_value=label_text)
        page.locator.return_value.all = AsyncMock(return_value=[mock_el])
        page.wait_for_selector = AsyncMock()
        return page

    def test_passes_when_both_filters_confirmed(self):
        import asyncio
        page = self._make_page(
            "Filtered by: Environment (Cleaned), Data Center Region (EU10)"
        )
        asyncio.run(_verify_filters_active(page))  # must not raise

    def test_raises_when_toolbar_absent(self):
        import asyncio
        from unittest.mock import AsyncMock
        page = MagicMock()
        page.locator.return_value.all = AsyncMock(return_value=[])
        page.wait_for_selector = AsyncMock()
        with pytest.raises(RuntimeError, match="SAFETY ABORT"):
            asyncio.run(_verify_filters_active(page))

    def test_raises_when_environment_filter_missing(self):
        import asyncio
        page = self._make_page("Filtered by: Data Center Region (EU10)")
        with pytest.raises(RuntimeError, match="Environment \\(Cleaned\\)"):
            asyncio.run(_verify_filters_active(page))

    def test_raises_when_region_filter_missing(self):
        import asyncio
        page = self._make_page("Filtered by: Environment (Cleaned)")
        with pytest.raises(RuntimeError, match="Data Center Region \\(EU10\\)"):
            asyncio.run(_verify_filters_active(page))

    def test_raises_when_both_filters_missing(self):
        import asyncio
        page = self._make_page("Filtered by: Status (Active)")
        with pytest.raises(RuntimeError, match="SAFETY ABORT"):
            asyncio.run(_verify_filters_active(page))

    def test_passes_with_all_three_filters_confirmed(self):
        import asyncio
        page = self._make_page(
            "Filtered by: Environment (Cleaned), Data Center Region (EU10), "
            "Planned end workshop (From: 2024-01-01, To: 2025-01-01), "
            "Planned start workshop (From: 2024-01-01, To: 2025-01-01)"
        )
        asyncio.run(_verify_filters_active(
            page,
            start_date_from="2024-01-01", start_date_to="2025-01-01",
            end_date_from="2024-01-01", end_date_to="2025-01-01",
        ))

    def test_raises_when_end_date_filter_expected_but_missing(self):
        import asyncio
        page = self._make_page(
            "Filtered by: Environment (Cleaned), Data Center Region (EU10)"
        )
        with pytest.raises(RuntimeError, match="Planned end workshop"):
            asyncio.run(_verify_filters_active(page, end_date_from="2024-01-01", end_date_to="2025-01-01"))

    def test_raises_when_start_date_filter_expected_but_missing(self):
        import asyncio
        page = self._make_page(
            "Filtered by: Environment (Cleaned), Data Center Region (EU10)"
        )
        with pytest.raises(RuntimeError, match="Planned start workshop"):
            asyncio.run(_verify_filters_active(page, start_date_from="2024-01-01", start_date_to="2025-01-01"))

    def test_passes_without_date_filter_when_not_requested(self):
        import asyncio
        page = self._make_page(
            "Filtered by: Environment (Cleaned), Data Center Region (EU10)"
        )
        # all four date params None — date checks must be skipped entirely
        asyncio.run(_verify_filters_active(page))

    def test_date_filter_not_checked_when_only_one_param_set(self):
        import asyncio
        # Only one end-date bound set — an incomplete range is treated as no date filter
        page = self._make_page(
            "Filtered by: Environment (Cleaned), Data Center Region (EU10)"
        )
        asyncio.run(_verify_filters_active(page, end_date_from="2024-01-01", end_date_to=None))

    def test_end_only_range_passes_without_start_chip(self):
        import asyncio
        # End range set, start range blank — only the end chip is required.
        page = self._make_page(
            "Filtered by: Environment (Cleaned), Data Center Region (EU10), "
            "Planned end workshop (From: 2024-01-01, To: 2025-01-01)"
        )
        asyncio.run(_verify_filters_active(page, end_date_from="2024-01-01", end_date_to="2025-01-01"))

    def test_independent_ranges_pass_with_different_dates(self):
        import asyncio
        # Start and End ranges differ — both chips must reflect their own values.
        page = self._make_page(
            "Filtered by: Environment (Cleaned), Data Center Region (EU10), "
            "Planned end workshop (From: 2024-06-01, To: 2024-12-31), "
            "Planned start workshop (From: 2024-01-01, To: 2024-03-31)"
        )
        asyncio.run(_verify_filters_active(
            page,
            start_date_from="2024-01-01", start_date_to="2024-03-31",
            end_date_from="2024-06-01", end_date_to="2024-12-31",
        ))


class TestVerifyFiltersActiveUS10:

    def _make_page(self, label_text):
        from unittest.mock import AsyncMock
        page = MagicMock()
        mock_el = AsyncMock()
        mock_el.inner_text = AsyncMock(return_value=label_text)
        page.locator.return_value.all = AsyncMock(return_value=[mock_el])
        page.wait_for_selector = AsyncMock()
        return page

    def test_passes_when_us10_filter_confirmed(self):
        import asyncio
        page = self._make_page(
            "Filtered by: Environment (Cleaned), Data Center Region (US10)"
        )
        asyncio.run(_verify_filters_active(page, dc_region="US10"))  # must not raise

    def test_raises_when_eu10_given_but_us10_in_toolbar(self):
        import asyncio
        page = self._make_page(
            "Filtered by: Environment (Cleaned), Data Center Region (US10)"
        )
        with pytest.raises(RuntimeError, match="Data Center Region \\(EU10\\)"):
            asyncio.run(_verify_filters_active(page, dc_region="EU10"))

    def test_passes_us10_with_date_filter(self):
        import asyncio
        page = self._make_page(
            "Filtered by: Environment (Cleaned), Data Center Region (US10), "
            "Planned end workshop (From: 2024-01-01, To: 2025-01-01), "
            "Planned start workshop (From: 2024-01-01, To: 2025-01-01)"
        )
        asyncio.run(_verify_filters_active(
            page, dc_region="US10",
            start_date_from="2024-01-01", start_date_to="2025-01-01",
            end_date_from="2024-01-01", end_date_to="2025-01-01",
        ))

    def test_raises_us10_when_date_filter_missing(self):
        import asyncio
        page = self._make_page(
            "Filtered by: Environment (Cleaned), Data Center Region (US10)"
        )
        with pytest.raises(RuntimeError, match="Planned end workshop"):
            asyncio.run(_verify_filters_active(
                page, dc_region="US10",
                end_date_from="2024-01-01", end_date_to="2025-01-01",
            ))
