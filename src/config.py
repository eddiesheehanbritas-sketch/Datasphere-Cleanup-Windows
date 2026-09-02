import os
import re
import shutil
import sys
import yaml
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# Folder created in the user's Documents on first launch.
APP_HOME = Path.home() / "Documents" / "Datasphere Cleanup"

# Subfolders created automatically inside APP_HOME.
_OUTPUT_DIRS = [
    "outputs/user_lists",
    "outputs/logs",
    "outputs/reports",
    "outputs/archive",
]

PORTAL_BASE_URL = "https://six-btp.cfapps.eu10-004.hana.ondemand.com/academy-main"

_DWAAS_CORE_SIGN_IN       = "/dwaas-core/index.html#/spaceManagement"
_DWAAS_CORE_SPACE_MGMT    = "/dwaas-core/index.html#/spaceManagement"
_DWAAS_UI_SIGN_IN         = "/dwaas-ui/index.html#/home"
_DWAAS_UI_SPACE_MGMT      = "/dwaas-ui/index.html#/managespaces&/ms/overview?view=tile"


def setup_app_home() -> Path:
    """Create ~/Documents/Datasphere Cleanup/ and seed config files if needed.

    Returns the app home path. Sets CWD to it so all relative paths in
    settings.yaml resolve correctly.
    """
    APP_HOME.mkdir(parents=True, exist_ok=True)

    for subdir in _OUTPUT_DIRS:
        (APP_HOME / subdir).mkdir(parents=True, exist_ok=True)

    # When running as a PyInstaller bundle, seed config files from the bundle
    # into APP_HOME if they don't exist yet. This means the user gets a clean
    # editable copy on first run and updates never overwrite their config.
    if getattr(sys, "frozen", False):
        bundle = Path(sys._MEIPASS)
        for name in ("settings.yaml", "allowlist.txt"):
            src = bundle / "config" / name
            dst = APP_HOME / "config" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() and src.exists():
                shutil.copy2(src, dst)

    os.chdir(APP_HOME)
    return APP_HOME


def _tenant_key(display_name: str) -> str:
    """Convert a display name like 'EU10(3)' to a safe YAML key like 'eu10_3'."""
    key = display_name.lower()
    key = re.sub(r'[^a-z0-9]+', '_', key)
    key = key.strip('_')
    return key


def add_tenant(
    display_name: str,
    base_url: str,
    dc_region: str,
    is_public: bool,
    path_style: str,
    settings_path: str = "config/settings.yaml",
) -> str:
    """Add a user-defined tenant to settings.yaml.

    Args:
        display_name: Human-readable name shown in the GUI (e.g. 'US10(3)').
        base_url: Datasphere base URL (e.g. 'https://...hcs.cloud.sap').
        dc_region: One of 'EU10', 'US10', 'AP11'.
        is_public: True → Public request(s) sidebar; False → Internal request(s).
        path_style: 'dwaas-ui' or 'dwaas-core'.
        settings_path: Path to settings.yaml (relative to CWD).

    Returns:
        The tenant key added (e.g. 'us10_3').

    Raises:
        ValueError: If the tenant key already exists or inputs are invalid.
    """
    if dc_region not in ("EU10", "US10", "AP11"):
        raise ValueError(f"Invalid dc_region '{dc_region}'. Must be EU10, US10, or AP11.")
    if path_style not in ("dwaas-ui", "dwaas-core"):
        raise ValueError(f"Invalid path_style '{path_style}'. Must be dwaas-ui or dwaas-core.")
    if not display_name.strip():
        raise ValueError("display_name cannot be empty.")
    if not base_url.strip():
        raise ValueError("base_url cannot be empty.")

    key = _tenant_key(display_name)

    path = Path(settings_path)
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    tenants = raw.get("tenants", {})
    if key in tenants:
        raise ValueError(f"Tenant key '{key}' already exists.")

    if path_style == "dwaas-core":
        sign_in_path    = _DWAAS_CORE_SIGN_IN
        space_mgmt_path = _DWAAS_CORE_SPACE_MGMT
    else:
        sign_in_path    = _DWAAS_UI_SIGN_IN
        space_mgmt_path = _DWAAS_UI_SPACE_MGMT

    # Escape double-quotes so user input can't produce invalid YAML strings.
    safe_display_name = display_name.replace('"', '\\"')
    safe_base_url     = base_url.rstrip("/").replace('"', '\\"')

    # Create empty output files so the pipeline never hits a missing-file error.
    output_paths = {
        "deleted_file":             f"outputs/user_lists/deleted_{key}.txt",
        "processed_workshops_file": f"outputs/user_lists/processed_workshops_{key}.txt",
        "pending_workshops_file":   f"outputs/user_lists/pending_workshops_{key}.txt",
    }
    for p_str in output_paths.values():
        p = Path(p_str)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.touch()

    # Append the new tenant block as raw YAML text so the original file
    # formatting and comments are fully preserved.
    requests_line = (
        f"\n      requests_tree_item: \"Public request(s)\""
        if is_public else ""
    )
    block_text = f"""  {key}:
    user_added: true
    display_name: "{safe_display_name}"
    batch:
      max_workshops: 300
    portal:
      base_url: "{PORTAL_BASE_URL}"
      session_file: "storage_state_portal_{key}.json"
      dc_region: "{dc_region}"{requests_line}
    datasphere:
      base_url: "{safe_base_url}"
      session_file: "storage_state_datasphere_{key}.json"
      sign_in_path: "{sign_in_path}"
      space_management_path: "{space_mgmt_path}"
    outputs:
      deleted_file:             "outputs/user_lists/deleted_{key}.txt"
      processed_workshops_file: "outputs/user_lists/processed_workshops_{key}.txt"
      pending_workshops_file:   "outputs/user_lists/pending_workshops_{key}.txt"
"""
    with open(path, "a", encoding="utf-8") as f:
        f.write(block_text)

    return key


def remove_tenant(
    tenant_key: str,
    settings_path: str = "config/settings.yaml",
) -> None:
    """Remove a user-added tenant from settings.yaml and delete its data files.

    Raises:
        ValueError: If the tenant does not exist or is not user-added.
    """
    path = Path(settings_path)
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    tenants = raw.get("tenants", {})
    if tenant_key not in tenants:
        raise ValueError(f"Tenant '{tenant_key}' not found.")

    block = tenants[tenant_key]
    if not block.get("user_added", False):
        raise ValueError(f"Tenant '{tenant_key}' is a built-in tenant and cannot be removed.")

    # Delete output files.
    for file_key in ("deleted_file", "processed_workshops_file", "pending_workshops_file"):
        p = Path(block["outputs"][file_key])
        if p.exists():
            p.unlink()

    # Delete session files.
    for session_key in ("session_file",):
        for section in ("portal", "datasphere"):
            sf = block.get(section, {}).get(session_key)
            if sf:
                p = Path(sf)
                if p.exists():
                    p.unlink()

    del tenants[tenant_key]

    # Remove the tenant block from the file as raw text to preserve formatting.
    # Strategy: find the line "  <key>:" and remove all lines belonging to it
    # (i.e. until the next 2-space-indented key at the same level, or EOF).
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    start = None
    end = None
    target = f"  {tenant_key}:\n"
    for i, line in enumerate(lines):
        if line == target:
            start = i
        elif start is not None and i > start:
            # Next sibling key at the same indentation level (2 spaces), or
            # a top-level key (no indent) signals the end of this block.
            if line and not line.startswith("   ") and line.strip():
                end = i
                break
    if start is not None:
        if end is None:
            end = len(lines)
        lines = lines[:start] + lines[end:]

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def is_user_added_tenant(tenant_key: str, settings_path: str = "config/settings.yaml") -> bool:
    """Return True if the tenant was added by the user (not built-in)."""
    path = Path(settings_path)
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return raw.get("tenants", {}).get(tenant_key, {}).get("user_added", False)


_ENV_PATTERN = re.compile(r'\$\{(\w+)\}')


def _interpolate(value: str) -> str:
    """Replace ${VAR} placeholders in a string with environment variable values."""
    def replacer(match):
        var = match.group(1)
        result = os.environ.get(var)
        if result is None:
            raise ValueError(f"Environment variable '{var}' referenced in settings.yaml is not set")
        return result
    return _ENV_PATTERN.sub(replacer, value)


def _resolve(obj):
    """Recursively interpolate env vars in all string values of a parsed YAML object."""
    if isinstance(obj, dict):
        return {k: _resolve(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(i) for i in obj]
    if isinstance(obj, str):
        return _interpolate(obj)
    return obj


def load_config(settings_path: str = "config/settings.yaml") -> dict:
    path = Path(settings_path)
    if not path.exists():
        raise FileNotFoundError(f"Settings file not found: {path}")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Settings file is empty or not a YAML mapping: {path}")
    return _resolve(raw)


def _deep_merge(base: dict, overrides: dict) -> None:
    for key, val in overrides.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val


def load_tenant_config(tenant: str, settings_path: str = "config/settings.yaml") -> dict:
    raw = load_config(settings_path)
    tenants = raw.get("tenants", {})
    if tenant not in tenants:
        raise ValueError(f"Unknown tenant '{tenant}'. Available: {list(tenants.keys())}")
    cfg = {k: v for k, v in raw.items() if k != "tenants"}
    _deep_merge(cfg, tenants[tenant])
    return cfg
