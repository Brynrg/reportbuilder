# ReportBuilder — Release Notes

## v0.1.0 — First Tester Distribution

**Date:** March 2026

This is the first externally shareable version of ReportBuilder. The application has been through truth-and-correctness verification and release-hardening passes.

---

### What This Version Supports

**Data Ingestion**
- Continuous folder watching with automatic file detection
- ZIP archive extraction and per-member processing
- Three parser families: Daily Tech Performance (DTP), MCA Snapshot, Mileage/Disbursed CSV
- Content-hash deduplication — re-ingestion of identical files is skipped
- Full lineage tracking from source file to warehouse observations

**Data Warehouse**
- SQLite-based local warehouse with entity/period/metric/observation schema
- Entity hierarchy (technician -> team, CID -> store)
- Schema migration system for safe database upgrades
- Full-text search support

**Report Generation**
- Team Efficiency Tenure Pack (multi-sheet ranked Excel)
- Snapshot vs Performance (CID-level cross-report comparison)
- Executive Infographic PDF (KPI cards, top performers, concerns)
- Trend Focus Pack (period-over-period, rank movement, volatility)
- Capability validation — unsupported requests are rejected clearly, never silently coerced

**AI Planning**
- Deterministic fallback parser for all common report requests (always available)
- Optional ONNX model support for flexible natural language understanding
- Structured JSON plan generation with user-editable intermediate step

**Desktop Application**
- PySide6 desktop UI with setup wizard and seven-tab main interface
- File > Re-run Setup Wizard for reconfiguration at any time
- Background report generation (UI stays responsive)
- Settings pointer file for reliable config discovery across restarts

---

### Major Fixes Applied

These issues were identified through audit and systematically corrected:

**Truth and Correctness (Pass 1)**

- **Observation deduplication** — content-hash based dedup prevents double-counting when the same file is ingested from different paths. Re-ingestion of corrected files supersedes old observations.
- **Historical attribution** — `parent_entity_id` on each observation records the team/parent at observation time. Historical rollups use this field, so team reassignments never corrupt past-period data.
- **Cross-report join narrowed** — Snapshot vs Performance template now honestly supports CID scope only. The template clearly reports when DTP data is not available at CID grain.
- **Team trends via real aggregation** — team-level trends are computed by aggregating child observations, not from seeded team-level data.
- **Setup wizard transactionality** — config changes are staged during the wizard and applied atomically on Finish. Cancel leaves the app unchanged.
- **ZIP ingest honesty** — ZIP processing status accurately reflects partial failures ("error", "partial", or "completed").

**Release Hardening (Pass 2)**

- **Schema migration** — existing databases are safely upgraded on startup (adds `parent_entity_id` column and indexes). Migration is idempotent.
- **Background report generation** — report execution runs on a background thread. The UI stays responsive with progress indication.
- **Session lifecycle** — all database sessions in UI views use try/finally to guarantee closure, even on exceptions.
- **Packaging readiness** — entrypoint handles both dev and PyInstaller frozen mode. Build script includes all required hidden imports.
- **Processing lock** — concurrent file processing uses a thread lock to prevent duplicate ingestion.

---

### What Is NOT Included

These are intentionally deferred:

- Additional parser families (only DTP, MCA Snapshot, Mileage are supported)
- Data migration between app data locations
- Scheduled or batch report generation
- Multi-user or networked mode
- AI model bundling (must be installed separately)
- Custom report templates (requires code changes)
- Code signing or notarization
- Cloud or email integration

---

### Known Limitations

- Large ZIP ingestion (300+ files) takes several minutes on first run
- Cross-report joins are limited to CID scope
- The deterministic planner handles common patterns well but may not parse unusual phrasing
- macOS will show a Gatekeeper warning on unsigned builds
- SQLAlchemy deprecation warnings appear in test output (functional, cosmetic only)

---

### Recommended Next Improvements

1. Additional parser families for more report types
2. Batch/scheduled report generation
3. Data migration tooling for app data relocation
4. Modernize SQLAlchemy API (replace deprecated utcnow, Query.get)
5. Performance optimization for large ZIP ingestion
6. Code signing for macOS distribution
