"""Executive Infographic PDF template.

Wraps the pdf_renderer.generate_executive_pdf as a proper ReportTemplate
so it can be discovered, validated, and executed through the registry.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import List

from sqlalchemy.orm import Session

from ..registry import ReportPlan, ReportTemplate
from ...analytics.engine import AnalyticsEngine

logger = logging.getLogger(__name__)


class ExecutiveInfographicTemplate(ReportTemplate):
    name = "executive_infographic_pdf"
    description = "Polished executive summary PDF with KPIs, rankings, and diagnostics"
    supported_formats = ["pdf"]
    supported_entity_scopes = ["all_teams"]
    supports_trends = False

    def generate(self, plan: ReportPlan, session: Session,
                 output_dir: str) -> List[str]:
        from ..pdf_renderer import generate_executive_pdf

        engine = AnalyticsEngine(session)
        start, end = self.resolve_period(session, plan.period_start, plan.period_end)

        rollups = engine.build_team_rollups(start, end, plan.team_merges)
        avgs = engine.compute_territory_averages(rollups)
        period_label = f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"

        filepath = generate_executive_pdf(
            rollups, avgs, period_label, output_dir
        )
        return [filepath]
