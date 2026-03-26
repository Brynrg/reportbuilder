"""Team Efficiency & Tenure Ranking workbook template.

Gold-standard output matching the target workbook structure:
- Ranked by Gross Efficiency
- Ranked by Net Efficiency
- Ranked by Tenure
- Diagnostic Summary
- Individual Tech Detail
- Mileage Analysis
- Legend
- Trend Summary
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import xlsxwriter

from sqlalchemy.orm import Session

from ..registry import ReportPlan, ReportTemplate
from ...analytics.engine import AnalyticsEngine, TeamRollup, TrendEngine

logger = logging.getLogger(__name__)

DIAG_ORDER = [
    "\U0001f422 Slow Techs",
    "\U0001f3c3 High Turnover",
    "\u2b50 Balanced",
    "\u2796 Middle Tier",
    "\u26a0\ufe0f Needs Help",
    "\U0001f4ca Low Volume",
]


class TeamEfficiencyTenureTemplate(ReportTemplate):
    name = "team_efficiency_tenure_pack"
    description = "Teams ranked by gross/net efficiency, tenure, diagnostics, tech detail, mileage"
    supported_formats = ["excel"]
    supported_entity_scopes = ["all_teams", "team"]
    supports_trends = False

    def generate(self, plan: ReportPlan, session: Session,
                 output_dir: str) -> List[str]:
        engine = AnalyticsEngine(session)

        start, end = self.resolve_period(session, plan.period_start, plan.period_end)

        rollups = engine.build_team_rollups(start, end, plan.team_merges)
        avgs = engine.compute_territory_averages(rollups)

        for r in rollups:
            r._gap_to_avg = engine.compute_gap_to_avg(r, avgs["avg_gross_dph"])

        outputs = []

        if "excel" in plan.output_formats:
            period_label = f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"
            xlsx_path = self._write_excel(
                rollups, avgs, period_label, output_dir, engine, start, end
            )
            outputs.append(xlsx_path)

        return outputs

    def _write_excel(self, rollups: List[TeamRollup], avgs: Dict,
                     period_label: str, output_dir: str,
                     engine: AnalyticsEngine,
                     start: date, end: date) -> str:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Team_Efficiency_Tenure_Ranking_{ts}.xlsx"
        filepath = str(Path(output_dir) / filename)

        wb = xlsxwriter.Workbook(filepath)
        styles = self._create_styles(wb)

        self._write_gross_sheet(wb, styles, rollups, avgs, period_label)
        self._write_net_sheet(wb, styles, rollups, avgs, period_label)
        self._write_tenure_sheet(wb, styles, rollups, period_label)
        self._write_diagnostic_sheet(wb, styles, rollups)
        self._write_tech_detail_sheet(wb, styles, rollups, engine)
        self._write_mileage_sheet(wb, styles, rollups, engine, avgs)
        self._write_legend_sheet(wb, styles)
        self._write_trend_summary(wb, styles, rollups)

        wb.close()
        logger.info("Generated workbook: %s", filename)
        return filepath

    def _create_styles(self, wb) -> Dict:
        s = {}
        s["title"] = wb.add_format({
            "bold": True, "font_size": 14, "font_name": "Calibri",
            "bottom": 2, "font_color": "#1a1a2e",
        })
        s["subtitle"] = wb.add_format({
            "italic": True, "font_size": 10, "font_color": "#555555",
            "font_name": "Calibri",
        })
        s["note"] = wb.add_format({
            "italic": True, "font_size": 9, "font_color": "#888888",
            "font_name": "Calibri",
        })
        s["header"] = wb.add_format({
            "bold": True, "font_size": 10, "font_name": "Calibri",
            "bg_color": "#1a1a2e", "font_color": "#ffffff",
            "bottom": 1, "text_wrap": True, "valign": "vcenter",
        })
        s["int"] = wb.add_format({"num_format": "#,##0", "font_name": "Calibri", "font_size": 10})
        s["dec2"] = wb.add_format({"num_format": "#,##0.00", "font_name": "Calibri", "font_size": 10})
        s["pct"] = wb.add_format({"num_format": "0.0%", "font_name": "Calibri", "font_size": 10})
        s["pct_raw"] = wb.add_format({"num_format": "0.0", "font_name": "Calibri", "font_size": 10})
        s["money"] = wb.add_format({"num_format": "#,##0", "font_name": "Calibri", "font_size": 10})
        s["text"] = wb.add_format({"font_name": "Calibri", "font_size": 10})
        s["diag_header"] = wb.add_format({
            "bold": True, "font_size": 11, "font_name": "Calibri",
            "bg_color": "#f0f0f0", "bottom": 1,
        })
        s["legend_title"] = wb.add_format({
            "bold": True, "font_size": 12, "font_name": "Calibri",
        })
        s["legend_section"] = wb.add_format({
            "bold": True, "font_size": 11, "font_name": "Calibri",
            "bottom": 1,
        })
        s["legend_text"] = wb.add_format({
            "font_size": 10, "font_name": "Calibri", "text_wrap": True,
        })

        for diag, color in [
            ("\U0001f422 Slow Techs", "#FFF2CC"),
            ("\U0001f3c3 High Turnover", "#D6EAF8"),
            ("\u2b50 Balanced", "#D5F5E3"),
            ("\u2796 Middle Tier", "#F2F3F4"),
            ("\u26a0\ufe0f Needs Help", "#FADBD8"),
            ("\U0001f4ca Low Volume", "#E8DAEF"),
        ]:
            s[f"diag_{diag}"] = wb.add_format({
                "font_name": "Calibri", "font_size": 10, "bg_color": color,
            })

        return s

    def _ranking_headers(self) -> List[str]:
        return [
            "Gross Efficiency Rank", "Net Efficiency Rank", "Tenure Rank",
            "Team Name", "Diagnosis", "Total Techs", "Total Hours",
            "Total Units", "Gross Revenue ($)", "Mileage Paid ($)",
            "Net Revenue ($)", "Gross $/Hr", "Net $/Hr", "Mileage Cost %",
            "Miles Per Hour", "Gap to Avg ($)", "Avg Days Worked Per Tech",
            "Core Techs (60+ Days)", "Reliable Techs (40-59 Days)",
            "Part-Time Techs (20-39 Days)", "New/Sporadic Techs (<20 Days)",
            "Core Tech %", "Rank Gap",
        ]

    def _team_row_data(self, r: TeamRollup, avgs: Dict) -> List:
        gap = (r.gross_dph - avgs["avg_gross_dph"]) * r.total_hours
        return [
            r.gross_rank, r.net_rank, r.tenure_rank,
            r.team_name, r.diagnosis, r.total_techs, round(r.total_hours, 2),
            r.total_units, round(r.gross_revenue, 2), round(r.mileage_paid, 2),
            round(r.net_revenue, 2), round(r.gross_dph, 2), round(r.net_dph, 2),
            round(r.mileage_cost_pct, 2), round(r.miles_per_hour, 2),
            round(gap), round(r.avg_days_worked, 2),
            r.core_techs, r.reliable_techs, r.parttime_techs, r.sporadic_techs,
            round(r.core_tech_pct, 1), r.rank_gap,
        ]

    def _write_ranking_sheet(self, wb, styles, sheet_name: str, title: str,
                             subtitle: str, rollups: List[TeamRollup],
                             avgs: Dict, sort_key, note: str = ""):
        ws = wb.add_worksheet(sheet_name)
        ws.freeze_panes(5, 4)
        ws.set_column("A:C", 8)
        ws.set_column("D:D", 35)
        ws.set_column("E:E", 18)
        ws.set_column("F:W", 12)

        ws.write(0, 0, title, styles["title"])
        ws.write(1, 0, subtitle, styles["subtitle"])
        if note:
            ws.write(2, 0, note, styles["note"])

        headers = self._ranking_headers()
        for col, h in enumerate(headers):
            ws.write(4, col, h, styles["header"])

        sorted_teams = sorted(rollups, key=sort_key, reverse=True)
        for row_idx, team in enumerate(sorted_teams, 5):
            data = self._team_row_data(team, avgs)
            diag_fmt = styles.get(f"diag_{team.diagnosis}", styles["text"])
            for col, val in enumerate(data):
                if col in (6, 8, 9, 10, 11, 12, 14, 15, 16):
                    ws.write(row_idx, col, val, styles["dec2"])
                elif col in (13,):
                    ws.write(row_idx, col, val, styles["pct_raw"])
                elif col == 4:
                    ws.write(row_idx, col, val, diag_fmt)
                elif isinstance(val, (int, float)):
                    ws.write(row_idx, col, val, styles["int"])
                else:
                    ws.write(row_idx, col, val, styles["text"])

        ws.autofilter(4, 0, 4 + len(rollups), len(headers) - 1)

    def _write_gross_sheet(self, wb, styles, rollups, avgs, period_label):
        avg_g = avgs["avg_gross_dph"]
        avg_n = avgs["avg_net_dph"]
        self._write_ranking_sheet(
            wb, styles,
            "Ranked by Gross Efficiency",
            "TEAMS RANKED BY GROSS EFFICIENCY ($/HR) - BEFORE MILEAGE",
            f"Data Period: {period_label} | Territory Avg Gross: ${avg_g:.2f}/hr | Net: ${avg_n:.2f}/hr",
            rollups, avgs,
            sort_key=lambda r: r.gross_dph,
        )

    def _write_net_sheet(self, wb, styles, rollups, avgs, period_label):
        self._write_ranking_sheet(
            wb, styles,
            "Ranked by Net Efficiency",
            "TEAMS RANKED BY NET EFFICIENCY ($/HR) - AFTER MILEAGE",
            f"Data Period: {period_label} | Net $/Hr = (Revenue - Mileage) / Hours",
            rollups, avgs,
            sort_key=lambda r: r.net_dph,
            note="This is the TRUE efficiency after accounting for mileage costs",
        )

    def _write_tenure_sheet(self, wb, styles, rollups, period_label):
        avgs = {"avg_gross_dph": 0, "avg_net_dph": 0}
        total_h = sum(r.total_hours for r in rollups)
        total_r = sum(r.gross_revenue for r in rollups)
        total_m = sum(r.mileage_paid for r in rollups)
        if total_h > 0:
            avgs["avg_gross_dph"] = total_r / total_h
            avgs["avg_net_dph"] = (total_r - total_m) / total_h

        self._write_ranking_sheet(
            wb, styles,
            "Ranked by Tenure",
            "TEAMS RANKED BY WORKFORCE STABILITY (CORE TECH %) - BEST TO WORST",
            "Core Tech % = Percentage of technicians who worked 60+ days in the period",
            rollups, avgs,
            sort_key=lambda r: r.core_tech_pct,
        )

    def _write_diagnostic_sheet(self, wb, styles, rollups):
        ws = wb.add_worksheet("Diagnostic Summary")
        ws.set_column("A:A", 35)
        ws.set_column("B:J", 14)

        ws.write(0, 0, "TEAM DIAGNOSTIC SUMMARY", styles["title"])
        ws.write(1, 0, "Rank Gap = Efficiency Rank - Tenure Rank", styles["subtitle"])

        groups = {}
        for r in rollups:
            groups.setdefault(r.diagnosis, []).append(r)

        row = 3
        diag_headers = [
            "Team", "Efficiency Rank", "Net Efficiency Rank", "Tenure Rank",
            "Rank Gap", "Gross $/Hr", "Net $/Hr", "Mileage Paid", "Core Tech %", "Hours",
        ]

        for diag in DIAG_ORDER:
            teams = groups.get(diag, [])
            if not teams:
                continue
            teams.sort(key=lambda r: abs(r.rank_gap), reverse=True)
            ws.write(row, 0, f"{diag} ({len(teams)} teams)", styles["diag_header"])
            row += 1

            for col, h in enumerate(diag_headers):
                ws.write(row, col, h, styles["header"])
            row += 1

            diag_fmt = styles.get(f"diag_{diag}", styles["text"])
            for team in teams:
                data = [
                    team.team_name, team.gross_rank, team.net_rank, team.tenure_rank,
                    team.rank_gap, round(team.gross_dph, 2), round(team.net_dph, 2),
                    round(team.mileage_paid, 2), round(team.core_tech_pct, 1),
                    round(team.total_hours, 2),
                ]
                for col, val in enumerate(data):
                    fmt = diag_fmt if col == 0 else (styles["dec2"] if isinstance(val, float) else styles["int"])
                    ws.write(row, col, val, fmt)
                row += 1
            row += 1

    def _write_tech_detail_sheet(self, wb, styles, rollups, engine):
        ws = wb.add_worksheet("Individual Tech Detail")
        ws.freeze_panes(4, 2)
        ws.set_column("A:A", 35)
        ws.set_column("B:B", 25)
        ws.set_column("C:K", 14)

        ws.write(0, 0, "INDIVIDUAL TECHNICIAN DETAIL WITH MILEAGE", styles["title"])
        ws.write(1, 0, "All technicians sorted by team, then by days worked (highest first)",
                 styles["subtitle"])

        headers = [
            "Team Name", "Technician Name", "Days Worked", "Total Hours",
            "Gross Revenue ($)", "Mileage Paid ($)", "Net Revenue ($)",
            "Gross $/Hr", "Net $/Hr", "Total Miles", "Tenure Category",
        ]
        for col, h in enumerate(headers):
            ws.write(3, col, h, styles["header"])

        details = engine.build_tech_detail_list(rollups)
        for row_idx, tech in enumerate(details, 4):
            ws.write(row_idx, 0, tech["team_name"], styles["text"])
            ws.write(row_idx, 1, tech["technician"], styles["text"])
            ws.write(row_idx, 2, tech["days_worked"], styles["int"])
            ws.write(row_idx, 3, round(tech["hours"], 2), styles["dec2"])
            ws.write(row_idx, 4, round(tech["gross_revenue"], 2), styles["dec2"])
            ws.write(row_idx, 5, round(tech["mileage_paid"], 2), styles["dec2"])
            ws.write(row_idx, 6, round(tech["net_revenue"], 2), styles["dec2"])
            ws.write(row_idx, 7, round(tech["gross_dph"], 2), styles["dec2"])
            ws.write(row_idx, 8, round(tech["net_dph"], 2), styles["dec2"])
            ws.write(row_idx, 9, round(tech["total_miles"], 2), styles["dec2"])
            ws.write(row_idx, 10, tech["tenure_category"], styles["text"])

        ws.autofilter(3, 0, 3 + len(details), len(headers) - 1)

    def _write_mileage_sheet(self, wb, styles, rollups, engine, avgs):
        ws = wb.add_worksheet("Mileage Analysis")
        ws.set_column("A:A", 35)
        ws.set_column("B:I", 14)

        total_mileage = sum(r.mileage_paid for r in rollups)
        total_hours = sum(r.total_hours for r in rollups)
        impact = total_mileage / total_hours if total_hours > 0 else 0

        ws.write(0, 0, "MILEAGE COST ANALYSIS BY TEAM", styles["title"])
        ws.write(1, 0,
                 f"Total Mileage Paid: ${total_mileage:,.0f} | Impact on $/Hr: -${impact:.2f}",
                 styles["subtitle"])

        headers = [
            "Team Name", "Mileage Paid ($)", "Mileage Cost %", "Total Miles",
            "Miles/Hour", "Gross $/Hr", "Net $/Hr", "Total Hours", "Diagnosis",
        ]
        for col, h in enumerate(headers):
            ws.write(3, col, h, styles["header"])

        analysis = engine.build_mileage_analysis(rollups)
        for row_idx, item in enumerate(analysis, 4):
            ws.write(row_idx, 0, item["team_name"], styles["text"])
            ws.write(row_idx, 1, round(item["mileage_paid"], 2), styles["dec2"])
            ws.write(row_idx, 2, round(item["mileage_cost_pct"], 2), styles["pct_raw"])
            ws.write(row_idx, 3, round(item["total_miles"], 2), styles["dec2"])
            ws.write(row_idx, 4, round(item["miles_per_hour"], 2), styles["dec2"])
            ws.write(row_idx, 5, round(item["gross_dph"], 2), styles["dec2"])
            ws.write(row_idx, 6, round(item["net_dph"], 2), styles["dec2"])
            ws.write(row_idx, 7, round(item["total_hours"], 2), styles["dec2"])
            ws.write(row_idx, 8, item["diagnosis"], styles["text"])

    def _write_legend_sheet(self, wb, styles):
        ws = wb.add_worksheet("Legend")
        ws.set_column("A:A", 80)

        entries = [
            ("COLOR LEGEND & DEFINITIONS", styles["legend_title"]),
            ("", None),
            ("DIAGNOSIS CATEGORIES:", styles["legend_section"]),
            ("\U0001f422 Slow Techs - Rank Gap > +15 (stable workforce but low productivity)", styles["legend_text"]),
            ("\U0001f3c3 High Turnover - Rank Gap < -15 (efficient but cant retain people)", styles["legend_text"]),
            ("\u2b50 Balanced - Efficiency Rank \u2264 20 AND Tenure Rank \u2264 20", styles["legend_text"]),
            ("\u2796 Middle Tier - Rank Gap between -15 and +15 (aligned performance)", styles["legend_text"]),
            ("\u26a0\ufe0f Needs Help - Efficiency Rank > 50 AND Tenure Rank > 50", styles["legend_text"]),
            ("\U0001f4ca Low Volume - Less than 1,000 hours (insufficient data to diagnose)", styles["legend_text"]),
            ("", None),
            ("MILEAGE COST % COLORS (Mileage Analysis tab):", styles["legend_section"]),
            ("Low (< 0.5%)", styles["legend_text"]),
            ("Moderate (0.5% - 1.5%)", styles["legend_text"]),
            ("High (1.5% - 2.5%)", styles["legend_text"]),
            ("Very High (> 2.5%)", styles["legend_text"]),
            ("", None),
            ("COLUMN DEFINITIONS:", styles["legend_section"]),
            ("Gross $/Hr = Gross Revenue / Total Hours", styles["legend_text"]),
            ("Net $/Hr = (Gross Revenue - Mileage Paid) / Total Hours", styles["legend_text"]),
            ("Mileage Cost % = Mileage Paid / Gross Revenue * 100", styles["legend_text"]),
            ("Miles Per Hour = Total Miles / Total Hours", styles["legend_text"]),
            ("Gap to Avg ($) = (Team Gross $/Hr - Territory Avg Gross $/Hr) * Team Hours", styles["legend_text"]),
            ("Core Tech % = Core Techs (60+ days) / Total Techs * 100", styles["legend_text"]),
            ("Rank Gap = Gross Efficiency Rank - Tenure Rank", styles["legend_text"]),
            ("", None),
            ("TENURE CATEGORIES:", styles["legend_section"]),
            ("Core: 60+ days worked in period", styles["legend_text"]),
            ("Reliable: 40-59 days worked", styles["legend_text"]),
            ("Part-Time: 20-39 days worked", styles["legend_text"]),
            ("New/Sporadic: <20 days worked", styles["legend_text"]),
        ]

        for row, (text, fmt) in enumerate(entries):
            if fmt:
                ws.write(row, 0, text, fmt)

    def _write_trend_summary(self, wb, styles, rollups):
        ws = wb.add_worksheet("Trend Summary")
        ws.set_column("A:A", 35)
        ws.set_column("B:H", 14)

        ws.write(0, 0, "TREND SUMMARY - TEAM RANKINGS", styles["title"])
        ws.write(1, 0, "Rank positions and key metrics for trend tracking", styles["subtitle"])

        headers = [
            "Team Name", "Gross Rank", "Net Rank", "Tenure Rank",
            "Rank Gap", "Gross $/Hr", "Net $/Hr", "Core Tech %",
        ]
        for col, h in enumerate(headers):
            ws.write(3, col, h, styles["header"])

        sorted_teams = sorted(rollups, key=lambda r: r.gross_dph, reverse=True)
        for row_idx, team in enumerate(sorted_teams, 4):
            ws.write(row_idx, 0, team.team_name, styles["text"])
            ws.write(row_idx, 1, team.gross_rank, styles["int"])
            ws.write(row_idx, 2, team.net_rank, styles["int"])
            ws.write(row_idx, 3, team.tenure_rank, styles["int"])
            ws.write(row_idx, 4, team.rank_gap, styles["int"])
            ws.write(row_idx, 5, round(team.gross_dph, 2), styles["dec2"])
            ws.write(row_idx, 6, round(team.net_dph, 2), styles["dec2"])
            ws.write(row_idx, 7, round(team.core_tech_pct, 1), styles["pct_raw"])
