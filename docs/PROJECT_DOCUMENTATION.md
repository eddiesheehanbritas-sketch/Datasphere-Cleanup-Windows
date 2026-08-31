# datasphere-cleanup — Project Documentation

This document is the full architecture reference for the datasphere-cleanup project.
For operational instructions (how to run, how to sign in, how to add tenants) see
`README.md` and `docs/adding-tenants.md`.

---

## 1. Purpose

Automates cleanup of residual SAP Datasphere spaces left by expired Academy (AC) and
GE trial users. Operates across **six tenants**: EU10, US10, AP11, AP11(2), EU10(2),
and US10(2). Driven by a four-stage pipeline:

1. **Stage 1** — Scrapes the SAP Self-Service Content Portal, filters by
   `Environment: Cleaned` and `DC Region`, and writes Cleaned workshop IDs to the
   pending-workshops queue for Stage 2.
2. **Stage 2** — For each pending workshop, searches Datasphere Space Management by
   workshop number, bulk-selects all matching spaces, and deletes them in one operation
   (the **workshop-sweep model**).
3. **Stage 3** — Re-queries every deleted space to confirm it is actually gone.
4. **Stage 4** — Permanently purges from the Datasphere recycle bin spaces deleted by
   this pipeline that are ≥7 days old.

---

## 2. Tech Stack

| Component | Version | Notes |
|---|---|---|
| Python | 3.9 | Required — entry points registered via setup.py |
| Playwright | ≥1.44.0 | `async_api` only — never revert to `sync_api` |
| PyQt5 | ≥5.15.11 | GUI windows (`app.py`, `combined.py`) |
| PyYAML | ≥6.0.1 | Config loading |
| python-dotenv | ≥1.0.0 | `.env` credential injection |
| pytest | ≥8.0.0 | Unit tests |
| pytest-asyncio | ≥1.2.0 | Async test support |
| pytest-cov | ≥7.1.0 | Coverage reporting |

**All Playwright code uses `async_playwright` from `playwright.async_api`.** The public
stage entry points are synchronous wrappers that call `asyncio.run()` on an internal
`_run_*_async` coroutine. Never use `sync_playwright` anywhere in production code.

---

## 3. Project Structure

```
datasphere-cleanup/
├── config/
│   ├── settings.yaml          ← all runtime config (shared + per-tenant overrides)
│   └── allowlist.txt          ← space IDs that must never be deleted
├── src/
│   ├── app.py                 ← PyQt5 single-tenant GUI
│   ├── auth.py                ← async browser session save/load
│   ├── combined.py            ← PyQt5 combined GUI (all active tenants)
│   ├── config.py              ← YAML + .env loader; load_tenant_config()
│   ├── datasphere_client.py   ← async Playwright: find/delete/verify spaces
│   ├── eu10.py / us10.py / ap11.py / ap11_2.py / eu10_2.py / us10_2.py
│   ├── logging_setup.py       ← structured logging; _ThreadFileHandler
│   ├── main.py                ← CLI entry point
│   ├── portal_client.py       ← async Playwright: portal scrape
│   ├── probes/                ← standalone DOM investigation scripts
│   ├── report.py              ← JSON report generation
│   ├── retry.py               ← async exponential backoff decorator
│   ├── stage1_discovery.py    ← Stage 1 orchestration
│   ├── stage2_deletion.py     ← Stage 2 orchestration
│   ├── stage3_verify.py       ← Stage 3 orchestration
│   └── stage4_purge.py        ← Stage 4 orchestration
├── tests/
└── outputs/
    ├── user_lists/            ← pending/processed/deleted/workshop state files
    ├── reports/               ← JSON deletion and verification reports
    └── logs/                  ← per-run structured log files
```

---

## 4. Entry Points

Registered in `setup.py` as console scripts, installed via `pip install -e .`:

| Command | Module | Description |
|---|---|---|
| `datasphere-cleanup-combined` | `src.combined:main` | **Preferred** — all active tenants |
| `datasphere-cleanup-combined-demo` | `src.combined:main_demo` | All tenants, Stage 1 capped |
| `datasphere-cleanup-eu10` | `src.eu10:main` | EU10 single-tenant GUI |
| `datasphere-cleanup-us10` | `src.us10:main` | US10 single-tenant GUI |
| `datasphere-cleanup-ap11` | `src.ap11:main` | AP11 single-tenant GUI |
| `datasphere-cleanup-ap11-2` | `src.ap11_2:main` | AP11(2) single-tenant GUI |
| `datasphere-cleanup-eu10-2` | `src.eu10_2:main` | EU10(2) single-tenant GUI |
| `datasphere-cleanup-us10-2` | `src.us10_2:main` | US10(2) single-tenant GUI |
| `datasphere-cleanup` | `src.main:main` | CLI entry point |

Each single-tenant shim (`eu10.py`, `us10.py`, etc.) is a 10-line file that calls
`src.app.main(tenant="<id>")`. Adding a new tenant requires creating one of these
shims and adding it to `setup.py` — no other code changes.

---

## 5. Configuration System (`src/config.py`)

Config is loaded by `load_tenant_config(tenant_id)`:

1. `config/settings.yaml` is parsed with PyYAML.
2. `${VAR}` placeholders are resolved from environment variables loaded from `.env`.
   A `ValueError` is raised immediately if any referenced variable is unset.
3. The top-level shared config is deep-merged with `tenants.<tenant_id>` overrides —
   tenant-specific values win.

**All output paths in `settings.yaml` are relative**, resolved against the process CWD.
Both GUI entry points (`app.py`, `combined.py`) call `os.chdir(project_root)` before
anything else, so they are always anchored correctly regardless of where launched from.
CLI (`main.py`) does not set CWD — must be run from the project root.

---

## 6. Multi-Tenant Architecture

Each tenant has its own:
- Portal and Datasphere browser sessions (JSON storage state files)
- Output state files (`pending_workshops_<tenant>.txt`, `deleted_<tenant>.txt`, etc.)
- Config block under `tenants.<tenant_id>` in `settings.yaml`
- Entry point shim (`src/<tenant_id>.py`)

**Datasphere URL paths differ by tenant:**

| Tenant | Sign-in path | Space Management path |
|---|---|---|
| EU10, AP11(2), EU10(2) | `/dwaas-core/index.html#/spaceManagement` | `/dwaas-core/index.html#/spaceManagement` |
| US10, AP11, US10(2) | `/dwaas-ui/index.html#/home` | `/dwaas-ui/index.html#/managespaces&/ms/overview?view=tile` |

**Portal behaviour differs by tenant type:**

| Key | Internal tenants (EU10/US10/AP11) | Public tenants (AP11(2)/EU10(2)/US10(2)) |
|---|---|---|
| `portal.requests_tree_item` | `"Internal request(s)"` | `"Public request(s)"` |
| `portal.dc_region` | `EU10` / `US10` / `AP11` | `AP11` / `EU10` / `US10` |
| Workshop hrefs | `/academy-request/` | `/ge-request/` |
| User ID format | `AC\d+U\d+` | `GE\d+` (no `U` suffix) |
| `datasphere.renamed_spaces` | `false` | `true` |

When `renamed_spaces: true`, Stage 2 uses the display name (headline) rather than the
user ID as the tile search term, because SAP no longer indexes renamed tiles by technical
ID.

---

## 7. Async Architecture

### Stage module pattern

Every stage module follows this pattern:

```python
async def _run_stageN_async(...):   # real implementation, uses await
    ...

def run_stageN(...):                # sync public wrapper called by GUI/CLI
    return asyncio.run(_run_stageN_async(...))
```

GUI workers call `run_stageN(...)` synchronously. `asyncio.run()` creates a fresh
event loop per stage invocation.

### Combined app concurrency

`combined.py` runs all active tenants via `_gather_tenants(tenants, run_tenant)`,
which calls `asyncio.gather(..., return_exceptions=True)`. This isolates per-tenant
failures — one tenant raising an exception does not cancel its siblings. Tenant-serial
operations (sign-in) use sequential awaits instead.

### `retry.py`

`with_retry(backoff)` wraps `async def` functions only. It retries on Playwright
`Error`/`TimeoutError`, `asyncio.TimeoutError`, and `RuntimeError` (the code's own
transient signals). Deterministic bugs (`KeyError`, `AttributeError`, `TypeError`,
`ValueError`) re-raise immediately — they are never retried.

---

## 8. Stage 1 — Portal Scrape (`portal_client.py`)

### Flow

1. `_go_to_filtered_list` navigates to the portal and applies filters:
   - Environment: Cleaned
   - DC Region (per tenant config)
   - Optionally: Start date range, End date range, Workshop ID range
2. After each filter's OK click, `_wait_for_filter_query_settled` runs. This is the
   **filter-stale-read safety gate** — it waits for the SAPUI5 busy overlay to clear,
   then hard-confirms that the visible workshop-ID set has actually changed from the
   pre-filter snapshot. If the rows never change within `_WAIT_TIMEOUT`, it raises
   `RuntimeError("SAFETY ABORT")` — fail-closed rather than scrape stale rows.
3. `_verify_filters_active` confirms the portal's own "Filtered by:" toolbar shows all
   required filters. This is belt-and-braces — the settle wait above is the real safety
   gate; the toolbar check adds a second confirmation.
4. `_collect_next_batch` scrolls the filtered list and collects unprocessed workshop IDs.
5. Each collected workshop ID is written to `pending_workshops_<tenant>.txt` via
   `append_pending_workshop` (dedup against pending and already-processed), then marked
   processed in `processed_workshops_<tenant>.txt`.

### Workbook selection

Stage 1 types a search term into the portal searchbox before applying filters. This
selects which workbook's requests appear. Three terms are defined in `portal_client.py`:

| Key | Search term typed |
|---|---|
| `overview` | `SAP Datasphere Overview` (default) |
| `integration` | `SAP Analytics Cloud Planning and Datasphere Integration` |
| `basic_trial` | `Basic Trial - Introduction to SAP Analytics Cloud` |

Set via `--search-term` on the CLI, or via radio buttons in the GUI. The term is stored
in `cfg["portal"]["search_term"]` — no dedicated parameter is threaded through the call
stack.

---

## 9. Stage 2 — Workshop-Sweep Deletion (primary model)

### Why the workshop-sweep model exists

The legacy per-user model searched Datasphere by AC user ID. Live probing showed this
misses spaces: a single workshop can have more spaces in Datasphere than users listed in
the portal (renamed `POOL_XA_*` spaces, users not listed). Searching by **workshop
number** surfaces all of a workshop's spaces in one query, including renamed ones.

### Flow (`stage2_deletion.py` → `datasphere_client.py`)

For each workshop in `pending_workshops_<tenant>.txt`:

1. `find_workshop_spaces(page, workshop, cfg)` — types the workshop number into Space
   Management search, presses Enter, waits for the grid to settle, then reads every
   card. Only cards whose leaf-text user ID matches `^(AC|GE)<workshop>(U\d+)?$` are
   returned (over-match guard: prevents `284660` from matching `1284660`).

2. **Search-settle guard** (`_wait_for_search_settled`) — polls until the tile grid
   reaches a stable terminal state:
   - **Stable empty** → valid "no spaces" result, returns `[]`
   - **Stable with matching cards** → at least one card's leaf text matches the workshop
     pattern (checked via `_visible_card_user_ids`, which walks card leaf nodes — not
     the headline — so renamed `POOL_XA_*`/`SPACE_*` tiles are recognised)
   - **Stable but no card matches** → stale default grid (search silently didn't fire) →
     keep polling; fail-closed on timeout with `RuntimeError`

3. `delete_workshop_spaces(page, workshop, cards, cfg, dry_run, allowlist)`:
   - Drops allowlisted cards (`skipped_allowlist`)
   - In dry-run mode: logs `skipped_dry_run` per card, no clicks
   - Live mode: ticks each card's `.sapMCb` checkbox by container index, asserts
     ticked-count == intended-count (guard), clicks bulk Delete button, types `DELETE`
     in the confirmation input, clicks OK — **once, not retried** (prepare/commit split)
   - Logs each deleted space ID to `deleted_<tenant>.txt`
   - Marks the workshop swept: removed from `pending_workshops_<tenant>.txt`, added to
     `processed_workshops_<tenant>.txt`

4. Navigates back to Space Management between workshops.

### Safety gates in Stage 2

| Gate | What it prevents |
|---|---|
| Per-card user-ID regex validation | Over-match — e.g. workshop `284660` matching space `1284660` |
| Allowlist check | Permanent protection for specific space IDs |
| ticked == intended assertion | Deleting an unexpected number of spaces |
| Prepare/commit split | Retrying a committed deletion against a navigated DOM |
| Single commit click | The committing OK click fires exactly once |
| dry_run + config gate | Live deletion without explicit intent |
| Circuit breaker (20% failure rate) | Runaway failures on the tenant run |

### Per-user fallback (`--input`)

`run_stage2(input_file, ...)` in `stage2_deletion.py` provides a legacy per-user path
invoked only when `--input <file>` is passed on the CLI. It reads AC/GE user IDs from
the file and searches Datasphere per user via `find_all_spaces` / `delete_all_spaces`.
This path is not used by either GUI or by `--stage2` without `--input`.

---

## 10. Stage 3 — Verification (`stage3_verify.py`)

Re-queries every space in the Stage 2 report via `search_and_verify_space`. Uses the
AC/GE user ID as the search key (immutable technical ID) and checks whether the specific
space ID is still in the autocomplete results. Writes a `verification_<run_id>.json`
report with `confirmed_deleted` or `still_exists` per space.

---

## 11. Stage 4 — Recycle Bin Purge (`stage4_purge.py`)

Permanently deletes from the Datasphere recycle bin spaces that:
1. Appear in `deleted_<tenant>.txt` (deleted by this pipeline)
2. Have been deleted for ≥7 days
3. Are NOT flagged `still_exists` in any `verification_*.json` report

`load_still_exists_exclusions` reads every verification report in `reports_dir` and
subtracts any `still_exists` space IDs from the eligible set before purging. This
prevents permanently purging a space that Stage 2 reported as deleted but Stage 3 later
found still existed.

---

## 12. Combined GUI (`src/combined.py`)

`datasphere-cleanup-combined` opens a single PyQt5 window with three sections:
Authentication, Pipeline, and Workshop.

**Key design points:**

- Tenant list is derived from `_all_tenants()` at startup — no hardcoded tenant names
  anywhere in the UI. Adding a new tenant to `settings.yaml` automatically updates all
  labels, buttons, and log routing.
- `_run_single(fn, label)` — one QThread; `fn` iterates active tenants via
  `_gather_tenants`, which uses `asyncio.gather(return_exceptions=True)` for per-tenant
  failure isolation.
- `_TenantLogHandler` routes log records to the GUI log box with `[TENANT]` prefix,
  using a `contextvars.ContextVar` (`_active_tenant_prefix`) set in
  `_patch_combined_logger`. ContextVars propagate into `asyncio.wait_for` child tasks,
  which plain thread-ident checks do not — this is why the log routing uses ContextVar.
- `Worker.run()` emits `done_signal` in every exit path (success, exception, Ctrl-C),
  so a failed run never leaves buttons permanently disabled.

---

## 13. Persistent State Files

| File | Written by | Read by | Notes |
|---|---|---|---|
| `pending_workshops_<tenant>.txt` | Stage 1 (append) | Stage 2 (read + remove) | Primary Stage 2 input |
| `processed_workshops_<tenant>.txt` | Stage 1 (append) | Stage 1 (skip) | Prevents re-scraping |
| `pending_<tenant>.txt` | Stage 1 legacy / `--input` | Stage 2 `--input` path | Legacy per-user queue |
| `processed_<tenant>.txt` | Stage 2 legacy | Stage 1 legacy, Stage 2 | Legacy per-user log |
| `deleted_<tenant>.txt` | Stage 2 (append) | Stage 4, audit | **Immutable audit log** |

`deleted_<tenant>.txt` format: `SPACE_ID YYYY-MM-DD` (one entry per line).

---

## 14. Logging Architecture

`logging_setup.py` defines `_ThreadFileHandler` — a file handler that only writes
records from a specific OS thread (`thread_ident`). This allows separate log files per
tenant when multiple tenants share one thread.

`combined.py` defines `_TenantLogHandler` — routes log records to the GUI log box with
`[TENANT]` prefix. Uses `contextvars.ContextVar` (not thread identity) because
`asyncio.wait_for` creates child tasks that do not inherit thread identity but do inherit
ContextVar values.

---

## 15. Circuit Breaker

Stage 2 aborts if the real failure rate exceeds 20% after at least 10 real attempts.
`skipped_dry_run`, `skipped_allowlist`, and `not_found` outcomes are excluded from the
failure rate calculation.

---

## 16. Safety Gate Detail — Filter Stale-Read Race

**This was the most serious bug the project has had (fixed 2026-08-07).**

The SAPUI5 "Filtered by:" toolbar chip updates synchronously when a filter's OK is
clicked, but the row set only updates when the background OData query returns. Reading
rows before the query settles scrapes the stale pre-filter set — which is how active
(non-Cleaned) workshops were being scraped despite the chip showing "Cleaned", causing
live users' spaces to be deleted.

The fix in `_go_to_filtered_list`:
- `_wait_for_filter_query_settled(page, prev_ids=...)` runs after each filter's OK click.
- First: best-effort wait for the SAPUI5 busy overlay to appear then clear, plus
  networkidle.
- Then for the Environment=Cleaned filter: hard confirmation — the pre-filter workshop-ID
  set is captured before OK, passed as `prev_ids`; polls until the visible ID set
  actually differs (or a no-data indicator shows). Raises `RuntimeError("SAFETY ABORT")`
  if rows never change within `_WAIT_TIMEOUT`.

`_verify_filters_active` (toolbar chip check) is necessary but not sufficient on its own
— it proves the chip is correct, which is decoupled from the rendered rows.

---

## 17. Safety Gate Detail — Search-Settle Guard

Stage 2's `_wait_for_search_settled` prevents reading a stale tile grid after a
workshop-number search. A stable empty grid is a valid "no spaces" result (confirmed on
AP11 for workshops with no remaining spaces). A stable grid where no card carries the
searched workshop's ID is not accepted — it means the default unfiltered grid is still
showing.

The guard matches against card leaf-text nodes (`_visible_card_user_ids`), not the
identifier-txt headline. This is essential for renamed-space workshops: a workshop with
25 `POOL_XA_*` headlines would never match on headline alone — the real AC/GE user ID
lives in a sibling text node inside each card.

---

## 18. Test Suite

**305 tests, all passing.** Run with:

```bash
python -m pytest tests/ -q
python -m pytest tests/ --cov=src --cov-report=term-missing
```

### Coverage

| File | Coverage | Notes |
|---|---|---|
| `stage3_verify.py` | 100% | Complete |
| `stage2_deletion.py` | 98% | Near-complete |
| `stage1_discovery.py` | 94% | Near-complete |
| `config.py` | 93% | Near-complete |
| `report.py` | 95% | Near-complete |
| `retry.py` | 90% | Near-complete |
| `stage4_purge.py` | 92% | Near-complete |
| `datasphere_client.py` | 73% | Remaining lines are live browser sequences |
| `portal_client.py` | 58% | Remaining lines are live browser sequences |

### What is not tested (and why)

The following require a live Playwright browser connected to SAP and cannot be unit tested:
- `_delete_one_space` — live deletion click sequence
- `_wait_for_space_mgmt_ready` — requires real SAPUI5 busy overlay
- `_go_to_filtered_list` — requires real portal DOM
- `run_portal_scrape` / `scrape_single_workshop` — require real portal session

All other paths — safety gates, outcome codes, file I/O, retry logic, circuit breaker,
workshop-sweep model, age filtering, pagination — are unit tested.

### Test files

| File | What it covers |
|---|---|
| `test_config.py` | YAML loading, env var interpolation, tenant deep-merge |
| `test_deletion.py` | Dry-run, allowlist, circuit breaker, retry, `DeleteResult` outcomes, `find_all_spaces`, `delete_all_spaces`, `_find_btn_id_for_user`, Pass 1/Pass 2 gating, renamed space detection |
| `test_discovery.py` | AC/GE user ID pattern, dedup, pending queue append logic |
| `test_integration.py` | End-to-end Stage 1 + Stage 2 with mocked browser |
| `test_portal_client.py` | User ID patterns, processed workshops, `_collect_next_batch`, `_verify_filters_active`, filter-settle safety gate, search term forwarding |
| `test_purge.py` | `load_deleted_log` age filtering, `_collect_tile_ids`, `_click_permanent_delete`, `PurgeResult` outcomes, multi-page loop |
| `test_verification.py` | Stage 3 report parsing, `confirmed_deleted` vs `still_exists` |
| `test_workshop_cleanup.py` | Single-workshop scrape, workshop queue UI logic (add/validate/remove/launch guard) |

### Mock pattern

All browser mocks use `make_async_playwright_mocks()` from `tests/conftest.py`. Always
patch `async_playwright` not `sync_playwright`. Async `side_effect` functions must be
`async def`. Never add browser-dependent assertions to unit tests.

---

## 19. Current Operational State (as of 2026-08-26)

| Metric | EU10 | US10 | AP11 | AP11(2) | EU10(2) | US10(2) |
|---|---|---|---|---|---|---|
| `pending_workshops` | 0 | 0 | 377 | 640 | 0 | 0 |
| `dry_run` in config | `false` | `false` | `false` | `false` | `false` | `false` |

⚠️ `dry_run: false` globally. The live-deletion gate is held only by omitting `--execute`
(CLI) or leaving the dialog dry-run box checked (GUI).

⚠️ **EU10(2):** 49 active `GE…` users from the 2026-08-07 filter-race incident are
quarantined in `outputs/user_lists/quarantine_eu10_2_active_users_20260807.txt`.
Inspect the quarantine before any EU10(2) run.

⚠️ **Corrupted spaces on AP11(2):** `SPACE_00012083`, `SPACE_00012214` (user `GE317815`),
and `SPACE_00006571` (user `GE301567`) have broken cross-space dependencies and return
HTTP 400 `validateDeleteSpaceObjects`. They are in `config/allowlist.txt` and must be
handled via SAP admin force-delete.

---

## 20. Known Fragile Selectors

### Portal (`portal_client.py`)
- Tree item: `[aria-label^='Tree Item Internal request(s)']` (starts-with — SAP appends trailing `, `)
- Filter button: `[role='option'][aria-label='Filter']`
- Environment filter: `li[role='listitem'] span.fd-list__title:text-is('Environment')` — text-based, stable
- Cleaned option: `li[role='option']:has-text('Cleaned')` — text-based, stable
- **Never use positional `#fd-list-item-N` IDs** — they shift when SAP adds/removes columns

### Datasphere (`datasphere_client.py`)
- Space Management searchbox: `[id*='manageSpaces--filterSpacesInput-I'], [id*='spaceManagement'] [role='searchbox'], [id*='managespaces'] input[type='search']`
- Tile identifier: `[id$='spaceTileHeader-identifier-txt']`
- Open button: `[id*='spaceTileFooter--openSpaceButton']`
- Additional Options: `#shellMainContent---managespacesComponent---spaceDetails--overflowToolbar-overflowButton`
- Bulk delete button: `[id$='manageSpaces--toolbar--deleteButton']`
- Confirm dialog input: `[id*='DeleteConfirmationDialog--dialog--view--deleteInput-inner']`
- Confirm OK: `[id*='DeleteConfirmationDialog--dialog--view--ok']`

If any selector stops working, run the relevant probe script before editing:
```bash
python -m src.probes.probe_portal
python -m src.probes.probe_datasphere
python -m src.probes.probe_recycle_bin
```
