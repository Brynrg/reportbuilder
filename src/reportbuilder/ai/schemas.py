"""Schemas for AI planner structured outputs and report request validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

VALID_TEMPLATES = [
    "team_efficiency_tenure_pack",
    "snapshot_vs_performance_pack",
    "executive_infographic_pdf",
    "trend_focus_pack",
]

VALID_INTENTS = [
    "generate_report",
    "explore_data",
    "compare_periods",
    "trend_analysis",
    "list_entities",
    "summarize",
]

VALID_OUTPUT_FORMATS = ["excel", "pdf"]

VALID_ENTITY_TYPES = [
    "all_teams", "team", "technician", "cid", "store",
    "rvp", "region", "district",
]

VALID_PERIOD_MODES = [
    "latest_complete_period",
    "specific_dates",
    "last_n_weeks",
    "last_n_months",
    "year_to_date",
    "quarter_to_date",
    "month_to_date",
    "custom_range",
]

VALID_COMPARISON_MODES = [
    "week_over_week",
    "month_over_month",
    "quarter_over_quarter",
    "rolling_window",
    "year_over_year",
]

PLANNER_SYSTEM_PROMPT = """You are a report planning assistant for a field service operations analytics platform.

Your job is to convert plain-English user requests into structured JSON report plans.
You MUST output ONLY valid JSON. No prose, no explanation, no markdown.

Available report templates:
- team_efficiency_tenure_pack: Teams ranked by gross/net efficiency, tenure stability, diagnostics, individual tech detail, mileage analysis
- snapshot_vs_performance_pack: Cross-report join of MCA Snapshot and Daily Tech Performance data
- executive_infographic_pdf: Polished executive summary PDF with KPIs, rankings, and diagnostics
- trend_focus_pack: Dedicated trend analysis workbook with period-over-period changes, rolling windows, rank movement

Available metrics: hours, units, gross_revenue, gross_dollars_per_hour, net_revenue, net_dollars_per_hour, mileage_paid, total_miles, days_worked, total_active_requests, total_remaining_requests, wtd_build, mtd_invoice_amount, ytd_invoice_amount, on_time_pct, missed_events, late_sces

Output format:
{
  "intent": "generate_report",
  "report_template": "<template_name>",
  "entity_scope": {"type": "all_teams"},
  "period_mode": "latest_complete_period",
  "period_start": "YYYY-MM-DD" (optional),
  "period_end": "YYYY-MM-DD" (optional),
  "metrics": ["metric1", "metric2"],
  "trend_options": {
    "include_trends": true/false,
    "comparison_mode": "week_over_week",
    "rolling_windows": [4, 8]
  },
  "output_formats": ["excel", "pdf"],
  "filters": [],
  "sorts": [{"field": "gross_dollars_per_hour", "direction": "desc"}],
  "narrative_style": "executive"
}
"""


def validate_plan(plan: Dict[str, Any]) -> tuple[bool, List[str]]:
    """Validate a report plan dict. Returns (is_valid, list_of_errors)."""
    errors = []

    if plan.get("intent") not in VALID_INTENTS:
        errors.append(f"Invalid intent: {plan.get('intent')}")

    template = plan.get("report_template", "")
    if template and template not in VALID_TEMPLATES:
        errors.append(f"Unknown template: {template}")

    for fmt in plan.get("output_formats", []):
        if fmt not in VALID_OUTPUT_FORMATS:
            errors.append(f"Invalid output format: {fmt}")

    scope = plan.get("entity_scope", {})
    if isinstance(scope, dict):
        etype = scope.get("type", "")
        if etype and etype not in VALID_ENTITY_TYPES:
            errors.append(f"Invalid entity scope type: {etype}")

    return len(errors) == 0, errors
