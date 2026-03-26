"""Hardening tests for config propagation and planner/execution contract.

These tests verify the exact failures identified in the audit:
  A) Setup/config propagation: changing paths actually affects downstream services
  B) Planner/execution contract: unsupported requests are rejected clearly, not silently coerced
  C) Trend execution integrity: trend plans route correctly through entity scopes
"""

import json
from datetime import date
from pathlib import Path

import pytest

from reportbuilder.config import ConfigManager, AppSettings
from reportbuilder.warehouse.models import get_session_factory
from reportbuilder.warehouse.repository import WarehouseRepository
from reportbuilder.reports.registry import (
    ReportPlan, ReportTemplate, TemplateRegistry, CapabilityCheck,
)
from reportbuilder.reports.templates.team_efficiency_tenure import TeamEfficiencyTenureTemplate
from reportbuilder.reports.templates.snapshot_vs_performance import SnapshotVsPerformanceTemplate
from reportbuilder.reports.templates.trend_focus import TrendFocusTemplate
from reportbuilder.reports.templates.executive_pdf import ExecutiveInfographicTemplate
from reportbuilder.ai.planner import DeterministicFallbackParser, ReportPlanner
from reportbuilder.ai.schemas import validate_plan


# ========================================================================
# A) SETUP / CONFIG PROPAGATION
# ========================================================================

class TestConfigPropagation:
    """Verify that changing app_data_dir correctly updates all derived paths."""

    def test_rederive_updates_db_path(self, tmp_path):
        s = AppSettings()
        s.app_data_dir = str(tmp_path / "original")
        s.resolve_paths()
        original_db = s.db_path

        s.app_data_dir = str(tmp_path / "moved")
        s.rederive_from_app_data()

        assert s.db_path != original_db
        assert "moved" in s.db_path
        assert "original" not in s.db_path

    def test_rederive_updates_staging_dir(self, tmp_path):
        s = AppSettings()
        s.app_data_dir = str(tmp_path / "v1")
        s.resolve_paths()

        s.app_data_dir = str(tmp_path / "v2")
        s.rederive_from_app_data()

        assert "v2" in s.staging_dir
        assert "v1" not in s.staging_dir

    def test_rederive_updates_output_dir(self, tmp_path):
        s = AppSettings()
        s.app_data_dir = str(tmp_path / "old")
        s.resolve_paths()

        s.app_data_dir = str(tmp_path / "new")
        s.rederive_from_app_data()

        assert "new" in s.output_dir

    def test_rederive_updates_model_dir(self, tmp_path):
        s = AppSettings()
        s.app_data_dir = str(tmp_path / "before")
        s.resolve_paths()

        s.app_data_dir = str(tmp_path / "after")
        s.rederive_from_app_data()

        assert "after" in s.ai_model_dir

    def test_apply_app_data_change_updates_config_path(self, tmp_path):
        cfg = ConfigManager(str(tmp_path / "settings.json"))
        new_dir = str(tmp_path / "custom_appdata")
        cfg.apply_app_data_change(new_dir)

        assert str(cfg.config_path) == str(Path(new_dir) / "settings.json")

    def test_apply_app_data_change_updates_all_paths(self, tmp_path):
        cfg = ConfigManager(str(tmp_path / "settings.json"))
        new_dir = str(tmp_path / "relocated")
        cfg.apply_app_data_change(new_dir)

        assert "relocated" in cfg.settings.db_path
        assert "relocated" in cfg.settings.staging_dir
        assert "relocated" in cfg.settings.output_dir
        assert "relocated" in cfg.settings.ai_model_dir


class TestConfigPersistence:
    """Verify save/load round-trips preserve all paths correctly."""

    def test_save_after_app_data_change_writes_to_new_location(self, tmp_path):
        cfg = ConfigManager(str(tmp_path / "settings.json"))
        new_dir = str(tmp_path / "newdata")
        cfg.apply_app_data_change(new_dir)
        cfg.settings.setup_complete = True
        cfg.save()

        expected_path = Path(new_dir) / "settings.json"
        assert expected_path.exists()

    def test_load_from_new_location_reads_correct_settings(self, tmp_path):
        new_dir = str(tmp_path / "freshdata")
        Path(new_dir).mkdir(parents=True)

        cfg = ConfigManager(str(tmp_path / "initial.json"))
        cfg.apply_app_data_change(new_dir)
        cfg.settings.intake_folder = "/custom/intake"
        cfg.settings.setup_complete = True
        cfg.save()

        cfg2 = ConfigManager(str(Path(new_dir) / "settings.json"))
        cfg2.load()
        assert cfg2.settings.intake_folder == "/custom/intake"
        assert cfg2.settings.setup_complete is True

    def test_restart_path_uses_latest_settings(self, tmp_path):
        """Simulates app restart: load config from persisted location."""
        cfg_path = str(tmp_path / "settings.json")
        cfg = ConfigManager(cfg_path)
        cfg.settings.intake_folder = "/updated/intake"
        cfg.settings.setup_complete = True
        cfg.save()

        cfg2 = ConfigManager(cfg_path)
        cfg2.load()
        assert cfg2.settings.intake_folder == "/updated/intake"
        assert cfg2.is_setup_complete()


class TestConfigServiceIntegration:
    """Verify that config changes propagate to service construction."""

    def test_db_session_uses_config_db_path(self, tmp_path):
        cfg = ConfigManager(str(tmp_path / "settings.json"))
        cfg.settings.app_data_dir = str(tmp_path / "appdata")
        cfg.settings.rederive_from_app_data()
        cfg.settings.ensure_directories()

        sf = get_session_factory(cfg.settings.db_path)
        session = sf()
        session.close()

        db_file = Path(cfg.settings.db_path)
        assert db_file.exists()

    def test_changed_db_path_creates_new_database(self, tmp_path):
        """Changing app_data -> new db_path -> new database file."""
        cfg = ConfigManager(str(tmp_path / "settings.json"))
        cfg.settings.app_data_dir = str(tmp_path / "loc1")
        cfg.settings.rederive_from_app_data()
        cfg.settings.ensure_directories()
        sf1 = get_session_factory(cfg.settings.db_path)
        s1 = sf1()
        s1.close()
        db1 = Path(cfg.settings.db_path)

        cfg.apply_app_data_change(str(tmp_path / "loc2"))
        cfg.settings.ensure_directories()
        sf2 = get_session_factory(cfg.settings.db_path)
        s2 = sf2()
        s2.close()
        db2 = Path(cfg.settings.db_path)

        assert db1 != db2
        assert db1.exists()
        assert db2.exists()

    def test_incomplete_setup_flag(self, tmp_path):
        cfg = ConfigManager(str(tmp_path / "settings.json"))
        assert not cfg.is_setup_complete()
        cfg.settings.setup_complete = True
        cfg.save()

        cfg2 = ConfigManager(str(tmp_path / "settings.json"))
        cfg2.load()
        assert cfg2.is_setup_complete()


# ========================================================================
# B) PLANNER / EXECUTION CONTRACT
# ========================================================================

def _full_registry() -> TemplateRegistry:
    """Build a registry with all production templates registered."""
    reg = TemplateRegistry()
    reg.register(TeamEfficiencyTenureTemplate())
    reg.register(SnapshotVsPerformanceTemplate())
    reg.register(TrendFocusTemplate())
    reg.register(ExecutiveInfographicTemplate())
    return reg


class TestCapabilityValidation:
    """The core contract: plans that can't execute must be rejected, not silently coerced."""

    def test_valid_team_efficiency_plan(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            entity_scope={"type": "all_teams"},
            output_formats=["excel"],
        )
        check = reg.validate_plan(plan)
        assert check.supported
        assert not check.errors

    def test_unknown_template_rejected(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="fictional_report_pack",
            output_formats=["excel"],
        )
        check = reg.validate_plan(plan)
        assert not check.supported
        assert any("not available" in e for e in check.errors)
        assert check.suggestions

    def test_unsupported_entity_scope_rejected(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            entity_scope={"type": "cid"},
            output_formats=["excel"],
        )
        check = reg.validate_plan(plan)
        assert not check.supported
        assert any("cid" in e for e in check.errors)

    def test_unsupported_entity_scope_suggests_alternatives(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            entity_scope={"type": "cid"},
            output_formats=["excel"],
        )
        check = reg.validate_plan(plan)
        assert check.suggestions

    def test_unsupported_output_format_rejected(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            entity_scope={"type": "all_teams"},
            output_formats=["pdf"],
        )
        check = reg.validate_plan(plan)
        assert not check.supported

    def test_trend_warning_on_non_trend_template(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            entity_scope={"type": "all_teams"},
            output_formats=["excel"],
            trend_options={"include_trends": True},
        )
        check = reg.validate_plan(plan)
        assert check.supported  # warning, not error
        assert check.warnings

    def test_trend_focus_accepts_trends(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="trend_focus_pack",
            entity_scope={"type": "team"},
            output_formats=["excel"],
            trend_options={"include_trends": True},
        )
        check = reg.validate_plan(plan)
        assert check.supported
        assert not check.warnings

    def test_execute_rejects_unsupported_plan(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="fictional_pack",
            output_formats=["excel"],
        )
        with pytest.raises(ValueError, match="Cannot execute"):
            reg.execute_plan(plan, None, "/tmp")

    def test_not_silently_coerced_to_team_report(self):
        """Key contract: a CID request to team-only template must fail, not silently produce teams."""
        reg = _full_registry()
        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            entity_scope={"type": "cid"},
            output_formats=["excel"],
        )
        with pytest.raises(ValueError):
            reg.execute_plan(plan, None, "/tmp")


class TestPlannerExecutionContract:
    """Planner output must be compatible with execution layer."""

    def test_deterministic_efficiency_plan_is_executable(self):
        reg = _full_registry()
        parser = DeterministicFallbackParser()
        plan_dict = parser.generate_plan("Build team efficiency report")
        plan = ReportPlan.from_dict(plan_dict)
        check = reg.validate_plan(plan)
        assert check.supported, f"Plan should be valid: {check.message}"

    def test_deterministic_trend_plan_is_executable(self):
        reg = _full_registry()
        parser = DeterministicFallbackParser()
        plan_dict = parser.generate_plan("Show me trends over time report pack")
        plan = ReportPlan.from_dict(plan_dict)
        check = reg.validate_plan(plan)
        assert check.supported, f"Plan should be valid: {check.message}"

    def test_deterministic_snapshot_plan_is_executable(self):
        reg = _full_registry()
        parser = DeterministicFallbackParser()
        plan_dict = parser.generate_plan("Compare snapshot vs performance")
        plan = ReportPlan.from_dict(plan_dict)
        check = reg.validate_plan(plan)
        assert check.supported, f"Plan should be valid: {check.message}"

    def test_deterministic_pdf_plan_is_executable(self):
        reg = _full_registry()
        parser = DeterministicFallbackParser()
        plan_dict = parser.generate_plan("Generate executive summary PDF")
        plan = ReportPlan.from_dict(plan_dict)
        check = reg.validate_plan(plan)
        assert check.supported, f"Plan should be valid: {check.message}"

    def test_cid_trend_plan_is_executable(self):
        """CID-level trend analysis should be supported by trend_focus_pack."""
        reg = _full_registry()
        plan = ReportPlan(
            report_template="trend_focus_pack",
            entity_scope={"type": "cid"},
            output_formats=["excel"],
            trend_options={"include_trends": True},
        )
        check = reg.validate_plan(plan)
        assert check.supported

    def test_technician_trend_plan_is_executable(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="trend_focus_pack",
            entity_scope={"type": "technician"},
            output_formats=["excel"],
            trend_options={"include_trends": True},
        )
        check = reg.validate_plan(plan)
        assert check.supported


class TestRegistryListCapabilities:
    """Registry must honestly advertise what it supports."""

    def test_list_includes_all_templates(self):
        reg = _full_registry()
        templates = reg.list_templates()
        names = {t["name"] for t in templates}
        assert "team_efficiency_tenure_pack" in names
        assert "snapshot_vs_performance_pack" in names
        assert "trend_focus_pack" in names
        assert "executive_infographic_pdf" in names

    def test_list_includes_entity_scopes(self):
        reg = _full_registry()
        templates = reg.list_templates()
        trend_tmpl = next(t for t in templates if t["name"] == "trend_focus_pack")
        assert "team" in trend_tmpl["entity_scopes"]
        assert "cid" in trend_tmpl["entity_scopes"]

    def test_list_includes_trend_support(self):
        reg = _full_registry()
        templates = reg.list_templates()
        trend_tmpl = next(t for t in templates if t["name"] == "trend_focus_pack")
        assert trend_tmpl["supports_trends"] is True

        team_tmpl = next(t for t in templates if t["name"] == "team_efficiency_tenure_pack")
        assert team_tmpl["supports_trends"] is False


# ========================================================================
# C) TREND EXECUTION INTEGRITY
# ========================================================================

class TestTrendFocusEntityScope:
    """TrendFocusTemplate must respect entity_scope from plan, not hardcode 'team'."""

    def test_resolve_entity_type_team(self):
        tmpl = TrendFocusTemplate()
        plan = ReportPlan(entity_scope={"type": "team"})
        assert tmpl._resolve_entity_type(plan) == "team"

    def test_resolve_entity_type_all_teams(self):
        tmpl = TrendFocusTemplate()
        plan = ReportPlan(entity_scope={"type": "all_teams"})
        assert tmpl._resolve_entity_type(plan) == "team"

    def test_resolve_entity_type_cid(self):
        tmpl = TrendFocusTemplate()
        plan = ReportPlan(entity_scope={"type": "cid"})
        assert tmpl._resolve_entity_type(plan) == "cid"

    def test_resolve_entity_type_technician(self):
        tmpl = TrendFocusTemplate()
        plan = ReportPlan(entity_scope={"type": "technician"})
        assert tmpl._resolve_entity_type(plan) == "technician"

    def test_resolve_entity_type_rvp(self):
        tmpl = TrendFocusTemplate()
        plan = ReportPlan(entity_scope={"type": "rvp"})
        assert tmpl._resolve_entity_type(plan) == "rvp"

    def test_trend_focus_generates_with_cid_scope(self, db_session, repo, tmp_path):
        """End-to-end: TrendFocusTemplate generates a file when scoped to CID."""
        family = repo.get_or_create_family("daily_tech_performance")
        metric = repo.get_or_create_metric("gross_revenue")
        for i in range(3):
            cid = repo.get_or_create_entity("cid", f"CID_{i}")
            for month in [10, 11, 12]:
                start = date(2025, month, 1)
                end = date(2025, month, 28)
                period = repo.get_or_create_period("month", start, end, f"2025-{month:02d}")
                repo.add_observation(cid.id, period.id, metric.id, value=1000.0 * (i + 1),
                                    report_family_id=family.id)
        db_session.commit()

        tmpl = TrendFocusTemplate()
        plan = ReportPlan(
            report_template="trend_focus_pack",
            entity_scope={"type": "cid"},
            period_start=date(2025, 10, 1),
            period_end=date(2025, 12, 31),
            output_formats=["excel"],
            metrics=["gross_revenue"],
        )
        outputs = tmpl.generate(plan, db_session, str(tmp_path))
        assert len(outputs) == 1
        assert Path(outputs[0]).exists()
        assert "cid" in Path(outputs[0]).name

    def test_trend_focus_generates_with_team_scope_via_aggregation(self, db_session, repo, tmp_path):
        """Team trends work via parent_entity_id aggregation from technician observations."""
        family = repo.get_or_create_family("daily_tech_performance")
        metric = repo.get_or_create_metric("gross_revenue")
        for i in range(3):
            team = repo.get_or_create_entity("team", f"Team_{i}")
            for j in range(2):
                tech = repo.get_or_create_entity("technician", f"Tech_{i}_{j}")
                tech.parent_id = team.id
                for month in [10, 11, 12]:
                    start = date(2025, month, 1)
                    end = date(2025, month, 28)
                    period = repo.get_or_create_period("month", start, end, f"2025-{month:02d}")
                    repo.add_observation(tech.id, period.id, metric.id,
                                        value=2500.0 * (i + 1),
                                        parent_entity_id=team.id,
                                        report_family_id=family.id)
        db_session.commit()

        tmpl = TrendFocusTemplate()
        plan = ReportPlan(
            report_template="trend_focus_pack",
            entity_scope={"type": "team"},
            period_start=date(2025, 10, 1),
            period_end=date(2025, 12, 31),
            output_formats=["excel"],
            metrics=["gross_revenue"],
        )
        outputs = tmpl.generate(plan, db_session, str(tmp_path))
        assert len(outputs) == 1
        assert Path(outputs[0]).exists()
        assert "team" in Path(outputs[0]).name


class TestTrendValidationCombinations:
    """Invalid trend/entity/template combinations must fail clearly."""

    def test_trend_request_on_pdf_only_template(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="executive_infographic_pdf",
            entity_scope={"type": "all_teams"},
            output_formats=["pdf"],
            trend_options={"include_trends": True},
        )
        check = reg.validate_plan(plan)
        assert check.supported  # warning not error (PDF still runs, just no trends)
        assert check.warnings

    def test_unsupported_entity_type_for_template(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="executive_infographic_pdf",
            entity_scope={"type": "cid"},
            output_formats=["pdf"],
        )
        check = reg.validate_plan(plan)
        assert not check.supported

    def test_snapshot_accepts_cid_scope(self):
        """SnapshotVsPerformance supports CID (store number) scoped comparison."""
        reg = _full_registry()
        plan = ReportPlan(
            report_template="snapshot_vs_performance_pack",
            entity_scope={"type": "cid"},
            output_formats=["excel"],
        )
        check = reg.validate_plan(plan)
        assert check.supported


class TestCapabilityCheckMessage:
    """CapabilityCheck.message surfaces clear user-facing information."""

    def test_supported_plan_message(self):
        check = CapabilityCheck(supported=True)
        assert "executable" in check.message.lower()

    def test_unsupported_plan_message_includes_errors(self):
        check = CapabilityCheck(supported=False, errors=["Template not found"])
        assert "Template not found" in check.message

    def test_message_includes_suggestions(self):
        check = CapabilityCheck(
            supported=False,
            errors=["Scope not supported"],
            suggestions=["Try trend_focus_pack"],
        )
        assert "Try" in check.message
        assert "trend_focus_pack" in check.message


# ========================================================================
# D) BLOCKER FIX VERIFICATION TESTS
# ========================================================================

from reportbuilder.config import (
    _pointer_file_path, _read_settings_pointer, _write_settings_pointer,
)
from reportbuilder.warehouse.models import OutputArtifact


class TestRestartSettingsDiscovery:
    """CRITICAL: Settings must survive restart when app_data_dir is changed."""

    def test_pointer_file_written_on_save(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "reportbuilder.config._default_app_data_dir",
            lambda: tmp_path / "default",
        )
        cfg = ConfigManager()
        cfg.settings.setup_complete = True
        cfg.save()

        pf = tmp_path / "default" / "settings_pointer.json"
        assert pf.exists()
        import json
        data = json.loads(pf.read_text())
        assert "settings_path" in data
        assert Path(data["settings_path"]).exists()

    def test_pointer_file_updated_on_app_data_change(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "reportbuilder.config._default_app_data_dir",
            lambda: tmp_path / "default",
        )
        cfg = ConfigManager()
        custom = str(tmp_path / "custom_location")
        cfg.apply_app_data_change(custom)
        cfg.settings.setup_complete = True
        cfg.save()

        pf = tmp_path / "default" / "settings_pointer.json"
        assert pf.exists()
        import json
        data = json.loads(pf.read_text())
        assert custom in data["settings_path"]

    def test_restart_discovers_custom_settings(self, tmp_path, monkeypatch):
        """The core restart contract: change app_data → save → new ConfigManager() finds it."""
        monkeypatch.setattr(
            "reportbuilder.config._default_app_data_dir",
            lambda: tmp_path / "default",
        )
        custom = str(tmp_path / "custom")
        cfg1 = ConfigManager()
        cfg1.apply_app_data_change(custom)
        cfg1.settings.intake_folder = "/my/special/intake"
        cfg1.settings.setup_complete = True
        cfg1.settings.ensure_directories()
        cfg1.save()

        cfg2 = ConfigManager()
        cfg2.load()
        assert cfg2.is_setup_complete()
        assert cfg2.settings.intake_folder == "/my/special/intake"
        assert custom in cfg2.settings.db_path

    def test_restart_after_multiple_relocations(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "reportbuilder.config._default_app_data_dir",
            lambda: tmp_path / "default",
        )
        cfg = ConfigManager()
        for i in range(3):
            loc = str(tmp_path / f"loc_{i}")
            cfg.apply_app_data_change(loc)
            cfg.settings.ensure_directories()
            cfg.save()

        final_loc = str(tmp_path / "loc_2")
        cfg2 = ConfigManager()
        cfg2.load()
        assert final_loc in cfg2.settings.db_path
        assert final_loc in cfg2.settings.staging_dir

    def test_missing_pointer_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "reportbuilder.config._default_app_data_dir",
            lambda: tmp_path / "default",
        )
        cfg = ConfigManager()
        assert not cfg.is_setup_complete()
        expected_default = str(tmp_path / "default" / "settings.json")
        assert str(cfg.config_path) == expected_default

    def test_corrupt_pointer_falls_back_safely(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "reportbuilder.config._default_app_data_dir",
            lambda: tmp_path / "default",
        )
        pf = tmp_path / "default" / "settings_pointer.json"
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text("not valid json {{{")

        cfg = ConfigManager()
        assert str(cfg.config_path) == str(tmp_path / "default" / "settings.json")

    def test_pointer_to_deleted_file_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "reportbuilder.config._default_app_data_dir",
            lambda: tmp_path / "default",
        )
        pf = tmp_path / "default" / "settings_pointer.json"
        pf.parent.mkdir(parents=True, exist_ok=True)
        import json
        pf.write_text(json.dumps({"settings_path": "/nonexistent/settings.json"}))

        cfg = ConfigManager()
        assert str(cfg.config_path) == str(tmp_path / "default" / "settings.json")


class TestSnapshotCIDSupport:
    """CID (store number) is a first-class entity in both MCA Snapshot and DTP.
    The snapshot template must generate correct CID-scoped output."""

    def test_snapshot_declares_cid_support(self):
        tmpl = SnapshotVsPerformanceTemplate()
        assert "cid" in tmpl.supported_entity_scopes

    def test_cid_request_to_snapshot_validates(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="snapshot_vs_performance_pack",
            entity_scope={"type": "cid"},
            output_formats=["excel"],
        )
        check = reg.validate_plan(plan)
        assert check.supported

    def test_snapshot_generates_cid_scoped_output(self, db_session, repo, tmp_path):
        """End-to-end: CID-scoped snapshot comparison uses CID entities, not teams."""
        snap_fam = repo.get_or_create_family("mca_snapshot")
        perf_fam = repo.get_or_create_family("daily_tech_performance")
        metric_a = repo.get_or_create_metric("total_active_requests")
        metric_b = repo.get_or_create_metric("hours")
        period = repo.get_or_create_period("month", date(2025, 11, 1), date(2025, 11, 30))

        for store_num in ["1001", "1002", "1003"]:
            cid = repo.get_or_create_entity("cid", store_num)
            repo.add_observation(cid.id, period.id, metric_a.id, value=50.0,
                                report_family_id=snap_fam.id)
        for store_num in ["1002", "1003", "1004"]:
            cid = repo.get_or_create_entity("cid", store_num)
            repo.add_observation(cid.id, period.id, metric_b.id, value=160.0,
                                report_family_id=perf_fam.id)
        db_session.commit()

        tmpl = SnapshotVsPerformanceTemplate()
        plan = ReportPlan(
            report_template="snapshot_vs_performance_pack",
            entity_scope={"type": "cid"},
            period_start=date(2025, 11, 1),
            period_end=date(2025, 11, 30),
            output_formats=["excel"],
        )
        outputs = tmpl.generate(plan, db_session, str(tmp_path))
        assert len(outputs) == 1
        filepath = outputs[0]
        assert Path(filepath).exists()
        assert "cid" in Path(filepath).name

    def test_snapshot_only_supports_cid_scope(self):
        """Template now honestly only supports CID scope, not team."""
        tmpl = SnapshotVsPerformanceTemplate()
        assert tmpl.supported_entity_scopes == ["cid"]

    def test_snapshot_team_scope_rejected(self):
        """Team scope is no longer supported — must be rejected by validation."""
        reg = _full_registry()
        plan = ReportPlan(
            report_template="snapshot_vs_performance_pack",
            entity_scope={"type": "team"},
            output_formats=["excel"],
        )
        check = reg.validate_plan(plan)
        assert not check.supported


class TestArtifactRecording:
    """Generated reports must be recorded as OutputArtifacts."""

    def test_execute_plan_records_artifact(self, db_session, repo, tmp_path):
        family = repo.get_or_create_family("daily_tech_performance")
        metric = repo.get_or_create_metric("gross_revenue")
        for i in range(3):
            team = repo.get_or_create_entity("team", f"TestTeam_{i}")
            tech = repo.get_or_create_entity("technician", f"Tech_art_{i}")
            tech.parent_id = team.id
            period = repo.get_or_create_period(
                "month", date(2025, 11, 1), date(2025, 11, 30), "2025-11"
            )
            repo.add_observation(tech.id, period.id, metric.id, value=10000.0 * (i + 1),
                                parent_entity_id=team.id,
                                report_family_id=family.id)
        db_session.commit()

        reg = _full_registry()
        plan = ReportPlan(
            report_template="trend_focus_pack",
            entity_scope={"type": "team"},
            period_start=date(2025, 11, 1),
            period_end=date(2025, 11, 30),
            output_formats=["excel"],
            metrics=["gross_revenue"],
        )
        outputs = reg.execute_plan(plan, db_session, str(tmp_path))
        assert len(outputs) == 1
        assert Path(outputs[0]).exists()

        artifacts = db_session.query(OutputArtifact).all()
        assert len(artifacts) == 1
        assert artifacts[0].template_name == "trend_focus_pack"
        assert artifacts[0].artifact_type == "xlsx"
        assert Path(artifacts[0].filepath).exists()

    def test_artifact_contains_plan_json(self, db_session, repo, tmp_path):
        family = repo.get_or_create_family("daily_tech_performance")
        metric = repo.get_or_create_metric("gross_revenue")
        team = repo.get_or_create_entity("team", "ArtTeam")
        tech = repo.get_or_create_entity("technician", "ArtTech")
        tech.parent_id = team.id
        period = repo.get_or_create_period(
            "month", date(2025, 10, 1), date(2025, 10, 31), "2025-10"
        )
        repo.add_observation(tech.id, period.id, metric.id, value=5000.0,
                            parent_entity_id=team.id,
                            report_family_id=family.id)
        db_session.commit()

        reg = _full_registry()
        plan = ReportPlan(
            report_template="trend_focus_pack",
            entity_scope={"type": "team"},
            period_start=date(2025, 10, 1),
            period_end=date(2025, 10, 31),
            output_formats=["excel"],
        )
        reg.execute_plan(plan, db_session, str(tmp_path))
        art = db_session.query(OutputArtifact).first()
        assert art.report_plan is not None
        plan_data = json.loads(art.report_plan)
        assert plan_data["report_template"] == "trend_focus_pack"


class TestPlannerTrendRouting:
    """Planner must route trend requests to trend-capable templates."""

    def test_trend_keywords_route_to_trend_template(self):
        parser = DeterministicFallbackParser()
        for query in [
            "show me trends",
            "trends over time",
            "revenue movement",
            "trajectory analysis",
        ]:
            plan = parser.generate_plan(query)
            assert plan["report_template"] == "trend_focus_pack", \
                f"'{query}' should route to trend_focus_pack, got {plan['report_template']}"

    def test_trend_with_technician_routes_correctly(self):
        parser = DeterministicFallbackParser()
        plan = parser.generate_plan("technician trends over time")
        assert plan["report_template"] == "trend_focus_pack"
        assert plan["entity_scope"]["type"] == "technician"
        assert plan["trend_options"]["include_trends"] is True

    def test_trend_with_cid_routes_correctly(self):
        parser = DeterministicFallbackParser()
        plan = parser.generate_plan("show CID trends over time")
        assert plan["report_template"] == "trend_focus_pack"
        assert plan["entity_scope"]["type"] == "cid"

    def test_efficiency_without_trend_stays_on_efficiency(self):
        parser = DeterministicFallbackParser()
        plan = parser.generate_plan("team efficiency ranking")
        assert plan["report_template"] == "team_efficiency_tenure_pack"
        assert plan["trend_options"].get("include_trends") is False

    def test_all_planner_outputs_validate(self):
        """Every plan the deterministic parser produces must pass validation."""
        reg = _full_registry()
        parser = DeterministicFallbackParser()
        queries = [
            "team efficiency report",
            "show me trends over time",
            "CID trend report",
            "technician trend workbook",
            "executive summary PDF",
            "compare snapshot vs performance",
            "revenue trends",
            "mileage analysis",
        ]
        for query in queries:
            plan_dict = parser.generate_plan(query)
            plan = ReportPlan.from_dict(plan_dict)
            check = reg.validate_plan(plan)
            assert check.supported, \
                f"'{query}' produced invalid plan: {check.message}"


class TestResolvePeriod:
    """Templates must use warehouse data range instead of hardcoded dates."""

    def test_explicit_dates_pass_through(self, db_session):
        start = date(2025, 6, 1)
        end = date(2025, 6, 30)
        result = ReportTemplate.resolve_period(db_session, start, end)
        assert result == (start, end)

    def test_none_dates_query_warehouse(self, db_session, repo):
        repo.get_or_create_period("month", date(2025, 1, 1), date(2025, 1, 31))
        repo.get_or_create_period("month", date(2025, 6, 1), date(2025, 6, 30))
        db_session.commit()

        start, end = ReportTemplate.resolve_period(db_session, None, None)
        assert start == date(2025, 1, 1)
        assert end == date(2025, 6, 30)

    def test_empty_warehouse_falls_back_to_recent(self, db_session):
        start, end = ReportTemplate.resolve_period(db_session, None, None)
        from datetime import timedelta
        today = date.today()
        assert end == today
        assert start == today - timedelta(days=90)


class TestNoSilentCoercion:
    """End-to-end: any request that cannot be fulfilled must fail, never produce wrong data."""

    def test_cid_to_team_only_template_fails(self):
        reg = _full_registry()
        for tmpl_name in ["team_efficiency_tenure_pack", "executive_infographic_pdf"]:
            plan = ReportPlan(
                report_template=tmpl_name,
                entity_scope={"type": "cid"},
                output_formats=["excel"] if "pack" in tmpl_name else ["pdf"],
            )
            with pytest.raises(ValueError, match="Cannot execute"):
                reg.execute_plan(plan, None, "/tmp")

    def test_technician_to_team_only_template_fails(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            entity_scope={"type": "technician"},
            output_formats=["excel"],
        )
        with pytest.raises(ValueError, match="Cannot execute"):
            reg.execute_plan(plan, None, "/tmp")

    def test_pdf_format_on_excel_only_template_fails(self):
        reg = _full_registry()
        plan = ReportPlan(
            report_template="trend_focus_pack",
            entity_scope={"type": "team"},
            output_formats=["pdf"],
        )
        with pytest.raises(ValueError, match="Cannot execute"):
            reg.execute_plan(plan, None, "/tmp")
