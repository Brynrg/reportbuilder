"""Infographic-style PDF report renderer using ReportLab.

Generates polished executive summary PDFs with KPI cards,
ranking tables, trend visuals, and diagnostic callouts.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from ..analytics.engine import TeamRollup

logger = logging.getLogger(__name__)

BRAND_DARK = colors.HexColor("#1a1a2e")
BRAND_ACCENT = colors.HexColor("#16213e")
BRAND_HIGHLIGHT = colors.HexColor("#0f3460")
BRAND_SUCCESS = colors.HexColor("#27ae60")
BRAND_WARNING = colors.HexColor("#f39c12")
BRAND_DANGER = colors.HexColor("#e74c3c")
BRAND_LIGHT = colors.HexColor("#f5f5f5")


def _build_styles():
    base = getSampleStyleSheet()
    styles = {}
    styles["title"] = ParagraphStyle(
        "InfTitle", parent=base["Title"],
        fontSize=22, textColor=BRAND_DARK, spaceAfter=6,
        fontName="Helvetica-Bold",
    )
    styles["subtitle"] = ParagraphStyle(
        "InfSubtitle", parent=base["Normal"],
        fontSize=12, textColor=colors.grey, spaceAfter=12,
        fontName="Helvetica",
    )
    styles["section"] = ParagraphStyle(
        "InfSection", parent=base["Heading2"],
        fontSize=14, textColor=BRAND_DARK, spaceBefore=16, spaceAfter=8,
        fontName="Helvetica-Bold",
    )
    styles["body"] = ParagraphStyle(
        "InfBody", parent=base["Normal"],
        fontSize=10, textColor=colors.black, spaceAfter=4,
        fontName="Helvetica",
    )
    styles["kpi_label"] = ParagraphStyle(
        "KPILabel", parent=base["Normal"],
        fontSize=8, textColor=colors.grey, alignment=TA_CENTER,
        fontName="Helvetica",
    )
    styles["kpi_value"] = ParagraphStyle(
        "KPIValue", parent=base["Normal"],
        fontSize=18, textColor=BRAND_DARK, alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    styles["callout"] = ParagraphStyle(
        "Callout", parent=base["Normal"],
        fontSize=10, textColor=BRAND_HIGHLIGHT,
        fontName="Helvetica-Oblique", leftIndent=12,
    )
    return styles


def generate_executive_pdf(
    rollups: List[TeamRollup],
    avgs: Dict[str, float],
    period_label: str,
    output_dir: str,
    title: str = "Executive Performance Summary",
) -> str:
    """Generate an infographic-style executive summary PDF."""

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Executive_Summary_{ts}.pdf"
    filepath = str(Path(output_dir) / filename)

    doc = SimpleDocTemplate(
        filepath, pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
    )
    styles = _build_styles()
    elements = []

    elements.append(Paragraph(title, styles["title"]))
    elements.append(Paragraph(f"Data Period: {period_label}", styles["subtitle"]))
    elements.append(Spacer(1, 12))

    kpi_data = _build_kpi_cards(rollups, avgs)
    kpi_table = Table(
        [[Paragraph(f"<b>{v}</b>", styles["kpi_value"]) for _, v in kpi_data],
         [Paragraph(label, styles["kpi_label"]) for label, _ in kpi_data]],
        colWidths=[doc.width / len(kpi_data)] * len(kpi_data),
    )
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_LIGHT),
        ("BACKGROUND", (0, 1), (-1, 1), BRAND_LIGHT),
        ("BOX", (0, 0), (-1, -1), 1, BRAND_DARK),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("Top 10 Teams by Gross Efficiency", styles["section"]))
    top10 = sorted(rollups, key=lambda r: r.gross_dph, reverse=True)[:10]
    top_table_data = [["Rank", "Team", "Gross $/Hr", "Net $/Hr", "Hours", "Diagnosis"]]
    for i, r in enumerate(top10, 1):
        top_table_data.append([
            str(i), r.team_name, f"${r.gross_dph:.2f}",
            f"${r.net_dph:.2f}", f"{r.total_hours:,.0f}", r.diagnosis,
        ])
    t = Table(top_table_data, colWidths=[40, 180, 70, 70, 70, 120])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 16))

    elements.append(Paragraph("Diagnostic Distribution", styles["section"]))
    diag_counts = {}
    for r in rollups:
        diag_counts[r.diagnosis] = diag_counts.get(r.diagnosis, 0) + 1
    diag_data = [["Category", "Teams", "% of Total"]]
    for diag, count in sorted(diag_counts.items(), key=lambda x: x[1], reverse=True):
        pct = count / len(rollups) * 100
        diag_data.append([diag, str(count), f"{pct:.1f}%"])
    dt = Table(diag_data, colWidths=[200, 60, 80])
    dt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(dt)
    elements.append(Spacer(1, 16))

    elements.append(Paragraph("Key Concerns", styles["section"]))
    bottom5 = sorted(rollups, key=lambda r: r.gross_dph)[:5]
    for r in bottom5:
        elements.append(Paragraph(
            f"\u2022 <b>{r.team_name}</b>: ${r.gross_dph:.2f}/hr gross, "
            f"Rank #{r.gross_rank}, {r.diagnosis}",
            styles["callout"],
        ))
    elements.append(Spacer(1, 16))

    high_mileage = sorted(rollups, key=lambda r: r.mileage_paid, reverse=True)[:5]
    elements.append(Paragraph("Highest Mileage Burden", styles["section"]))
    for r in high_mileage:
        elements.append(Paragraph(
            f"\u2022 <b>{r.team_name}</b>: ${r.mileage_paid:,.0f} "
            f"({r.mileage_cost_pct:.1f}% of revenue)",
            styles["callout"],
        ))

    elements.append(Spacer(1, 20))
    elements.append(Paragraph(
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
        f"ReportBuilder v1.0",
        styles["kpi_label"],
    ))

    doc.build(elements)
    logger.info("Generated PDF: %s", filename)
    return filepath


def _build_kpi_cards(rollups, avgs):
    total_teams = len(rollups)
    total_techs = sum(r.total_techs for r in rollups)
    total_hours = sum(r.total_hours for r in rollups)
    total_revenue = sum(r.gross_revenue for r in rollups)
    total_mileage = sum(r.mileage_paid for r in rollups)

    return [
        ("Teams", str(total_teams)),
        ("Technicians", f"{total_techs:,}"),
        ("Total Hours", f"{total_hours:,.0f}"),
        ("Gross Revenue", f"${total_revenue:,.0f}"),
        ("Avg Gross $/Hr", f"${avgs.get('avg_gross_dph', 0):.2f}"),
        ("Total Mileage", f"${total_mileage:,.0f}"),
    ]
