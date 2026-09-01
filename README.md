# Datasphere Cleanup

Automates the cleanup of residual SAP Datasphere spaces left behind by expired
Academy (AC) and GE trial users across six tenants: **EU10, US10, AP11, AP11(2),
EU10(2), and US10(2)**.

The tool works in four stages:

1. **Stage 1 — Discovery:** Scrapes the SAP Self-Service Content Portal to find
   workshops whose environment is marked "Cleaned", and queues them for cleanup.
2. **Stage 2 — Deletion:** For each queued workshop, searches Datasphere Space
   Management by workshop number, bulk-selects all matching spaces, and deletes
   them in one operation.
3. **Stage 3 — Verification:** Re-checks every deleted space to confirm it is
   actually gone, and flags any discrepancies.
4. **Stage 4 — Recycle Bin Purge:** Permanently removes from the Datasphere
   recycle bin any space deleted by this pipeline that is ≥7 days old.

> **Safety gate:** No deletions occur unless you explicitly confirm in the
> Stage 2 dialog (the Dry Run box must be unchecked). Leave it checked to preview
> without deleting anything.

---

## Install

You do **not** need Python or any developer tools — just download the app.

1. Go to the [**Releases** page](../../releases/latest) and download
   `Datasphere Cleanup.dmg`.
2. Double-click the `.dmg`, then drag **Datasphere Cleanup** into your
   `Applications` folder.
3. **First launch only** — **right-click** (or Control-click) the app icon and
   choose **Open**, then click **Open** again in the dialog. macOS remembers this,
   so every later launch is a normal double-click.

   If it still refuses to open with a *"damaged"* message, clear the download
   flag once in Terminal:
   ```bash
   xattr -dr com.apple.quarantine "/Applications/Datasphere Cleanup.app"
   ```

**Requirements:** an Apple Silicon Mac (M1 or later) and SAP Datasphere admin
credentials. Chromium is bundled inside the app — nothing else to install.

On first launch the app creates `~/Documents/Datasphere Cleanup/` for its config
and outputs.

---

## Running the tool

Launch **Datasphere Cleanup** from Applications. It opens a single window that
runs all active tenants. The three sections are **Authentication**, **Pipeline**,
and **Workshop**.

**Standard run order:**

1. **Sign In — Portal** — complete portal login for each tenant in the browser
2. **Sign In — Datasphere** — complete Datasphere login for each tenant
3. **Run Stage 1** — scrapes the portal and queues workshops for cleanup
4. **Run Stage 2** — review the confirmation dialog; **uncheck Dry Run** to delete
5. **Run Stage 3** — verify deletions; check the log for any `still_exists` entries
6. **Run Stage 4** — purge the recycle bin; set a max-per-tenant limit if desired

Sessions are saved and reused across runs (valid for several hours). Re-run the
sign-in steps whenever a session expires.

### Targeted workshop scrape

The **Workshop** section lets you clean specific workshops by ID without running a
full Stage 1:

1. Type a 5–7 digit workshop ID into the input field and click **Add** (or press
   Enter). Repeat for as many workshops as needed — each appears in the queue list.
2. To remove an ID before launching, select it and click **Remove Selected**.
3. Click **Launch (N)** to scrape all queued workshops in order.

---

## Understanding the outputs

All outputs are written under `~/Documents/Datasphere Cleanup/outputs/`.

### Log — `outputs/logs/run_<run_id>.log`

Timestamped record of every action. Key lines:

```
[INFO]    workshop 284660: 21 space(s) matched (from 21 card(s))
[INFO]    workshop 284660: bulk-deleted 21 space(s)
[INFO]    workshop 234287: 0 space(s) matched — no spaces to delete
[WARNING] Circuit breaker triggered: failure rate 25% exceeds threshold 20%
```

### Report — `outputs/reports/report_<run_id>.json`

**Outcome meanings:**

| Outcome | Meaning | Action required |
|---|---|---|
| `deleted` | Space successfully deleted | None |
| `not_found` | No space found for this workshop — already clean | None — normal and expected |
| `skipped_dry_run` | Dry Run was on — no deletion attempted | Re-run with Dry Run unchecked |
| `skipped_allowlist` | Space is on the protected allowlist | Intentional — review allowlist if unexpected |
| `failed` | Deletion attempted but errored | Check the log; re-run after fixing |

### Verification report — `outputs/reports/verification_<run_id>.json`

Any `still_exists` entries mean a space reported as deleted is still present.
Re-run Stage 2 for the affected tenant to retry.

---

## Allowlist

To permanently protect specific spaces from deletion, add their space IDs (one per
line) to `config/allowlist.txt` inside `~/Documents/Datasphere Cleanup/`. The
allowlist is checked before every delete, regardless of the Dry Run setting.

---

## Safety architecture

Multiple independent layers protect against accidental deletions:

1. **Dry Run** — leave the Stage 2 dialog's Dry Run box checked to preview only
2. **Allowlist** — permanent protection for specific space IDs
3. **Filter verification** — Stage 1 halts (SAFETY ABORT) if the portal's
   Environment:Cleaned / DC Region filters are not confirmed active
4. **Search-settle guard** — Stage 2 refuses to act until the search results have
   stabilised; it fails closed rather than acting on a stale list
5. **Circuit breaker** — Stage 2 aborts if the failure rate exceeds 20%

---

## Recovering from failures

**Session expired mid-run:** re-run the **Sign In — Datasphere** step for the
affected tenant, then re-run the stage.

**Stage 3 reports `still_exists`:** re-run Stage 2 for that tenant to retry the
deletion.

**Circuit breaker tripped:** check `outputs/logs/` for the specific error. The
most common cause is an expired session — re-sign-in and re-run.

**Re-running after a partial failure:** re-runs are safe. Workshops that were
already processed are tracked and skipped automatically.
