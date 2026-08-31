# datasphere-cleanup

Automates the cleanup of residual SAP Datasphere spaces left behind by expired
Academy (AC) and GE trial users across six tenants: **EU10, US10, AP11, AP11(2),
EU10(2), and US10(2)**.

The tool works in four stages:

1. **Stage 1 — Discovery:** Scrapes the SAP Self-Service Content Portal to find
   workshops whose environment is marked "Cleaned", and appends their IDs to the
   tenant-specific pending-workshops queue.
2. **Stage 2 — Deletion:** For each pending workshop, searches Datasphere Space
   Management by workshop number, bulk-selects all matching spaces, and deletes
   them in one operation. This is the **workshop-sweep model** — it finds every
   space in a workshop (including renamed ones) in a single search, which is more
   complete than searching per user ID.
3. **Stage 3 — Verification:** Re-queries every deleted space to confirm it is
   actually gone, and flags any discrepancies.
4. **Stage 4 — Recycle Bin Purge:** Permanently removes from the Datasphere
   recycle bin any space deleted by this pipeline that is ≥7 days old.

The preferred entry point is `datasphere-cleanup-combined`, which runs all active
tenants from a single window.

> **Safety gate:** No deletions occur unless `dry_run: false` is set in config
> **AND** you confirm in the GUI dialog (or pass `--execute` on the CLI). Both
> gates must be open simultaneously.

---

## Prerequisites

- Python 3.9+
- A SAP Universal ID with:
  - Access to the SAP Self-Service Content Portal
  - Full admin rights on all Datasphere tenants you intend to clean
- Your SAP operator I-number (format: `I######`)

---

## Setup

### 1. Create a virtual environment and install dependencies

```bash
cd datasphere-cleanup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Create the output directories

```bash
mkdir -p outputs/user_lists outputs/logs outputs/reports/archive
```

### 3. Configure credentials

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```dotenv
PORTAL_BASE_URL=https://...
DATASPHERE_BASE_URL_EU10=https://...
DATASPHERE_BASE_URL_US10=https://...
DATASPHERE_BASE_URL_AP11=https://...
DATASPHERE_BASE_URL_AP11_2=https://...
DATASPHERE_BASE_URL_EU10_2=https://...
DATASPHERE_BASE_URL_US10_2=https://...
```

Credentials are never hardcoded and never committed — `.env` is gitignored.

### 4. Install entry points

```bash
pip install -e .
```

### 5. Review settings

Open `config/settings.yaml`. Key settings to confirm before first use:

| Setting | Default | Notes |
|---|---|---|
| `dry_run` | `false` | Set `true` to preview without deleting |
| `circuit_breaker.failure_rate_threshold` | `0.20` | Aborts Stage 2 if >20% of attempts fail |
| `retry.backoff_seconds` | `[5, 15, 60]` | Wait times between retry attempts |
| `datasphere.post_delete_pause` | `12.0s` | Gap after each deletion; SAP's backend is async |

---

## Running the tool

### Recommended: combined GUI (all tenants)

```bash
cd ~/Desktop/datasphere-cleanup
source .venv/bin/activate
datasphere-cleanup-combined
```

This opens a single window that runs all active tenants serially. The three
sections are Authentication, Pipeline, and Workshop.

**Standard run order:**

1. **Sign In — Portal** — complete portal login for each tenant in the browser
2. **Sign In — Datasphere** — complete Datasphere login for each tenant
3. **Run Stage 1** — scrapes portal, populates pending-workshops queues
4. **Run Stage 2** — review the confirmation dialog, uncheck Dry Run for live deletions
5. **Run Stage 3** — verify deletions; check log for any `still_exists` entries
6. **Run Stage 4** — purge recycle bin; set a max-per-tenant limit if desired

Sessions are saved as JSON files and reused across runs (valid for several hours).
Re-sign-in whenever a session expires.

---

### Targeted workshop scrape (GUI)

The Workshop section lets you scrape specific workshops by ID and feed them
directly into the pending-workshops queue, without running a full Stage 1.

1. Type a 5–7 digit workshop ID into the input field and click **Add** (or press Enter).
   Repeat for as many workshops as needed — each ID appears in the queue list.
2. To remove an ID before launching, select it and click **Remove Selected**.
3. Click **Launch (N)** to scrape all queued workshops in order. The queue is
   cleared immediately when launch begins.

---

### Single-tenant GUIs

```bash
datasphere-cleanup-eu10        # EU10 only
datasphere-cleanup-us10        # US10 only
datasphere-cleanup-ap11        # AP11 only
datasphere-cleanup-ap11-2      # AP11(2) only
datasphere-cleanup-eu10-2      # EU10(2) only
datasphere-cleanup-us10-2      # US10(2) only
datasphere-cleanup-combined-demo   # All tenants, Stage 1 capped at 10 workshops
```

---

### CLI

```bash
# Stage 1
python -m src.main --tenant eu10 --stage1
python -m src.main --tenant us10 --stage1
python -m src.main --tenant ap11 --stage1
python -m src.main --tenant ap11_2 --stage1
python -m src.main --tenant eu10_2 --stage1
python -m src.main --tenant us10_2 --stage1

# Workbook / portal search term (Stage 1 and --workshop)
# Default: "SAP Datasphere Overview" (from config)
python -m src.main --tenant eu10 --stage1 --search-term overview
python -m src.main --tenant eu10 --stage1 --search-term integration
python -m src.main --tenant eu10 --stage1 --search-term basic_trial

# Stage 1 with date-range filters (all optional; each range requires both ends)
python -m src.main --tenant eu10 --stage1 --end-date-from 2024-01-01 --end-date-to 2024-06-30
python -m src.main --tenant eu10 --stage1 --start-date-from 2024-01-01 --start-date-to 2024-06-30
python -m src.main --tenant ap11 --stage1 --workshop-id-from 277373 --workshop-id-to 281952

# Stage 2 — dry-run (safe, no deletions)
python -m src.main --tenant eu10 --stage2

# Stage 2 — live (requires dry_run: false in config AND --execute)
python -m src.main --tenant eu10 --stage2 --execute

# Stage 3
python -m src.main --tenant eu10 --stage3 --report outputs/reports/report_eu10_<run_id>.json

# Stage 4
python -m src.main --tenant eu10 --stage4 --execute
python -m src.main --tenant eu10 --stage4 --execute --max-purge 50

# Run all stages end-to-end
python -m src.main --tenant eu10 --all --execute

# Sign in
python -m src.main --tenant eu10 --sign-in
python -m src.main --tenant eu10 --sign-in-datasphere

# Targeted single-workshop scrape
python -m src.main --tenant eu10 --workshop <WORKSHOP_ID>
python -m src.main --tenant ap11_2 --workshop <WORKSHOP_ID>
```

---

## Understanding the outputs

### Log file — `outputs/logs/run_<run_id>.log`

Structured timestamped log of every action. Key lines:

```
[INFO]    workshop 284660: 21 space(s) matched (from 21 card(s))
[INFO]    workshop 284660: bulk-deleted 21 space(s)
[INFO]    workshop 234287: 0 space(s) matched — no spaces to delete
[WARNING] Circuit breaker triggered: failure rate 25% exceeds threshold 20%
```

---

### JSON report — `outputs/reports/report_<run_id>.json`

```json
{
  "run_id": "20260810_220000",
  "generated_at": "2026-08-10T22:00:00+00:00",
  "dry_run": false,
  "summary": {
    "total_users_processed": 83,
    "deleted": 83,
    "not_found": 0,
    "skipped_allowlist": 0,
    "skipped_dry_run": 0,
    "failed": 0
  }
}
```

**Outcome meanings:**

| Outcome | Meaning | Action required |
|---|---|---|
| `deleted` | Space successfully deleted | None |
| `not_found` | No space found for this workshop — already clean | None — normal and expected |
| `skipped_dry_run` | Dry-run was on — no deletion attempted | Re-run with dry-run disabled |
| `skipped_allowlist` | Space is on the protected allowlist | Intentional — review allowlist if unexpected |
| `failed` | Deletion attempted but errored | Check `error` field and log; re-run after fixing |

---

### Verification report — `outputs/reports/verification_<run_id>.json`

```json
{
  "summary": {
    "total_verified": 83,
    "confirmed_deleted": 83,
    "still_exists": 0,
    "check_failed": 0
  }
}
```

Any `still_exists` entries: manually add those user IDs back to
`pending_<tenant>.txt`, remove them from `processed_<tenant>.txt`, and re-run
Stage 2.

---

## Persistent state files

All state is stored as plain text files in `outputs/user_lists/`.

| File | Format | Purpose |
|---|---|---|
| `pending_workshops_<tenant>.txt` | One workshop ID per line | Live sweep queue — consumed by Stage 2 |
| `processed_workshops_<tenant>.txt` | One workshop ID per line | Stage 1 skips already-scraped workshops |
| `pending_<tenant>.txt` | One AC/GE user ID per line | Legacy per-user queue (--input path only) |
| `processed_<tenant>.txt` | One AC/GE user ID per line | Legacy per-user processed log |
| `deleted_<tenant>.txt` | `SPACE_ID YYYY-MM-DD` per line | Immutable audit log — read by Stage 4 |

`deleted_<tenant>.txt` is an **immutable audit log** — never clear or delete it.

---

## Allowlist

Add space IDs to `config/allowlist.txt` (one per line) to permanently protect
them from deletion. Checked before every delete, regardless of dry-run setting.

```
# config/allowlist.txt
# SPACE_00012083    ← example protected space
```

---

## Safety architecture

Six independent layers protect against accidental deletions:

1. **Dry-run mode** — `dry_run: false` in `config/settings.yaml` must be set explicitly
2. **Execute intent** — GUI dry-run checkbox must be unchecked / CLI `--execute` must be passed
3. **Allowlist** — permanent protection for specific space IDs
4. **Filter verification** — Stage 1 reads the portal's own filter toolbar and halts
   (SAFETY ABORT) if Environment:Cleaned or DC Region is not confirmed active
5. **Search-settle guard** — Stage 2 refuses to read tiles until the search grid has
   stabilised to a matching terminal state; fail-closed if it never settles
6. **Circuit breaker** — Stage 2 aborts if the real failure rate exceeds 20% after ≥10 attempts

---

## Recovering from failures

**Session expired mid-run:**
```bash
python -m src.main --tenant eu10 --sign-in-datasphere
```

**Stage 3 reports `still_exists`:**
Manually add the affected user IDs back to `pending_eu10.txt`, remove them from
`processed_eu10.txt`, and re-run Stage 2.

**Circuit breaker tripped:**
Check `outputs/logs/` for the specific error. Common causes: session expired
mid-run (re-sign-in then re-run), or a SAP UI change (run the probe script,
update selectors).

**Re-running after partial failure:**
Re-runs are safe — processed workshops are tracked and skipped automatically.

---

## Selector troubleshooting

The portal and Datasphere are SAPUI5/Fiori applications whose DOM can change
after SAP updates. If a stage produces unexpected results, run the relevant probe
script before editing any selectors:

```bash
python -m src.probes.probe_portal        # portal navigation
python -m src.probes.probe_datasphere    # Datasphere Space Management
python -m src.probes.probe_recycle_bin   # recycle bin UI
```

Each probe steps through the navigation interactively, saves HTML snapshots and
screenshots to `outputs/logs/`, and pauses at each step for inspection.

**Rules:**
- Never use positional SAPUI5 IDs like `#fd-list-item-N` — they shift after portal updates
- Always read the live DOM from the probe before changing a selector
- `page.content()` can lie in SAPUI5 — use `page.evaluate()` for ground truth

---

## Adding a new tenant

See **`docs/adding-tenants.md`** for the full step-by-step guide. It covers:

- **Internal tenants** (EU10/US10/AP11 pattern) — portal uses "Internal request(s)", user IDs are `AC\d+U\d+`
- **Public tenants** (AP11(2)/EU10(2)/US10(2) pattern) — portal uses "Public request(s)", user IDs are `GE\d+`, spaces are renamed

The two config keys that control all behavioural differences:
```yaml
portal:
  requests_tree_item: "Public request(s)"   # public tenants only
datasphere:
  renamed_spaces: true                       # public tenants only
```

---

## Testing

```bash
source .venv/bin/activate
python -m pytest tests/ -v
python -m pytest tests/ --cov=src --cov-report=term-missing  # with coverage
```

305 tests covering: workshop ID pattern matching, deduplication, allowlist
enforcement, dry-run safety, circuit breaker logic, retry behaviour, Stage 4 age
filtering, report generation, filter-settle safety gates, and workshop queue UI
logic. All tests are pure unit tests — no browser, no network.

---

## Project structure

```
datasphere-cleanup/
├── README.md
├── CLAUDE.md                          ← AI context file
├── requirements.txt
├── setup.py
├── .env.example                       ← Copy to .env and fill in your values
├── config/
│   ├── settings.yaml                  ← All runtime configuration
│   └── allowlist.txt                  ← Space IDs that must never be deleted
├── docs/
│   ├── adding-tenants.md              ← Step-by-step guide for adding tenants
│   ├── adding-workbooks.md            ← Guide for adding portal search terms
│   └── PROJECT_DOCUMENTATION.md      ← Full architecture reference
├── src/
│   ├── app.py                         ← PyQt5 single-tenant GUI
│   ├── auth.py                        ← Async browser session save/load
│   ├── combined.py                    ← PyQt5 combined GUI (all active tenants)
│   ├── config.py                      ← YAML + .env loader
│   ├── datasphere_client.py           ← Playwright wrapper: space find/delete/verify
│   ├── eu10.py                        ← EU10 single-tenant entry point
│   ├── us10.py                        ← US10 single-tenant entry point
│   ├── ap11.py                        ← AP11 single-tenant entry point
│   ├── ap11_2.py                      ← AP11(2) single-tenant entry point
│   ├── eu10_2.py                      ← EU10(2) single-tenant entry point
│   ├── us10_2.py                      ← US10(2) single-tenant entry point
│   ├── logging_setup.py               ← Structured logging with thread isolation
│   ├── main.py                        ← CLI entry point
│   ├── portal_client.py               ← Playwright wrapper: portal scrape
│   ├── probes/                        ← Interactive DOM investigation scripts
│   │   ├── probe_datasphere.py
│   │   ├── probe_portal.py
│   │   ├── probe_portal_date_filter.py
│   │   ├── probe_recycle_bin.py
│   │   ├── probe_workshop_bulk.py
│   │   ├── probe_workshop_nodata.py
│   │   └── probe_interactive.py
│   ├── report.py                      ← JSON report generation
│   ├── retry.py                       ← Async exponential backoff decorator
│   ├── stage1_discovery.py            ← Stage 1 orchestration
│   ├── stage2_deletion.py             ← Stage 2 orchestration
│   ├── stage3_verify.py               ← Stage 3 orchestration
│   └── stage4_purge.py                ← Stage 4 orchestration
├── tests/
│   ├── conftest.py                    ← Fixtures and async mock factory
│   ├── test_config.py
│   ├── test_deletion.py
│   ├── test_discovery.py
│   ├── test_integration.py
│   ├── test_purge.py
│   ├── test_verification.py
│   └── test_workshop_cleanup.py
└── outputs/                           ← Generated at runtime (gitignored)
    ├── user_lists/                    ← Pending queues, processed logs, deleted log
    ├── reports/                       ← JSON deletion and verification reports
    └── logs/                          ← Per-run structured log files
```
