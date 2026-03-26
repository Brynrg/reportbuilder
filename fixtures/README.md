# Test Fixtures

This directory is for local test fixture files. These files are **not** included in the repository because they contain real operational data.

## Files Used by Tests

Tests that require real fixture files use `@pytest.mark.skipif` to skip gracefully when fixtures are absent. To run the full integration test suite, place these files here or in `~/Downloads/`:

| File | Used By | Description |
|---|---|---|
| `2025_DailyTechPerformance.zip` | `test_ingestion.py`, `test_parsers.py` | ZIP of daily Excel tech performance reports |
| `MCA_disbursedmileage_*.csv` | `test_ingestion.py` | Mileage/disbursement CSV |
| `2025_MCA_Snapshot.zip` | (future) | MCA Snapshot ZIP archive |

## For Testers Without Real Data

The unit tests (config, analytics, warehouse, AI, hardening) run without any fixture files. Only the ingestion and parser integration tests require real data files.
