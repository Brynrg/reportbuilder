"""Trend Focus Pack template.

Dedicated multi-sheet trend workbook for analyzing entity performance over time.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List

import xlsxwriter
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from ..registry import ReportPlan, ReportTemplate
from ...analytics.engine import AnalyticsEngine, TrendEngine
from ...warehouse.models import Entity, Observation, Metric, Period

logger = logging.getLogger(__name__)


SUPPORTED_TREND_ENTITY_TYPES = ["team", "technician", "cid", "rvp", "region"]


class TrendFocusTemplate(ReportTemplate):
    name = "trend_focus_pack"
    description = "Dedicated trend analysis workbook with period-over-period changes"
    supported_formats = ["excel"]
    supported_entity_scopes = ["all_teams", "team", "technician", "cid", "rvp", "region"]
    supports_trends = True

    def _resolve_entity_type(self, plan: ReportPlan) -> str:
        scope = plan.entity_scope if isinstance(plan.entity_scope, dict) else {}
        scope_type = scope.get("type", "all_teams")
        if scope_type in ("all_teams", "team"):
            return "team"
        if scope_type in SUPPORTED_TREND_ENTITY_TYPES:
            return scope_type
        return "team"

    def generate(self, plan: ReportPlan, session: Session,
                 output_dir: str) -> List[str]:
        start, end = self.resolve_period(session, plan.period_start, plan.period_end)

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        entity_type = self._resolve_entity_type(plan)
        filename = f"Trend_Focus_{entity_type}_{ts}.xlsx"
        filepath = str(Path(output_dir) / filename)

        engine = AnalyticsEngine(session)
        trend_engine = TrendEngine(session)

        months = self._build_monthly_periods(start, end)
        metric_name = "gross_revenue"
        if plan.metrics:
            metric_name = plan.metrics[0]

        trends = []
        if months:
            trends = trend_engine.compute_period_trends(
                entity_type, metric_name, months
            )

        wb = xlsxwriter.Workbook(filepath)
        title_fmt = wb.add_format({
            "bold": True, "font_size": 14, "font_name": "Calibri",
            "bottom": 2, "font_color": "#1a1a2e",
        })
        header_fmt = wb.add_format({
            "bold": True, "font_size": 10, "font_name": "Calibri",
            "bg_color": "#1a1a2e", "font_color": "#ffffff",
            "text_wrap": True,
        })
        num_fmt = wb.add_format({"num_format": "#,##0.00", "font_name": "Calibri", "font_size": 10})
        pct_fmt = wb.add_format({"num_format": "0.0%", "font_name": "Calibri", "font_size": 10})
        text_fmt = wb.add_format({"font_name": "Calibri", "font_size": 10})
        int_fmt = wb.add_format({"num_format": "#,##0", "font_name": "Calibri", "font_size": 10})

        ws = wb.add_worksheet("Trend Overview")
        ws.set_column("A:A", 35)
        ws.set_column("B:H", 14)
        ws.write(0, 0, f"TREND OVERVIEW - {metric_name.upper()}", title_fmt)
        ws.write(1, 0, f"Period: {start} to {end}", text_fmt)

        headers = ["Entity", "Current", "Previous", "Change", "% Change",
                    "Rolling 4", "Rolling 8", "Volatility"]
        for c, h in enumerate(headers):
            ws.write(3, c, h, header_fmt)

        for i, t in enumerate(sorted(trends, key=lambda x: x.current_value or 0, reverse=True), 4):
            ws.write(i, 0, t.entity_name, text_fmt)
            ws.write(i, 1, t.current_value or 0, num_fmt)
            ws.write(i, 2, t.previous_value or 0, num_fmt)
            ws.write(i, 3, t.absolute_change or 0, num_fmt)
            ws.write(i, 4, (t.percent_change or 0) / 100, pct_fmt)
            ws.write(i, 5, t.rolling_4_avg or 0, num_fmt)
            ws.write(i, 6, t.rolling_8_avg or 0, num_fmt)
            ws.write(i, 7, t.volatility or 0, num_fmt)

        ws2 = wb.add_worksheet("Rank Movement")
        ws2.set_column("A:A", 35)
        ws2.set_column("B:E", 14)
        ws2.write(0, 0, "RANK MOVEMENT", title_fmt)
        headers2 = ["Entity", "Current Rank", "Previous Rank", "Rank Change", "Direction"]
        for c, h in enumerate(headers2):
            ws2.write(2, c, h, header_fmt)

        ranked = [t for t in trends if t.rank_change is not None]
        ranked.sort(key=lambda x: x.rank_change or 0, reverse=True)
        for i, t in enumerate(ranked, 3):
            ws2.write(i, 0, t.entity_name, text_fmt)
            ws2.write(i, 1, t.current_rank or 0, int_fmt)
            ws2.write(i, 2, t.previous_rank or 0, int_fmt)
            ws2.write(i, 3, t.rank_change or 0, int_fmt)
            direction = "Improved" if (t.rank_change or 0) > 0 else ("Declined" if (t.rank_change or 0) < 0 else "Stable")
            ws2.write(i, 4, direction, text_fmt)

        ws3 = wb.add_worksheet("Top Improvers & Decliners")
        ws3.set_column("A:A", 35)
        ws3.set_column("B:D", 14)
        ws3.write(0, 0, "TOP IMPROVERS", title_fmt)
        improvers = trend_engine.get_top_movers(trends, n=10, direction="improved")
        for c, h in enumerate(["Entity", "Rank Change", "Current Value"]):
            ws3.write(2, c, h, header_fmt)
        for i, t in enumerate(improvers, 3):
            ws3.write(i, 0, t.entity_name, text_fmt)
            ws3.write(i, 1, t.rank_change or 0, int_fmt)
            ws3.write(i, 2, t.current_value or 0, num_fmt)

        row_offset = len(improvers) + 5
        ws3.write(row_offset, 0, "TOP DECLINERS", title_fmt)
        decliners = trend_engine.get_top_movers(trends, n=10, direction="declined")
        for c, h in enumerate(["Entity", "Rank Change", "Current Value"]):
            ws3.write(row_offset + 2, c, h, header_fmt)
        for i, t in enumerate(decliners, row_offset + 3):
            ws3.write(i, 0, t.entity_name, text_fmt)
            ws3.write(i, 1, t.rank_change or 0, int_fmt)
            ws3.write(i, 2, t.current_value or 0, num_fmt)

        ws4 = wb.add_worksheet("Stability & Volatility")
        ws4.set_column("A:A", 35)
        ws4.set_column("B:C", 14)
        ws4.write(0, 0, "STABILITY / VOLATILITY ANALYSIS", title_fmt)

        ws4.write(2, 0, "MOST STABLE", header_fmt)
        stable = trend_engine.get_most_stable(trends, n=10)
        for c, h in enumerate(["Entity", "Volatility", "Current Value"]):
            ws4.write(3, c, h, header_fmt)
        for i, t in enumerate(stable, 4):
            ws4.write(i, 0, t.entity_name, text_fmt)
            ws4.write(i, 1, t.volatility or 0, num_fmt)
            ws4.write(i, 2, t.current_value or 0, num_fmt)

        vol_offset = len(stable) + 6
        ws4.write(vol_offset, 0, "MOST VOLATILE", header_fmt)
        volatile = trend_engine.get_most_volatile(trends, n=10)
        for c, h in enumerate(["Entity", "Volatility", "Current Value"]):
            ws4.write(vol_offset + 1, c, h, header_fmt)
        for i, t in enumerate(volatile, vol_offset + 2):
            ws4.write(i, 0, t.entity_name, text_fmt)
            ws4.write(i, 1, t.volatility or 0, num_fmt)
            ws4.write(i, 2, t.current_value or 0, num_fmt)

        ws5 = wb.add_worksheet("Definitions")
        ws5.set_column("A:A", 80)
        ws5.write(0, 0, "TREND DEFINITIONS", title_fmt)
        defs = [
            "Rolling 4: Average of the last 4 period values",
            "Rolling 8: Average of the last 8 period values",
            "Volatility: Standard deviation of values across periods",
            "Rank Change: Positive = improved (moved up), Negative = declined",
            "% Change: (Current - Previous) / Previous * 100",
        ]
        for i, d in enumerate(defs, 2):
            ws5.write(i, 0, d, text_fmt)

        wb.close()
        logger.info("Generated: %s", filename)
        return [filepath]

    def _build_monthly_periods(self, start: date, end: date) -> List[tuple]:
        periods = []
        current = start.replace(day=1)
        while current <= end:
            import calendar
            last_day = calendar.monthrange(current.year, current.month)[1]
            month_end = current.replace(day=last_day)
            if month_end > end:
                month_end = end
            periods.append((current, month_end))
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        return periods
