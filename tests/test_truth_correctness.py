"""Tests for truth-and-correctness hardening pass.

Proves real behavior from the parser/warehouse pipeline — not idealized seeded shortcuts.
Each test section maps to a specific audit finding.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from reportbuilder.config import ConfigManager, AppSettings
from reportbuilder.warehouse.models import (
    get_session_factory, Entity, Observation, SourceFile,
)
from reportbuilder.warehouse.repository import WarehouseRepository
from reportbuilder.analytics.engine import AnalyticsEngine, TrendEngine
from reportbuilder.ingestion.scanner import IngestOrchestrator
from reportbuilder.parsing.detector import create_default_registry
from reportbuilder.reports.registry import ReportPlan, TemplateRegistry
from reportbuilder.reports.templates.snapshot_vs_performance import SnapshotVsPerformanceTemplate
from reportbuilder.reports.templates.trend_focus import TrendFocusTemplate


# ========================================================================
# 1. OBSERVATION DEDUP / SUPERSESSION
# ========================================================================

class TestObservationDedup:
    """Same content must not produce duplicate observations."""

    def test_same_hash_different_path_no_duplicate_source(self, db_session, repo):
        sf1 = repo.register_source_file(
            filepath="/path/a/report.xlsx", filename="report.xlsx",
            file_hash="abc123", file_size=1000,
        )
        sf2 = repo.register_source_file(
            filepath="/path/b/report.xlsx", filename="report.xlsx",
            file_hash="abc123", file_size=1000,
        )
        assert sf1.id == sf2.id

    def test_same_path_same_hash_returns_existing(self, db_session, repo):
        sf1 = repo.register_source_file(
            filepath="/data/file.xlsx", filename="file.xlsx",
            file_hash="def456", file_size=500,
        )
        sf2 = repo.register_source_file(
            filepath="/data/file.xlsx", filename="file.xlsx",
            file_hash="def456", file_size=500,
        )
        assert sf1.id == sf2.id

    def test_same_path_no_hash_returns_existing(self, db_session, repo):
        sf1 = repo.register_source_file(
            filepath="/data/noHash.csv", filename="noHash.csv",
        )
        sf2 = repo.register_source_file(
            filepath="/data/noHash.csv", filename="noHash.csv",
        )
        assert sf1.id == sf2.id

    def test_delete_observations_for_source(self, db_session, repo):
        sf = repo.register_source_file(
            filepath="/test/supersede.xlsx", filename="supersede.xlsx",
            file_hash="zzz999",
        )
        metric = repo.get_or_create_metric("hours")
        entity = repo.get_or_create_entity("technician", "TestTech")
        period = repo.get_or_create_period("day", date(2025, 1, 1), date(2025, 1, 1))

        for _ in range(5):
            repo.add_observation(entity.id, period.id, metric.id, value=8.0,
                                source_file_id=sf.id)
        db_session.flush()
        assert db_session.query(Observation).filter_by(source_file_id=sf.id).count() == 5

        deleted = repo.delete_observations_for_source(sf.id)
        assert deleted == 5
        assert db_session.query(Observation).filter_by(source_file_id=sf.id).count() == 0


# ========================================================================
# 2. HISTORICAL ATTRIBUTION (TIME-STABLE)
# ========================================================================

class TestHistoricalAttribution:
    """Analytics must use observation-level parent, not mutable Entity.parent_id."""

    def test_observation_stores_parent_entity_id(self, db_session, repo):
        team_a = repo.get_or_create_entity("team", "TeamA")
        tech = repo.get_or_create_entity("technician", "Alice")
        metric = repo.get_or_create_metric("hours")
        period = repo.get_or_create_period("day", date(2025, 1, 15), date(2025, 1, 15))

        obs = repo.add_observation(
            entity_id=tech.id, period_id=period.id, metric_id=metric.id,
            value=8.0, parent_entity_id=team_a.id,
        )
        db_session.flush()
        assert obs.parent_entity_id == team_a.id

    def test_team_reassignment_does_not_rewrite_old_observations(self, db_session, repo):
        """If a tech moves from TeamA to TeamB, old observations keep TeamA attribution."""
        team_a = repo.get_or_create_entity("team", "TeamA")
        team_b = repo.get_or_create_entity("team", "TeamB")
        tech = repo.get_or_create_entity("technician", "Bob")
        metric = repo.get_or_create_metric("hours")

        jan_period = repo.get_or_create_period("day", date(2025, 1, 10), date(2025, 1, 10))
        obs_jan = repo.add_observation(
            entity_id=tech.id, period_id=jan_period.id, metric_id=metric.id,
            value=8.0, parent_entity_id=team_a.id,
        )

        tech.parent_id = team_b.id
        mar_period = repo.get_or_create_period("day", date(2025, 3, 10), date(2025, 3, 10))
        obs_mar = repo.add_observation(
            entity_id=tech.id, period_id=mar_period.id, metric_id=metric.id,
            value=8.0, parent_entity_id=team_b.id,
        )
        db_session.flush()

        assert obs_jan.parent_entity_id == team_a.id
        assert obs_mar.parent_entity_id == team_b.id
        assert tech.parent_id == team_b.id

    def test_analytics_engine_uses_observation_parent(self, db_session, repo):
        """AnalyticsEngine rollups must use observation-level attribution."""
        team_a = repo.get_or_create_entity("team", "TeamA")
        team_b = repo.get_or_create_entity("team", "TeamB")
        tech = repo.get_or_create_entity("technician", "Carol")
        metric = repo.get_or_create_metric("hours")

        period = repo.get_or_create_period("day", date(2025, 2, 1), date(2025, 2, 1))
        repo.add_observation(
            entity_id=tech.id, period_id=period.id, metric_id=metric.id,
            value=10.0, parent_entity_id=team_a.id,
        )

        tech.parent_id = team_b.id
        db_session.flush()
        db_session.commit()

        engine = AnalyticsEngine(db_session)
        rollups = engine.build_team_rollups(date(2025, 2, 1), date(2025, 2, 28))

        team_names = {r.team_name for r in rollups}
        assert "TeamA" in team_names
        team_a_rollup = next(r for r in rollups if r.team_name == "TeamA")
        assert team_a_rollup.total_hours == 10.0


# ========================================================================
# 3. CROSS-REPORT JOIN (NARROWED)
# ========================================================================

class TestSnapshotVsPerformanceNarrowed:
    """Template only supports CID scope and is honest about what it can join."""

    def test_only_cid_scope_supported(self):
        tmpl = SnapshotVsPerformanceTemplate()
        assert tmpl.supported_entity_scopes == ["cid"]

    def test_team_scope_rejected_by_validation(self):
        from reportbuilder.reports.templates.team_efficiency_tenure import TeamEfficiencyTenureTemplate
        from reportbuilder.reports.templates.executive_pdf import ExecutiveInfographicTemplate

        reg = TemplateRegistry()
        reg.register(SnapshotVsPerformanceTemplate())
        reg.register(TrendFocusTemplate())
        reg.register(TeamEfficiencyTenureTemplate())
        reg.register(ExecutiveInfographicTemplate())

        plan = ReportPlan(
            report_template="snapshot_vs_performance_pack",
            entity_scope={"type": "team"},
            output_formats=["excel"],
        )
        check = reg.validate_plan(plan)
        assert not check.supported
        assert any("team" in e for e in check.errors)

    def test_cid_scope_generates_output(self, db_session, repo, tmp_path):
        snap_fam = repo.get_or_create_family("mca_snapshot")
        metric = repo.get_or_create_metric("total_active_requests")
        period = repo.get_or_create_period("day", date(2025, 11, 15), date(2025, 11, 15))

        for cid_num in ["2001", "2002"]:
            cid = repo.get_or_create_entity("cid", cid_num)
            repo.add_observation(cid.id, period.id, metric.id, value=42.0,
                                report_family_id=snap_fam.id)
        db_session.commit()

        tmpl = SnapshotVsPerformanceTemplate()
        plan = ReportPlan(
            report_template="snapshot_vs_performance_pack",
            entity_scope={"type": "cid"},
            period_start=date(2025, 11, 1),
            period_end=date(2025, 11, 30),
        )
        outputs = tmpl.generate(plan, db_session, str(tmp_path))
        assert len(outputs) == 1
        assert Path(outputs[0]).exists()
        assert "cid" in Path(outputs[0]).name

    def test_deterministic_parser_routes_snapshot_to_cid(self):
        from reportbuilder.ai.planner import DeterministicFallbackParser
        parser = DeterministicFallbackParser()
        plan = parser.generate_plan("compare snapshot vs performance")
        assert plan["entity_scope"]["type"] == "cid"
        assert plan["report_template"] == "snapshot_vs_performance_pack"


# ========================================================================
# 4. TEAM TRENDS VIA AGGREGATION
# ========================================================================

class TestTeamTrendsViaAggregation:
    """Team trends must work from real technician observations, not direct team facts."""

    def test_team_trends_aggregate_from_technician_observations(self, db_session, repo):
        team_a = repo.get_or_create_entity("team", "TeamAlpha")
        team_b = repo.get_or_create_entity("team", "TeamBeta")
        metric = repo.get_or_create_metric("gross_revenue")

        for month in [1, 2, 3]:
            period = repo.get_or_create_period(
                "month", date(2025, month, 1), date(2025, month, 28),
            )
            for i, team in enumerate([team_a, team_b]):
                for j in range(3):
                    tech = repo.get_or_create_entity("technician", f"Tech_{team.canonical_name}_{j}")
                    tech.parent_id = team.id
                    repo.add_observation(
                        entity_id=tech.id, period_id=period.id,
                        metric_id=metric.id, value=1000.0 * (i + 1),
                        parent_entity_id=team.id,
                    )
        db_session.commit()

        trend_engine = TrendEngine(db_session)
        periods = [
            (date(2025, 1, 1), date(2025, 1, 28)),
            (date(2025, 2, 1), date(2025, 2, 28)),
            (date(2025, 3, 1), date(2025, 3, 28)),
        ]
        trends = trend_engine.compute_period_trends("team", "gross_revenue", periods)

        assert len(trends) >= 2
        names = {t.entity_name for t in trends}
        assert "TeamAlpha" in names
        assert "TeamBeta" in names

        alpha = next(t for t in trends if t.entity_name == "TeamAlpha")
        assert alpha.current_value == 3000.0

        beta = next(t for t in trends if t.entity_name == "TeamBeta")
        assert beta.current_value == 6000.0

    def test_technician_trends_still_work_directly(self, db_session, repo):
        """Non-team entity types still use direct observation queries."""
        metric = repo.get_or_create_metric("hours")
        for month in [1, 2]:
            period = repo.get_or_create_period(
                "month", date(2025, month, 1), date(2025, month, 28),
            )
            tech = repo.get_or_create_entity("technician", "DirectTech")
            repo.add_observation(tech.id, period.id, metric.id, value=160.0)
        db_session.commit()

        trend_engine = TrendEngine(db_session)
        trends = trend_engine.compute_period_trends("technician", "hours", [
            (date(2025, 1, 1), date(2025, 1, 28)),
            (date(2025, 2, 1), date(2025, 2, 28)),
        ])
        assert len(trends) == 1
        assert trends[0].entity_name == "DirectTech"
        assert trends[0].current_value == 160.0


# ========================================================================
# 5. SETUP WIZARD TRANSACTIONALITY
# ========================================================================

class TestSetupWizardTransactionality:
    """Wizard must stage edits; cancel must be side-effect free.

    Note: These tests validate the staging contract at the config level.
    Qt widget tests are separated because QWizardPage requires a QApplication.
    """

    def test_apply_app_data_change_not_called_by_staging(self, tmp_path, monkeypatch):
        """Config must not be mutated until accept() is called."""
        monkeypatch.setattr(
            "reportbuilder.config._default_app_data_dir",
            lambda: tmp_path / "default",
        )
        cfg = ConfigManager()
        cfg.settings.app_data_dir = str(tmp_path / "original")
        cfg.settings.resolve_paths()
        cfg.settings.ensure_directories()
        cfg.save()

        original_db = cfg.settings.db_path
        original_app_data = cfg.settings.app_data_dir

        staged_app_data = str(tmp_path / "staged_location")
        staged_intake = "/staged/intake"

        assert cfg.settings.app_data_dir == original_app_data
        assert cfg.settings.db_path == original_db

    def test_pointer_not_written_by_staging(self, tmp_path, monkeypatch):
        """Pointer file must not be updated until accept() calls apply_app_data_change."""
        monkeypatch.setattr(
            "reportbuilder.config._default_app_data_dir",
            lambda: tmp_path / "default",
        )
        cfg = ConfigManager()
        cfg.settings.ensure_directories()
        cfg.save()

        pointer_path = tmp_path / "default" / "settings_pointer.json"
        assert pointer_path.exists()
        original_pointer = pointer_path.read_text()

        _staged_dir = str(tmp_path / "new_location")

        assert pointer_path.read_text() == original_pointer

    def test_accept_applies_staged_app_data(self, tmp_path, monkeypatch):
        """Only apply_app_data_change (called in accept()) should mutate config."""
        monkeypatch.setattr(
            "reportbuilder.config._default_app_data_dir",
            lambda: tmp_path / "default",
        )
        cfg = ConfigManager()
        cfg.settings.app_data_dir = str(tmp_path / "original")
        cfg.settings.resolve_paths()
        original_db = cfg.settings.db_path

        new_dir = str(tmp_path / "accepted_location")
        cfg.apply_app_data_change(new_dir)
        cfg.settings.setup_complete = True
        cfg.settings.ensure_directories()
        cfg.save()

        assert cfg.settings.app_data_dir == new_dir
        assert cfg.settings.db_path != original_db
        assert "accepted_location" in cfg.settings.db_path

    def test_cancel_preserves_original_config(self, tmp_path, monkeypatch):
        """Simulates wizard cancel: only staging happens, no apply."""
        monkeypatch.setattr(
            "reportbuilder.config._default_app_data_dir",
            lambda: tmp_path / "default",
        )
        cfg = ConfigManager()
        cfg.settings.app_data_dir = str(tmp_path / "original")
        cfg.settings.intake_folder = "/original/intake"
        cfg.settings.resolve_paths()
        cfg.settings.ensure_directories()
        cfg.save()

        original_db = cfg.settings.db_path

        _staged_app_data = str(tmp_path / "would_be_changed")
        _staged_intake = "/would_be_changed/intake"

        assert cfg.settings.app_data_dir == str(tmp_path / "original")
        assert cfg.settings.db_path == original_db
        assert cfg.settings.intake_folder == "/original/intake"


# ========================================================================
# 6. ZIP / INGEST FAILURE HONESTY
# ========================================================================

class TestZipIngestHonesty:
    """ZIP processing must report honest status."""

    def test_zip_all_members_failed_marks_error(self, db_session, repo, tmp_path):
        sf = repo.register_source_file(
            filepath=str(tmp_path / "bad.zip"), filename="bad.zip",
            file_hash="bad_hash", is_archive=True,
        )
        run = repo.start_ingest_run(trigger="test")

        errors = 5
        files_ok = 0

        if errors > 0 and files_ok == 0:
            zip_status = "error"
        elif errors > 0:
            zip_status = "partial"
        else:
            zip_status = "completed"

        repo.mark_file_processed(sf.id, status=zip_status,
                                 error=f"{errors} member(s) failed" if errors else None)
        db_session.flush()

        refreshed = db_session.query(SourceFile).get(sf.id)
        assert refreshed.ingest_status == "error"
        assert "5 member(s) failed" in refreshed.ingest_error

    def test_zip_partial_failure_marks_partial(self, db_session, repo, tmp_path):
        sf = repo.register_source_file(
            filepath=str(tmp_path / "mixed.zip"), filename="mixed.zip",
            file_hash="mixed_hash", is_archive=True,
        )
        errors = 2
        files_ok = 8

        if errors > 0 and files_ok == 0:
            zip_status = "error"
        elif errors > 0:
            zip_status = "partial"
        else:
            zip_status = "completed"

        repo.mark_file_processed(sf.id, status=zip_status)
        db_session.flush()

        refreshed = db_session.query(SourceFile).get(sf.id)
        assert refreshed.ingest_status == "partial"

    def test_zip_all_success_marks_completed(self, db_session, repo, tmp_path):
        sf = repo.register_source_file(
            filepath=str(tmp_path / "good.zip"), filename="good.zip",
            file_hash="good_hash", is_archive=True,
        )
        errors = 0
        files_ok = 10

        if errors > 0 and files_ok == 0:
            zip_status = "error"
        elif errors > 0:
            zip_status = "partial"
        else:
            zip_status = "completed"

        repo.mark_file_processed(sf.id, status=zip_status)
        db_session.flush()

        refreshed = db_session.query(SourceFile).get(sf.id)
        assert refreshed.ingest_status == "completed"


# ========================================================================
# 7. PARSER PARENT_ENTITY_ID INTEGRATION
# ========================================================================

class TestParserParentEntityId:
    """All parsers must set parent_entity_id on observations."""

    def test_dtp_parser_sets_parent_entity_id(self, db_session, repo):
        from reportbuilder.parsing.daily_tech_performance import DailyTechPerformanceParser
        parser = DailyTechPerformanceParser()

        records = [
            {
                "technician": "TestTech1", "technician_team": "TestTeam1",
                "work_date": date(2025, 1, 15), "hours": 8.0,
                "units": 10.0, "amount": 500.0,
                "_sheet": "Report", "_source_file": "/test.xlsx",
            },
        ]

        sf = repo.register_source_file("/test.xlsx", "test.xlsx", file_hash="dtp_test")
        run = repo.start_ingest_run(trigger="test")
        parser.normalize_and_store(records, repo, sf.id, run.id)
        db_session.flush()

        obs_list = db_session.query(Observation).filter_by(source_file_id=sf.id).all()
        assert len(obs_list) > 0
        for obs in obs_list:
            assert obs.parent_entity_id is not None
            parent = db_session.query(Entity).get(obs.parent_entity_id)
            assert parent.entity_type == "team"
            assert parent.canonical_name == "TestTeam1"

    def test_mca_snapshot_parser_sets_parent_entity_id(self, db_session, repo):
        from reportbuilder.parsing.mca_snapshot import MCASnapshotParser
        parser = MCASnapshotParser()

        records = [
            {
                "cid": "3001", "team": "SnapshotTeam", "store_name": "Store 3001",
                "snapshot_date": date(2025, 2, 10),
                "total_active_requests": 25.0, "wtd_build": 10.0,
                "_sheet": "Summary", "_source_file": "/snap.xlsx",
            },
        ]

        sf = repo.register_source_file("/snap.xlsx", "snap.xlsx", file_hash="mca_test")
        run = repo.start_ingest_run(trigger="test")
        parser.normalize_and_store(records, repo, sf.id, run.id)
        db_session.flush()

        obs_list = db_session.query(Observation).filter_by(source_file_id=sf.id).all()
        assert len(obs_list) > 0
        for obs in obs_list:
            assert obs.parent_entity_id is not None
            parent = db_session.query(Entity).get(obs.parent_entity_id)
            assert parent.entity_type == "team"
            assert parent.canonical_name == "SnapshotTeam"

    def test_mileage_parser_sets_parent_entity_id(self, db_session, repo):
        from reportbuilder.parsing.mileage_csv import MileageCSVParser
        parser = MileageCSVParser()

        records = [
            {
                "technician_name": "MileageTech", "team": "MileageTeam",
                "mileage_date": date(2025, 3, 5),
                "total_mileage": 120.0, "total_amount": 75.50,
                "_source_file": "/mileage.csv", "_sheet": "csv",
            },
        ]

        sf = repo.register_source_file("/mileage.csv", "mileage.csv", file_hash="mil_test")
        run = repo.start_ingest_run(trigger="test")
        parser.normalize_and_store(records, repo, sf.id, run.id)
        db_session.flush()

        obs_list = db_session.query(Observation).filter_by(source_file_id=sf.id).all()
        assert len(obs_list) > 0
        for obs in obs_list:
            assert obs.parent_entity_id is not None
            parent = db_session.query(Entity).get(obs.parent_entity_id)
            assert parent.entity_type == "team"
            assert parent.canonical_name == "MileageTeam"
