"""Report template registry, plan validation, and execution."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..warehouse.repository import WarehouseRepository

logger = logging.getLogger(__name__)


@dataclass
class ReportPlan:
    intent: str = "generate_report"
    report_template: str = ""
    entity_scope: Dict[str, Any] = field(default_factory=lambda: {"type": "all_teams"})
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    period_mode: str = "latest_complete_period"
    metrics: List[str] = field(default_factory=list)
    trend_options: Dict[str, Any] = field(default_factory=dict)
    output_formats: List[str] = field(default_factory=lambda: ["excel"])
    filters: List[Dict] = field(default_factory=list)
    sorts: List[Dict] = field(default_factory=list)
    narrative_style: str = "executive"
    team_merges: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        d = {
            "intent": self.intent,
            "report_template": self.report_template,
            "entity_scope": self.entity_scope,
            "period_mode": self.period_mode,
            "metrics": self.metrics,
            "trend_options": self.trend_options,
            "output_formats": self.output_formats,
            "filters": self.filters,
            "sorts": self.sorts,
            "narrative_style": self.narrative_style,
        }
        if self.period_start:
            d["period_start"] = self.period_start.isoformat()
        if self.period_end:
            d["period_end"] = self.period_end.isoformat()
        if self.team_merges:
            d["team_merges"] = self.team_merges
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> ReportPlan:
        plan = cls()
        for key, val in d.items():
            if key in ("period_start", "period_end") and isinstance(val, str):
                val = date.fromisoformat(val)
            if hasattr(plan, key):
                setattr(plan, key, val)
        return plan

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


class ReportTemplate:
    """Base class for report templates."""

    name: str = ""
    description: str = ""
    supported_formats: List[str] = ["excel"]
    supported_entity_scopes: List[str] = ["all_teams"]
    supports_trends: bool = False

    @staticmethod
    def resolve_period(session: Session,
                       start: Optional[date],
                       end: Optional[date]) -> tuple:
        """Return (start, end) dates for a report.

        If the plan provides explicit dates, use them.  Otherwise query the
        warehouse for the actual data range and fall back to the last 90 days.
        """
        if start and end:
            return start, end
        from ..warehouse.models import Period
        from sqlalchemy import func as sa_func
        row = session.query(
            sa_func.min(Period.start_date),
            sa_func.max(Period.end_date),
        ).first()
        if row and row[0] and row[1]:
            return row[0], row[1]
        from datetime import timedelta
        today = date.today()
        return today - timedelta(days=90), today

    def generate(self, plan: ReportPlan, session: Session,
                 output_dir: str) -> List[str]:
        raise NotImplementedError


@dataclass
class CapabilityCheck:
    """Result of validating a plan against registry capabilities."""
    supported: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        parts = []
        if self.errors:
            parts.append("Unsupported: " + "; ".join(self.errors))
        if self.warnings:
            parts.append("Warnings: " + "; ".join(self.warnings))
        if self.suggestions:
            parts.append("Try: " + "; ".join(self.suggestions))
        return " | ".join(parts) if parts else "Plan is executable."


class TemplateRegistry:
    """Registry of available report templates with capability validation."""

    def __init__(self):
        self._templates: Dict[str, ReportTemplate] = {}

    def register(self, template: ReportTemplate) -> None:
        self._templates[template.name] = template
        logger.info("Registered template: %s", template.name)

    def get(self, name: str) -> Optional[ReportTemplate]:
        return self._templates.get(name)

    def list_templates(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "formats": t.supported_formats,
                "entity_scopes": t.supported_entity_scopes,
                "supports_trends": t.supports_trends,
            }
            for t in self._templates.values()
        ]

    def validate_plan(self, plan: ReportPlan) -> CapabilityCheck:
        """Validate a plan against actual registered capabilities.

        Returns a CapabilityCheck indicating whether execution would succeed,
        with clear errors for unsupported requests and suggestions for alternatives.
        """
        errors = []
        warnings = []
        suggestions = []

        template = self.get(plan.report_template)
        if not template:
            available = list(self._templates.keys())
            errors.append(f"Template '{plan.report_template}' is not available")
            if available:
                suggestions.append(f"Available templates: {', '.join(available)}")
            return CapabilityCheck(
                supported=False, errors=errors, suggestions=suggestions
            )

        unsupported_fmts = [
            f for f in plan.output_formats if f not in template.supported_formats
        ]
        if unsupported_fmts:
            errors.append(
                f"Output format(s) {unsupported_fmts} not supported by "
                f"'{template.name}' (supported: {template.supported_formats})"
            )

        scope_type = plan.entity_scope.get("type", "all_teams") if isinstance(plan.entity_scope, dict) else "all_teams"
        if scope_type not in template.supported_entity_scopes:
            errors.append(
                f"Entity scope '{scope_type}' not supported by '{template.name}' "
                f"(supported: {template.supported_entity_scopes})"
            )
            matching = [
                t.name for t in self._templates.values()
                if scope_type in t.supported_entity_scopes
            ]
            if matching:
                suggestions.append(
                    f"Templates supporting '{scope_type}': {', '.join(matching)}"
                )

        wants_trends = plan.trend_options.get("include_trends", False)
        if wants_trends and not template.supports_trends:
            warnings.append(
                f"Trend options requested but '{template.name}' does not support "
                f"dedicated trend analysis. Trends will be basic/omitted."
            )
            trend_templates = [
                t.name for t in self._templates.values() if t.supports_trends
            ]
            if trend_templates:
                suggestions.append(
                    f"For trend analysis, use: {', '.join(trend_templates)}"
                )

        return CapabilityCheck(
            supported=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
        )

    def execute_plan(self, plan: ReportPlan, session: Session,
                     output_dir: str) -> List[str]:
        """Execute a validated plan. Raises ValueError if unsupported.

        After successful generation, records each output as an OutputArtifact
        in the warehouse for lineage tracking.
        """
        check = self.validate_plan(plan)
        if not check.supported:
            raise ValueError(f"Cannot execute plan: {check.message}")

        if check.warnings:
            logger.warning("Plan warnings: %s", check.warnings)

        template = self.get(plan.report_template)
        outputs = template.generate(plan, session, output_dir)

        repo = WarehouseRepository(session)
        period_label = None
        if plan.period_start and plan.period_end:
            period_label = f"{plan.period_start} to {plan.period_end}"
        for filepath in outputs:
            p = Path(filepath)
            fmt = p.suffix.lstrip(".").lower() or "unknown"
            repo.record_artifact(
                filename=p.name,
                filepath=str(p),
                artifact_type=fmt,
                template_name=plan.report_template,
                report_plan=plan.to_json(),
                period_label=period_label,
            )
        session.commit()

        return outputs
