"""Tests for AI planner and fallback parser."""

from reportbuilder.ai.planner import (
    DeterministicFallbackParser, ReportPlanner,
)
from reportbuilder.ai.schemas import validate_plan, VALID_TEMPLATES
from reportbuilder.ai.model_manager import ModelManager


class TestDeterministicFallback:

    def test_available(self):
        parser = DeterministicFallbackParser()
        assert parser.is_available()

    def test_efficiency_report(self):
        parser = DeterministicFallbackParser()
        plan = parser.generate_plan("Build me the team efficiency report")
        assert plan["report_template"] == "team_efficiency_tenure_pack"

    def test_pdf_request(self):
        parser = DeterministicFallbackParser()
        plan = parser.generate_plan("Generate an executive summary PDF")
        assert "pdf" in plan["output_formats"]
        assert plan["report_template"] == "executive_infographic_pdf"

    def test_trend_request(self):
        parser = DeterministicFallbackParser()
        plan = parser.generate_plan("Show trends over time for team rankings")
        assert plan["trend_options"]["include_trends"] is True

    def test_snapshot_request(self):
        parser = DeterministicFallbackParser()
        plan = parser.generate_plan("Compare snapshot vs performance data")
        assert plan["report_template"] == "snapshot_vs_performance_pack"

    def test_mileage_metrics(self):
        parser = DeterministicFallbackParser()
        plan = parser.generate_plan("Show me mileage analysis")
        assert "mileage_paid" in plan["metrics"]

    def test_both_formats(self):
        parser = DeterministicFallbackParser()
        plan = parser.generate_plan("Generate excel and pdf report")
        assert "excel" in plan["output_formats"]
        assert "pdf" in plan["output_formats"]


class TestPlanValidation:

    def test_valid_plan(self):
        plan = {
            "intent": "generate_report",
            "report_template": "team_efficiency_tenure_pack",
            "entity_scope": {"type": "all_teams"},
            "output_formats": ["excel"],
        }
        valid, errors = validate_plan(plan)
        assert valid
        assert len(errors) == 0

    def test_invalid_intent(self):
        plan = {"intent": "invalid_thing"}
        valid, errors = validate_plan(plan)
        assert not valid

    def test_invalid_template(self):
        plan = {"intent": "generate_report", "report_template": "nonexistent"}
        valid, errors = validate_plan(plan)
        assert not valid

    def test_invalid_format(self):
        plan = {"intent": "generate_report", "output_formats": ["docx"]}
        valid, errors = validate_plan(plan)
        assert not valid


class TestReportPlanner:

    def test_planner_uses_fallback(self):
        planner = ReportPlanner(model_dir="")
        plan = planner.plan("Build efficiency report")
        assert plan is not None
        assert plan.get("_provider") == "deterministic_fallback"

    def test_active_provider(self):
        planner = ReportPlanner(model_dir="")
        assert planner.active_provider == "deterministic_fallback"


class TestModelManager:

    def test_check_status_no_model(self, tmp_path):
        mm = ModelManager(str(tmp_path / "models"))
        status = mm.check_status()
        assert not status.installed
        assert not status.ready

    def test_create_placeholder(self, tmp_path):
        mm = ModelManager(str(tmp_path / "models"))
        mm.create_placeholder()
        readme = tmp_path / "models" / "README.md"
        assert readme.exists()

    def test_get_model_info_empty(self, tmp_path):
        mm = ModelManager(str(tmp_path / "models"))
        info = mm.get_model_info()
        assert info["installed"] is False
