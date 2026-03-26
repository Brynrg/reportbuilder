"""Tests for configuration management."""

from pathlib import Path
from reportbuilder.config import ConfigManager, AppSettings


class TestAppSettings:

    def test_defaults(self):
        s = AppSettings()
        s.resolve_paths()
        assert s.app_data_dir != ""
        assert s.intake_folder != ""

    def test_ensure_directories(self, tmp_path):
        s = AppSettings()
        s.app_data_dir = str(tmp_path / "appdata")
        s.staging_dir = str(tmp_path / "staging")
        s.output_dir = str(tmp_path / "output")
        s.ai_model_dir = str(tmp_path / "models")
        s.ensure_directories()
        assert Path(s.staging_dir).exists()
        assert Path(s.output_dir).exists()


class TestConfigManager:

    def test_save_and_load(self, tmp_path):
        cfg = ConfigManager(str(tmp_path / "settings.json"))
        cfg.settings.intake_folder = "/test/intake"
        cfg.save()

        cfg2 = ConfigManager(str(tmp_path / "settings.json"))
        cfg2.load()
        assert cfg2.settings.intake_folder == "/test/intake"

    def test_update(self, tmp_path):
        cfg = ConfigManager(str(tmp_path / "settings.json"))
        cfg.update(intake_folder="/new/path", setup_complete=True)

        cfg2 = ConfigManager(str(tmp_path / "settings.json"))
        cfg2.load()
        assert cfg2.settings.intake_folder == "/new/path"
        assert cfg2.settings.setup_complete is True

    def test_setup_incomplete_by_default(self, tmp_path):
        cfg = ConfigManager(str(tmp_path / "settings.json"))
        assert not cfg.is_setup_complete()

    def test_default_intake_suggestion(self, tmp_path):
        cfg = ConfigManager(str(tmp_path / "settings.json"))
        suggestion = cfg.default_intake_suggestion()
        assert "DAILY DOWNLOADS" in suggestion or "Desktop" in suggestion
