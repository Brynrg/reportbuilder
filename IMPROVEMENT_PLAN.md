# Improvement Plan — Brynrg/reportbuilder

> P0 = blockers / unbreaks / shippable in days. P1 = high-leverage in 1–2 weeks. P2 = quality-of-life. P3 = nice-to-have.

---

## P0 — Unblock & ship

### P0-1 — Fix `pyproject.toml` build-backend string (single-line diff)

The current build backend reference is wrong and will fail any clean-env `pip install -e .` or `python -m build`.

**File:** `pyproject.toml` (line 3)

**Diff:**

```diff
 [build-system]
 requires = ["setuptools>=68.0", "wheel"]
-build-backend = "setuptools.backends._legacy:_Backend"
+build-backend = "setuptools.build_meta"
```

(Use `setuptools.build_meta:__legacy__` only if the project actually needs the legacy backend for a `setup.py` shim — this repo has no `setup.py`, so the modern `setuptools.build_meta` is correct.)

**Acceptance:**

- `python -m venv .venv && source .venv/bin/activate && pip install -e .` succeeds end-to-end in a fresh venv.
- `python -m build` produces a sdist + wheel.
- `python -c "import reportbuilder; print(reportbuilder.__file__)"` works after install.

### P0-2 — GitHub Actions: run `pytest` on push

The 11-module test suite is the project's single biggest asset and currently never runs in CI.

**New file:** `.github/workflows/test.yml`

```yaml
name: tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  pytest:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Install Qt offscreen dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y libegl1 libxkbcommon0 libdbus-1-3 libxcb-cursor0

      - name: Install package + dev deps
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Run pytest
        env:
          QT_QPA_PLATFORM: offscreen
          PYTHONPATH: src
        run: pytest tests/ -v --tb=short
```

**Notes:**

- `QT_QPA_PLATFORM=offscreen` makes PySide6 importable in headless CI.
- Parser tests that depend on `~/Downloads/` fixtures use `pytest.mark.skipif` and will skip gracefully — they are not a CI blocker.
- After P0-4 lands (synthetic fixtures committed), update the workflow to add `env: REPORTBUILDER_FIXTURES_DIR=fixtures` and adjust `tests/test_parsers.py` constants accordingly (see P0-4).

**Acceptance:** PR shows a green `pytest (3.11)` and `pytest (3.12)` check.

### P0-3 — Ship first PyInstaller binary as a GitHub Release

Build infrastructure already exists (`scripts/build.py`, `[build]` optional-deps group). Cut the first artifact for the tester checklist that's already written.

**Steps:**

1. On a clean macOS host (the tester platform), tag `v0.1.0`:

   ```bash
   git checkout main && git pull
   git tag -a v0.1.0 -m "v0.1.0 — first tester binary"
   git push origin v0.1.0
   ```

2. Build the bundle locally:

   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -e ".[build]"
   python scripts/build.py
   ```

   Output: `dist/ReportBuilder/` (one-dir bundle).

3. Compress for upload:

   ```bash
   cd dist && zip -r ReportBuilder-v0.1.0-macos.zip ReportBuilder/
   ```

4. Create the GitHub Release:

   ```bash
   gh release create v0.1.0 \
     --title "v0.1.0 — first tester binary" \
     --notes-file docs/RELEASE_NOTES.md \
     dist/ReportBuilder-v0.1.0-macos.zip
   ```

5. (Optional but recommended) Add a release-on-tag workflow at `.github/workflows/release.yml` that builds + uploads on tag push, matrix over `macos-latest` and `windows-latest`. Reuse the same `pip install -e ".[build]"` + `python scripts/build.py` recipe; use `gh release upload ${{ github.ref_name }} <artifact>` to attach.

**Acceptance:**

- `gh release view v0.1.0` lists at least one binary asset.
- README's "GitHub-distributed binaries" promise is no longer aspirational.
- Tester checklist in `TESTER_CHECKLIST.md` can be run without a Python toolchain installed.

### P0-4 — Populate `fixtures/` with at least one synthetic sample per supported file type

`fixtures/README.md` currently lists three expected files but ships none of them. `tests/test_parsers.py` references them under `~/Downloads/` and silently skips when absent — meaning the parser integration tests are effectively dead in CI and on any developer's machine without the real ops data.

**Files to add (synthetic, no real personnel data):**

| Path                                              | Generator                                                                                                                                                                                                                                |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `fixtures/daily_tech_performance_sample.zip`      | ZIP containing one `.xlsx` with the DTP header signature and ~10 fake technicians across 2 teams over 5 days. Use `openpyxl` to write the workbook so the header detection used by `DailyTechPerformanceParser.can_parse` will return ≥0.5. |
| `fixtures/mca_snapshot_sample.zip`                | ZIP containing one `.xlsx` with the MCA Snapshot header signature and ~5 fake CIDs.                                                                                                                                                       |
| `fixtures/mileage_disbursed_sample.csv`           | CSV with columns `technician_name,total_mileage,total_amount,...` and ~20 fake rows.                                                                                                                                                      |
| `fixtures/generate.py`                            | Reproducible generator script. Keep deterministic (fixed seed) so the fixtures regen byte-identical.                                                                                                                                      |

**Then update** `tests/test_parsers.py`:

```diff
-DOWNLOADS = Path.home() / "Downloads"
-FIXTURE_DTP_ZIP = DOWNLOADS / "2025_DailyTechPerformance.zip"
-FIXTURE_MCA_ZIP = DOWNLOADS / "2025_MCA_Snapshot.zip"
-FIXTURE_MILEAGE_CSV = DOWNLOADS / "MCA_disbursedmileage_10.1.25_12.31.25.csv"
+REPO_ROOT = Path(__file__).resolve().parent.parent
+FIXTURES = Path(os.environ.get("REPORTBUILDER_FIXTURES_DIR", REPO_ROOT / "fixtures"))
+FIXTURE_DTP_ZIP = FIXTURES / "daily_tech_performance_sample.zip"
+FIXTURE_MCA_ZIP = FIXTURES / "mca_snapshot_sample.zip"
+FIXTURE_MILEAGE_CSV = FIXTURES / "mileage_disbursed_sample.csv"
```

Keep the `skipif` guards so private real data in `~/Downloads/` can still be used by overriding the env var.

**Acceptance:**

- Parser integration tests in `test_parsers.py` actually run (no skips) on a fresh clone.
- `pytest tests/test_parsers.py -v` reports `~15 passed, 0 skipped` in CI.
- `fixtures/README.md` updated to document the committed fixtures + the env-var override.

---

## P1 — Cross-repo porting (from File-Analyzer)

These take the unique pieces of the Electron + TS sibling and bring them into the canonical Python codebase.

### P1-1 — Port three-role Ollama config from File-Analyzer/server/ollama.ts

**Source:** `brynr-builds/File-Analyzer:server/ollama.ts` — `OLLAMA_MODEL_ASK` / `OLLAMA_MODEL_SUMMARY` / `OLLAMA_MODEL_GRAPH` env split with a single default fallback, plus `getOllamaModelStatus()` that returns `{ ollamaReachable, modelsRequired, modelsInstalled, modelsMissing, ready, hint }`.

**Target:** new file `src/reportbuilder/ai/ollama_adapter.py`.

**Minimum surface to port:**

- `OllamaRuntimeConfig` dataclass with `base_url`, `model_ask`, `model_summary`, `model_graph`, `timeout_s`, `keep_alive`. Default model `llama3.2:3b` per File-Analyzer's `OLLAMA_DEFAULT_MODEL_TAG`. Env-var overrides: `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_MODEL_ASK`, `OLLAMA_MODEL_SUMMARY`, `OLLAMA_MODEL_GRAPH`, `OLLAMA_TIMEOUT_MS`, `OLLAMA_KEEP_ALIVE`.
- `get_ollama_model_status()` calling `GET {base_url}/api/tags` with a 5s timeout, returning the same shape. Handle base-tag matching (a request for `qwen3:14b` accepts an installed `qwen3:14b-q4_K_M`).
- `OllamaError` with codes `UNAVAILABLE | HTTP_ERROR | EMPTY_RESPONSE | ABORTED`.
- `ollama_chat(messages, model=None, format_json=False, keep_alive=None)` non-streaming wrapper over `POST {base_url}/api/chat`.

**Integration points:**

- Register a new `OllamaPlannerProvider(PlannerProvider)` in `ai/planner.py` that uses `model_ask` and falls back gracefully when `get_ollama_model_status().ready is False`. The planner already supports stacked providers — Ollama slots in between ONNX and the deterministic fallback.
- Expose a "model status" surface on the Settings tab in `ui/main_window.py` (banner if `ollama_reachable` is False or any required model is missing, with copy-to-clipboard `ollama pull ...` hints — mirrors File-Analyzer's missing-model UI banner).

**Tests:** add `tests/test_ollama_adapter.py` with mocked `httpx`/`requests` for tags/reachability matrix (reachable + missing, reachable + ready, unreachable, timeout). No live Ollama in CI.

**Acceptance:** with `OLLAMA_BASE_URL=http://invalid:1` the app boots, settings panel shows "Ollama not reachable", planner silently falls back to deterministic.

### P1-2 — Port deterministic ChartSpec planner from File-Analyzer/server/aiGraph.ts

**Source:** `brynr-builds/File-Analyzer:server/aiGraph.ts` + `shared/askTheData.ts` (`ChartSpec`, `ChartType`, `ChartSeries`). Mechanism: pure intent detection routes a question to one of `trend | ranking | scatter | groupedBar | bar`. Aggregation is deterministic, LLM only writes a 1–3 sentence takeaway. Unsupported chart types (pie, donut, heatmap, histogram, boxplot, stacked) return a structured fallback with a suggested alternative.

**Target:** new files

- `src/reportbuilder/ai/chart_spec.py` — Python dataclasses mirroring `ChartSpec` (chart_type Literal, title, description, x_key, y_keys, data, series, horizontal, x_label, y_label).
- `src/reportbuilder/ai/graph_planner.py` — `is_graph_intent(question)` + `build_graph_plan(question, filters, observations)` returning `GraphPlanResult = ok | fallback`.

**Reuse:**

- The five intent regexes from `aiGraph.ts` lines 14–20 (UNSUPPORTED_CHARTS) and 37–44 (`isGraphIntent`).
- The metric-keyword routing in `buildTrendMetric`/`buildRankingMetric` translates 1:1.
- Use `analytics/engine.py` rollups as the data source instead of `reportAnalytics.ts.buildAggregatedData` / `buildHistoricalData`.

**Why now:** reportbuilder has no charting today, but this is the single highest-leverage piece in File-Analyzer that doesn't exist in the canonical repo. Bringing it in unlocks an Ask-the-Data chart response without touching the report generation path (which must stay fully deterministic).

**Tests:** see File-Analyzer P0-3 — the same intent-detection cases apply here. Port them as `tests/test_graph_planner.py`.

**Acceptance:** `build_graph_plan("show me revenue over time")` returns an `ok=True` result with `chart_type="line"` and at least one data point; `build_graph_plan("pie chart of revenue")` returns `ok=False` with the canned suggestion.

### P1-3 — Add structured logging + log rotation

App currently uses module-level `logger = logging.getLogger(__name__)` but never configures a handler or log file. For a desktop app that runs in the background with watchdog, an on-disk log under `<app data>/logs/reportbuilder.log` (with `RotatingFileHandler`, 10 MB × 5 backups) is the single easiest debuggability improvement.

Wire it in `app.py` immediately after settings are loaded. Surface "Open log folder" on Settings tab.

---

## P2 — Quality

### P2-1 — Modernize SQLAlchemy 2.x usage

Release notes call out deprecation warnings. Replace:

- `datetime.utcnow` → `datetime.now(timezone.utc)` in model `default=` arguments.
- `Query.get()` → `Session.get()`.
- Make sure all model declarations use `DeclarativeBase` consistently (already done for `Base`).

Run `pytest -W error::DeprecationWarning` once to catch survivors.

### P2-2 — Pre-commit hooks

Add `.pre-commit-config.yaml` with `ruff` (lint + format), `mypy --strict` against `src/reportbuilder/`, and `pytest-style` checks. Keeps the diff churn low while raising the floor.

### P2-3 — Surface ingest-run telemetry in UI

`IngestRun` table is populated but not displayed. Add an "Ingest History" sub-tab under Sources showing the last 20 runs with `started_at / files_processed / observations_created / errors / status`. Five-line change in `ui/main_window.py`.

### P2-4 — Periodic snapshot of `_schema_version` in About dialog

Helps support diagnose state when a user sends a screenshot.

---

## P3 — Nice-to-have

- **P3-1** — Code-sign + notarize the macOS PyInstaller bundle. Out of P0 scope but eliminates the right-click-to-open friction in the README.
- **P3-2** — Windows installer via `nsis` or `briefcase`. Cross-platform release matrix.
- **P3-3** — Custom report templates loaded from `<app data>/templates/` (Python module discovery). Currently requires code changes.
- **P3-4** — Replace the keyword-only deterministic planner with a small CFG-based one so phrasing like "rank teams by net dollars per hour after mileage" routes correctly. Bring `OLLAMA_MODEL_ASK` in as the third tier (after ONNX, before deterministic) once P1-1 lands.
- **P3-5** — Data migration tooling when the user changes app-data location (release notes list this as a known limitation).
