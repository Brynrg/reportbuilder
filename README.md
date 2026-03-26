# ReportBuilder

A local-first desktop application that ingests Excel, CSV, and ZIP report files, warehouses the data, and generates polished ranking reports, trend analyses, and executive PDFs — all offline, all on your machine.

**Your data never leaves your computer.**

---

## What This App Does

ReportBuilder is built for operations managers and analysts who receive daily or weekly report files (technician performance, store snapshots, mileage disbursements) and need to turn that raw data into actionable, formatted reports.

You drop files into a folder. The app ingests them, normalizes the data into a local database, and lets you generate Excel workbooks, trend analyses, and PDF summaries on demand.

Everything runs locally. No cloud. No accounts. No internet required after install.

---

## Key Features

- **Continuous ingestion** — watches a folder for new Excel, CSV, and ZIP files
- **Excel + PDF report generation** — ranked workbooks, cross-report comparisons, executive summaries
- **Trend analysis** — period-over-period comparisons, rank movement, volatility scoring
- **Historical accuracy** — past data is never rewritten when teams change
- **Content-based deduplication** — the same file ingested twice is never double-counted
- **Offline operation** — no cloud, no network, no accounts
- **Ask the Data** — type what you want in plain English, get a structured report
- **Optional AI model** — works fully without it; deterministic planner handles all common requests

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/reportbuilder.git
cd reportbuilder
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -e .
```

Or, if you prefer a plain requirements file:

```bash
pip install -r requirements.txt
```

### 4. Run the app

```bash
python run.py
```

### 5. Complete the Setup Wizard

The wizard opens on first launch. Choose:

1. **Intake folder** — where you drop report files (Excel, CSV, ZIP)
2. **App data location** — where the database and generated reports are stored
3. **Initial scan** — optionally process any files already in the intake folder

Click Finish. The main window opens.

---

## How to Use

### Ingest Data

Drop Excel (.xlsx), CSV (.csv), or ZIP (.zip) files into your intake folder. The app detects the report family automatically and processes them.

Supported report families:

| Report Family | File Type | Key Data |
|---|---|---|
| Daily Tech Performance (DTP) | `.xlsx` inside `.zip` | Technician, Team, Hours, Units, Revenue |
| MCA Snapshot | `.xlsx` inside `.zip` | CID/Store, Team, Requests, Builds, Invoices |
| Mileage/Disbursed | `.csv` | Technician, Team, Miles, Amount |

You can also trigger a manual scan from the **Sources** tab.

### Generate Reports

Go to **Ask the Data** and type what you want:

- `team efficiency report` — ranked Excel workbook with team and tech detail
- `show me trends for gross revenue` — period-over-period trend analysis
- `executive summary PDF` — KPI cards, top performers, concerns
- `compare snapshot and performance data` — CID-level cross-report comparison

Click **Generate Plan** to preview, then **Execute Plan** to produce the report.

### View Trends

Go to the **Trends** tab. Select an entity type (team, technician, or CID) and a metric. Click **Compute Trends** to see period-over-period performance.

### Find Your Reports

Generated reports are saved inside your app data folder. Check the exact path on the **Settings** tab, or click **Open Output Folder** on the **Reports** tab.

### Change Settings

**File > Re-run Setup Wizard** lets you reconfigure paths at any time.

---

## Where Files Go

| What | Location |
|---|---|
| Database | `<app data>/warehouse.db` |
| Generated reports | `<app data>/output/` |
| Settings | `<app data>/settings.json` |
| Staging (temp extraction) | `<app data>/staging/` |

Default app data location:

| Platform | Path |
|---|---|
| macOS | `~/Library/Application Support/ReportBuilder/` |
| Windows | `%APPDATA%\ReportBuilder\` |
| Linux | `~/.reportbuilder/` |

---

## AI Model (Optional)

The app works fully without any AI model. The built-in deterministic planner handles all common report requests.

If you want more flexible natural language understanding, you can optionally install ONNX model support:

```bash
pip install -r requirements-ai.txt
```

Then place ONNX model files in the model directory shown on the **Settings** tab.

The AI only generates report *plans*. All calculations, rankings, and output are deterministic.

---

## Running Tests

```bash
source .venv/bin/activate
./scripts/run_tests.sh
```

Or directly:

```bash
PYTHONPATH=src python -m pytest tests/ -v
```

Tests that require real fixture files (DTP ZIPs, mileage CSVs) are automatically skipped if those files are not present.

---

## Building a Standalone App

```bash
pip install pyinstaller
python scripts/build.py
```

Output: `dist/ReportBuilder/`

Note: The build is not code-signed or notarized. macOS may show a Gatekeeper warning on first launch.

---

## Known Limitations

Be aware of these before testing:

- **No installer** — run via Python (see Quick Start)
- **No code signing** — macOS may warn on first launch (right-click > Open to bypass)
- **Three report families only** — DTP, MCA Snapshot, and Mileage. Other formats are skipped.
- **Large ZIP files** — a ZIP with 300+ Excel files takes several minutes on first ingest. Re-runs skip completed files.
- **Cross-report joins** — Snapshot vs Performance works at CID level only. A full technician-to-CID join is not yet implemented.
- **No data migration** — changing app data location creates a new environment. Old data stays at the old path.
- **Single user** — no multi-user or networked mode
- **AI model not bundled** — optional ONNX model must be downloaded separately

---

## Recommended First Test

1. Run the app (`python run.py`)
2. Complete the setup wizard
3. Drop sample report files into the intake folder
4. Go to **Ask the Data** and generate:
   - `team efficiency report` (Excel)
   - `show me trends for gross revenue` (Excel)
   - `executive summary PDF` (PDF)
5. Check the **Reports** and **Trends** tabs
6. Quit and relaunch — verify data persists and no wizard appears
7. Try **File > Re-run Setup Wizard** — verify it works safely

---

## Troubleshooting

| Problem | Solution |
|---|---|
| App won't start | Ensure dependencies are installed: `pip install -e .` |
| `ModuleNotFoundError` | Activate the virtual environment first: `source .venv/bin/activate` |
| No data on Dashboard | Ingest files first — go to Sources > Scan Now |
| Reports tab is empty | Generate a report first via Ask the Data |
| Can't find generated reports | Check the output path on the Settings tab |
| macOS Gatekeeper warning | Right-click the app > Open |
| Setup wizard keeps reappearing | App data location may have changed — use File > Re-run Setup Wizard |

---

## Project Structure

```
reportbuilder/
├── run.py                     # Launch the app
├── requirements.txt           # Core dependencies
├── pyproject.toml             # Package configuration
├── scripts/
│   ├── build.py               # PyInstaller build script
│   ├── run_tests.sh           # Test runner
│   └── run_dev.sh             # Dev launcher
├── src/reportbuilder/
│   ├── app.py                 # Application entry + service lifecycle
│   ├── config.py              # Settings management
│   ├── warehouse/             # SQLite warehouse (models + repository + migrations)
│   ├── ingestion/             # File watcher, ZIP handler, ingest orchestrator
│   ├── parsing/               # Report family parsers (DTP, MCA, Mileage)
│   ├── normalization/         # Entity/period/metric resolution
│   ├── analytics/             # Rollups, rankings, trends, diagnostics
│   ├── reports/               # Template registry + report generators
│   ├── ai/                    # AI planner + deterministic fallback
│   └── ui/                    # PySide6 desktop UI
├── tests/                     # Test suite
└── docs/                      # Detailed tester checklist + release notes
```

---

## Links

- [Tester Checklist](TESTER_CHECKLIST.md) — quick validation for first-time testers
- [Full Test Guide](docs/TESTING.md) — detailed step-by-step testing walkthrough
- [Release Notes](docs/RELEASE_NOTES.md) — what's included, what's not, what was fixed
