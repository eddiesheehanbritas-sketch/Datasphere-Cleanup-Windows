# Adding a New Workbook (Portal Search Term) — Step-by-Step Reference

A "workbook" is the string typed into the SAP Self-Service Content Portal searchbox before
the Environment=Cleaned / DC-Region / date filters are applied. It selects which workbook's
workshop requests are listed. Adding a new workbook requires changes to exactly 5 files.

---

## What a workbook is

In `_go_to_filtered_list` (`src/portal_client.py`), the code does:

```python
await searchbox.fill(search_term)
await searchbox.press("Enter")
```

`search_term` is read from `cfg["portal"]["search_term"]`. The string must match the portal
workbook name **character for character**, including capitalisation, spaces, and hyphens.
Confirm the exact string in the portal before adding it.

---

## Checklist — 5 files, in order

### 1. `src/portal_client.py` — add the constant and alias

Add one constant and one entry in `SEARCH_TERMS`:

```python
SEARCH_TERM_<NAME> = "<Exact portal string>"
SEARCH_TERMS = {
    "overview":    SEARCH_TERM_OVERVIEW,
    "integration": SEARCH_TERM_INTEGRATION,
    "<alias>":     SEARCH_TERM_<NAME>,   # ← add this line
}
```

- The constant name is `SEARCH_TERM_` + screaming-snake version of the alias (e.g. `SEARCH_TERM_BASIC_TRIAL`).
- The alias is the short CLI key (e.g. `basic_trial`) — lowercase, underscores, no spaces.
- The string value is the **exact portal workbook name**.

### 2. `src/main.py` — add to `--search-term` choices

```python
parser.add_argument("--search-term", ..., choices=["overview", "integration", "<alias>"],
                    help="... '<alias>' = <Exact portal string>")
```

Both the `choices` list and the `help` string need updating.

### 3. `src/combined.py` — add a third radio button

In `_build_pipeline_page`:

```python
from src.portal_client import SEARCH_TERM_OVERVIEW, SEARCH_TERM_INTEGRATION, SEARCH_TERM_<NAME>
...
self._search_<alias>_radio = QRadioButton(SEARCH_TERM_<NAME>)
for _rb in (..., self._search_<alias>_radio):
    _rb.setStyleSheet(...)
self._search_term_group.addButton(self._search_<alias>_radio)
search_row.addWidget(self._search_<alias>_radio)
```

Pattern: mirror exactly what was done for `_search_integration_radio`.

### 4. `src/app.py` — same radio button addition

Identical change to step 3, in `app.py`'s `_build_pipeline_page`.

### 5. `tests/test_portal_client.py` — update the constant assertion

`TestSearchTermSelection.test_constants_have_expected_values` asserts `SEARCH_TERMS` exactly.
Add the new constant import and the new key/value:

```python
from src.portal_client import (
    SEARCH_TERM_OVERVIEW, SEARCH_TERM_INTEGRATION, SEARCH_TERM_<NAME>, SEARCH_TERMS,
)
assert SEARCH_TERM_<NAME> == "<Exact portal string>"
assert SEARCH_TERMS == {
    "overview":    SEARCH_TERM_OVERVIEW,
    "integration": SEARCH_TERM_INTEGRATION,
    "<alias>":     SEARCH_TERM_<NAME>,
}
```

---

## Verify

```bash
python -m pytest tests/ -q
```

All tests must pass. The new option is immediately available:

```bash
# CLI
python -m src.main --tenant eu10 --stage1 --search-term <alias>

# GUI — the new radio button appears in the Workbook row on the Pipeline page
datasphere-cleanup-combined
```

---

## How the search term flows end-to-end

```
GUI radio / --search-term flag
    └─ sets cfg["portal"]["search_term"] = SEARCH_TERM_<NAME>
        └─ run_portal_scrape reads cfg["portal"]["search_term"]
            └─ passes search_term= to _go_to_filtered_list
                └─ searchbox.fill(search_term) + press("Enter")
                    └─ portal filters to that workbook's workshops
```

No other code needs to change. The string is used verbatim.

---

## Quick reference — current workbooks

| Alias | Portal string | Constant |
|---|---|---|
| `overview` | `SAP Datasphere Overview` | `SEARCH_TERM_OVERVIEW` |
| `integration` | `SAP Analytics Cloud Planning and Datasphere Integration` | `SEARCH_TERM_INTEGRATION` |
| `basic_trial` | `Basic Trial - Introduction to SAP Analytics Cloud` | `SEARCH_TERM_BASIC_TRIAL` |
