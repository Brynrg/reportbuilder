"""Shared test fixtures."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reportbuilder.config import ConfigManager, AppSettings
from reportbuilder.warehouse.models import get_session_factory, Base, create_warehouse_engine
from reportbuilder.warehouse.repository import WarehouseRepository
from reportbuilder.parsing.detector import create_default_registry

DOWNLOADS = Path.home() / "Downloads"
FIXTURE_DTP_ZIP = DOWNLOADS / "2025_DailyTechPerformance.zip"
FIXTURE_MCA_ZIP = DOWNLOADS / "2025_MCA_Snapshot.zip"
FIXTURE_MILEAGE_CSV = DOWNLOADS / "MCA_disbursedmileage_10.1.25_12.31.25.csv"
FIXTURE_TARGET_XLSX = Path.home() / "Desktop" / "Team_Efficiency_Tenure_Ranking_1.xlsx"


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def db_session(tmp_path):
    db_path = str(tmp_path / "test.db")
    sf = get_session_factory(db_path)
    session = sf()
    yield session
    session.close()


@pytest.fixture
def session_factory(tmp_path):
    db_path = str(tmp_path / "test.db")
    return get_session_factory(db_path)


@pytest.fixture
def repo(db_session):
    return WarehouseRepository(db_session)


@pytest.fixture
def config(tmp_path):
    cfg = ConfigManager(str(tmp_path / "settings.json"))
    cfg.settings.app_data_dir = str(tmp_path / "appdata")
    cfg.settings.intake_folder = str(tmp_path / "intake")
    cfg.settings.staging_dir = str(tmp_path / "staging")
    cfg.settings.output_dir = str(tmp_path / "output")
    cfg.settings.db_path = str(tmp_path / "test.db")
    cfg.settings.ai_model_dir = str(tmp_path / "models")
    cfg.settings.resolve_paths()
    cfg.settings.ensure_directories()
    return cfg


@pytest.fixture
def parser_registry():
    return create_default_registry()


def has_fixture(path: Path) -> bool:
    return path.exists()
