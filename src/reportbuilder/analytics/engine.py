"""Core analytics engine: builds team-level rollups, rankings, diagnostics, and trends.

This module performs all deterministic calculations against the warehouse.
The AI planner only creates report plans; this module executes them.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, and_, text
from sqlalchemy.orm import Session

from ..warehouse.models import (
    Entity, Observation, Metric, Period, ReportFamily, TrendSummary,
)

logger = logging.getLogger(__name__)


@dataclass
class TechRecord:
    name: str
    team: str
    hours: float = 0.0
    units: int = 0
    gross_revenue: float = 0.0
    mileage_paid: float = 0.0
    total_miles: float = 0.0
    days_worked: int = 0
    work_dates: set = field(default_factory=set)

    @property
    def net_revenue(self) -> float:
        return self.gross_revenue - self.mileage_paid

    @property
    def gross_dph(self) -> float:
        return self.gross_revenue / self.hours if self.hours > 0 else 0.0

    @property
    def net_dph(self) -> float:
        return self.net_revenue / self.hours if self.hours > 0 else 0.0

    @property
    def tenure_category(self) -> str:
        if self.days_worked >= 60:
            return "Core (60+ days)"
        elif self.days_worked >= 40:
            return "Reliable (40-59 days)"
        elif self.days_worked >= 20:
            return "Part-Time (20-39 days)"
        return "New/Sporadic (<20 days)"


@dataclass
class TeamRollup:
    team_name: str
    techs: List[TechRecord] = field(default_factory=list)

    @property
    def total_techs(self) -> int:
        return len(self.techs)

    @property
    def total_hours(self) -> float:
        return sum(t.hours for t in self.techs)

    @property
    def total_units(self) -> int:
        return sum(t.units for t in self.techs)

    @property
    def gross_revenue(self) -> float:
        return sum(t.gross_revenue for t in self.techs)

    @property
    def mileage_paid(self) -> float:
        return sum(t.mileage_paid for t in self.techs)

    @property
    def total_miles(self) -> float:
        return sum(t.total_miles for t in self.techs)

    @property
    def net_revenue(self) -> float:
        return self.gross_revenue - self.mileage_paid

    @property
    def gross_dph(self) -> float:
        return self.gross_revenue / self.total_hours if self.total_hours > 0 else 0.0

    @property
    def net_dph(self) -> float:
        return self.net_revenue / self.total_hours if self.total_hours > 0 else 0.0

    @property
    def mileage_cost_pct(self) -> float:
        return (self.mileage_paid / self.gross_revenue * 100) if self.gross_revenue > 0 else 0.0

    @property
    def miles_per_hour(self) -> float:
        return self.total_miles / self.total_hours if self.total_hours > 0 else 0.0

    @property
    def avg_days_worked(self) -> float:
        if not self.techs:
            return 0.0
        return sum(t.days_worked for t in self.techs) / len(self.techs)

    @property
    def core_techs(self) -> int:
        return sum(1 for t in self.techs if t.days_worked >= 60)

    @property
    def reliable_techs(self) -> int:
        return sum(1 for t in self.techs if 40 <= t.days_worked < 60)

    @property
    def parttime_techs(self) -> int:
        return sum(1 for t in self.techs if 20 <= t.days_worked < 40)

    @property
    def sporadic_techs(self) -> int:
        return sum(1 for t in self.techs if t.days_worked < 20)

    @property
    def core_tech_pct(self) -> float:
        return (self.core_techs / self.total_techs * 100) if self.total_techs > 0 else 0.0

    gross_rank: int = 0
    net_rank: int = 0
    tenure_rank: int = 0
    diagnosis: str = ""

    @property
    def rank_gap(self) -> int:
        return self.gross_rank - self.tenure_rank


def compute_diagnosis(team: TeamRollup) -> str:
    """Assign diagnostic category based on rank gap and position.

    Categories per the target workbook Legend:
    - Slow Techs: Rank Gap > +15 (stable workforce but low productivity)
    - High Turnover: Rank Gap < -15 (efficient but cant retain people)
    - Balanced: Efficiency Rank <= 20 AND Tenure Rank <= 20
    - Middle Tier: Rank Gap between -15 and +15
    - Needs Help: Efficiency Rank > 50 AND Tenure Rank > 50
    - Low Volume: Less than 1,000 hours
    """
    if team.total_hours < 1000:
        return "\U0001f4ca Low Volume"

    rank_gap = team.rank_gap

    if team.gross_rank > 50 and team.tenure_rank > 50:
        return "\u26a0\ufe0f Needs Help"

    if team.gross_rank <= 20 and team.tenure_rank <= 20:
        return "\u2b50 Balanced"

    if rank_gap > 15:
        return "\U0001f422 Slow Techs"

    if rank_gap < -15:
        return "\U0001f3c3 High Turnover"

    return "\u2796 Middle Tier"


class AnalyticsEngine:
    """Runs deterministic analytics against warehouse data."""

    def __init__(self, session: Session):
        self.session = session

    def build_team_rollups(self, start_date: date, end_date: date,
                            team_merges: Dict[str, str] = None) -> List[TeamRollup]:
        """Build team-level rollups from technician observations in date range.

        team_merges: dict mapping old team name -> new team name for merges.
        """
        tech_data = self._load_tech_data(start_date, end_date)
        mileage_data = self._load_mileage_data(start_date, end_date)

        for tech_name, mileage_info in mileage_data.items():
            if tech_name in tech_data:
                tech_data[tech_name]["mileage_paid"] += mileage_info["mileage_paid"]
                tech_data[tech_name]["total_miles"] += mileage_info["total_miles"]
            else:
                tech_data[tech_name] = mileage_info

        team_techs: Dict[str, List[TechRecord]] = defaultdict(list)
        for tech_name, data in tech_data.items():
            team_name = data.get("team", "Unknown")
            if team_merges and team_name in team_merges:
                team_name = team_merges[team_name]

            tr = TechRecord(
                name=tech_name,
                team=team_name,
                hours=data.get("hours", 0.0),
                units=int(data.get("units", 0)),
                gross_revenue=data.get("gross_revenue", 0.0),
                mileage_paid=data.get("mileage_paid", 0.0),
                total_miles=data.get("total_miles", 0.0),
                days_worked=len(data.get("work_dates", set())),
                work_dates=data.get("work_dates", set()),
            )
            team_techs[team_name].append(tr)

        rollups = []
        for team_name, techs in team_techs.items():
            rollup = TeamRollup(team_name=team_name, techs=techs)
            rollups.append(rollup)

        self._assign_ranks(rollups)
        for r in rollups:
            r.diagnosis = compute_diagnosis(r)

        return rollups

    def _load_tech_data(self, start_date: date, end_date: date) -> Dict[str, Dict]:
        """Load technician-level performance data from warehouse.

        Uses Observation.parent_entity_id for time-stable team attribution
        rather than Entity.parent_id which reflects only the latest assignment.
        """
        tech_data: Dict[str, Dict] = {}

        metric_names = {
            "hours": "hours",
            "units": "units",
            "gross_revenue": "gross_revenue",
            "gross_dollars_per_hour": None,
        }

        ParentEntity = Entity.__table__.alias("parent_entity")

        for metric_key, field_name in metric_names.items():
            if field_name is None:
                continue

            rows = (
                self.session.query(
                    Entity.canonical_name.label("tech_name"),
                    Observation.parent_entity_id,
                    func.sum(Observation.value).label("total"),
                    func.count(func.distinct(Period.start_date)).label("distinct_days"),
                )
                .join(Observation, Observation.entity_id == Entity.id)
                .join(Metric, Observation.metric_id == Metric.id)
                .join(Period, Observation.period_id == Period.id)
                .filter(
                    Entity.entity_type == "technician",
                    Metric.canonical_name == metric_key,
                    Period.start_date >= start_date,
                    Period.end_date <= end_date,
                )
                .group_by(Entity.canonical_name, Observation.parent_entity_id)
                .all()
            )

            for row in rows:
                name = row.tech_name
                if name not in tech_data:
                    tech_data[name] = {
                        "team": self._resolve_team_name(row.parent_entity_id),
                        "hours": 0.0, "units": 0, "gross_revenue": 0.0,
                        "mileage_paid": 0.0, "total_miles": 0.0,
                        "work_dates": set(),
                    }
                tech_data[name][field_name] = float(row.total or 0)

        work_dates_rows = (
            self.session.query(
                Entity.canonical_name,
                Period.start_date,
            )
            .join(Observation, Observation.entity_id == Entity.id)
            .join(Period, Observation.period_id == Period.id)
            .join(Metric, Observation.metric_id == Metric.id)
            .filter(
                Entity.entity_type == "technician",
                Metric.canonical_name == "hours",
                Period.start_date >= start_date,
                Period.end_date <= end_date,
            )
            .distinct()
            .all()
        )
        for row in work_dates_rows:
            if row.canonical_name in tech_data:
                tech_data[row.canonical_name]["work_dates"].add(row.start_date)

        return tech_data

    def _load_mileage_data(self, start_date: date, end_date: date) -> Dict[str, Dict]:
        """Load mileage data for technicians in date range.

        Uses Observation.parent_entity_id for time-stable team attribution.
        """
        mileage_data: Dict[str, Dict] = {}

        for metric_name in ("mileage_paid", "total_miles"):
            rows = (
                self.session.query(
                    Entity.canonical_name.label("tech_name"),
                    Observation.parent_entity_id,
                    func.sum(Observation.value).label("total"),
                )
                .join(Observation, Observation.entity_id == Entity.id)
                .join(Metric, Observation.metric_id == Metric.id)
                .join(Period, Observation.period_id == Period.id)
                .filter(
                    Entity.entity_type == "technician",
                    Metric.canonical_name == metric_name,
                    Period.start_date >= start_date,
                    Period.end_date <= end_date,
                )
                .group_by(Entity.canonical_name, Observation.parent_entity_id)
                .all()
            )

            for row in rows:
                if row.tech_name not in mileage_data:
                    mileage_data[row.tech_name] = {
                        "team": self._resolve_team_name(row.parent_entity_id),
                        "mileage_paid": 0.0, "total_miles": 0.0,
                        "hours": 0.0, "units": 0, "gross_revenue": 0.0,
                        "work_dates": set(),
                    }
                mileage_data[row.tech_name][metric_name] = float(row.total or 0)

        return mileage_data

    def _resolve_team_name(self, parent_id: Optional[int]) -> str:
        if parent_id is None:
            return "Unknown"
        team = self.session.query(Entity).filter_by(id=parent_id).first()
        return team.canonical_name if team else "Unknown"

    def _assign_ranks(self, rollups: List[TeamRollup]) -> None:
        by_gross = sorted(rollups, key=lambda r: r.gross_dph, reverse=True)
        for i, r in enumerate(by_gross, 1):
            r.gross_rank = i

        by_net = sorted(rollups, key=lambda r: r.net_dph, reverse=True)
        for i, r in enumerate(by_net, 1):
            r.net_rank = i

        by_tenure = sorted(rollups, key=lambda r: r.core_tech_pct, reverse=True)
        for i, r in enumerate(by_tenure, 1):
            r.tenure_rank = i

    def compute_territory_averages(self, rollups: List[TeamRollup]) -> Dict[str, float]:
        total_hours = sum(r.total_hours for r in rollups)
        total_revenue = sum(r.gross_revenue for r in rollups)
        total_mileage = sum(r.mileage_paid for r in rollups)

        return {
            "avg_gross_dph": total_revenue / total_hours if total_hours > 0 else 0.0,
            "avg_net_dph": (total_revenue - total_mileage) / total_hours if total_hours > 0 else 0.0,
            "total_hours": total_hours,
            "total_revenue": total_revenue,
            "total_mileage": total_mileage,
        }

    def compute_gap_to_avg(self, rollup: TeamRollup, avg_gross_dph: float) -> float:
        """Dollar gap: (team_dph - territory_avg_dph) * team_hours."""
        return (rollup.gross_dph - avg_gross_dph) * rollup.total_hours

    def build_tech_detail_list(self, rollups: List[TeamRollup]) -> List[Dict]:
        """Build individual tech detail sorted by team, then days worked desc."""
        details = []
        for rollup in rollups:
            for tech in sorted(rollup.techs, key=lambda t: t.days_worked, reverse=True):
                details.append({
                    "team_name": rollup.team_name,
                    "technician": tech.name,
                    "days_worked": tech.days_worked,
                    "hours": tech.hours,
                    "gross_revenue": tech.gross_revenue,
                    "mileage_paid": tech.mileage_paid,
                    "net_revenue": tech.net_revenue,
                    "gross_dph": tech.gross_dph,
                    "net_dph": tech.net_dph,
                    "total_miles": tech.total_miles,
                    "tenure_category": tech.tenure_category,
                })
        return details

    def build_diagnostic_groups(self, rollups: List[TeamRollup]) -> Dict[str, List[TeamRollup]]:
        groups: Dict[str, List[TeamRollup]] = defaultdict(list)
        for r in rollups:
            groups[r.diagnosis].append(r)
        for key in groups:
            groups[key].sort(key=lambda r: abs(r.rank_gap), reverse=True)
        return dict(groups)

    def build_mileage_analysis(self, rollups: List[TeamRollup]) -> List[Dict]:
        analysis = []
        for r in sorted(rollups, key=lambda r: r.mileage_paid, reverse=True):
            analysis.append({
                "team_name": r.team_name,
                "mileage_paid": r.mileage_paid,
                "mileage_cost_pct": r.mileage_cost_pct,
                "total_miles": r.total_miles,
                "miles_per_hour": r.miles_per_hour,
                "gross_dph": r.gross_dph,
                "net_dph": r.net_dph,
                "total_hours": r.total_hours,
                "diagnosis": r.diagnosis,
            })
        return analysis


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

@dataclass
class PeriodTrend:
    entity_name: str
    metric_name: str
    current_value: float
    previous_value: Optional[float]
    absolute_change: Optional[float]
    percent_change: Optional[float]
    current_rank: Optional[int]
    previous_rank: Optional[int]
    rank_change: Optional[int]
    rolling_4_avg: Optional[float]
    rolling_8_avg: Optional[float]
    volatility: Optional[float]


class TrendEngine:
    """Computes period-over-period trends, rolling averages, and rank movements."""

    def __init__(self, session: Session):
        self.session = session

    def compute_period_trends(self, entity_type: str, metric_name: str,
                               periods: List[Tuple[date, date]],
                               ) -> List[PeriodTrend]:
        """Compute trends for all entities of a type across ordered periods."""
        values_by_entity: Dict[str, List[Optional[float]]] = defaultdict(
            lambda: [None] * len(periods)
        )
        ranks_by_entity: Dict[str, List[Optional[int]]] = defaultdict(
            lambda: [None] * len(periods)
        )

        for idx, (start, end) in enumerate(periods):
            period_values = self._get_entity_values(entity_type, metric_name, start, end)
            sorted_vals = sorted(period_values.items(), key=lambda x: x[1], reverse=True)
            for rank, (ename, val) in enumerate(sorted_vals, 1):
                values_by_entity[ename][idx] = val
                ranks_by_entity[ename][idx] = rank

        trends = []
        for ename in values_by_entity:
            vals = values_by_entity[ename]
            ranks = ranks_by_entity[ename]

            current = vals[-1]
            previous = vals[-2] if len(vals) >= 2 else None

            if current is None:
                continue

            abs_change = None
            pct_change = None
            if previous is not None:
                abs_change = current - previous
                pct_change = (abs_change / previous * 100) if previous != 0 else None

            cur_rank = ranks[-1]
            prev_rank = ranks[-2] if len(ranks) >= 2 else None
            rank_chg = (prev_rank - cur_rank) if (cur_rank and prev_rank) else None

            non_none = [v for v in vals if v is not None]
            r4 = sum(non_none[-4:]) / len(non_none[-4:]) if len(non_none) >= 4 else None
            r8 = sum(non_none[-8:]) / len(non_none[-8:]) if len(non_none) >= 8 else None

            volatility = None
            if len(non_none) >= 3:
                mean = sum(non_none) / len(non_none)
                variance = sum((v - mean) ** 2 for v in non_none) / len(non_none)
                volatility = variance ** 0.5

            trends.append(PeriodTrend(
                entity_name=ename, metric_name=metric_name,
                current_value=current, previous_value=previous,
                absolute_change=abs_change, percent_change=pct_change,
                current_rank=cur_rank, previous_rank=prev_rank,
                rank_change=rank_chg, rolling_4_avg=r4, rolling_8_avg=r8,
                volatility=volatility,
            ))

        return trends

    def _get_entity_values(self, entity_type: str, metric_name: str,
                            start: date, end: date) -> Dict[str, float]:
        if entity_type == "team":
            return self._get_team_values_via_aggregation(metric_name, start, end)

        rows = (
            self.session.query(
                Entity.canonical_name,
                func.sum(Observation.value).label("total"),
            )
            .join(Observation, Observation.entity_id == Entity.id)
            .join(Metric, Observation.metric_id == Metric.id)
            .join(Period, Observation.period_id == Period.id)
            .filter(
                Entity.entity_type == entity_type,
                Metric.canonical_name == metric_name,
                Period.start_date >= start,
                Period.end_date <= end,
            )
            .group_by(Entity.canonical_name)
            .all()
        )
        return {r.canonical_name: float(r.total) for r in rows}

    def _get_team_values_via_aggregation(self, metric_name: str,
                                          start: date, end: date) -> Dict[str, float]:
        """Aggregate child-entity observations grouped by parent_entity_id
        to produce real team-level values from technician/CID observations."""
        TeamEntity = Entity.__table__.alias("team_entity")

        from sqlalchemy import select
        from sqlalchemy.orm import aliased

        TeamAlias = aliased(Entity, name="team_entity")

        rows = (
            self.session.query(
                TeamAlias.canonical_name,
                func.sum(Observation.value).label("total"),
            )
            .join(Observation, Observation.parent_entity_id == TeamAlias.id)
            .join(Metric, Observation.metric_id == Metric.id)
            .join(Period, Observation.period_id == Period.id)
            .filter(
                TeamAlias.entity_type == "team",
                Metric.canonical_name == metric_name,
                Period.start_date >= start,
                Period.end_date <= end,
            )
            .group_by(TeamAlias.canonical_name)
            .all()
        )
        return {r.canonical_name: float(r.total) for r in rows}

    def get_top_movers(self, trends: List[PeriodTrend], n: int = 10,
                       direction: str = "improved") -> List[PeriodTrend]:
        valid = [t for t in trends if t.rank_change is not None]
        if direction == "improved":
            return sorted(valid, key=lambda t: t.rank_change or 0, reverse=True)[:n]
        else:
            return sorted(valid, key=lambda t: t.rank_change or 0)[:n]

    def get_most_volatile(self, trends: List[PeriodTrend], n: int = 10) -> List[PeriodTrend]:
        valid = [t for t in trends if t.volatility is not None]
        return sorted(valid, key=lambda t: t.volatility or 0, reverse=True)[:n]

    def get_most_stable(self, trends: List[PeriodTrend], n: int = 10) -> List[PeriodTrend]:
        valid = [t for t in trends if t.volatility is not None]
        return sorted(valid, key=lambda t: t.volatility or 0)[:n]
