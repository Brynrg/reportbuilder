# Completion Status — Brynrg/reportbuilder

> Refined status doc for AI agents working on this repo. Verified against tree + every source file on 2026-05-19.

**Score:** 78 / 100 — **Canonical** implementation for technician/operations report analysis. Mature architecture, real test suite, packaging infra in place, but no CI and no shipped binary yet.
**State:** Public repo. Created 2026-03-26, pushed 2026-05-19. Active development.
**Stack:** Python 3.11+ / PySide6 desktop · SQLAlchemy 2.x SQLite warehouse (WAL, FK on, FTS5) · watchdog folder watcher · pandas/openpyxl/XlsxWriter for parsing & Excel · reportlab for PDF · optional onnxruntime + transformers for local "Ask the Data" planner.

---

## Architecture (verified)

```
src/reportbuilder/
├── app.py                # Service lifecycle (warehouse, ingestion, planner, registry)
├── config.py             # AppSettings + ConfigManager (per-OS pointer file → settings.json)
├── ingestion/
│   ├── scanner.py        # IngestOrchestrator + content-hash dedup + StabilizationTracker
│   ├── watcher.py        # watchdog FolderWatcher
│   └── zip_handler.py    # inspect_zip / extract_zip (member-level)
├── parsing/
│   ├── base.py           # BaseParser ABC + ParserRegistry (confidence-scored detect)
│   ├── detector.py       # create_default_registry() → 3 parsers
│   ├── daily_tech_performance.py   # DTP family (.xlsx in .zip)
│   ├── mca_snapshot.py              # MCA Snapshot family (.xlsx in .zip)
│   └── mileage_csv.py               # Mileage/Disbursed (.csv)
├── normalization/
│   └── resolvers.py      # Entity/period/metric canonicalization + alias support
├── warehouse/
│   ├── models.py         # Two-layer schema (raw lineage + canonical/analytical)
│   ├── repository.py     # WarehouseRepository data-access methods
│   └── migrations.py     # _schema_version table, idempotent migrations (001 = parent_entity_id)
├── analytics/
│   └── engine.py         # Rollups, rankings, trend computation
├── reports/
│   ├── registry.py       # Template registry + plan validation
│   ├── pdf_renderer.py   # reportlab PDF rendering
│   └── templates/
│       ├── team_efficiency_tenure.py
│       ├── snapshot_vs_performance.py
│       ├── trend_focus.py
│       └── executive_pdf.py
├── ai/
│   ├── planner.py        # ReportPlanner: ONNX provider + DeterministicFallbackParser
│   ├── model_manager.py  # ModelManager (status, install, manifest)
│   └── schemas.py        # PLANNER_SYSTEM_PROMPT + validate_plan
└── ui/
    ├── main_window.py    # PySide6 main window (Dashboard / Sources / Data Explorer / Ask the Data / Reports / Trends / Settings tabs)
    └── setup_wizard.py   # First-run wizard (intake folder, app data, optional initial scan)
```

---

## Parser registry (registered in `parsing/detector.create_default_registry()`)

| Family name              | Class                          | Inputs                | Detection signal                                                       |
| ------------------------ | ------------------------------ | --------------------- | ---------------------------------------------------------------------- |
| `daily_tech_performance` | `DailyTechPerformanceParser`   | `.xlsx` (incl. inside `.zip`) | Header tokens: technician, team, hours, units, revenue            |
| `mca_snapshot`           | `MCASnapshotParser`            | `.xlsx` (incl. inside `.zip`) | CID/store-grain rows, MCA Snapshot header signature              |
| `mileage_disbursed`      | `MileageCSVParser`             | `.csv`                | Header: technician_name + total_mileage + total_amount                |

Registry uses `BaseParser.can_parse() → confidence [0,1]`; selects highest confidence ≥ 0.3 (`ParserRegistry.detect_and_get_parser`).

---

## Warehouse schema (verified in `warehouse/models.py`)

**Raw / Lineage layer:**

- `watched_folders` — registered intake folders
- `source_files` — hash, size, mtime, parent archive id, archive member path, ingest_status, version
- `source_sheets` — per-sheet metadata (header_row, data_start_row, detected_family, parse_confidence)
- `ingest_runs` — orchestrator run telemetry

**Canonical / Analytical layer:**

- `report_families`, `entities` (+ `entity_aliases`), `periods`, `metrics` (+ `metric_aliases`)
- `observations` — core fact table: (entity_id, period_id, metric_id, **parent_entity_id**, value, text_value, source_file_id, source_sheet, source_row, confidence, ingest_run_id, version)
  - `parent_entity_id` records the team/parent at observation time → historical attribution survives reorgs. Analytics rollups MUST use this column, not `Entity.parent_id`.
- `trend_summaries` — materialized period-over-period cache (current vs previous value, rank, rolling 4/8 avg, volatility)
- `output_artifacts` — generated Excel/PDF files
- `report_requests` — user query history

**Engine setup (`create_warehouse_engine`):** SQLite with `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`. FTS5 virtual table `observations_fts` created post-table-init.

**Migrations:** `_schema_version` table with idempotent migration list. Currently `001 = parent_entity_id column + ix_obs_parent index`.

---

## Test inventory (11 modules in `tests/`)

| Module                          | Test classes (verified)                                                                                                                                                                                                                                                  |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_ai.py`                    | `TestDeterministicFallback`, `TestPlanValidation`, `TestReportPlanner`, `TestModelManager`                                                                                                                                                                                                  |
| `test_analytics.py`             | `TestTechRecord`, `TestTeamRollup`, `TestDiagnosis`, `TestAnalyticsEngine`                                                                                                                                                                                                                  |
| `test_config.py`                | `TestAppSettings`, `TestConfigManager`                                                                                                                                                                                                                                                       |
| `test_hardening.py`             | 15 classes incl. `TestConfigPropagation`, `TestConfigPersistence`, `TestCapabilityValidation`, `TestPlannerExecutionContract`, `TestRegistryListCapabilities`, `TestTrendFocusEntityScope`, `TestTrendValidationCombinations`, `TestCapabilityCheckMessage`, `TestRestartSettingsDiscovery`, `TestSnapshotCIDSupport`, `TestArtifactRecording`, `TestPlannerTrendRouting`, `TestResolvePeriod`, `TestNoSilentCoercion` |
| `test_ingestion.py`             | `TestSupportedFiles`, `TestStabilizationTracker`, `TestFileHash`, `TestFolderWatcher`, `TestIngestOrchestrator`                                                                                                                                                                              |
| `test_parsers.py`               | `TestDailyTechPerformanceParser`, `TestMCASnapshotParser`, `TestMileageCSVParser`, `TestParserRegistry`, `TestZipHandler` — most data-dependent tests use `pytest.mark.skipif` against `~/Downloads/` fixtures                                                                              |
| `test_release_hardening.py`     | `TestSchemaMigration`, `TestReportWorker`, `TestSessionSafety`, `TestPackagingSanity`, `TestMigrationHelpers`                                                                                                                                                                                |
| `test_reports.py`               | `TestReportPlan`, `TestTemplateRegistry`, `TestTeamEfficiencyTemplate`                                                                                                                                                                                                                       |
| `test_truth_correctness.py`     | `TestObservationDedup`, `TestHistoricalAttribution`, `TestSnapshotVsPerformanceNarrowed`, `TestTeamTrendsViaAggregation`, `TestSetupWizardTransactionality`, `TestZipIngestHonesty`, `TestParserParentEntityId`                                                                                |
| `test_warehouse.py`             | `TestWarehouseRepository`                                                                                                                                                                                                                                                                    |
| `conftest.py`                   | `repo` fixture (in-memory SQLite + repository)                                                                                                                                                                                                                                               |

Two test files (`test_truth_correctness.py`, `test_release_hardening.py`) document the historical "Pass 1" and "Pass 2" audits called out in `docs/RELEASE_NOTES.md`. These are the highest-value regression net in the repo and MUST stay green.

---

## AI surface (verified in `src/reportbuilder/ai/`)

- **Planner.** `ReportPlanner.plan(user_query)` tries providers in order: `ONNXPlannerProvider(model_dir)` if a model dir is set, then `DeterministicFallbackParser` (always available). Final hard-coded default if all providers fail.
- **ONNX provider.** Lazy-loads via `onnxruntime.InferenceSession` + `transformers.AutoTokenizer`. Plan is validated against `schemas.validate_plan`.
- **Deterministic fallback.** Pure keyword routing → JSON plan with `intent`, `report_template`, `entity_scope`, `period_mode`, `metrics[]`, `trend_options`, `output_formats[]`, `filters[]`, `sorts[]`, `narrative_style`. Routes between four templates: `team_efficiency_tenure_pack`, `executive_infographic_pdf`, `snapshot_vs_performance_pack`, `trend_focus_pack`.
- **ModelManager.** Inspects model dir for `*.onnx`, checks `onnxruntime` import, writes `manifest.json`. Single-provider only — no separate ask / summary / graph roles.

---

## What works

- Modular package layout with clean dependencies (UI → app service → repository → models).
- Two-layer warehouse with content-hash dedup and **time-stable historical attribution via `parent_entity_id`** — the architectural feature explicitly verified by `test_truth_correctness.py`.
- Idempotent schema migrations on startup.
- Setup wizard with transactional staging — Cancel leaves config untouched.
- Background report generation (UI stays responsive).
- `scripts/build.py` lists every required hidden import for PyInstaller (33+ submodules) and builds a one-dir bundle via `--onedir --windowed`.
- Comprehensive split-requirements layout (`requirements.txt`, `requirements-ai.txt`, `requirements-dev.txt`) so the optional AI stack stays optional.

## Known gaps

- **No CI.** The strongest asset (115+ tests across 11 modules) never runs on push. Highest-leverage fix.
- **`pyproject.toml` build-backend typo (verified line 3):** `build-backend = "setuptools.backends._legacy:_Backend"` — the real string is `setuptools.build_meta:__legacy__` (or just `setuptools.build_meta`). Will fail `pip install -e .` and `python -m build` in any clean env that strictly resolves the backend.
- **No shipped binary.** README promises GitHub-distributed binaries; no GitHub Releases yet. Build script exists.
- **`fixtures/` has only a README.** Tester checklist depends on real data files in `~/Downloads/` because the parser tests use `@pytest.mark.skipif(not has_fixture(...))`. Without synthetic fixtures, all parser integration tests are silently skipped.
- `tests/conftest.py` provides a `repo` fixture but no fixture for sample report files.
- Three SQLAlchemy `utcnow` deprecation warnings called out in release notes — cosmetic but worth retiring.

## Priority improvements (see IMPROVEMENT_PLAN.md)

1. Fix `pyproject.toml` build-backend string (one-line diff).
2. GitHub Actions workflow running `pytest` on push.
3. Ship first PyInstaller binary as a GitHub Release using existing `scripts/build.py`.
4. Populate `fixtures/` with at least one synthetic sample per supported file type.
5. (P1) Port File-Analyzer's three-role Ollama config and deterministic ChartSpec planner into `src/reportbuilder/ai/`.

---

## Notes for AI agents

- **Canonical implementation** for technician/operations report analysis in this user's portfolio. `brynr-builds/Tech-Analyzer` was archived as a duplicate. `brynr-builds/File-Analyzer` is the dashboard sibling — its `tech_analyzer/` Python subdir is the same archived code embedded; do not import from it. Patterns worth porting back are in `File-Analyzer/server/ollama.ts`, `aiGraph.ts`, `aiContext.ts`, `shared/askTheData.ts`.
- **Local-first by design.** Do not introduce network calls in the warehouse, ingestion, or reports paths. The optional ONNX model is gated behind the `[ai]` extras group — do not promote those packages to base deps.
- If you touch parsing or warehouse code, **run `tests/test_truth_correctness.py`** — it inspects real dedup/supersession, historical attribution, and parser→`parent_entity_id` wiring. The dedup and `parent_entity_id` behaviors are load-bearing architectural commitments.
- `parent_entity_id` (NOT `Entity.parent_id`) is the source of truth for historical rollups.
- Schema migrations live in `warehouse/migrations.py` and are idempotent. Append new migrations to the `MIGRATIONS` list — never edit existing ones.
- The Ask-the-Data planner returns JSON plans only; **report rendering is fully deterministic**. Never put a model in the rendering path.
