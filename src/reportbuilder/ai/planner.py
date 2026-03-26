"""AI planner: converts natural language requests to structured report plans.

Provider abstraction with fallback to deterministic parser.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .schemas import PLANNER_SYSTEM_PROMPT, validate_plan

logger = logging.getLogger(__name__)


class PlannerProvider(ABC):
    """Abstract interface for AI planner providers."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def generate_plan(self, user_query: str) -> Dict[str, Any]: ...


class ONNXPlannerProvider(PlannerProvider):
    """Local ONNX model planner provider using transformers + onnxruntime."""

    @property
    def name(self) -> str:
        return "local_onnx"

    def __init__(self, model_dir: str):
        self._model_dir = model_dir
        self._session = None
        self._tokenizer = None

    def is_available(self) -> bool:
        try:
            from pathlib import Path
            model_path = Path(self._model_dir)
            if not model_path.exists():
                return False
            model_files = list(model_path.glob("*.onnx"))
            return len(model_files) > 0
        except Exception:
            return False

    def load(self) -> bool:
        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer
            from pathlib import Path

            model_path = Path(self._model_dir)
            onnx_files = list(model_path.glob("*.onnx"))
            if not onnx_files:
                logger.warning("No ONNX model files found in %s", self._model_dir)
                return False

            self._session = ort.InferenceSession(str(onnx_files[0]))
            self._tokenizer = AutoTokenizer.from_pretrained(str(model_path))
            logger.info("ONNX planner model loaded from %s", model_path)
            return True
        except Exception as e:
            logger.warning("Failed to load ONNX planner: %s", e)
            return False

    def generate_plan(self, user_query: str) -> Dict[str, Any]:
        if not self._session or not self._tokenizer:
            if not self.load():
                raise RuntimeError("ONNX model not available")

        prompt = f"{PLANNER_SYSTEM_PROMPT}\n\nUser request: {user_query}\n\nJSON plan:"

        inputs = self._tokenizer(prompt, return_tensors="np", max_length=512, truncation=True)
        input_names = [inp.name for inp in self._session.get_inputs()]
        feed = {name: inputs[name] for name in input_names if name in inputs}

        outputs = self._session.run(None, feed)
        generated_ids = outputs[0]
        text = self._tokenizer.decode(generated_ids[0], skip_special_tokens=True)

        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            plan = json.loads(json_match.group())
            valid, errors = validate_plan(plan)
            if valid:
                return plan
            logger.warning("ONNX plan validation errors: %s", errors)

        raise ValueError("ONNX model did not produce valid JSON plan")


class DeterministicFallbackParser(PlannerProvider):
    """Rule-based fallback that parses common query patterns without AI."""

    @property
    def name(self) -> str:
        return "deterministic_fallback"

    def is_available(self) -> bool:
        return True

    TREND_SUPPORTING_TEMPLATES = {"trend_focus_pack"}

    def generate_plan(self, user_query: str) -> Dict[str, Any]:
        query = user_query.lower().strip()
        plan = {
            "intent": "generate_report",
            "report_template": "team_efficiency_tenure_pack",
            "entity_scope": {"type": "all_teams"},
            "period_mode": "latest_complete_period",
            "metrics": [],
            "trend_options": {"include_trends": False},
            "output_formats": ["excel"],
            "filters": [],
            "sorts": [{"field": "gross_dollars_per_hour", "direction": "desc"}],
            "narrative_style": "executive",
        }

        if any(w in query for w in ["pdf", "infographic", "executive summary"]):
            plan["output_formats"] = ["pdf"]
            plan["report_template"] = "executive_infographic_pdf"

        if any(w in query for w in ["trend", "over time", "movement", "trajectory"]):
            plan["trend_options"] = {
                "include_trends": True,
                "comparison_mode": "week_over_week",
                "rolling_windows": [4, 8],
            }
            plan["report_template"] = "trend_focus_pack"

        if any(w in query for w in ["snapshot", "vs performance", "cross-report", "comparison"]):
            plan["report_template"] = "snapshot_vs_performance_pack"
            plan["entity_scope"] = {"type": "cid"}

        if any(w in query for w in ["efficiency", "tenure", "ranking"]):
            plan["report_template"] = "team_efficiency_tenure_pack"

        if "excel" in query and "pdf" in query:
            plan["output_formats"] = ["excel", "pdf"]
        elif "pdf" in query:
            plan["output_formats"] = ["pdf"]
        elif "excel" in query:
            plan["output_formats"] = ["excel"]

        if any(w in query for w in ["mileage", "miles"]):
            plan["metrics"].append("mileage_paid")
            plan["metrics"].append("total_miles")

        if any(w in query for w in ["revenue", "dollar", "efficiency"]):
            plan["metrics"].extend(["gross_revenue", "gross_dollars_per_hour",
                                     "net_revenue", "net_dollars_per_hour"])

        if any(w in query for w in ["technician", "tech detail", "individual"]):
            plan["entity_scope"] = {"type": "technician"}

        if any(w in query for w in ["cid", "store", "location"]):
            plan["entity_scope"] = {"type": "cid"}

        date_match = re.search(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})', query)
        if date_match:
            plan["period_mode"] = "specific_dates"

        if plan["trend_options"].get("include_trends") and \
                plan["report_template"] not in self.TREND_SUPPORTING_TEMPLATES:
            plan["report_template"] = "trend_focus_pack"

        return plan


class ReportPlanner:
    """Main planner that tries providers in order with fallback."""

    def __init__(self, model_dir: str = ""):
        self._providers: List[PlannerProvider] = []
        if model_dir:
            self._providers.append(ONNXPlannerProvider(model_dir))
        self._providers.append(DeterministicFallbackParser())

    def plan(self, user_query: str) -> Dict[str, Any]:
        for provider in self._providers:
            if not provider.is_available():
                logger.debug("Planner provider %s not available", provider.name)
                continue
            try:
                plan = provider.generate_plan(user_query)
                plan["_provider"] = provider.name
                logger.info("Plan generated by %s for: %s", provider.name,
                          user_query[:80])
                return plan
            except Exception as e:
                logger.warning("Provider %s failed: %s", provider.name, e)
                continue
        return {
            "intent": "generate_report",
            "report_template": "team_efficiency_tenure_pack",
            "entity_scope": {"type": "all_teams"},
            "period_mode": "latest_complete_period",
            "output_formats": ["excel"],
            "_provider": "hardcoded_default",
        }

    @property
    def active_provider(self) -> Optional[str]:
        for p in self._providers:
            if p.is_available():
                return p.name
        return None
