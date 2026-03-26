"""Entity, period, and metric resolution utilities.

Handles normalization of raw parsed values into canonical warehouse records.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from ..warehouse.repository import WarehouseRepository


TEAM_NAME_NORMALIZATIONS = {
    r"\s+": " ",
    r"\s*=\s*": " = ",
}


def normalize_team_name(raw: str) -> str:
    """Normalize team name to canonical form."""
    name = raw.strip()
    for pattern, replacement in TEAM_NAME_NORMALIZATIONS.items():
        name = re.sub(pattern, replacement, name)
    return name


def normalize_technician_name(raw: str) -> str:
    """Normalize technician name."""
    name = raw.strip()
    name = re.sub(r"\s+", " ", name)
    return name


def detect_period_type(start: date, end: date) -> str:
    """Detect period type from date range."""
    delta = (end - start).days
    if delta == 0:
        return "day"
    elif delta <= 7:
        return "week"
    elif delta <= 31:
        return "month"
    elif delta <= 93:
        return "quarter"
    return "custom"


def build_period_label(start: date, end: date, period_type: str = None) -> str:
    if not period_type:
        period_type = detect_period_type(start, end)
    if period_type == "day":
        return start.strftime("%Y-%m-%d")
    elif period_type == "week":
        return f"Week {start.isocalendar()[1]} ({start.strftime('%m/%d')}-{end.strftime('%m/%d')})"
    elif period_type == "month":
        return start.strftime("%B %Y")
    elif period_type == "quarter":
        q = (start.month - 1) // 3 + 1
        return f"Q{q} {start.year}"
    return f"{start.strftime('%m/%d/%Y')}-{end.strftime('%m/%d/%Y')}"


def find_containing_periods(target_start: date, target_end: date,
                             repo: WarehouseRepository) -> list:
    """Find periods that contain the target range."""
    from ..warehouse.models import Period
    from sqlalchemy import and_
    return (
        repo.session.query(Period)
        .filter(and_(Period.start_date <= target_start, Period.end_date >= target_end))
        .all()
    )


def find_adjacent_periods_by_type(period_type: str, ref_start: date,
                                   repo: WarehouseRepository, n: int = 4) -> list:
    """Find N adjacent periods of the same type before and after."""
    from ..warehouse.models import Period
    before = (
        repo.session.query(Period)
        .filter(Period.period_type == period_type, Period.end_date < ref_start)
        .order_by(Period.start_date.desc())
        .limit(n)
        .all()
    )
    after = (
        repo.session.query(Period)
        .filter(Period.period_type == period_type, Period.start_date > ref_start)
        .order_by(Period.start_date.asc())
        .limit(n)
        .all()
    )
    return list(reversed(before)) + after


CANONICAL_METRICS: Dict[str, Dict] = {
    "hours": {"display": "Hours Worked", "unit": "hours", "agg": "sum"},
    "units": {"display": "Units Completed", "unit": "count", "agg": "sum"},
    "gross_revenue": {"display": "Gross Revenue", "unit": "dollars", "agg": "sum"},
    "gross_dollars_per_hour": {"display": "Gross $/Hr", "unit": "dollars/hour", "agg": "avg"},
    "net_revenue": {"display": "Net Revenue", "unit": "dollars", "agg": "sum"},
    "net_dollars_per_hour": {"display": "Net $/Hr", "unit": "dollars/hour", "agg": "avg"},
    "mileage_paid": {"display": "Mileage Paid", "unit": "dollars", "agg": "sum"},
    "total_miles": {"display": "Total Miles", "unit": "miles", "agg": "sum"},
    "commission_rate": {"display": "Commission Rate", "unit": "rate", "agg": "avg"},
    "units_per_hour": {"display": "Units/Hour", "unit": "rate", "agg": "avg"},
    "total_active_requests": {"display": "Active Requests", "unit": "count", "agg": "sum"},
    "total_remaining_requests": {"display": "Remaining Requests", "unit": "count", "agg": "sum"},
    "wtd_build": {"display": "WTD Build", "unit": "count", "agg": "sum"},
    "wtd_invoice_amount": {"display": "WTD Invoice Amount", "unit": "dollars", "agg": "sum"},
    "mtd_invoice_amount": {"display": "MTD Invoice Amount", "unit": "dollars", "agg": "sum"},
    "ytd_invoice_amount": {"display": "YTD Invoice Amount", "unit": "dollars", "agg": "sum"},
    "on_time_pct": {"display": "On Time %", "unit": "percent", "agg": "avg"},
    "missed_events": {"display": "Missed Events", "unit": "count", "agg": "sum"},
    "late_sces": {"display": "Late SCEs", "unit": "count", "agg": "sum"},
    "days_worked": {"display": "Days Worked", "unit": "days", "agg": "sum"},
}


METRIC_ALIASES: Dict[str, str] = {
    "Total Hours": "hours",
    "Hours": "hours",
    "Amount": "gross_revenue",
    "Revenue": "gross_revenue",
    "Gross Revenue": "gross_revenue",
    "Dollar/Hour": "gross_dollars_per_hour",
    "Dollars Per Hour": "gross_dollars_per_hour",
    "Units": "units",
    "Total Mileage": "total_miles",
    "Total Amount": "mileage_paid",
    "Mileage Paid": "mileage_paid",
}


def resolve_metric_name(raw_name: str) -> str:
    """Resolve a raw metric name to canonical form."""
    if raw_name in CANONICAL_METRICS:
        return raw_name
    if raw_name in METRIC_ALIASES:
        return METRIC_ALIASES[raw_name]
    normalized = raw_name.lower().replace(" ", "_")
    if normalized in CANONICAL_METRICS:
        return normalized
    return raw_name
