# Adding a New Tenant — Step-by-Step Reference

This document is the authoritative guide for adding new tenants to the datasphere-cleanup pipeline.
It is split into two tracks: **Internal tenants** (EU10, US10, AP11) and **Public tenants** (AP11(2) and any future public-portal tenant).
Read the relevant track top to bottom before touching any code.

---

## How to tell Internal from Public

Open the SAP Self-Service Content Portal. In the left sidebar you will see tree items:

- **Internal request(s)** — EU10, US10, AP11 users live here
- **Public request(s)** — AP11(2) and future public tenants live here

If the new tenant's users appear under **Public request(s)**, follow the **Public tenant** track.
If they appear under **Internal request(s)**, follow the **Internal tenant** track.

---

## Track A — Adding an Internal Tenant

### What differs from existing tenants
- Portal sidebar click: `[aria-label^='Tree Item Internal request(s)']` (default, no change needed)
- Workshop rows: `a[href*="/academy-request/"]`
- User IDs: `AC\d+U\d+` format (e.g. `AC304708U00`)
- Search input on portal: `[role="searchbox"]`
- Datasphere autocomplete renders fast — existing 15s timeouts are fine

### Checklist

**1. `config/settings.yaml` — add tenant block**
```yaml
tenants:
  <tenant_id>:               # e.g. eu10, us10, ap11
    portal:
      base_url: "${PORTAL_BASE_URL}"
      session_file: "storage_state_portal_<tenant_id>.json"
      dc_region: "<DC_REGION>"         # e.g. EU10, US10, AP11
      # No requests_tree_item needed — defaults to "Internal request(s)"
    datasphere:
      base_url: "${DATASPHERE_BASE_URL_<TENANT_ID>}"
      session_file: "storage_state_datasphere_<tenant_id>.json"
      sign_in_path: "/dwaas-core/index.html#/spaceManagement"   # EU10 path
      # OR for US10/AP11:
      # sign_in_path: "/dwaas-ui/index.html#/home"
      space_management_path: "/dwaas-core/index.html#/spaceManagement"
      # OR for US10/AP11:
      # space_management_path: "/dwaas-ui/index.html#/managespaces&/ms/overview?view=tile"
      renamed_spaces: false   # set true if spaces are known to be renamed (AP11 = true)
    outputs:
      pending_file:             "outputs/user_lists/pending_<tenant_id>.txt"
      processed_file:           "outputs/user_lists/processed_<tenant_id>.txt"
      deleted_file:             "outputs/user_lists/deleted_<tenant_id>.txt"
      processed_workshops_file: "outputs/user_lists/processed_workshops_<tenant_id>.txt"
```

**2. `.env` and `.env.example`**
```
DATASPHERE_BASE_URL_<TENANT_ID>=https://<tenant-base-url>
```

**3. `src/main.py`** — add to `--tenant` choices:
```python
choices=["eu10", "us10", "ap11", "ap11_2", "<tenant_id>"]
```

**4. `src/<tenant_id>.py`** — create entry point shim:
```python
from src.app import main as _app_main
def main():
    _app_main(tenant="<tenant_id>")
```

**5. `setup.py`** — add console script:
```python
"datasphere-cleanup-<tenant-id>=src.<tenant_id>:main",
```

**6. Output files** — create the five state files:
```bash
touch outputs/user_lists/pending_<tenant_id>.txt
touch outputs/user_lists/processed_<tenant_id>.txt
touch outputs/user_lists/deleted_<tenant_id>.txt
touch outputs/user_lists/pending_workshops_<tenant_id>.txt
touch outputs/user_lists/processed_workshops_<tenant_id>.txt
```

**7. Reinstall entry points:**
```bash
pip install -e .
```

**8. Sign in:**
```bash
python -m src.main --tenant <tenant_id> --sign-in
python -m src.main --tenant <tenant_id> --sign-in-datasphere
```

### What happens automatically
- Combined GUI picks up the new tenant via `_all_tenants()` — no UI code changes
- Sidebar footer, top bar subtitle, and stage button labels update automatically
- Tenant checkbox appears in the Authentication page
- Log routing (`[TENANT]` prefix) works without changes

---

## Track B — Adding a Public Tenant

Public tenants have several DOM differences from internal tenants. Each was discovered
empirically on AP11(2) and is documented here so future tenants don't repeat the same debugging.

### Known differences (confirmed on AP11(2))

| Area | Internal | Public |
|---|---|---|
| Portal sidebar selector | `Tree Item Internal request(s)` | `Tree Item Public request(s)` |
| Portal search input | `[role="searchbox"]` | `input[type='search'].fdp-search-field__input` |
| Workshop row hrefs | `a[href*="/academy-request/"]` | `a[href*="/ge-request/"]` |
| User ID format | `AC\d+U\d+` (e.g. `AC304708U00`) | `GE\d+` (e.g. `GE334927`, no `U\d+` suffix) |
| Datasphere identifier-txt | Contains technical ID | Contains display name (e.g. `SPACE_00017554`) |
| Autocomplete render speed | Fast (< 3s) | Slow (can exceed 3s — use 15s timeout) |

All of the above are already handled in the codebase. Adding a new public tenant requires
only config + files — **no code changes** — as long as the new tenant matches AP11(2)'s pattern.

### Checklist

**1. `config/settings.yaml` — add tenant block**

The critical difference is `requests_tree_item: "Public request(s)"` in the portal section,
and `renamed_spaces: true` in the datasphere section:

```yaml
tenants:
  <tenant_id>:               # e.g. ap11_2, ap11_3
    portal:
      base_url: "${PORTAL_BASE_URL}"
      session_file: "storage_state_portal_<tenant_id>.json"
      dc_region: "<DC_REGION>"         # e.g. AP11
      requests_tree_item: "Public request(s)"   # ← REQUIRED for public tenants
    datasphere:
      base_url: "${DATASPHERE_BASE_URL_<TENANT_ID>}"
      session_file: "storage_state_datasphere_<tenant_id>.json"
      sign_in_path: "/dwaas-core/index.html#/spaceManagement"
      space_management_path: "/dwaas-core/index.html#/managespaces&/ms/overview?view=tile"
      renamed_spaces: true    # ← REQUIRED — public tenant spaces are always renamed
    outputs:
      pending_file:             "outputs/user_lists/pending_<tenant_id>.txt"
      processed_file:           "outputs/user_lists/processed_<tenant_id>.txt"
      deleted_file:             "outputs/user_lists/deleted_<tenant_id>.txt"
      processed_workshops_file: "outputs/user_lists/processed_workshops_<tenant_id>.txt"
```

**2–8.** Same as Track A steps 2–8 above.

### What the code does automatically for public tenants

Once `requests_tree_item` and `renamed_spaces` are set in config, the following all
happen without any code changes:

**Stage 1 (portal scrape):**
- `_go_to_filtered_list` clicks "Public request(s)" instead of "Internal request(s)"
- `_extract_users_from_workshop` navigates directly to each workshop by ID via `_go_to_filtered_list`
  (no scroll-to-find loop) — this is essential for tenants with long workshop lists where
  the batch may collect IDs from far down the page
- `_search_autocomplete` waits up to 15s for the dropdown (handles slow render)
- `_WORKSHOP_IDS_JS` matches `/ge-request/` hrefs
- `_wait_for_list_ready` accepts `/ge-request/` rows
- `_extract_users_from_workshop` reads `td.fd-table__cell` and matches `GE\d+(?:U\d+)?`

**Stage 2 (deletion):**
- Pass 1 searches by exact user ID — works even for renamed spaces (subheading still matches)
- Pass 2 fires when Pass 1 returns nothing — uses full `GE\d+` ID as prefix
- `space_was_renamed` detected when `headline != user_id` — uses display name for tile search
- `_find_btn_id_for_user(match_text=headline)` scans identifier-txt for the display name

---

## Diagnosing "not_found" false negatives on a new tenant

If Stage 2 reports everything as `not_found` but you can see the spaces in Datasphere:

### Step 1 — Is the autocomplete returning results?

In the Datasphere Space Management page, type a user ID in the search box and run:
```javascript
document.querySelector('[role="listbox"].sapMSelectList')?.innerHTML.slice(0, 500)
```
- If `null`: the autocomplete isn't appearing. Check `_SPACE_MGMT_SEARCHBOX` selector.
- If HTML appears but Playwright still returns `[]`: the 15s timeout is still too short
  (unlikely but increase `_WAIT_TIMEOUT` in `datasphere_client.py`).

### Step 2 — What does identifier-txt contain?

Search by the user ID or display name, let tiles load, then run:
```javascript
[...document.querySelectorAll('[id$="spaceTileHeader-identifier-txt"]')]
  .map(e => e.innerText.trim()).slice(0, 5).join('\n')
```
- If it shows the **technical ID** (e.g. `GE334927`): `space_was_renamed = False` path is correct.
- If it shows the **display name** (e.g. `SPACE_00017554`): `space_was_renamed = True` path needed —
  confirm `renamed_spaces: true` is set in config.

### Step 3 — Does searching by display name load one tile or many?

If `tile_search_id = headline = SPACE_00017554` loads 25+ unrelated tiles, the
identifier-txt scan with `match_text=headline` is the only way to find the right tile —
this is already implemented. Check that `space_was_renamed` is being set correctly.

### Step 4 — Check for short hardcoded timeouts

**This was the root cause of all AP11(2) false negatives.** Search for short timeouts:
```bash
grep -n "timeout=[0-9]\{4\}" src/datasphere_client.py src/portal_client.py
```
Any timeout under 15000ms that guards a wait-for-selector call is a candidate.
On a slow tenant, `_search_autocomplete` silently returns `[]` if the dropdown
takes longer than the timeout — every subsequent fix is built on a false foundation.

---

## Quick reference — config keys that control tenant behaviour

| Key | Default | Effect |
|---|---|---|
| `portal.requests_tree_item` | `"Internal request(s)"` | Which sidebar item to click on the portal |
| `portal.dc_region` | `"EU10"` | DC Region filter applied during scrape |
| `datasphere.renamed_spaces` | `false` | Enables Pass 2 prefix search + display-name tile matching |
| `datasphere.sign_in_path` | — | Path used to navigate to Datasphere for sign-in |
| `datasphere.space_management_path` | — | Path used to navigate to Space Management |
