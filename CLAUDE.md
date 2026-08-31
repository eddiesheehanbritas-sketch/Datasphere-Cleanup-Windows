# datasphere-cleanup — Claude Context

This file is the single source of truth for any Claude instance working on this project.
Update it whenever code, state, or architecture changes.

---

## Working Methodology — MANDATORY

**These rules apply to every single prompt without exception. They cannot be skipped, abbreviated, or reordered regardless of how simple the request appears. Human involvement is the highest priority at every step.**

This methodology governs every interaction. The goal is maximum human involvement at every step. No code is written without explicit user permission. No solution is handed off unless it is certain to work. If a solution could fail, either request more information from the user to achieve certainty, or continue the investigative process until the minimal chance of failure is reached. Do not hand the user partial or speculative fixes.

---

### The Six-Step Process

Every prompt — bug report, feature request, question, or operational task — follows this sequence in order. Do not skip steps.

**Step 1 — Receive and analyse the prompt**

Read the prompt carefully. Identify:
- What is being asked (bug fix, feature, question, new tenant, operational task)
- What information is present
- What information is missing
- What files would need to be read to understand the problem fully

Do not open any files yet. Do not form a solution yet. Tell the user what class of request you believe this is and what information you still need.

**Step 2 — Ask questions to fill knowledge gaps**

Before reading any code or forming a solution, ask the user every question needed to fully understand the problem. Tell the user why each question is being asked. Do not proceed until these are answered.

Questions to ask as appropriate:
- Which tenant is affected? (EU10 / US10 / AP11 / AP11(2))
- Which stage is involved? (Stage 1 / 2 / 3 / 4 / Workshop)
- What is the exact symptom? (error message, wrong outcome code, hang, unexpected behaviour)
- Can you share the relevant lines from `outputs/logs/`?
- Is this happening in the GUI or CLI?
- Has this ever worked before, or is it a new setup?
- Is `dry_run` currently true or false in config?

**Never guess at missing information. Always ask.** A solution built on incomplete information will fail. An extra question costs seconds; a wrong fix costs the user's time and risks live data.

**Step 3 — Read the relevant source and state**

Once the problem is fully understood, read exactly the files needed to diagnose it. Before reading each file, tell the user:

> "I'm going to read `src/datasphere_client.py` to understand how the autocomplete timeout is handled, because the symptom you described matches a timeout expiring before the dropdown renders."

Do not read files speculatively. Do not read more than is necessary. After reading, summarise what was found and what it means for the diagnosis.

**Step 4 — Diagnose precisely and present the solution**

State the exact cause:
- The exact file, line number, and variable or condition that is wrong
- Why it is wrong
- What the fix will change
- Why the fix will work
- What could still go wrong and how that risk is mitigated

**Only present a solution you are certain will work.** If there is meaningful uncertainty — missing DOM data, unknown live behaviour, a selector that may have changed — do not present a partial solution. Instead, tell the user what additional information is needed (log output, probe script results, a screenshot) and ask for it before going further.

Do not hand the user a "try this and see" fix. If it might not work, say so explicitly and ask for what is needed to make it certain.

**Step 5 — Wait for explicit confirmation before writing any code**

After presenting the diagnosis and solution, stop completely. Ask the user:

> "Shall I go ahead and make this change?"

Do not begin writing any code until the user gives a clear and explicit yes. If the user has questions or wants changes to the proposed approach, address them fully and re-present the plan before proceeding. Confirmation of one change does not imply confirmation of any subsequent change.

**Step 6 — Implement, verify, and report back**

Make exactly the change described — no more, no less. Then:

1. Run `python -m pytest tests/ -q` and show the result to the user
2. Report clearly what was changed, which file, which line
3. Tell the user whether the fix is verifiable by tests alone or requires a live browser run
4. If a live browser run is needed to confirm, say so explicitly — do not claim the fix is complete until it can be verified

**If anything unexpected is encountered mid-implementation — a file that doesn't match expectations, a test that fails for an unexpected reason, a dependency that makes the change more complex — stop immediately.** Do not push through. Notify the user, explain exactly what was found, and ask how to proceed before continuing.

---

### If a Solution Cannot Be Made Certain

If full certainty requires information that only exists in the live browser (a DOM snapshot, a selector confirmation, a specific SAP UI state), the correct response is:

1. Tell the user clearly that certainty is not possible from code alone
2. Ask the user to run the relevant probe script (`src/probes/probe_portal.py`, `probe_datasphere.py`, `probe_recycle_bin.py`) and share the output
3. Wait for that output before forming the solution

Never skip this step to save time. A selector that worked last week may have changed after a SAP update. Always verify from the live DOM before committing to a selector fix.

---

### Handling Ambiguous or Vague Prompts

When the prompt is vague ("something's broken", "fix the portal", "stage 2 isn't working"):

1. Do not open any files
2. Tell the user what you need to proceed
3. Ask one focused clarifying question at a time — tenant, stage, symptom, log output
4. Ask the user to share the relevant lines from `outputs/logs/` — the outcome codes (`not_found`, `failed`, `still_exists`, circuit breaker message) almost always pinpoint the class of problem
5. Only proceed to Step 3 once the symptom is specific enough to know exactly which files to read

---

### Classifying the Request

Before doing anything, identify which class of request this is and tell the user which class you have identified:

| Class | Indicators | Key question to ask |
|---|---|---|
| **Bug report** | "not working", error message, unexpected outcome code, hang, crash | "Which tenant and stage? Can you share the log output?" |
| **Selector failure** | `not_found` when spaces exist, timeout errors, element not visible | "Can you run the probe script and share the output?" |
| **Feature request** | "add X", "make it do Y", new behaviour | "What exact behaviour do you want, and on which tenants?" |
| **New tenant** | New SAP tenant to onboard | "Is this an internal or public tenant? Which sidebar item do the users appear under?" |
| **Operational question** | "how do I run X", "what does Y mean" | Answer from CLAUDE.md / README — no code changes |
| **Config/state question** | "what's in pending", "how many spaces" | Read the output files directly — ask which tenant first |

---

### Handling Selector Failures

Selector failures are the most common live issue. Never edit a selector by reading source code alone.

1. Tell the user: "I can't confirm the correct selector from code alone — I need the live DOM."
2. Ask the user to run: `python -m src.probes.probe_datasphere` / `probe_portal` / `probe_recycle_bin`
3. Ask them to share the HTML snapshot from `outputs/logs/`
4. Confirm the selector in the snapshot before writing anything
5. **Before concluding a selector is wrong, check for short hardcoded timeouts:** `grep -n "timeout=[0-9]\{4\}" src/datasphere_client.py src/portal_client.py` — a timeout expiring before an element renders looks identical to a missing element. This was the root cause of all AP11(2) `not_found` false negatives.
6. Never use positional SAPUI5 IDs (`#fd-list-item-N`) — they shift after any portal update

---

### Handling "Tests Pass But Live Browser Fails"

The mock does not reflect what SAP actually renders. Do not change production code to match a broken mock.

1. Tell the user: "The tests are passing against a mock that no longer reflects the live UI. I need the live DOM before making any code change."
2. Ask for the probe script output
3. Update the test mock to reflect the live UI
4. Then fix the production code if needed
5. Re-run tests to confirm consistency
6. Report both changes to the user and wait for confirmation before closing the task

---

### Handling Feature Requests

1. Ask the clarifying questions needed to fully understand the desired behaviour before reading any code
2. Read the relevant source files and summarise what was found to the user
3. Draft the full plan: which files change, which new functions are needed, which tests are needed
4. Present the plan in full and wait for explicit confirmation before writing a single line
5. Write tests first if the feature involves a new outcome code, a new safety gate, or a new config key
6. Implement one file at a time, reporting back after each file and asking whether to continue

---

### Handling New Tenant Requests

1. Ask: "Is this an internal or public tenant — which sidebar item do the users appear under on the portal?"
2. Present the relevant checklist from `docs/adding-tenants.md` to the user and confirm each step before executing it
3. No code changes are needed for a standard tenant — config + output files + entry point shim only
4. If the new tenant shows mass `not_found` after setup: follow the renamed space diagnosis below before touching any selectors

---

### Handling Renamed Space `not_found` Failures

This is a recurring failure class with a specific, known cause. Symptoms: Stage 2 reports `not_found` for a user, but the space is visible in Datasphere with a name like `SPACE_00017554` or `POOL_XA_00000284` instead of the original user ID.

**Root cause:** SAP allows admins to rename spaces. When a space is renamed, its display name (headline) in the autocomplete changes, but the original AC/GE user ID remains as the technical ID (subheading). The code handles this via a two-pass strategy — but if the wrong config is set, or a new tenant has a previously unseen rename pattern, the detection silently falls through and records `not_found`.

**Step 1 — Ask the user to confirm what they see in Datasphere**

Before touching any code or config, ask:

> "Can you search for the user ID in Datasphere Space Management and tell me what the autocomplete dropdown shows? Specifically: what is the display name (the text before the brackets) and what is the technical ID (the text inside the brackets)?"

Expected format in the dropdown: `DISPLAY_NAME (TECHNICAL_ID)`

- If `TECHNICAL_ID == user_id` and `DISPLAY_NAME != user_id` → space is renamed, detection should work — proceed to Step 2
- If `TECHNICAL_ID != user_id` → unexpected rename pattern not yet handled — proceed to Step 4
- If nothing appears in the dropdown at all → this is a timeout issue, not a renamed space issue — follow the Selector Failures workflow instead

**Step 2 — Check `renamed_spaces` config for the affected tenant**

Ask the user to check `config/settings.yaml` for the affected tenant's `datasphere.renamed_spaces` value.

- If `renamed_spaces: false` or absent on a tenant where spaces are renamed → this is the fix: set `renamed_spaces: true`. Present this change and wait for confirmation before editing the file.
- If `renamed_spaces: true` is already set → config is correct, proceed to Step 3.

**Why this matters:** Pass 2 (the prefix fallback search) only fires when `renamed_spaces: true`. Without it, Pass 1 fails to match and the user is immediately recorded as `not_found`.

**Step 3 — Check for short hardcoded timeouts**

Even with `renamed_spaces: true`, renamed space detection fails silently if the autocomplete times out before rendering. Run:

```bash
grep -n "timeout=[0-9]\{4\}" src/datasphere_client.py src/portal_client.py
```

Any timeout under 15000ms guarding a `wait_for_selector` or autocomplete wait is a candidate. Ask the user:

> "Is this tenant noticeably slower than EU10/US10 when navigating in the browser?"

If yes, raise the relevant timeout to `_WAIT_TIMEOUT` (15s). Present the specific line and value to the user before editing. This was the confirmed root cause of all AP11(2) `not_found` false negatives.

**Step 4 — Unknown rename pattern**

If the autocomplete shows a technical ID that does not match the searched user ID, this is a new pattern not yet handled. Do not attempt a fix without:

1. Asking the user to run `python -m src.probes.probe_datasphere` and share the full autocomplete HTML
2. Understanding the exact `headline` and `subheading` values for the new format
3. Checking whether `_find_btn_id_for_user` also needs updating (does `identifier-txt` hold the display name or the technical ID on this tenant?)

Only after receiving that information, draft the fix, explain it in full, and wait for confirmation.

**Pass 1 / Pass 2 summary (for reference)**

| Pass | Search term | Fires when | Purpose |
|---|---|---|---|
| Pass 1 | Exact `user_id` | Always | Finds spaces where display name = user ID (unmodified spaces) |
| Pass 2 | Workshop prefix (e.g. `AC355278` stripped of `U\d+`) | `renamed_spaces: true` AND `pass1_only: false` | Finds renamed spaces where the prefix still surfaces the entry |
| Re-search after deletion | `pass1_only=True` always | After each deletion in `delete_all_spaces` | Avoids re-triggering Pass 2 on multi-space users |

---

### Handling Stage 1 Portal Scrape Failures (rewritten 2026-08-07)

The portal scrape (`run_portal_scrape` in `portal_client.py`) was substantially reworked.
Understand the current model before touching it:

**Batch-of-1, re-navigate-per-workshop.** The scrape collects exactly ONE workshop at a
time (`_collect_next_batch(..., batch_size=1)`), clicks into it while its link is still
rendered, extracts users, then fully re-navigates the filtered list before collecting the
next. This replaced the old collect-50-then-process model. Reason: the SAP portal NEVER
preserves filters across `go_back()` (confirmed on every tenant), so every workshop forced
a full re-navigation that reset the list to the top — and the old code then tried to
re-find a deep-in-the-list workshop by scrolling with a 10-step cap, which silently failed
("Workshop N not found after scrolling") for any workshop past the top. `_return_to_filtered_list`
and its `go_back()` fast path were DELETED as dead code. `_extract_users_from_workshop` no
longer scrolls to find the link (the caller just located it) and matches by
`get_by_role("link", name=workshop_id, exact=True)` — `exact=True` prevents `135278` from
matching `1352780`.

**Termination is guaranteed:** every workshop is marked processed in a `finally` (success,
timeout, or error), added to the in-memory `already_processed` set, so it can never be
re-collected; the loop ends when `_collect_next_batch` returns `[]`.

**The filter stale-read race (the catastrophic bug, fixed 2026-08-07).** The SAPUI5
"Filtered by:" toolbar chip updates SYNCHRONOUSLY when the filter's OK is clicked, but the
row set only updates when the background OData query returns. Reading rows (or verifying
filters via the chip) before the query settles scrapes the STALE pre-filter set — which is
how ACTIVE (non-Cleaned) workshops were being scraped despite the chip showing "Cleaned".
This deleted live users' spaces and is the single worst failure this project has had.

The fix, in `_go_to_filtered_list`:
- `_wait_for_filter_query_settled(page, prev_ids=...)` runs after each filter's OK click,
  BEFORE `_verify_filters_active` or any row read.
- It first does a best-effort wait for the SAPUI5 busy overlay
  (`.sapUiLocalBusyIndicator, .sapUiBlockLayerTabbable`) to appear then clear, plus
  networkidle (mirrors the proven post-nav wait in `datasphere_client.py`).
- Then, for the Environment=Cleaned filter, it does a HARD confirmation: the pre-filter
  workshop-ID set is captured before the OK click and passed as `prev_ids`; the function
  polls until the visible ID set actually DIFFERS from `prev_ids` (or a no-data indicator
  shows). If the rows never change within `_WAIT_TIMEOUT`, it raises
  `RuntimeError("SAFETY ABORT: filtered result set did not change...")` — fail CLOSED
  rather than scrape stale rows. `_collect_next_batch` also calls the settle wait
  (best-effort) before reading, as belt-and-braces.

**`_verify_filters_active` is necessary but NOT sufficient on its own** — it only proves
the toolbar chip is correct, which is decoupled from the rendered rows. The row-change
hard confirmation is the real safety signal. Never rely on the chip alone.

**If a scrape stalls or scrapes wrong workshops:** confirm the busy-overlay class is still
`.sapUiLocalBusyIndicator`/`.sapUiBlockLayerTabbable` via `src/probes/probe_portal.py`, and that the
Environment filter genuinely shrinks the list when applied by hand. If manual filtering
works but the tool scrapes active workshops, the settle/hard-confirm wait is the place to
look — not the filter-click selectors.

---

### Workbook selection — portal search term (added 2026-08-18)

Stage 1 (and `--workshop`) types a **search term** into the content-portal search bar in
`_go_to_filtered_list` *before* applying the Environment=Cleaned / DC-Region / date filters.
This term selects which workbook's requests are listed. Two terms are supported:

| Option | String typed into the portal searchbox |
|---|---|
| `overview` (default) | `SAP Datasphere Overview` |
| `integration` | `SAP Analytics Cloud Planning and Datasphere Integration` |

**How it flows:** the term is read from `cfg["portal"]["search_term"]` by `run_portal_scrape`
and `scrape_single_workshop` — no dedicated parameter is threaded through. Every entry point
just overrides that config key:
- **GUI (`app.py`, `combined.py`):** a "Workbook:" row with two `QRadioButton`s sits below the
  Max-workshops field (Overview checked by default). `_selected_search_term()` reads the checked
  button's label on the GUI thread; `_run_stage1` and `_run_workshop_scrape` then set
  `cfg["portal"]["search_term"]` before dispatching the worker (in `combined.py` the override is
  applied per-tenant inside `run_tenant`).
- **CLI (`main.py`):** `--search-term {overview,integration}` maps via `SEARCH_TERMS` and sets the
  key right after `load_tenant_config`. Absent flag → config default (unchanged behaviour).
- **Constants** live in `src/portal_client.py`: `SEARCH_TERM_OVERVIEW`, `SEARCH_TERM_INTEGRATION`,
  `SEARCH_TERMS` — the single source of truth shared by both GUIs and the CLI.

**Default is unchanged:** `settings.yaml:portal.search_term` remains `"SAP Datasphere Overview"`;
nothing overrides it unless the `integration` radio/flag is chosen.

**Tested vs. not:** `TestSearchTermSelection` in `test_portal_client.py` proves the constants,
the alias map, and that `run_portal_scrape` forwards the configured term verbatim to
`_go_to_filtered_list`. What tests CANNOT prove is that the portal returns results for the
`integration` term — that depends on live SAP data and the exact workbook name. If the
`integration` option returns an empty filtered list, that is a term-name/portal issue (confirm
the exact string as it appears in the portal), not a code bug.

---

## Purpose

Automates cleanup of residual SAP Datasphere spaces left by expired Academy (AC) trial users
across **five tenants**: EU10, US10, AP11, AP11(2), EU10(2). Driven by a four-stage pipeline:

1. **Stage 1** — Scrapes the SAP Self-Service Content Portal to discover AC/GE user IDs from
   workshop entries. Filters by `Environment: Cleaned` + `DC Region` (per tenant).
   Appends new users to the tenant-specific pending file.
2. **Stage 2** — For each user in the pending file, searches Datasphere Space Management,
   finds all their spaces via the autocomplete dropdown, and deletes them.
3. **Stage 3** — Re-checks every space reported as deleted to confirm it is actually gone.
4. **Stage 4** — Permanently purges from the Datasphere recycle bin spaces deleted by this
   pipeline that are ≥7 days old.

---

## Tech Stack

- Python 3.9
- **async Playwright** (Chromium, headed — sessions saved to JSON storage state files)
- PyQt5 (GUI — `src/app.py`, `src/combined.py`)
- PyYAML + python-dotenv (config)
- pytest (unit tests — all pure unit tests, no browser)

**IMPORTANT:** All Playwright code uses `async_playwright` / `async_api`. The public stage
entry points (`run_stage1`, `run_stage2`, `run_stage3`, `run_stage4`, `run_workshop_scrape`)
are synchronous wrappers that call `asyncio.run()` on an internal `_run_*_async` coroutine.
`open_browser`, all client functions, and all session save functions are `async def`.
Never revert to `sync_playwright` or `sync_api`.

---

## Project Structure

```
datasphere-cleanup/
├── CLAUDE.md                          ← this file
├── .env                               ← live credentials (gitignored)
├── .env.example
├── config/
│   ├── settings.yaml                  ← all runtime config (shared + per-tenant overrides)
│   └── allowlist.txt                  ← space IDs that must never be deleted
├── src/
│   ├── app.py                         ← PyQt5 GUI entry point (single tenant, accepts tenant param)
│   ├── auth.py                        ← async browser session save/load
│   ├── combined.py                    ← PyQt5 GUI for all active tenants in one window
│   ├── config.py                      ← YAML + .env loader; load_tenant_config()
│   ├── datasphere_client.py           ← async Playwright wrapper: find/delete spaces
│   ├── eu10.py / us10.py              ← single-tenant entry point shims
│   ├── ap11_2.py / eu10_2.py         ← public-request tenant entry point shims
│   ├── logging_setup.py               ← structured logging; _ThreadFileHandler for tenant isolation
│   ├── main.py                        ← CLI entry point (--tenant eu10|us10|ap11|ap11_2|eu10_2)
│   ├── portal_client.py               ← async Playwright wrapper: portal scrape
│   ├── probes/                        ← standalone DOM investigation scripts (not production code)
│   │   ├── probe_datasphere.py
│   │   ├── probe_portal.py
│   │   ├── probe_portal_date_filter.py
│   │   ├── probe_recycle_bin.py
│   │   ├── probe_workshop_bulk.py
│   │   ├── probe_workshop_nodata.py
│   │   └── probe_interactive.py
│   ├── report.py                      ← JSON report generation
│   ├── retry.py                       ← async exponential backoff decorator (transient-only)
│   ├── stage1_discovery.py            ← Stage 1 orchestration
│   ├── stage2_deletion.py             ← Stage 2 orchestration
│   ├── stage3_verify.py               ← Stage 3 orchestration
│   └── stage4_purge.py                ← Stage 4 orchestration (recycle bin purge)
├── tests/
│   ├── conftest.py                    ← autouse cwd fixture + make_async_playwright_mocks()
│   ├── test_config.py
│   ├── test_deletion.py
│   ├── test_discovery.py
│   ├── test_integration.py
│   ├── test_purge.py
│   ├── test_verification.py
│   └── test_workshop_cleanup.py
├── outputs/
│   ├── user_lists/
│   │   ├── pending_<tenant>.txt
│   │   ├── processed_<tenant>.txt
│   │   ├── deleted_<tenant>.txt
│   │   ├── pending_workshops_<tenant>.txt
│   │   └── processed_workshops_<tenant>.txt
│   ├── reports/
│   │   └── archive/                   ← older reports moved here
│   ├── archive/                       ← probe data and old workshop lists
│   └── logs/
├── requirements.txt
└── setup.py
```

---

## Running the Project

```bash
cd ~/Desktop/datasphere-cleanup
source .venv/bin/activate

# GUI — combined (all active tenants in one window) — PREFERRED
datasphere-cleanup-combined
datasphere-cleanup-combined-demo   # combined, demo mode (Stage 1 capped)

# GUI — single tenant
datasphere-cleanup-eu10
datasphere-cleanup-us10
datasphere-cleanup-ap11-2          # AP11(2) public-request tenant
datasphere-cleanup-eu10-2          # EU10(2) public-request tenant

# CLI  (--tenant choices: eu10 | us10 | ap11 | ap11_2 | eu10_2)
python -m src.main --tenant eu10 --stage1
python -m src.main --tenant us10 --stage1
python -m src.main --tenant eu10 --stage2 --execute
python -m src.main --tenant eu10 --stage3 --report outputs/reports/report_eu10_<run_id>.json
python -m src.main --tenant eu10 --stage4 --execute
python -m src.main --tenant eu10 --stage4 --execute --max-purge 10
python -m src.main --tenant eu10 --workshop <ID>
python -m src.main --tenant eu10 --all --execute

# Workbook (portal search term) — Stage 1 / --workshop
# Default (no flag) = "SAP Datasphere Overview" (config settings.yaml:portal.search_term)
python -m src.main --tenant eu10 --stage1 --search-term overview
python -m src.main --tenant eu10 --stage1 --search-term integration  # "SAP Analytics Cloud Planning and Datasphere Integration"

# Sign-in
python -m src.main --tenant eu10 --sign-in
python -m src.main --tenant eu10 --sign-in-datasphere
python -m src.main --tenant us10 --sign-in
python -m src.main --tenant us10 --sign-in-datasphere

# Run tests
python -m pytest tests/ -v

# DOM probes
python -m src.probes.probe_datasphere
python -m src.probes.probe_recycle_bin
python -m src.probes.probe_portal
```

---

## Safety Gates — IMPORTANT

Live deletions require **both** conditions to be true simultaneously:

1. `dry_run: false` in `config/settings.yaml`
2. `--execute` flag passed on the CLI

**The GUI now enforces the same double gate (fixed 2026-08-07).** Previously the GUI
Stage 2 confirmation dialog read only its dry-run checkbox and ignored `cfg["dry_run"]`,
so a default click-through on `dry_run: true` config would delete live data. Now both
`src/app.py` and `src/combined.py` compute `effective_dry_run = dialog_dry_run or cfg["dry_run"]`
per tenant inside the Stage 2 worker — a live deletion happens only when config has
`dry_run: false` AND the dialog's dry-run box is left unchecked. If config says
`dry_run: true`, the run is forced to dry-run regardless of the checkbox and logs a notice.
This mirrors the CLI's `live = not dry_run and args.execute`.

---

## Combined Dual-Tenant GUI (`src/combined.py`)

`datasphere-cleanup-combined` opens a single PyQt5 window that runs both tenants.

- Same three-section nav (Authentication / Pipeline / Workshop) as the single-tenant app
- Each stage button runs EU10 **then** US10 serially in one background thread
- Log box shows `[EU10]` and `[US10]` prefixed lines from both tenants
- Sign-in runs EU10 browser first, then US10 (sequential — two browsers simultaneously is confusing)
- Stage 2 shows a single confirmation dialog with both tenant pending queue sizes
- Stage 4 dialog has a "Max spaces per tenant" spinbox (same limit applied to both)

**Why serial not concurrent:** Playwright's async API shares one event loop per `asyncio.run()` call. Both tenants run inside a single `asyncio.run()` call via `_run_single` → one QThread. The async event loop handles both tenants' browser I/O concurrently at the Python level — EU10 `await`s yield to US10 operations and vice versa — which is the correct form of concurrency for I/O-bound Playwright work.

**Per-tenant failure isolation (fixed 2026-08-07):** all concurrent stages run tenants via
`_gather_tenants(tenants, run_tenant)`, which calls `asyncio.gather(..., return_exceptions=True)`.
Previously a bare `asyncio.gather` meant one tenant raising would propagate out of `asyncio.run`,
cancelling the sibling tenant mid-operation — potentially between a confirm-click and the
state-record, leaving a space deleted in SAP but absent from `deleted_<tenant>.txt`.
`_gather_tenants` isolates each tenant's failure, logs it with `[TENANT]` attribution, and lets
the others finish safely.

**Logging isolation:** `_TenantLogHandler` in `combined.py` routes GUI log lines to the right
`[EU10]`/`[US10]` prefix. It routes on a `contextvars.ContextVar` (`_active_tenant_prefix`, set in
`_patch_combined_logger`), NOT raw `asyncio.Task` identity — because a contextvar propagates into
`asyncio.wait_for` child tasks. Without it, any log line emitted inside a `wait_for`-wrapped
coroutine (the per-workshop `found N user(s)` line runs inside `asyncio.wait_for` in
`run_portal_scrape`) was attributed to the child task, failed the identity check, and was
silently dropped from the GUI while still reaching the file log. Task-identity and OS-thread-ident
checks remain as fallbacks for the serial sign-in path. `_ThreadFileHandler` in `logging_setup.py`
does the file-log routing.

**Worker error handling (fixed 2026-08-07):** `Worker.run` (in `app.py`, used by both GUIs) emits
`done_signal` in every exit path — success, `Exception`, or `BaseException` (Ctrl-C/SystemExit) —
so a failed run can never leave the buttons permanently disabled. On failure it emits the full
traceback (not just `str(exc)`) via `error_signal`, and the status label shows "{label} failed".
Note: buttons DO re-enable after a failure (forcibly disabling them would wedge the GUI) — treat a
run that logged `ERROR:` as failed, not clean.

---

## Async Architecture (migrated 2026-07-27)

All browser-touching code uses `async_playwright` from `playwright.async_api`.

### Pattern for stage modules
Each stage has:
- `async def _run_stageN_async(...)` — the real implementation
- `def run_stageN(...)` — synchronous public wrapper: `return asyncio.run(_run_stageN_async(...))`

This means the GUI workers (`Worker.run()` in `app.py`) call stage functions synchronously, and `asyncio.run()` manages the event loop per stage invocation.

### `retry.py`
`with_retry` now wraps `async def` functions. The inner wrapper is `async def wrapper(...)` and uses `await asyncio.sleep(wait)`. Any function decorated with `@with_retry(...)` must be `async def`.

**Only transient errors are retried (fixed 2026-08-07).** `with_retry` retries on Playwright
`Error`/`TimeoutError`, `asyncio.TimeoutError`, and `RuntimeError` (the code's own
"not settled yet" signals, e.g. "tile not visible at deletion time"). Deterministic bugs
— `KeyError`, `AttributeError`, `TypeError`, `ValueError` — re-raise immediately instead of
burning `len(backoff)+1` attempts with 5/15/60s sleeps per item. This stops a systemic
breakage (e.g. a selector changed by a SAP update) from looping silently for minutes per
user before surfacing. The retryable set is `_RETRYABLE` in `src/retry.py`.

### `auth.py`
`open_browser`, `save_portal_session`, `save_datasphere_session` are all `async def`.
Callers in `app.py` and `combined.py` wrap them: `asyncio.run(save_portal_session(...))`.
CLI (`main.py`) also uses `asyncio.run(...)`.

### Testing async code
`tests/conftest.py` exports `make_async_playwright_mocks()` which returns async context manager mocks. All integration tests patch `async_playwright` (not `sync_playwright`). Async side_effect functions use `async def`. `asyncio.run()` is used in unit tests that call async client functions directly.

---

## PRIMARY DELETION MODEL: Workshop-ID Bulk Sweep (added 2026-08-07)

**This is now the primary Stage 2 model.** It replaced the per-user model on the CLI live
path. The per-user model (`find_all_spaces`/`delete_all_spaces`, documented below) is retained
but unreachable in normal CLI use — see "Model status" below.

### Why it exists
The per-user model scrapes user IDs from the portal and searches Datasphere one user at a time.
Live probing (2026-08-07) proved this **misses spaces**: the portal lists 1 user for workshop
284660 but Datasphere has 21 spaces for it; workshop 279401 shows 44 portal users but 25 renamed
`POOL_XA_*` spaces. Because the workshop is marked processed after the portal scrape, those extra
spaces were never found or cleaned — a silent completeness gap. Searching Datasphere by the
**workshop number** (present in every space's user-ID subheading) returns ALL of a workshop's
spaces in one query; they can then be bulk-selected and deleted in one operation.

### Confirmed on all 5 tenants (via `src/probes/probe_workshop_bulk.py`)
Every result card exposes the user ID in a `__textNNN` node (sibling to
`spaceTileHeader-identifier-txt` within `spacesContainer-N`), each row has a `.sapMCb` checkbox,
and the confirm dialog is identical. AC tenants → `AC<workshop>U\d+`; GE public tenants
(ap11_2/eu10_2) → **bare** `GE<workshop>` (no `U` suffix). Renamed spaces (headline
`POOL_XA_*`/`SPACE_*`) are still matched because the user ID is in the `__text` node, not the headline.

### Flow
- **Stage 1** (`portal_client.run_portal_scrape`): unchanged scrape + Cleaned filter + hard-confirm
  settle. Now ALSO calls `append_pending_workshop(wid, cfg)` (before `mark_workshop_processed`, so
  dedup works) → writes Cleaned workshop IDs to `pending_workshops_<tenant>.txt`.
- **Stage 2** (`stage2_deletion.run_stage2_workshops` / `_run_stage2_workshops_async`): iterate the
  pending-workshops queue. Per workshop:
  1. `find_workshop_spaces(page, workshop, cfg)` — search workshop number, read every card
     (container index, headline, user-ID text), keep only cards whose user ID matches
     `^(AC|GE)<workshop>(U\d+)?$` (over-match guard via `_workshop_id_re`).
  2. `delete_workshop_spaces(page, workshop, cards, cfg, dry_run, allowlist)` — drop allowlisted
     (skipped_allowlist), dry-run emits skipped_dry_run with NO clicks, else tick each `.sapMCb`,
     assert ticked-count == validated-count, click bulk Delete `[id$='manageSpaces--toolbar--deleteButton']`,
     type DELETE into `[id*='deleteInput-inner']`, click OK `[id*='DeleteConfirmationDialog--dialog--view--ok']`.
     Commit click fired ONCE, not retried (prepare/commit split).
  3. Log each deleted space ID to `deleted.txt`; mark workshop swept (removed from pending, added
     to processed_workshops) — only when NOT dry_run.
  - Per-workshop circuit breaker; re-navigate to Space Management between workshops.

### Safety guards
- Per-row user-ID regex validation (over-match protection: `284660` can't match `1284660`).
- Allowlist per space before selection.
- ticked-count == validated-count assertion before the commit click.
- Single commit, not retried.
- dry_run + config gate unchanged.
- Every individual space ID logged to `deleted.txt` (Stage 3/4 remain per-space).

### Search-settle guard — `_wait_for_search_settled` (fixed 2026-08-10)
`find_workshop_spaces` must not read the tile grid until the search's async OData query has
returned, or it scrapes the STALE pre-filter set (confirmed live on AP11: an unfiltered grid
shows the same 25 unrelated `AC092254..` tiles). The original guard
(`_wait_for_tile_set_changed`) waited for the tile-ID set to CHANGE from a pre-search
snapshot — which had a fatal gap: when the grid was **already empty before** the search
(e.g. after `navigate_to_space_management` left an empty filtered state, or a prior empty
search), an empty→empty transition never "changes", so it failed closed and aborted the
ENTIRE tenant run with `RuntimeError('filtered tile set did not change...')`. This hit AP11
on the first genuinely-empty workshop (233717 swept by luck — its predecessor grid had 25
tiles; 234287 aborted the run).

**Root cause proven by `src/probes/probe_workshop_nodata.py` (2026-08-10):** the no-data escape
hatch selector `.sapMListNoData, [class*='noData']` matches NOTHING on the AP11 space grid —
the only "No data" on the page belongs to the unrelated **Elastic Compute Nodes side panel**
(`...manageSpaces--spacesSidePanel...`). Never use that selector to detect an empty space
grid. The probe also confirmed `_current_tile_ids` is reliable: a populated workshop (99557)
returns its 6 `AC099557U*` tiles, so a 0-tile reading means genuinely empty, not a missed
selector.

**Renamed-space refinement (same day, 2026-08-10):** a first cut of the fix matched the
settle check against `_current_tile_ids` (the `identifier-txt` **headline**). That regressed
on renamed-space workshops — live AP11 workshop **279401** has 25 spaces whose headline is a
renamed `POOL_XA_*` (e.g. `POOL_XA_00000978`) that never matches `^(AC|GE)279401...`; the real
user ID (`AC279401U00`) lives in a **sibling card leaf-text node**, not the headline. The
guard saw a stable-but-non-matching grid and fail-closed with "never settled" on exactly the
renamed workshops the sweep exists to clean. The probe's stability trace proved timing was NOT
the cause (25 tiles stable from t+0s); the headline-vs-cardtext mismatch was.

**The fix** — `_wait_for_search_settled(page, workshop)` waits for a STABLE terminal state
(two consecutive equal `_current_tile_ids` reads — stability judged on the headline set, which
is reliably stable) that is EITHER empty (→ valid "no spaces", returns `[]`) OR has ≥1 visible
CARD whose leaf texts contain a user ID matching `^(AC|GE)<workshop>(U\d+)?$`. The match is
read via `_visible_card_user_ids(page)`, which walks each tile up to its `.sapFCard` and
collects leaf-text nodes — the SAME card-walk the card-reader uses — so renamed
`POOL_XA_*`/`SPACE_*` tiles are recognised. A stable grid where NO card carries the searched
workshop's id (the stale default grid because the search silently didn't fire) is never
accepted — keep polling, fail closed on timeout (`RuntimeError('...never settled...')`). The
busy-overlay-hidden + networkidle waits still run first. Empty results are now a normal
outcome, not an abort.

**Search submission — DO NOT touch (settled 2026-08-10, verified by a full live run):** the
search in `find_workshop_spaces` is deliberately just:
```python
await searchbox.fill("")
await searchbox.fill(workshop)
await searchbox.press("Enter")   # ONE Enter — this is what filters the grid
```
The Enter is REQUIRED — it submits the search and filters the tile grid; typing/`fill()`
alone does NOT filter. A dead-end detour tried removing Enter and using `.type()` (theory:
SAP live-filters as you type). It does NOT — every workshop then reported "never settled".
Two other dead ends: `Escape` CLEARS the field (never use it here); worrying about the
autocomplete dropdown "hijacking" Enter is a non-issue in practice — the single Enter filters
correctly, and space selection happens later in `delete_workshop_spaces`. Keep it simple:
fill, one Enter. Confirmed by a clean live run — 83/83 spaces deleted across 10 workshops,
0 failed, including 25 renamed `POOL_XA_*` on workshop 279401.


- **CLI:** `python -m src.main --tenant <t> --stage2 [--execute]` → workshop-sweep (primary).
  `--input <file>` → falls back to the per-user model for targeted user-list runs.
- **GUIs (`app.py`, `combined.py`): WIRED TO THE WORKSHOP-SWEEP** (confirmed on disk 2026-08-10).
  Both `_run_stage2`/`_do_run_stage2` read the workshop queue via `load_pending_workshops`, show a
  "N workshop(s)" confirmation dialog, apply the C1 dry-run gate (`effective_dry_run = dialog OR
  cfg["dry_run"]`), and call `run_stage2_workshops` (`app.py`) / `_run_stage2_workshops_async`
  inside `_gather_tenants` (`combined.py`). No GUI path calls the old per-user model.
- Old per-user code (`find_all_spaces`, `delete_all_spaces`, `_delete_one_space`,
  `_search_autocomplete`, `_find_btn_id_for_user`, etc.) is **present and fully tested** but
  unreachable via the CLI sweep path. Physical removal was intentionally deferred.

### Key files
- `src/datasphere_client.py` — `find_workshop_spaces`, `delete_workshop_spaces`, `_workshop_id_re`,
  bulk selector constants (`_BULK_*`).
- `src/portal_client.py` — `load_pending_workshops`, `append_pending_workshop`, `_pending_workshops_path`.
- `src/stage2_deletion.py` — `run_stage2_workshops`, `_run_stage2_workshops_async`,
  `_batch_remove_from_pending_workshops`.
- `src/probes/probe_workshop_bulk.py` — the read-only DOM probe used to validate all 5 tenants.

---

## Key Architecture: How find_all_spaces Works (LEGACY per-user model — backup only)

`find_all_spaces()` in `src/datasphere_client.py` was the core of the per-user Stage 2. It is now
the backup model (see the workshop-sweep section above). It:

1. Types the AC user ID into the Space Management search box
2. Waits for the **autocomplete dropdown** (`[role="listbox"].sapMSelectList`) to appear
3. Reads each suggestion — format is `DISPLAY_NAME (TECHNICAL_ID)` where TECHNICAL_ID is
   always the AC user ID, even if the space has been renamed
4. Filters suggestions to only those whose technical ID matches the searched user
5. Dismisses the dropdown (Escape), re-fills and presses Enter to load tiles
6. Calls `_find_btn_id_for_user()` to locate the Open button **by identity, not position**

### _find_btn_id_for_user — identity-based tile matching

Scans `[id$="spaceTileHeader-identifier-txt"]` elements on each page of the tile view.
Each tile has exactly one such element whose `innerText` is the space's technical ID.
When a match is found, extracts the container index `N` from the element ID and constructs
the Open button ID as `...spacesContainer-N--spaceTileFooter--openSpaceButton`.

If the tile is not on page 1, clicks through pagination buttons
(`[id*="pagesSegmentedButton"] [role="option"]`) until found or all pages exhausted.

**Why identity not position:** The old approach paired autocomplete suggestions to tile
buttons by position index and aborted if the counts didn't match. This broke on large
workshops because SAP's autocomplete caps at ~20 suggestions while the tile view
paginates at 25 — the counts never matched. The identity approach is immune to both
limits: it finds the right tile regardless of how many siblings exist or how many pages
SAP renders.

**Confirmed DOM structure (both EU10 and US10, 2026-07-30):**
- Identifier: `...spacesContainer-N--spaceTileHeader-identifier-txt` (innerText = technical ID)
- Open button: `...spacesContainer-N--spaceTileFooter--openSpaceButton`
- Pagination: `[id*="pagesSegmentedButton"] [role="option"]` (absent when ≤25 tiles)

---

## Deletion Flow

```
find_all_spaces()
    → for each tile: _delete_one_space()
        → _prepare_delete()  [retried on transient errors]
            → click Open button
            → wait_for overflowToolbar-overflowButton to be VISIBLE (45s timeout)
            → Additional Options → Delete → type "DELETE"
        → _commit_delete()   [fired EXACTLY ONCE — never retried]
            → click the final Delete confirm button
        → record DeleteResult(outcome="deleted") BEFORE navigation
        → wait for SAP auto-navigation (toast + searchbox presence)
```

**Why prepare/commit are split (fixed 2026-08-07):** the whole open→delete→confirm
sequence used to be wrapped in `@with_retry`. If the confirm click committed the deletion
server-side but the coroutine then raised (e.g. a timeout reading the response), retry
re-ran the entire sequence against a DOM SAP had already navigated — and could open and
delete a *different* space. Now only `_prepare_delete` (idempotent navigation up to typing
"DELETE") is retried; `_commit_delete` (the committing click) runs once, outside retry. If
the commit click itself fails, the outcome is recorded `failed` and Stage 3 verifies —
we never re-issue a commit.

For users with multiple spaces, `delete_all_spaces()` re-searches after each deletion.

---

## Post-Deletion Navigation

After deletion, SAP auto-navigates back to Space Management. The code waits via
`_wait_for_sap_post_deletion_nav()`. **Do not add `goto()` or `go_back()` to the
post-deletion flow** — redundant navigation triggers two cascading SAP SPA error screens.

---

## Persistent State Files

| File | Purpose | Written by | Read by |
|---|---|---|---|
| `pending_<tenant>.txt` | Live work queue | Stage 1 (append) | Stage 2 (read + remove per user) |
| `processed_<tenant>.txt` | All handled users | Stage 2 | Stage 1 (filter), Stage 2 (skip) |
| `deleted_<tenant>.txt` | Confirmed deleted space IDs + dates | Stage 2 | Stage 4, Audit |
| `processed_workshops_<tenant>.txt` | Scraped workshop IDs | Stage 1 | Stage 1 (skip) |

`deleted_<tenant>.txt` format: `SPACE_ID YYYY-MM-DD` (one per line). The 532 pre-existing
EU10 entries were backfilled with `2026-06-23`.

---

## Logging Architecture

`logging_setup.py` defines `_ThreadFileHandler(logging.FileHandler)` — a file handler that
only writes records from a specific OS thread (identified by `thread_ident`). This allows the
combined app to run both tenants through one thread and still produce separate log files.

`combined.py` defines `_TenantLogHandler(logging.Handler)` — routes log records to the GUI
log box with `[EU10]` or `[US10]` prefix, filtered by thread ident.

Single-tenant `app.py` uses `setup_logging(thread_ident=None)` — writes from any thread,
correct for single-stage-at-a-time operation.

---

## Circuit Breaker

Stage 2 aborts if real failure rate exceeds 20% after at least 10 real attempts.
`skipped_dry_run`, `skipped_allowlist`, and `not_found` outcomes are excluded.

---

## Current Operational State (as of 2026-08-10)

| Metric | EU10 | US10 | AP11 | AP11(2) | EU10(2) |
|---|---|---|---|---|---|
| Users in pending queue (per-user model) | 0 | 0 | 391 | 0 | 0 |
| Workshops in pending_workshops (sweep) | 0 | 0 | 0 | 0 | 0 |
| `dry_run` in config | `false` | `false` | `false` | `false` | `false` |

⚠️ **`dry_run: false` globally** (single shared key in `config/settings.yaml:38`). The live-deletion
gate is held ONLY by omitting `--execute` (CLI) or leaving the dialog dry-run box checked (GUI).

✅ **AP11 workshop-sweep FIRST LIVE RUN COMPLETE (2026-08-10):** the sweep ran live for the first
time and cleanly — **83 spaces deleted across 10 workshops, 0 failed, 0 not_found** (report
`report_ap11_20260810_222520.json`). `pending_workshops_ap11.txt` is now empty; all swept workshops
are in `processed_workshops_ap11.txt`; every deleted space logged to `deleted_ap11.txt` with today's
date. The four search/settle fixes made tonight (empty→empty, renamed-space card-text matching,
`fill+Enter` search submission) are all verified end-to-end by this run.

- **292 tests passing** (all pure unit tests, no browser).
- **Project is NOT under git** — all changes are on-disk only, no version control. Back up before
  large edits.
- **AP11 sweep done:** `pending_workshops_ap11.txt` empty. (`pending_ap11.txt` still has 391 users
  from the old per-user model — irrelevant to the sweep, which uses the workshop queue.)
- ⚠️ **EU10(2):** 49 active `GE…` users from the 2026-08-07 filter-race incident are quarantined in
  `outputs/user_lists/quarantine_eu10_2_active_users_20260807.txt`; `pending_eu10_2.txt` is empty.
  Inspect the quarantine before any EU10(2) run. AP11 workshop-log residue from the same day was
  also quarantined earlier (38 IDs removed from `processed_workshops_ap11.txt`).

---

## Multi-Tenant Architecture

Each tenant has its own portal session, Datasphere session, output files, and entry point.
Config under `tenants.eu10` / `tenants.us10` / `tenants.ap11` / `tenants.ap11_2` in `config/settings.yaml`.

**Datasphere paths:**
- EU10: `/dwaas-core/index.html#/spaceManagement` (sign-in + space management)
- US10 sign-in: `/dwaas-ui/index.html#/home`
- US10 space management: `/dwaas-ui/index.html#/managespaces&/ms/overview?view=tile`
- AP11: same paths as US10 (`/dwaas-ui/`)
- AP11(2): same paths as EU10 (`/dwaas-core/`); base URL `https://academydatasphere-1.ap11.hcs.cloud.sap`

**Portal sidebar — `requests_tree_item` config key (`portal.requests_tree_item`):**
All tenants use "Internal request(s)" (the default) except AP11(2) which uses "Public request(s)".
`_go_to_filtered_list`, `run_portal_scrape`, `scrape_single_workshop`, and `_return_to_filtered_list`
all read this key from `cfg["portal"].get("requests_tree_item", "Internal request(s)")` and pass it
as `requests_tree_item=` to `_go_to_filtered_list`. The selector is `[aria-label^='Tree Item {value}']`.

**AP11(2) portal differences vs EU10/US10/AP11:**
- Workshop rows use `a[href*="/ge-request/"]` instead of `/academy-request/` — both handled in `_WORKSHOP_IDS_JS` and `_wait_for_list_ready`
- Search input is `input[type='search'].fdp-search-field__input` (no `[role="searchbox"]`) — `_go_to_filtered_list` tries both
- User IDs are `GE\d+` format (no `U\d+` suffix, e.g. `GE334927`) in `td.fd-table__cell` elements — `_extract_users_from_workshop` uses `td.fd-table__cell` selector and `_USER_ID_CELL_RE = ^(?:AC\d+U\d+|GE\d+(?:U\d+)?)$`
- `AC_USER_PATTERN` matches both `AC\d+U\d+` and `GE\d+(?:U\d+)?`

**Portal scrape robustness (`_extract_users_from_workshop`):**
- Wrapped in `asyncio.wait_for(timeout=30.0)` — broken workshops time out cleanly instead of hanging
- On `asyncio.TimeoutError`: workshop marked processed, full `_go_to_filtered_list` re-navigation (never `go_back()` after a timeout — page state is unknown)
- Link-finding loop capped at 10 steps (was 200 — potential 100s hang)
- Users table scroll capped at 20 steps with 2-consecutive-stable-read break condition

**AP11(2) timeout sensitivity — IMPORTANT:**
AP11(2) renders UI elements significantly slower than EU10/US10/AP11. Three places had hardcoded short timeouts that caused silent failures (all returning `[]` or `""` without erroring):
- `_search_autocomplete`: was 3000ms → now `_WAIT_TIMEOUT` (15s). Root cause of all `not_found` false negatives — autocomplete silently returned `[]` before dropdown appeared.
- `_scan_current_page` identifier-txt wait: was 3000ms → now `_WAIT_TIMEOUT`
- `wait_for_selector(_OPEN_BTN_SELECTOR)`: was 8000ms → now `_WAIT_TIMEOUT`
If a future tenant shows mass `not_found` false negatives, check for short hardcoded timeouts first.

**AP11(2) deletion — renamed spaces (`find_all_spaces`):**
On AP11(2) all spaces are renamed (e.g. `GE335515` → `SPACE_00017554`). The autocomplete
returns `{headline: "SPACE_00017554", subheading: "GE335515"}`. Detection and handling:
- `space_was_renamed = (headline != user_id)` — True when display name differs from user ID
- `tile_search_id = headline` when `space_was_renamed` — searches tiles by display name
- `_find_btn_id_for_user(match_text=headline)` — scans `identifier-txt` for the display name
  (on AP11(2) identifier-txt holds the display name, not the technical ID)
- Pass 2 prefix search: bare `GE\d+` IDs have no `U\d+` suffix to strip — the full ID is
  used as the prefix directly. `found_via_prefix = True` forces `tile_search_id = headline`.

**For full tenant addition checklists see `docs/adding-tenants.md`.**

---

## Stage 4 — Recycle Bin Purge

Permanently deletes from the Datasphere recycle bin only spaces that:
1. Appear in `deleted_<tenant>.txt` (deleted by this pipeline)
2. Have been there for ≥7 days
3. Were NOT flagged `still_exists` by any Stage 3 verification report (added 2026-08-07)

**still_exists exclusion (fixed 2026-08-07):** Stage 2 appends a space to `deleted.txt` the
moment it records `outcome="deleted"` — before Stage 3 verifies the server-side deletion
actually happened. If Stage 3 later finds the space still exists (delete failed/rolled
back), the `deleted.txt` entry is stale but was never removed automatically, so Stage 4
could permanently purge a space that was never really deleted. `load_still_exists_exclusions`
in `stage4_purge.py` now reads every `verification_*.json` in `reports_dir` and
`_run_stage4_async` subtracts any `still_exists` space IDs from the eligible set. Unreadable
reports are skipped with a warning (can't silently drop an exclusion).

**Recycle bin selectors (confirmed 2026-07-23):**
- Recycle Bin tab: `[id*='deletedSpacesListItem']`
- Tile ID: `[id$='spaceTileHeader-identifier-txt']`
- Tile checkbox: `[role='checkbox'].sapMCb`
- Permanent delete button: `[id*='toolbar--physicalDeleteButton']`
- Confirmation dialog: `[id*='DeleteConfirmationDialog--dialog']`
- DELETE input: `[id*='DeleteConfirmationDialog--dialog--view--deleteInput-inner']`
- OK button: `[id*='DeleteConfirmationDialog--dialog--view--ok']`
- Pagination: `[id*='pagesSegmentedButton'] [role='option']`

---

## Workshop-Targeted Cleanup

The Workshop section provides a **multi-item queue** flow instead of a single-shot input dialog.

### GUI flow
1. User types a 5–7 digit workshop ID into the input field and clicks **Add** (or presses Enter).
2. The ID is validated (digits only, 5–7 chars, no duplicates) and appended to a `QListWidget` queue below.
3. Repeat for additional workshops. The **Launch (N)** button label updates live with the queue count.
4. **Remove Selected** removes the highlighted item from the queue before launch.
5. Clicking **Launch (N)** captures the queue, clears it from the UI immediately, then calls
   `_run_workshop_scrape_async` (combined) or `run_workshop_scrape` (single-tenant) once per ID in order.
6. Launch is disabled when the queue is empty; `_set_buttons_enabled(False)` during a run keeps it
   disabled — it only re-enables if the queue is non-empty when the run completes.

### Underlying scrape functions (unchanged)
`scrape_single_workshop(page, cfg, workshop_id)` in `portal_client.py` — scrapes one workshop by ID.
`run_workshop_scrape(workshop_id, cfg, run_id)` / `_run_workshop_scrape_async(...)` in `stage1_discovery.py` wrap it.
CLI: `--workshop <ID>` (single ID only — queue is GUI-only).

---

## Known Fragile Selectors

### Portal (`portal_client.py`, `_go_to_filtered_list`)
- Tree item: `[aria-label^='Tree Item Internal request(s)']` (starts-with, SAP adds trailing `, `)
- Filter button: `[role='option'][aria-label='Filter']`
- Environment filter: `li[role='listitem'] span.fd-list__title:text-is('Environment')` — text-based, stable
- Cleaned option: `li[role='option']:has-text('Cleaned')` — text-based, stable
- **Never use positional `#fd-list-item-N` IDs** — they shift when SAP adds/removes columns

### Portal — workshop link timeouts
`link.click(timeout=_WAIT_TIMEOUT)` and `page.get_by_role("tab", name="Users").click(timeout=_WAIT_TIMEOUT)`
both have explicit 15s timeouts. Old/broken workshops that don't respond in 15s are logged as
failed and skipped — the scrape continues. EU10 has older workshop IDs (135xxx range) that
are slower than US10's newer IDs (3xxxxx range).

### Datasphere (`datasphere_client.py`)
```
#shellMainContent---managespacesComponent---spaceDetails--overflowToolbar-overflowButton
#shellMainContent---managespacesComponent---spaceDetails--overflowToolbar-popover
```
Component-scoped IDs, stable. If they break, run `python -m src.probes.probe_datasphere`.

---

## Common Issues and Fixes

### "Target page, context or browser has been closed" on Stage 1
Previously caused by running sync_playwright from two threads simultaneously. Resolved by
migrating to async_playwright — both tenants share one event loop.

### Workshop hangs / freezes on EU10
Old EU10 workshops (135xxx range) can be slow or broken. Both `link.click()` and the Users
tab click now have explicit `_WAIT_TIMEOUT` (15s). If a workshop doesn't respond, it's logged
as failed and the scrape continues to the next workshop.

### "Additional Options" button not visible / timeout
The space detail page has an async loading phase. Wait for `overflowToolbar-overflowButton`
to be visible (45s). If failing, check if Datasphere changed the toolbar structure.

### Stage 3 discrepancies (still_exists after reported deletion)
Datasphere deletion is async server-side. Re-queue affected users manually in `pending.txt`
(remove from `processed.txt` and `deleted.txt`) for a retry run.

### Session expired
```bash
python -m src.main --tenant eu10 --sign-in-datasphere
```

---

## Test Suite

**290 tests, all passing.** Run with:

```bash
python -m pytest tests/ -q
python -m pytest tests/ --cov=src --cov-report=term-missing  # with coverage
```

### Coverage (as of 2026-08-05)

| File | Coverage | Notes |
|---|---|---|
| `stage3_verify.py` | 100% | Complete |
| `stage2_deletion.py` | 98% | Near-complete |
| `stage1_discovery.py` | 94% | Near-complete |
| `config.py` | 93% | Near-complete |
| `report.py` | 95% | Near-complete |
| `retry.py` | 90% | Near-complete |
| `datasphere_client.py` | 73% | Remaining lines are live browser sequences |
| `portal_client.py` | 58% | Remaining lines are live browser sequences |
| `stage4_purge.py` | 92% | Remaining lines are live browser sequences |
| **Total** | **57%** | Headline is low due to untestable browser-only code |

### What is not tested (and why)

The following are genuinely untestable without a live Playwright browser connected to SAP:
- `_delete_one_space` — live deletion click sequence
- `_wait_for_space_mgmt_ready` — requires real SAPUI5 busy overlay
- `_navigate_to_recycle_bin` — requires real browser navigation
- `_go_to_filtered_list` — requires real portal DOM
- `run_portal_scrape` / `scrape_single_workshop` — requires real portal session

All other paths — safety gates, outcome codes, file I/O, retry logic, renamed space detection, Pass 1/Pass 2, circuit breaker, age filtering, pagination — are unit tested.

### Test files

| File | What it covers |
|---|---|
| `test_config.py` | YAML loading, env var interpolation, tenant deep-merge |
| `test_deletion.py` | Dry-run, allowlist, circuit breaker, retry, `DeleteResult` outcomes, renamed space detection, Pass 1/Pass 2 gating, `_find_btn_id_for_user`, `delete_all_spaces`, `search_and_verify_space`, `_dismiss_any_sap_dialogs`, `_space_mgmt_url`, `_single_open_btn_id`, `_wait_for_sap_post_deletion_nav` |
| `test_discovery.py` | AC/GE user ID pattern, dedup, pending queue append logic |
| `test_integration.py` | End-to-end Stage 1 + Stage 2 with mocked browser |
| `test_portal_client.py` | User ID patterns, processed workshops, `_collect_next_batch`, `_extract_users_from_workshop`, `_verify_filters_active`, `_return_to_filtered_list` |
| `test_purge.py` | `load_deleted_log` age filtering, `_collect_tile_ids`, `_click_permanent_delete`, `_select_tile`, `_get_page_count`, `_go_to_page`, `PurgeResult` outcomes, progress callback, multi-page loop |
| `test_verification.py` | Stage 3 report parsing, `confirmed_deleted` vs `still_exists` |
| `test_workshop_cleanup.py` | Targeted single-workshop scrape, workshop queue UI logic |

### Mock pattern

All browser mocks use `make_async_playwright_mocks()` from `tests/conftest.py`. Patch `async_playwright` not `sync_playwright`. Async `side_effect` functions must be `async def`. Never add browser-dependent assertions to unit tests — if a test needs a real page, it belongs in a probe script, not the test suite.

---

## Code Conventions

- All Playwright code is `async def` — never add sync Playwright calls
- `with_retry` decorator wraps `async def` functions only
- All file I/O uses `encoding="utf-8"` explicitly
- All report timestamps are UTC (`datetime.now(timezone.utc).isoformat()`)
- `open_browser(playwright, headless=False)` is the single browser creation point — always `await` it
- Tests: patch `async_playwright` not `sync_playwright`; use `make_async_playwright_mocks()` from conftest; async side_effects use `async def`
- `PENDING_QUEUE`, `PROCESSED_LOG`, `DELETED_LOG` constants in `stage2_deletion.py` are canonical

---

## What to Do Next

**Before anything else — the 2026-08-07 filter-race fixes are verified by tests only, not by
a live run.** The safety-critical browser paths (filter settle/hard-confirm, prepare/commit
split, per-tenant gather isolation, exact link match, and the ENTIRE workshop-sweep model) are
mocked in tests. The workshop-sweep has NEVER run live. Confirm before trusting deletion:

1. **Wire the GUIs to the workshop-sweep** — DONE (confirmed on disk 2026-08-10). Both `app.py` and
   `combined.py` call the sweep (`run_stage2_workshops` / `_run_stage2_workshops_async`), read the
   workshop queue via `load_pending_workshops` for their pending count + confirmation dialog, and
   preserve the C1 dry-run gate. No further work needed here.
2. **Dry-run the workshop-sweep on AP11.** ⚠️ `dry_run: false` in config as of 2026-08-10, so the
   dry-run gate is held ONLY by omitting `--execute`. 133 workshops are seeded in
   `pending_workshops_ap11.txt`. Run `python -m src.main --tenant ap11 --stage2` (NO `--execute`) and
   watch: each workshop → one search → validated `AC<workshop>U\d+` set → "would delete N", no
   clicks. Spot-check a couple against the portal.
3. **First live sweep:** set `dry_run: false`, `--tenant ap11 --stage2 --execute`, watch the first
   2-3 workshops in Chrome — confirm only `AC<workshop>U\d+` rows are selected/deleted, each logged
   to `deleted_ap11.txt`.
4. **(Optional cleanup)** physically purge the old per-user functions once the sweep is trusted.
5. **EU10(2)** — 49 active users are quarantined in `quarantine_eu10_2_active_users_20260807.txt`;
   `pending_eu10_2.txt` is empty. Inspect the quarantine before any EU10(2) run.
6. **Stage 4** — purges recycle bin (excludes `still_exists` spaces); run per tenant when ready.

**To add a new tenant:** see `docs/adding-tenants.md`
**To add a new workbook (portal search term):** see `docs/adding-workbooks.md`
