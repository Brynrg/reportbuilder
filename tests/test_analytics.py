"""Tests for analytics engine: rollups, rankings, diagnostics, trends."""

from datetime import date
import pytest

from reportbuilder.analytics.engine import (
    AnalyticsEngine, TechRecord, TeamRollup, compute_diagnosis, TrendEngine,
)
from reportbuilder.warehouse.repository import WarehouseRepository


class TestTechRecord:

    def test_net_revenue(self):
        tr = TechRecord("A", "T1", hours=100, gross_revenue=5000, mileage_paid=200)
        assert tr.net_revenue == 4800

    def test_gross_dph(self):
        tr = TechRecord("A", "T1", hours=100, gross_revenue=5000)
        assert tr.gross_dph == 50.0

    def test_net_dph(self):
        tr = TechRecord("A", "T1", hours=100, gross_revenue=5000, mileage_paid=500)
        assert tr.net_dph == 45.0

    def test_tenure_core(self):
        tr = TechRecord("A", "T1", days_worked=65)
        assert tr.tenure_category == "Core (60+ days)"

    def test_tenure_reliable(self):
        tr = TechRecord("A", "T1", days_worked=45)
        assert tr.tenure_category == "Reliable (40-59 days)"

    def test_tenure_parttime(self):
        tr = TechRecord("A", "T1", days_worked=25)
        assert tr.tenure_category == "Part-Time (20-39 days)"

    def test_tenure_sporadic(self):
        tr = TechRecord("A", "T1", days_worked=10)
        assert tr.tenure_category == "New/Sporadic (<20 days)"


class TestTeamRollup:

    def _make_rollup(self) -> TeamRollup:
        techs = [
            TechRecord("A", "Team1", hours=500, units=100, gross_revenue=25000,
                       mileage_paid=200, total_miles=1000, days_worked=65),
            TechRecord("B", "Team1", hours=300, units=60, gross_revenue=12000,
                       mileage_paid=100, total_miles=500, days_worked=45),
            TechRecord("C", "Team1", hours=100, units=20, gross_revenue=3000,
                       mileage_paid=50, total_miles=200, days_worked=15),
        ]
        return TeamRollup("Team1", techs)

    def test_total_techs(self):
        r = self._make_rollup()
        assert r.total_techs == 3

    def test_total_hours(self):
        r = self._make_rollup()
        assert r.total_hours == 900

    def test_gross_revenue(self):
        r = self._make_rollup()
        assert r.gross_revenue == 40000

    def test_gross_dph(self):
        r = self._make_rollup()
        assert abs(r.gross_dph - 40000 / 900) < 0.01

    def test_net_revenue(self):
        r = self._make_rollup()
        assert r.net_revenue == 40000 - 350

    def test_mileage_cost_pct(self):
        r = self._make_rollup()
        assert abs(r.mileage_cost_pct - 350 / 40000 * 100) < 0.01

    def test_core_techs(self):
        r = self._make_rollup()
        assert r.core_techs == 1

    def test_reliable_techs(self):
        r = self._make_rollup()
        assert r.reliable_techs == 1

    def test_sporadic_techs(self):
        r = self._make_rollup()
        assert r.sporadic_techs == 1

    def test_core_tech_pct(self):
        r = self._make_rollup()
        assert abs(r.core_tech_pct - 1 / 3 * 100) < 0.1


class TestDiagnosis:

    def test_low_volume(self):
        r = TeamRollup("T", [TechRecord("A", "T", hours=500)])
        r.gross_rank = 10
        r.tenure_rank = 10
        assert "Low Volume" in compute_diagnosis(r)

    def test_balanced(self):
        r = TeamRollup("T", [TechRecord("A", "T", hours=2000)])
        r.gross_rank = 5
        r.tenure_rank = 5
        assert "Balanced" in compute_diagnosis(r)

    def test_slow_techs(self):
        r = TeamRollup("T", [TechRecord("A", "T", hours=2000)])
        r.gross_rank = 50
        r.tenure_rank = 10
        assert "Slow Techs" in compute_diagnosis(r)

    def test_high_turnover(self):
        r = TeamRollup("T", [TechRecord("A", "T", hours=2000)])
        r.gross_rank = 5
        r.tenure_rank = 50
        assert "High Turnover" in compute_diagnosis(r)

    def test_needs_help(self):
        r = TeamRollup("T", [TechRecord("A", "T", hours=2000)])
        r.gross_rank = 55
        r.tenure_rank = 55
        assert "Needs Help" in compute_diagnosis(r)

    def test_middle_tier(self):
        r = TeamRollup("T", [TechRecord("A", "T", hours=2000)])
        r.gross_rank = 30
        r.tenure_rank = 25
        assert "Middle Tier" in compute_diagnosis(r)


class TestAnalyticsEngine:

    def _seed_data(self, repo):
        family = repo.get_or_create_family("daily_tech_performance")
        hours_m = repo.get_or_create_metric("hours", "Hours")
        units_m = repo.get_or_create_metric("units", "Units")
        rev_m = repo.get_or_create_metric("gross_revenue", "Revenue")

        team = repo.get_or_create_entity("team", "Alpha Team")

        for day in range(1, 4):
            d = date(2025, 10, day)
            period = repo.get_or_create_period("day", d, d, d.isoformat())
            tech = repo.get_or_create_entity("technician", f"Tech_{day}")
            tech.parent_id = team.id

            repo.add_observation(tech.id, period.id, hours_m.id, value=8.0,
                               parent_entity_id=team.id,
                               report_family_id=family.id)
            repo.add_observation(tech.id, period.id, units_m.id, value=10,
                               parent_entity_id=team.id,
                               report_family_id=family.id)
            repo.add_observation(tech.id, period.id, rev_m.id, value=400.0,
                               parent_entity_id=team.id,
                               report_family_id=family.id)
        repo.session.commit()

    def test_build_team_rollups(self, db_session, repo):
        self._seed_data(repo)
        engine = AnalyticsEngine(db_session)
        rollups = engine.build_team_rollups(date(2025, 10, 1), date(2025, 10, 31))
        assert len(rollups) >= 1
        alpha = [r for r in rollups if r.team_name == "Alpha Team"]
        assert len(alpha) == 1
        assert alpha[0].total_hours == 24.0
        assert alpha[0].gross_revenue == 1200.0

    def test_territory_averages(self, db_session, repo):
        self._seed_data(repo)
        engine = AnalyticsEngine(db_session)
        rollups = engine.build_team_rollups(date(2025, 10, 1), date(2025, 10, 31))
        avgs = engine.compute_territory_averages(rollups)
        assert avgs["total_hours"] == 24.0
        assert avgs["total_revenue"] == 1200.0
        assert abs(avgs["avg_gross_dph"] - 50.0) < 0.01

    def test_diagnostic_groups(self, db_session, repo):
        self._seed_data(repo)
        engine = AnalyticsEngine(db_session)
        rollups = engine.build_team_rollups(date(2025, 10, 1), date(2025, 10, 31))
        groups = engine.build_diagnostic_groups(rollups)
        assert isinstance(groups, dict)

    def test_tech_detail(self, db_session, repo):
        self._seed_data(repo)
        engine = AnalyticsEngine(db_session)
        rollups = engine.build_team_rollups(date(2025, 10, 1), date(2025, 10, 31))
        details = engine.build_tech_detail_list(rollups)
        assert len(details) >= 3
