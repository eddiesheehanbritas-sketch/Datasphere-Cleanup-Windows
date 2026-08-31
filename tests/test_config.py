import pytest
from unittest.mock import patch
from pathlib import Path


def _write_settings(tmp_path, extra: str = "") -> Path:
    content = f"""
portal:
  base_url: "${{PORTAL_BASE_URL}}"
  search_term: "SAP Datasphere Overview"
  scroll_pause: 0.5
datasphere:
  post_delete_pause: 12.0
batch:
  size: 50
outputs:
  user_lists_dir: "outputs/user_lists"
  logs_dir: "outputs/logs"
  reports_dir: "outputs/reports"
  allowlist_file: "config/allowlist.txt"
  pending_file: "outputs/user_lists/pending.txt"
  processed_file: "outputs/user_lists/processed.txt"
  deleted_file: "outputs/user_lists/deleted.txt"
  processed_workshops_file: "outputs/user_lists/processed_workshops.txt"
dry_run: true
tenants:
  eu10:
    portal:
      base_url: "${{PORTAL_BASE_URL}}"
      session_file: "storage_state_portal_eu10.json"
      dc_region: "EU10"
    datasphere:
      base_url: "${{DATASPHERE_BASE_URL_EU10}}"
      session_file: "storage_state_datasphere_eu10.json"
      sign_in_path: "/dwaas-core/index.html#/spaceManagement"
      space_management_path: "/dwaas-core/index.html#/spaceManagement"
    outputs:
      pending_file: "outputs/user_lists/pending_eu10.txt"
      processed_file: "outputs/user_lists/processed_eu10.txt"
      deleted_file: "outputs/user_lists/deleted_eu10.txt"
      processed_workshops_file: "outputs/user_lists/processed_workshops_eu10.txt"
  us10:
    portal:
      base_url: "${{PORTAL_BASE_URL}}"
      session_file: "storage_state_portal_us10.json"
      dc_region: "US10"
    datasphere:
      base_url: "${{DATASPHERE_BASE_URL_US10}}"
      session_file: "storage_state_datasphere_us10.json"
      sign_in_path: "/dwaas-ui/index.html#/home"
      space_management_path: "/dwaas-ui/index.html#/managespaces&/ms/overview?view=tile"
    outputs:
      pending_file: "outputs/user_lists/pending_us10.txt"
      processed_file: "outputs/user_lists/processed_us10.txt"
      deleted_file: "outputs/user_lists/deleted_us10.txt"
      processed_workshops_file: "outputs/user_lists/processed_workshops_us10.txt"
{extra}
"""
    p = tmp_path / "settings.yaml"
    p.write_text(content, encoding="utf-8")
    return p


_ENV = {
    "PORTAL_BASE_URL": "https://portal.example.com",
    "DATASPHERE_BASE_URL_EU10": "https://eu10.example.com",
    "DATASPHERE_BASE_URL_US10": "https://us10.example.com",
}


class TestLoadTenantConfig:

    def test_eu10_session_files(self, tmp_path):
        from src.config import load_tenant_config
        settings = _write_settings(tmp_path)
        with patch.dict("os.environ", _ENV):
            cfg = load_tenant_config("eu10", str(settings))
        assert cfg["portal"]["session_file"] == "storage_state_portal_eu10.json"
        assert cfg["datasphere"]["session_file"] == "storage_state_datasphere_eu10.json"

    def test_us10_dc_region(self, tmp_path):
        from src.config import load_tenant_config
        settings = _write_settings(tmp_path)
        with patch.dict("os.environ", _ENV):
            cfg = load_tenant_config("us10", str(settings))
        assert cfg["portal"]["dc_region"] == "US10"
        assert cfg["datasphere"]["space_management_path"] == "/dwaas-ui/index.html#/managespaces&/ms/overview?view=tile"
        assert cfg["datasphere"]["sign_in_path"] == "/dwaas-ui/index.html#/home"

    def test_shared_keys_preserved(self, tmp_path):
        from src.config import load_tenant_config
        settings = _write_settings(tmp_path)
        with patch.dict("os.environ", _ENV):
            cfg = load_tenant_config("eu10", str(settings))
        assert cfg["datasphere"]["post_delete_pause"] == 12.0
        assert cfg["portal"]["search_term"] == "SAP Datasphere Overview"
        assert cfg["dry_run"] is True

    def test_invalid_tenant_raises(self, tmp_path):
        from src.config import load_tenant_config
        settings = _write_settings(tmp_path)
        with patch.dict("os.environ", _ENV):
            with pytest.raises(ValueError, match="Unknown tenant 'xx10'"):
                load_tenant_config("xx10", str(settings))

    def test_outputs_pending_file_scoped_to_tenant(self, tmp_path):
        from src.config import load_tenant_config
        settings = _write_settings(tmp_path)
        with patch.dict("os.environ", _ENV):
            eu10 = load_tenant_config("eu10", str(settings))
            us10 = load_tenant_config("us10", str(settings))
        assert eu10["outputs"]["pending_file"] == "outputs/user_lists/pending_eu10.txt"
        assert us10["outputs"]["pending_file"] == "outputs/user_lists/pending_us10.txt"
        assert eu10["outputs"]["deleted_file"] == "outputs/user_lists/deleted_eu10.txt"
        assert us10["outputs"]["deleted_file"] == "outputs/user_lists/deleted_us10.txt"
