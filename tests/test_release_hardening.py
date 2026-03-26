"""Tests for release-hardening fixes: schema migration, background report
execution, session safety, and packaging entrypoint sanity."""

import json
import os
import sys
import threading
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text, inspect, Column, Integer, String, Float, Text
from sqlalchemy.orm import sessionmaker, Session

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reportbuilder.warehouse.models import (
    Base, Observation, Entity, Metric, Period, SourceFile, OutputArtifact,
    create_warehouse_engine, get_session_factory,
)
from reportbuilder.warehouse.repository import WarehouseRepository
from reportbuilder.warehouse.migrations import (
    run_migrations, _get_current_version, _column_exists,
    _index_exists, _table_exists,
)


# =========================================================================
# 1. SCHEMA MIGRATION TESTS
# =========================================================================

class TestSchemaMigration:
    """Verify the migration system upgrades existing databases safely."""

    def _create_legacy_db(self, db_path: str):
        """Create a database with the pre-migration schema (no parent_entity_id)."""
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE entities (
                    id INTEGER PRIMARY KEY,
                    entity_type VARCHAR(50) NOT NULL,
                    canonical_name TEXT NOT NULL,
                    parent_id INTEGER,
                    created_at TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE periods (
                    id INTEGER PRIMARY KEY,
                    period_type VARCHAR(30) NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    label VARCHAR(100),
                    year INTEGER, month INTEGER, week INTEGER,
                    created_at TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE metrics (
                    id INTEGER PRIMARY KEY,
                    canonical_name VARCHAR(100) NOT NULL UNIQUE,
                    display_name TEXT,
                    unit VARCHAR(30),
                    aggregation VARCHAR(30) DEFAULT 'sum',
                    description TEXT,
                    trend_eligible BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE report_families (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(100) NOT NULL UNIQUE,
                    description TEXT,
                    source_pattern TEXT,
                    created_at TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE source_files (
                    id INTEGER PRIMARY KEY,
                    watched_folder_id INTEGER,
                    filename TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    file_hash VARCHAR(64),
                    file_size INTEGER,
                    file_modified TIMESTAMP,
                    is_archive BOOLEAN DEFAULT 0,
                    parent_archive_id INTEGER,
                    archive_member_path TEXT,
                    detected_family VARCHAR(100),
                    ingest_status VARCHAR(30) DEFAULT 'pending',
                    ingest_error TEXT,
                    first_seen TIMESTAMP,
                    last_processed TIMESTAMP,
                    version INTEGER DEFAULT 1,
                    created_at TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE ingest_runs (
                    id INTEGER PRIMARY KEY,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    trigger VARCHAR(50),
                    files_processed INTEGER DEFAULT 0,
                    observations_created INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    status VARCHAR(30) DEFAULT 'running',
                    notes TEXT
                )
            """))
            conn.execute(text("""
                CREATE TABLE observations (
                    id INTEGER PRIMARY KEY,
                    entity_id INTEGER NOT NULL REFERENCES entities(id),
                    period_id INTEGER NOT NULL REFERENCES periods(id),
                    metric_id INTEGER NOT NULL REFERENCES metrics(id),
                    value FLOAT,
                    text_value TEXT,
                    report_family_id INTEGER REFERENCES report_families(id),
                    source_file_id INTEGER REFERENCES source_files(id),
                    source_sheet TEXT,
                    source_row INTEGER,
                    confidence FLOAT DEFAULT 1.0,
                    ingest_run_id INTEGER REFERENCES ingest_runs(id),
                    version INTEGER DEFAULT 1,
                    created_at TIMESTAMP
                )
            """))
            conn.execute(text(
                "INSERT INTO entities (id, entity_type, canonical_name) "
                "VALUES (1, 'technician', 'Alice')"
            ))
            conn.execute(text(
                "INSERT INTO periods (id, period_type, start_date, end_date, label) "
                "VALUES (1, 'month', '2025-01-01', '2025-01-31', 'Jan 2025')"
            ))
            conn.execute(text(
                "INSERT INTO metrics (id, canonical_name) VALUES (1, 'hours')"
            ))
            conn.execute(text(
                "INSERT INTO observations (entity_id, period_id, metric_id, value) "
                "VALUES (1, 1, 1, 40.0)"
            ))
            conn.commit()
        engine.dispose()

    def test_migration_adds_parent_entity_id(self, tmp_path):
        """Existing DB without parent_entity_id is upgraded safely."""
        db_path = str(tmp_path / "legacy.db")
        self._create_legacy_db(db_path)

        engine = create_warehouse_engine(db_path)
        assert not _column_exists(engine, "observations", "parent_entity_id")

        applied = run_migrations(engine)
        assert applied == 1
        assert _column_exists(engine, "observations", "parent_entity_id")
        assert _index_exists(engine, "observations", "ix_obs_parent")

        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT value, parent_entity_id FROM observations WHERE id = 1"
            )).fetchone()
            assert row[0] == 40.0
            assert row[1] is None
        engine.dispose()

    def test_migration_is_idempotent(self, tmp_path):
        """Running migration twice does not error or double-apply."""
        db_path = str(tmp_path / "legacy.db")
        self._create_legacy_db(db_path)

        engine = create_warehouse_engine(db_path)
        first = run_migrations(engine)
        assert first == 1

        second = run_migrations(engine)
        assert second == 0

        assert _get_current_version(engine) == 1
        engine.dispose()

    def test_migrated_db_works_normally(self, tmp_path):
        """After migration, the full ORM layer works against the DB."""
        db_path = str(tmp_path / "legacy.db")
        self._create_legacy_db(db_path)

        sf = get_session_factory(db_path)
        session = sf()
        try:
            repo = WarehouseRepository(session)
            entity = repo.get_or_create_entity("technician", "Alice")
            assert entity.id == 1

            period = session.query(Period).first()
            metric = session.query(Metric).first()
            repo.add_observation(
                entity.id, period.id, metric.id, value=50.0,
                parent_entity_id=None,
            )
            session.commit()

            obs_count = session.query(Observation).count()
            assert obs_count == 2
        finally:
            session.close()

    def test_fresh_db_has_migrations_applied(self, tmp_path):
        """A brand new database gets both create_all and migrations."""
        db_path = str(tmp_path / "fresh.db")
        sf = get_session_factory(db_path)
        engine = create_warehouse_engine(db_path)

        assert _column_exists(engine, "observations", "parent_entity_id")
        assert _index_exists(engine, "observations", "ix_obs_parent")
        assert _get_current_version(engine) == 1
        engine.dispose()


# =========================================================================
# 2. BACKGROUND REPORT EXECUTION TESTS
# =========================================================================

class TestReportWorker:
    """Verify the ReportWorker QThread contract without requiring a GUI."""

    def test_worker_calls_execute_plan(self, tmp_path):
        """Worker invokes registry.execute_plan and emits finished."""
        from reportbuilder.reports.registry import ReportPlan

        mock_registry = MagicMock()
        mock_registry.execute_plan.return_value = [str(tmp_path / "out.xlsx")]

        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            entity_scope={"type": "team"},
            output_formats=["xlsx"],
        )

        sf = get_session_factory(str(tmp_path / "test.db"))

        from reportbuilder.ui.main_window import ReportWorker
        worker = ReportWorker(mock_registry, plan, sf, str(tmp_path))

        results = []
        errors = []
        worker.finished.connect(results.append)
        worker.error.connect(errors.append)

        worker.run()

        assert len(results) == 1
        assert results[0] == [str(tmp_path / "out.xlsx")]
        assert len(errors) == 0
        mock_registry.execute_plan.assert_called_once()

    def test_worker_emits_error_on_failure(self, tmp_path):
        """Worker emits error signal when execute_plan raises."""
        from reportbuilder.reports.registry import ReportPlan

        mock_registry = MagicMock()
        mock_registry.execute_plan.side_effect = RuntimeError("test failure")

        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            entity_scope={"type": "team"},
            output_formats=["xlsx"],
        )

        sf = get_session_factory(str(tmp_path / "test.db"))

        from reportbuilder.ui.main_window import ReportWorker
        worker = ReportWorker(mock_registry, plan, sf, str(tmp_path))

        results = []
        errors = []
        worker.finished.connect(results.append)
        worker.error.connect(errors.append)

        worker.run()

        assert len(errors) == 1
        assert "test failure" in errors[0]
        assert len(results) == 0

    def test_worker_closes_session_on_error(self, tmp_path):
        """Session is always closed, even when execute_plan raises."""
        from reportbuilder.reports.registry import ReportPlan

        mock_registry = MagicMock()
        mock_registry.execute_plan.side_effect = RuntimeError("boom")

        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            entity_scope={"type": "team"},
            output_formats=["xlsx"],
        )

        mock_session = MagicMock(spec=Session)
        mock_sf = MagicMock(return_value=mock_session)

        from reportbuilder.ui.main_window import ReportWorker
        worker = ReportWorker(mock_registry, plan, mock_sf, str(tmp_path))

        errors = []
        worker.error.connect(errors.append)
        worker.run()

        mock_session.close.assert_called_once()


# =========================================================================
# 3. SESSION SAFETY TESTS
# =========================================================================

class TestSessionSafety:
    """Verify sessions are closed even when exceptions occur."""

    def test_ingest_orchestrator_closes_session_on_error(self, tmp_path):
        """IngestOrchestrator.process_file closes session even on exception."""
        from reportbuilder.ingestion.scanner import IngestOrchestrator

        test_file = tmp_path / "test.xlsx"
        test_file.write_text("dummy")

        mock_session = MagicMock(spec=Session)
        mock_sf = MagicMock(return_value=mock_session)

        mock_repo_cls = MagicMock()
        mock_repo_cls.return_value.register_source_file.side_effect = RuntimeError("db error")

        orchestrator = IngestOrchestrator(mock_sf, str(tmp_path))

        with patch("reportbuilder.ingestion.scanner.WarehouseRepository", mock_repo_cls):
            result = orchestrator.process_file(str(test_file))

        assert result is False
        mock_session.close.assert_called()

    def test_ingest_lock_prevents_duplicate_processing(self, tmp_path):
        """Concurrent calls with the same filepath are rejected."""
        from reportbuilder.ingestion.scanner import IngestOrchestrator

        sf = get_session_factory(str(tmp_path / "test.db"))
        orchestrator = IngestOrchestrator(sf, str(tmp_path))

        test_file = tmp_path / "test.xlsx"
        test_file.write_text("dummy")

        with orchestrator._lock:
            orchestrator._processing.add(str(test_file))

        result = orchestrator.process_file(str(test_file))
        assert result is False


# =========================================================================
# 4. PACKAGING / ENTRYPOINT SANITY TESTS
# =========================================================================

class TestPackagingSanity:
    """Verify entrypoint and import assumptions hold."""

    def test_run_py_exists(self):
        run_py = Path(__file__).parent.parent / "run.py"
        assert run_py.exists(), "run.py must exist at project root"

    def test_run_py_handles_frozen_mode(self):
        """run.py _resolve_src_path handles sys.frozen attribute."""
        run_py = Path(__file__).parent.parent / "run.py"
        source = run_py.read_text()
        assert "frozen" in source, "run.py must handle frozen (packaged) mode"
        assert "_MEIPASS" in source, "run.py must reference _MEIPASS for PyInstaller"

    def test_main_entrypoint_importable(self):
        from reportbuilder.app import main
        assert callable(main)

    def test_pyproject_entrypoint_matches(self):
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        content = pyproject.read_text()
        assert 'reportbuilder = "reportbuilder.app:main"' in content

    def test_build_script_includes_migrations_import(self):
        build_py = Path(__file__).parent.parent / "scripts" / "build.py"
        content = build_py.read_text()
        assert "reportbuilder.warehouse.migrations" in content

    def test_build_script_no_false_signing_claims(self):
        build_py = Path(__file__).parent.parent / "scripts" / "build.py"
        content = build_py.read_text()
        assert "NOT code-signed" in content or "not notarized" in content.lower()


# =========================================================================
# 5. MIGRATION MODULE UNIT TESTS
# =========================================================================

class TestMigrationHelpers:
    """Unit tests for migration helper functions."""

    def test_table_exists_positive(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE foo (id INTEGER PRIMARY KEY)"))
            conn.commit()
        assert _table_exists(engine, "foo")
        engine.dispose()

    def test_table_exists_negative(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE foo (id INTEGER PRIMARY KEY)"))
            conn.commit()
        assert not _table_exists(engine, "bar")
        engine.dispose()

    def test_column_exists_positive(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE t (id INTEGER, name TEXT)"))
            conn.commit()
        assert _column_exists(engine, "t", "name")
        engine.dispose()

    def test_column_exists_negative(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE t (id INTEGER)"))
            conn.commit()
        assert not _column_exists(engine, "t", "name")
        engine.dispose()

    def test_schema_version_starts_at_zero(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        assert _get_current_version(engine) == 0
        engine.dispose()
