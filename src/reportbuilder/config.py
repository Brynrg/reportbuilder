"""Application configuration and persistent settings management."""

from __future__ import annotations

import json
import logging
import os
import platform
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _default_app_data_dir() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "ReportBuilder"
    elif system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "ReportBuilder"
    return Path.home() / ".reportbuilder"


def _pointer_file_path() -> Path:
    """Fixed-location pointer that tells the app where the real settings live.

    Always at the platform default regardless of where the user moved app_data.
    """
    return _default_app_data_dir() / "settings_pointer.json"


def _read_settings_pointer() -> Optional[str]:
    """Read the settings pointer file and return the actual settings path, or None."""
    pf = _pointer_file_path()
    if not pf.exists():
        return None
    try:
        with open(pf, "r") as f:
            data = json.load(f)
        path = data.get("settings_path")
        if path and Path(path).exists():
            return path
        logger.warning("Pointer references missing file: %s", path)
        return None
    except Exception as e:
        logger.warning("Failed to read settings pointer: %s", e)
        return None


def _write_settings_pointer(settings_path: str) -> None:
    """Atomically update the pointer file at the default platform location.

    Best-effort: if the directory cannot be created (e.g. sandbox, permissions)
    the failure is logged but does not block normal operation.
    """
    pf = _pointer_file_path()
    tmp = pf.with_suffix(".tmp")
    try:
        pf.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w") as f:
            json.dump({"settings_path": settings_path}, f, indent=2)
        tmp.replace(pf)
    except Exception as e:
        logger.warning("Failed to write settings pointer: %s", e)
        try:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _default_intake_folder() -> str:
    return str(Path.home() / "Desktop" / "M&C DAILY DOWNLOADS")


@dataclass
class AppSettings:
    intake_folder: str = ""
    app_data_dir: str = ""
    staging_dir: str = ""
    output_dir: str = ""
    db_path: str = ""
    ai_model_dir: str = ""
    ai_provider: str = "local_onnx"
    setup_complete: bool = False
    watcher_enabled: bool = True
    reconciliation_interval_minutes: int = 30
    file_stabilization_seconds: int = 5
    log_level: str = "INFO"

    def resolve_paths(self) -> None:
        if not self.app_data_dir:
            self.app_data_dir = str(_default_app_data_dir())
        base = Path(self.app_data_dir)
        if not self.staging_dir:
            self.staging_dir = str(base / "staging")
        if not self.output_dir:
            self.output_dir = str(base / "output")
        if not self.db_path:
            self.db_path = str(base / "warehouse.db")
        if not self.ai_model_dir:
            self.ai_model_dir = str(base / "models")
        if not self.intake_folder:
            self.intake_folder = _default_intake_folder()

    def rederive_from_app_data(self) -> None:
        """Re-derive all sub-paths from app_data_dir.

        Call this when app_data_dir changes to ensure staging, output, db,
        and model paths follow the new base instead of pointing at stale locations.
        Only overrides paths that were under the old app_data_dir (i.e. defaults).
        """
        if not self.app_data_dir:
            self.app_data_dir = str(_default_app_data_dir())
        base = Path(self.app_data_dir)
        self.staging_dir = str(base / "staging")
        self.output_dir = str(base / "output")
        self.db_path = str(base / "warehouse.db")
        self.ai_model_dir = str(base / "models")

    def ensure_directories(self) -> None:
        for d in [self.app_data_dir, self.staging_dir, self.output_dir, self.ai_model_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)


class ConfigManager:
    """Loads and saves AppSettings to a JSON file in the app data directory.

    On construction with no explicit config_path, the manager checks a
    fixed-location pointer file at the platform default directory.  If the
    pointer exists and references a valid settings file, that file is used.
    Otherwise the manager falls back to the default path.  Every save()
    updates the pointer so restarts always find the current settings.
    """

    def __init__(self, config_path: Optional[str] = None):
        self._settings = AppSettings()
        self._settings.resolve_paths()
        self._explicit_config_path = config_path

        if config_path:
            self._config_path = Path(config_path)
        else:
            pointed = _read_settings_pointer()
            if pointed:
                self._config_path = Path(pointed)
            else:
                self._config_path = Path(self._settings.app_data_dir) / "settings.json"

    @property
    def settings(self) -> AppSettings:
        return self._settings

    @property
    def config_path(self) -> Path:
        return self._config_path

    def _sync_config_path(self) -> None:
        """Keep config_path aligned with app_data_dir unless explicitly overridden."""
        if not self._explicit_config_path:
            self._config_path = Path(self._settings.app_data_dir) / "settings.json"

    def load(self) -> AppSettings:
        if self._config_path.exists():
            with open(self._config_path, "r") as f:
                data = json.load(f)
            for key, val in data.items():
                if hasattr(self._settings, key):
                    setattr(self._settings, key, val)
        self._settings.resolve_paths()
        self._sync_config_path()
        return self._settings

    def save(self) -> None:
        self._sync_config_path()
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w") as f:
            json.dump(asdict(self._settings), f, indent=2)
        _write_settings_pointer(str(self._config_path))

    def update(self, **kwargs) -> None:
        for key, val in kwargs.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, val)
        self.save()

    def apply_app_data_change(self, new_app_data_dir: str) -> None:
        """Change app_data_dir and re-derive all dependent paths.

        This is an explicit relocation: config_path follows the new app_data_dir
        regardless of whether an explicit config_path was provided at construction.
        The pointer file is updated immediately so a crash before save() is safe.
        """
        self._settings.app_data_dir = new_app_data_dir
        self._settings.rederive_from_app_data()
        self._explicit_config_path = None
        self._sync_config_path()
        _write_settings_pointer(str(self._config_path))

    def is_setup_complete(self) -> bool:
        return self._settings.setup_complete

    def default_intake_suggestion(self) -> str:
        return _default_intake_folder()
