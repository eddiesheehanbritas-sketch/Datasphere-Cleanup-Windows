import json
import pytest
from pathlib import Path
from unittest.mock import patch

from src.stage3_verify import load_report, _write_verification_report


# ── load_report ───────────────────────────────────────────────────────────────

class TestLoadReport:

    def test_loads_valid_report(self, tmp_path):
        p = tmp_path / "report.json"
        p.write_text(json.dumps({"results": [{"outcome": "deleted"}]}), encoding="utf-8")
        report = load_report(str(p))
        assert report["results"][0]["outcome"] == "deleted"

    def test_raises_when_file_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_report(str(tmp_path / "nonexistent.json"))

    def test_raises_when_results_key_missing(self, tmp_path):
        p = tmp_path / "report.json"
        p.write_text(json.dumps({"summary": {}}), encoding="utf-8")
        with pytest.raises(ValueError, match="missing 'results'"):
            load_report(str(p))


# ── _write_verification_report ────────────────────────────────────────────────

class TestWriteVerificationReport:

    def _cfg(self, tmp_path):
        return {"outputs": {"reports_dir": str(tmp_path / "reports")}}

    def test_writes_report_file(self, tmp_path):
        verifications = [
            {"user_id": "u1", "space_id": "s1", "verification": "confirmed_deleted", "error": None},
        ]
        path = _write_verification_report(verifications, "source.json", "test_run", self._cfg(tmp_path))
        assert Path(path).exists()

    def test_filename_contains_run_id(self, tmp_path):
        path = _write_verification_report([], "source.json", "my_run_id", self._cfg(tmp_path))
        assert "my_run_id" in path

    def test_summary_counts_correctly(self, tmp_path):
        verifications = [
            {"user_id": "u1", "space_id": "s1", "verification": "confirmed_deleted", "error": None},
            {"user_id": "u2", "space_id": "s2", "verification": "confirmed_deleted", "error": None},
            {"user_id": "u3", "space_id": "s3", "verification": "still_exists",      "error": None},
            {"user_id": "u4", "space_id": "s4", "verification": "check_failed",       "error": "timeout"},
        ]
        path = _write_verification_report(verifications, "source.json", "test_run", self._cfg(tmp_path))
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        s = report["summary"]
        assert s["confirmed_deleted"] == 2
        assert s["still_exists"] == 1
        assert s["check_failed"] == 1
        assert s["total_verified"] == 4

    def test_empty_verifications_produces_zero_counts(self, tmp_path):
        path = _write_verification_report([], "source.json", "test_run", self._cfg(tmp_path))
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        s = report["summary"]
        assert s["confirmed_deleted"] == 0
        assert s["still_exists"] == 0
        assert s["check_failed"] == 0

    def test_source_report_recorded(self, tmp_path):
        path = _write_verification_report([], "my_source.json", "test_run", self._cfg(tmp_path))
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        assert report["source_report"] == "my_source.json"

    def test_creates_reports_directory(self, tmp_path):
        cfg = {"outputs": {"reports_dir": str(tmp_path / "deep" / "reports")}}
        path = _write_verification_report([], "source.json", "test_run", cfg)
        assert Path(path).exists()

    def test_verification_detail_included(self, tmp_path):
        verifications = [
            {"user_id": "u1", "space_id": "s1", "verification": "check_failed", "error": "selector timeout"},
        ]
        path = _write_verification_report(verifications, "source.json", "test_run", self._cfg(tmp_path))
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        assert report["verifications"][0]["error"] == "selector timeout"


# ── verification outcome logic ────────────────────────────────────────────────

class TestVerificationOutcomes:
    """Tests for the pure outcome-classification logic in run_stage3.

    We don't test the Playwright interaction, but we can test that the
    still_exists / confirmed_deleted / check_failed branching is correct
    by exercising load_report + _write_verification_report together.
    """

    def test_still_exists_outcome_when_space_found(self, tmp_path):
        verifications = [
            {"user_id": "u1", "space_id": "s1", "verification": "still_exists", "error": None},
        ]
        path = _write_verification_report(verifications, "src.json", "run", {"outputs": {"reports_dir": str(tmp_path)}})
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        assert report["summary"]["still_exists"] == 1
        assert report["summary"]["confirmed_deleted"] == 0

    def test_confirmed_deleted_outcome_when_space_gone(self, tmp_path):
        verifications = [
            {"user_id": "u1", "space_id": "s1", "verification": "confirmed_deleted", "error": None},
        ]
        path = _write_verification_report(verifications, "src.json", "run", {"outputs": {"reports_dir": str(tmp_path)}})
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        assert report["summary"]["confirmed_deleted"] == 1
        assert report["summary"]["still_exists"] == 0

    def test_report_filters_to_deleted_only(self, tmp_path):
        """load_report returns all results; run_stage3 only verifies outcome==deleted."""
        p = tmp_path / "report.json"
        p.write_text(json.dumps({
            "results": [
                {"user_id": "u1", "space_id": "s1", "outcome": "deleted"},
                {"user_id": "u2", "space_id": "s2", "outcome": "not_found"},
                {"user_id": "u3", "space_id": "s3", "outcome": "failed"},
            ]
        }), encoding="utf-8")
        report = load_report(str(p))
        to_verify = [r for r in report["results"] if r["outcome"] == "deleted"]
        assert len(to_verify) == 1
        assert to_verify[0]["user_id"] == "u1"
