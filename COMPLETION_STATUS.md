# Completion Status

> Status doc for AI agents working on this repo. Updated 2026-05-19.

**Score:** 65 / 100 — Real v0.1 with tests + docs, but no CI/binaries shipped
**State:** v0.1 released 2026-03-26. Single commit, never iterated.
**Stack:** Python / PySide6 desktop, SQLAlchemy warehouse, reportlab PDF, optional ONNX/transformers "Ask the Data" planner

## What works
- Well-modularized: `ingestion` (watchdog folder scanner + ZIP handler), `parsing` (3 concrete parsers + detector), `normalization`, `warehouse` (models/migrations/repository), `analytics`, `reports` (registry + 4 templates incl. PDF), `ui` (setup wizard)
- Real test suite (10 files): AI, analytics, config, ingestion, parsers, reports, warehouse, plus `test_truth_correctness.py` and `test_release_hardening.py`
- `pyproject.toml` with `[project.scripts]` entry point
- Three split requirements files (base/ai/dev)
- `scripts/build.py` for PyInstaller packaging
- `docs/TESTING.md`, `docs/RELEASE_NOTES.md`, `TESTER_CHECKLIST.md`

## Known gaps
- **No CI** — strongest asset (tests) never gets exercised
- `pyproject.toml` build-backend reads `setuptools.backends._legacy:_Backend` — **looks like a typo** of `setuptools.build_meta:__legacy__`. May break `pip install -e .` in clean envs.
- README promises GitHub-distributed binaries; **no GitHub Releases / PyInstaller artifacts shipped**
- `fixtures/` has only a README — no actual sample data, blocking tester checklist
- Single commit; never iterated past v0.1

## Priority improvements
1. **Add GitHub Actions** running `pytest` on push (matrix over Python versions if PySide6 allows)
2. **Fix `pyproject.toml` build-backend string** — should be `setuptools.build_meta:__legacy__` or `setuptools.build_meta`. Verify `pip install -e .` works clean.
3. **Ship a PyInstaller binary as a GitHub Release** — the build infra exists, just hasn't been run
4. **Populate `fixtures/`** with at least one sample Excel/CSV/ZIP per supported file type

## Notes for AI agents
- Local-first by design — no cloud dependencies. Don't introduce network calls in the warehouse path.
- The "Ask the Data" ONNX path is **optional** and gated behind the `[ai]` extras group. Don't promote it to a base dep.
- If touching parsing, run `tests/test_truth_correctness.py` — it inspects real dedup/supersession behavior, not toy stubs.
