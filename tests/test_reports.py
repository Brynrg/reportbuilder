"""Tests for report generation and templates."""

from datetime import date
from pathlib import Path

import pytest

from reportbuilder.reports.registry import ReportPlan, TemplateRegistry
from reportbuilder.reports.templates.team_efficiency_tenure import TeamEfficiencyTenureTemplate
from reportbuilder.analytics.engine import AnalyticsEngine, TeamRollup, TechRecord


class TestReportPlan:

    def test_to_dict_roundtrip(self):
        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            period_start=date(2025, 10, 1),
            period_end=date(2025, 12, 30),
        )
        d = plan.to_dict()
        assert d["report_template"] == "team_efficiency_tenure_pack"

        plan2 = ReportPlan.from_dict(d)
        assert plan2.report_template == "team_efficiency_tenure_pack"
        assert plan2.period_start == date(2025, 10, 1)

    def test_to_json(self):
        plan = ReportPlan(report_template="test")
        j = plan.to_json()
        assert "test" in j


class TestTemplateRegistry:

    def test_register_and_get(self):
        reg = TemplateRegistry()
        template = TeamEfficiencyTenureTemplate()
        reg.register(template)
        assert reg.get("team_efficiency_tenure_pack") is not None

    def test_list_templates(self):
        reg = TemplateRegistry()
        reg.register(TeamEfficiencyTenureTemplate())
        templates = reg.list_templates()
        assert len(templates) == 1
        assert templates[0]["name"] == "team_efficiency_tenure_pack"

    def test_unknown_template(self):
        reg = TemplateRegistry()
        with pytest.raises(ValueError):
            reg.execute_plan(
                ReportPlan(report_template="nonexistent"),
                None, "/tmp"
            )


class TestTeamEfficiencyTemplate:

    def _seed_and_build(self, repo, session):
        family = repo.get_or_create_family("daily_tech_performance")
        hours_m = repo.get_or_create_metric("hours")
        units_m = repo.get_or_create_metric("units")
        rev_m = repo.get_or_create_metric("gross_revenue")

        for team_name in ["Team Alpha", "Team Beta"]:
            team = repo.get_or_create_entity("team", team_name)
            for i in range(5):
                for day in range(1, 11):
                    d = date(2025, 10, day)
                    period = repo.get_or_create_period("day", d, d, d.isoformat())
                    tech = repo.get_or_create_entity("technician", f"{team_name}_Tech{i}")
                    tech.parent_id = team.id
                    repo.add_observation(tech.id, period.id, hours_m.id, value=8.0,
                                        report_family_id=family.id)
                    repo.add_observation(tech.id, period.id, units_m.id, value=10,
                                        report_family_id=family.id)
                    repo.add_observation(tech.id, period.id, rev_m.id, value=400.0,
                                        report_family_id=family.id)
        session.commit()

    def test_generate_excel(self, db_session, repo, tmp_path):
        self._seed_and_build(repo, db_session)

        template = TeamEfficiencyTenureTemplate()
        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            period_start=date(2025, 10, 1),
            period_end=date(2025, 10, 31),
            output_formats=["excel"],
        )

        outputs = template.generate(plan, db_session, str(tmp_path))
        assert len(outputs) == 1
        assert Path(outputs[0]).exists()
        assert outputs[0].endswith(".xlsx")

    def test_workbook_has_expected_sheets(self, db_session, repo, tmp_path):
        self._seed_and_build(repo, db_session)

        template = TeamEfficiencyTenureTemplate()
        plan = ReportPlan(
            report_template="team_efficiency_tenure_pack",
            period_start=date(2025, 10, 1),
            period_end=date(2025, 10, 31),
            output_formats=["excel"],
        )
        outputs = template.generate(plan, db_session, str(tmp_path))

        import openpyxl
        wb = openpyxl.load_workbook(outputs[0])
        sheets = wb.sheetnames
        assert "Ranked by Gross Efficiency" in sheets
        assert "Ranked by Net Efficiency" in sheets
        assert "Ranked by Tenure" in sheets
        assert "Diagnostic Summary" in sheets
        assert "Individual Tech Detail" in sheets
        assert "Mileage Analysis" in sheets
        assert "Legend" in sheets
        wb.close()
