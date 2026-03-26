"""Base parser interface and parser registry."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..warehouse.repository import WarehouseRepository

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """Base class for report family parsers."""

    @property
    @abstractmethod
    def family_name(self) -> str:
        """Canonical name of the report family this parser handles."""
        ...

    @abstractmethod
    def can_parse(self, filepath: str) -> float:
        """Return confidence score 0.0-1.0 that this parser can handle the file."""
        ...

    @abstractmethod
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        """Parse the file and return normalized record dicts."""
        ...

    @abstractmethod
    def normalize_and_store(self, records: List[Dict], repo: WarehouseRepository,
                           source_file_id: int, run_id: int) -> int:
        """Normalize parsed records and store as observations. Returns count."""
        ...


class ParserRegistry:
    """Registry of all available parsers. Detects which parser to use for a file."""

    def __init__(self):
        self._parsers: List[BaseParser] = []

    def register(self, parser: BaseParser) -> None:
        self._parsers.append(parser)
        logger.debug("Registered parser: %s", parser.family_name)

    def detect_and_get_parser(self, filepath: str) -> Optional[BaseParser]:
        best_parser = None
        best_confidence = 0.0
        for parser in self._parsers:
            try:
                confidence = parser.can_parse(filepath)
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_parser = parser
            except Exception:
                logger.debug("Parser %s failed detection for %s",
                           parser.family_name, filepath)
        if best_confidence >= 0.3:
            logger.info("Detected %s (%.0f%%) for %s",
                       best_parser.family_name, best_confidence * 100,
                       Path(filepath).name)
            return best_parser
        return None

    @property
    def parsers(self) -> List[BaseParser]:
        return list(self._parsers)
