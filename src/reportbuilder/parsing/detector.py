"""Report family detection and parser factory."""

from __future__ import annotations

from .base import ParserRegistry
from .daily_tech_performance import DailyTechPerformanceParser
from .mca_snapshot import MCASnapshotParser
from .mileage_csv import MileageCSVParser


def create_default_registry() -> ParserRegistry:
    """Create a parser registry with all built-in parsers."""
    registry = ParserRegistry()
    registry.register(DailyTechPerformanceParser())
    registry.register(MCASnapshotParser())
    registry.register(MileageCSVParser())
    return registry
