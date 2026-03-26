# ReportBuilder — Tester Checklist

This checklist covers the full first-user validation flow. A non-developer tester should be able to complete this in 10–15 minutes.

---

## Prerequisites

- Python 3.12+ installed
- Repository cloned and dependencies installed (see README Quick Start)
- At least one of these test files available:
  - A DTP ZIP archive (e.g., `2025_DailyTechPerformance.zip`)
  - A mileage CSV file (e.g., `MCA_disbursedmileage_10.1.25_12.31.25.csv`)
  - An MCA Snapshot ZIP archive

If you don't have real report files, the app will still launch and be navigable — you just won't have data for report generation.

---

## Checklist

### 1. First Launch and Setup Wizard

- [ ] Run `python run.py` — the setup wizard should appear
- [ ] **Welcome page**: read the overview, click Next
- [ ] **Intake Folder page**: browse to a folder containing your test files (or accept the default)
- [ ] **App Data page**: accept the default location (or choose a custom one)
  - If you change app-data, a **warning dialog** should appear asking you to confirm
- [ ] **Summary page**: review settings, optionally check "Scan intake folder on finish"
- [ ] Click Finish — the main window should open

**Pass criteria:** Wizard completes without errors. Main window appears.

### 2. Dashboard and Initial Data

- [ ] The Dashboard tab should show entity/period/metric counts
- [ ] If you scanned on finish, counts should be non-zero
- [ ] The intake folder path displayed should match what you chose

**Pass criteria:** Dashboard reflects ingested data (or zeros if no scan was run).

### 3. Manual Ingestion

- [ ] Navigate to the **Sources** tab
- [ ] Click **Scan Now**
- [ ] After scanning completes, the file table should populate with ingested files
- [ ] Each file should show a status (`completed` or `skipped`), family name, and size

**Pass criteria:** Files appear in the table. At least one shows "completed" status.

### 4. Data Explorer

- [ ] Navigate to the **Data Explorer** tab
- [ ] The **Entities** sub-tab should list teams, technicians, or CIDs
- [ ] The **Observations** sub-tab should show metric values linked to entities and periods

**Pass criteria:** Entities and observations are present and browsable.

### 5. Generate a Team Efficiency Report (Excel)

- [ ] Navigate to **Ask the Data**
- [ ] Type: `team efficiency report`
- [ ] Click **Generate Plan** — a JSON plan should appear
- [ ] The status should say "ready to execute" (not "NOT executable")
- [ ] Click **Execute Plan**
- [ ] Status should confirm file(s) generated
- [ ] Navigate to **Reports** tab — the new report should appear with filename, type, template, and timestamp

**Pass criteria:** Excel report generated and visible in Reports tab.

### 6. Generate a Trend Report (Excel)

- [ ] Go back to **Ask the Data**
- [ ] Type: `show me trends for gross revenue`
- [ ] Click **Generate Plan** → verify plan shows `trend_focus_pack` template
- [ ] Click **Execute Plan**
- [ ] Verify report appears in Reports tab

**Pass criteria:** Trend report generated successfully.

### 7. Generate an Executive PDF

- [ ] In **Ask the Data**, type: `executive summary PDF`
- [ ] Click **Generate Plan** → verify plan shows `executive_infographic_pdf` template
- [ ] Click **Execute Plan**
- [ ] Verify PDF appears in Reports tab

**Pass criteria:** PDF report generated successfully.

### 8. Trends Tab (Interactive)

- [ ] Navigate to the **Trends** tab
- [ ] Select an entity type (e.g., `team`) and a metric (e.g., `gross_revenue`)
- [ ] Click **Compute Trends**
- [ ] The table should populate with entities showing current/previous values, changes, ranks, and volatility

**Pass criteria:** Trend table populates with data.

### 9. Settings Tab

- [ ] Navigate to **Settings**
- [ ] Verify all paths are displayed (Intake Folder, App Data, Output Dir, Database, AI Model Dir)
- [ ] Verify AI Model status shows either "Not installed — using deterministic fallback" or "Installed and ready"

**Pass criteria:** All paths shown. AI model status is clear.

### 10. Restart Persistence

- [ ] Quit the app completely
- [ ] Run `python run.py` again
- [ ] The main window should open directly — **no setup wizard**
- [ ] Dashboard should show the same data as before
- [ ] Settings tab should show the same paths

**Pass criteria:** App remembers settings across restart. No wizard on re-launch.

### 11. Re-run Setup Wizard

- [ ] From the menu bar, click **File > Re-run Setup Wizard**
- [ ] A confirmation dialog should appear — click Yes
- [ ] The setup wizard should open
- [ ] Navigate through the wizard (you can accept all defaults)
- [ ] Click Finish
- [ ] The main window should refresh — data should still be present

**Pass criteria:** Setup wizard re-runs safely without data loss or errors.

### 12. Open Output Folder

- [ ] Go to the **Reports** tab
- [ ] Click **Open Output Folder**
- [ ] Your file manager should open showing the generated report files

**Pass criteria:** Folder opens with the correct generated files.

---

## Negative / Edge Case Tests (Optional)

These verify error handling:

- [ ] In Ask the Data, type something nonsensical (e.g., `asdfghjkl`) → should still generate a fallback plan
- [ ] Try executing a plan for a template that doesn't support your entity scope → should show clear rejection message
- [ ] Launch the app without any files in the intake folder → should work fine, just show zero counts

---

## Test Results

| Test | Pass / Fail | Notes |
|---|---|---|
| 1. First Launch | | |
| 2. Dashboard | | |
| 3. Manual Ingestion | | |
| 4. Data Explorer | | |
| 5. Team Efficiency Report | | |
| 6. Trend Report | | |
| 7. Executive PDF | | |
| 8. Trends Tab | | |
| 9. Settings Tab | | |
| 10. Restart Persistence | | |
| 11. Re-run Setup | | |
| 12. Open Output Folder | | |

**Tester name:** ___________________
**Date:** ___________________
**Overall result:** PASS / FAIL
**Notes:** ___________________
