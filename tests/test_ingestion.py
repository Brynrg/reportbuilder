"""Tests for ingestion engine: watcher, scanner, ZIP handler."""

import time
from datetime import date
from pathlib import Path

import pytest

from reportbuilder.ingestion.watcher import (
    FolderWatcher, StabilizationTracker, is_supported_file, file_hash,
)
from reportbuilder.ingestion.zip_handler import inspect_zip, extract_zip
from reportbuilder.ingestion.scanner import IngestOrchestrator
from reportbuilder.parsing.detector import create_default_registry

DOWNLOADS = Path.home() / "Downloads"
FIXTURE_DTP_ZIP = DOWNLOADS / "2025_DailyTechPerformance.zip"
FIXTURE_MILEAGE_CSV = DOWNLOADS / "MCA_disbursedmileage_10.1.25_12.31.25.csv"

def has_fixture(path: Path) -> bool:
    return path.exists()


class TestSupportedFiles:

    def test_xlsx(self):
        assert is_supported_file(Path("report.xlsx"))

    def test_csv(self):
        assert is_supported_file(Path("data.csv"))

    def test_zip(self):
        assert is_supported_file(Path("archive.zip"))

    def test_xlsm(self):
        assert is_supported_file(Path("macro.xlsm"))

    def test_unsupported(self):
        assert not is_supported_file(Path("readme.txt"))

    def test_temp_file(self):
        assert not is_supported_file(Path("~$temp.xlsx"))


class TestStabilizationTracker:

    def test_touch_and_stable(self):
        tracker = StabilizationTracker(stabilization_seconds=0.1)
        tracker.touch("/test/file.xlsx")
        assert tracker.pending_count == 1

        time.sleep(0.15)
        stable = tracker.get_stable_files()
        assert len(stable) == 1
        assert stable[0] == "/test/file.xlsx"

    def test_not_stable_yet(self):
        tracker = StabilizationTracker(stabilization_seconds=10.0)
        tracker.touch("/test/file.xlsx")
        stable = tracker.get_stable_files()
        assert len(stable) == 0


class TestFileHash:

    def test_hash_consistency(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h1 = file_hash(f)
        h2 = file_hash(f)
        assert h1 == h2
        assert len(h1) == 64

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")
        assert file_hash(f1) != file_hash(f2)


class TestFolderWatcher:

    def test_scan_existing(self, tmp_path):
        (tmp_path / "report.xlsx").write_text("fake")
        (tmp_path / "data.csv").write_text("fake")
        (tmp_path / "readme.txt").write_text("fake")

        watcher = FolderWatcher(str(tmp_path), on_file_ready=lambda f: None)
        found = watcher.scan_existing()
        assert len(found) == 2

    def test_nonexistent_folder(self):
        watcher = FolderWatcher("/nonexistent/path", on_file_ready=lambda f: None)
        found = watcher.scan_existing()
        assert len(found) == 0


class TestIngestOrchestrator:

    @pytest.mark.skipif(not has_fixture(FIXTURE_MILEAGE_CSV), reason="Mileage CSV needed")
    def test_process_csv_file(self, session_factory, tmp_path):
        registry = create_default_registry()
        orchestrator = IngestOrchestrator(session_factory, str(tmp_path / "staging"), registry)
        result = orchestrator.process_file(str(FIXTURE_MILEAGE_CSV))
        assert result is True

    @pytest.mark.skipif(not has_fixture(FIXTURE_DTP_ZIP), reason="DTP ZIP needed")
    def test_process_zip(self, session_factory, tmp_path):
        registry = create_default_registry()
        orchestrator = IngestOrchestrator(session_factory, str(tmp_path / "staging"), registry)
        result = orchestrator.process_file(str(FIXTURE_DTP_ZIP))
        assert result is True
