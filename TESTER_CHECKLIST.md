# ReportBuilder — Tester Checklist

Quick validation for first-time testers. Takes 10 minutes.

For detailed step-by-step instructions, see [docs/TESTING.md](docs/TESTING.md).

---

## Setup

- [ ] `python run.py` — app launches
- [ ] Setup wizard appears on first run
- [ ] Choose intake folder and app data location
- [ ] Click Finish — main window opens

## Ingestion

- [ ] Drop report files (Excel, CSV, or ZIP) into intake folder
- [ ] Go to Sources tab > click Scan Now
- [ ] Files appear in the table with "completed" status

## Report Generation

- [ ] Go to Ask the Data
- [ ] Type `team efficiency report` > Generate Plan > Execute Plan
- [ ] Excel report appears in Reports tab
- [ ] Type `show me trends for gross revenue` > Generate Plan > Execute Plan
- [ ] Trend report appears in Reports tab
- [ ] Type `executive summary PDF` > Generate Plan > Execute Plan
- [ ] PDF appears in Reports tab

## Trends

- [ ] Go to Trends tab
- [ ] Select entity type and metric > click Compute Trends
- [ ] Table populates with data

## Persistence

- [ ] Quit the app
- [ ] Run `python run.py` again
- [ ] Main window opens directly (no wizard)
- [ ] Data is still there

## Re-run Setup

- [ ] File > Re-run Setup Wizard
- [ ] Wizard opens, complete it
- [ ] App continues working

---

**Tester:** ___________________
**Date:** ___________________
**Result:** PASS / FAIL
**Notes:** ___________________
