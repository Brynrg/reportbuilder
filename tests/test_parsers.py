"""Tests for report family parsers."""

import os
from pathlib import Path

import pytest

from reportbuilder.parsing.daily_tech_performance import DailyTechPerformanceParser
from reportbuilder.parsing.mca_snapshot import MCASnapshotParser
from reportbuilder.parsing.mileage_csv import MileageCSVParser
from reportbuilder.parsing.detector import create_default_registry
from reportbuilder.ingestion.zip_handler import inspect_zip, extract_zip

DOWNLOADS = Path.home() / "Downloads"
FIXTURE_DTP_ZIP = DOWNLOADS / "2025_DailyTechPerformance.zip"
FIXTURE_MCA_ZIP = DOWNLOADS / "2025_MCA_Snapshot.zip"
FIXTURE_MILEAGE_CSV = DOWNLOADS / "MCA_disbursedmileage_10.1.25_12.31.25.csv"

def has_fixture(path: Path) -> bool:
    return path.exists()


class TestDailyTechPerformanceParser:

    def test_family_name(self):
        parser = DailyTechPerformanceParser()
        assert parser.family_name == "daily_tech_performance"

    @pytest.mark.skipif(not has_fixture(FIXTURE_DTP_ZIP), reason="DTP ZIP not available")
    def test_detect_from_zip_member(self, tmp_path):
        extracted = extract_zip(str(FIXTURE_DTP_ZIP), str(tmp_path))
        assert len(extracted) > 0

        parser = DailyTechPerformanceParser()
        first_file = extracted[0][0]
        confidence = parser.can_parse(first_file)
        assert confidence >= 0.5

    @pytest.mark.skipif(not has_fixture(FIXTURE_DTP_ZIP), reason="DTP ZIP not available")
    def test_parse_records(self, tmp_path):
        extracted = extract_zip(str(FIXTURE_DTP_ZIP), str(tmp_path))
        parser = DailyTechPerformanceParser()

        oct_files = [e for e in extracted if "10.1.25" in e[0]]
        if not oct_files:
            oct_files = extracted[:1]

        records = parser.parse(oct_files[0][0])
        assert len(records) > 0

        rec = records[0]
        assert "technician" in rec
        assert "hours" in rec
        assert "technician_team" in rec

    @pytest.mark.skipif(not has_fixture(FIXTURE_DTP_ZIP), reason="DTP ZIP not available")
    def test_normalize_and_store(self, tmp_path, repo):
        extracted = extract_zip(str(FIXTURE_DTP_ZIP), str(tmp_path))
        parser = DailyTechPerformanceParser()
        records = parser.parse(extracted[0][0])

        sf = repo.register_source_file(
            filepath=extracted[0][0], filename=Path(extracted[0][0]).name,
        )
        run = repo.start_ingest_run("test")
        repo.session.flush()

        count = parser.normalize_and_store(records, repo, sf.id, run.id)
        repo.session.commit()
        assert count > 0

    def test_csv_not_detected(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("a,b,c\n1,2,3\n")
        parser = DailyTechPerformanceParser()
        assert parser.can_parse(str(csv_file)) == 0.0


class TestMCASnapshotParser:

    def test_family_name(self):
        parser = MCASnapshotParser()
        assert parser.family_name == "mca_snapshot"

    @pytest.mark.skipif(not has_fixture(FIXTURE_MCA_ZIP), reason="MCA ZIP not available")
    def test_detect_from_zip_member(self, tmp_path):
        extracted = extract_zip(str(FIXTURE_MCA_ZIP), str(tmp_path))
        assert len(extracted) > 0

        parser = MCASnapshotParser()
        confidence = parser.can_parse(extracted[0][0])
        assert confidence >= 0.5

    @pytest.mark.skipif(not has_fixture(FIXTURE_MCA_ZIP), reason="MCA ZIP not available")
    def test_parse_records(self, tmp_path):
        extracted = extract_zip(str(FIXTURE_MCA_ZIP), str(tmp_path))
        parser = MCASnapshotParser()
        records = parser.parse(extracted[0][0])
        assert len(records) > 0
        assert "cid" in records[0]


class TestMileageCSVParser:

    def test_family_name(self):
        parser = MileageCSVParser()
        assert parser.family_name == "mileage_disbursed"

    @pytest.mark.skipif(not has_fixture(FIXTURE_MILEAGE_CSV), reason="Mileage CSV not available")
    def test_detect(self):
        parser = MileageCSVParser()
        confidence = parser.can_parse(str(FIXTURE_MILEAGE_CSV))
        assert confidence >= 0.7

    @pytest.mark.skipif(not has_fixture(FIXTURE_MILEAGE_CSV), reason="Mileage CSV not available")
    def test_parse_records(self):
        parser = MileageCSVParser()
        records = parser.parse(str(FIXTURE_MILEAGE_CSV))
        assert len(records) > 100
        rec = records[0]
        assert "technician_name" in rec
        assert "total_mileage" in rec
        assert "total_amount" in rec

    @pytest.mark.skipif(not has_fixture(FIXTURE_MILEAGE_CSV), reason="Mileage CSV not available")
    def test_normalize_and_store(self, repo):
        parser = MileageCSVParser()
        records = parser.parse(str(FIXTURE_MILEAGE_CSV))

        sf = repo.register_source_file(
            filepath=str(FIXTURE_MILEAGE_CSV), filename="mileage.csv",
        )
        run = repo.start_ingest_run("test")
        repo.session.flush()

        count = parser.normalize_and_store(records, repo, sf.id, run.id)
        repo.session.commit()
        assert count > 0

    def test_non_mileage_csv_not_detected(self, tmp_path):
        csv_file = tmp_path / "random.csv"
        csv_file.write_text("x,y,z\n1,2,3\n")
        parser = MileageCSVParser()
        assert parser.can_parse(str(csv_file)) < 0.3


class TestParserRegistry:

    def test_registry_has_three_parsers(self):
        reg = create_default_registry()
        assert len(reg.parsers) == 3

    @pytest.mark.skipif(not has_fixture(FIXTURE_MILEAGE_CSV), reason="Mileage CSV not available")
    def test_registry_detects_mileage(self):
        reg = create_default_registry()
        parser = reg.detect_and_get_parser(str(FIXTURE_MILEAGE_CSV))
        assert parser is not None
        assert parser.family_name == "mileage_disbursed"


class TestZipHandler:

    @pytest.mark.skipif(not has_fixture(FIXTURE_DTP_ZIP), reason="DTP ZIP not available")
    def test_inspect_zip(self):
        members = inspect_zip(str(FIXTURE_DTP_ZIP))
        assert len(members) > 0
        assert all(m["extension"] in (".xlsx", ".csv") for m in members)

    @pytest.mark.skipif(not has_fixture(FIXTURE_DTP_ZIP), reason="DTP ZIP not available")
    def test_extract_zip(self, tmp_path):
        extracted = extract_zip(str(FIXTURE_DTP_ZIP), str(tmp_path))
        assert len(extracted) > 0
        for path, member in extracted:
            assert Path(path).exists()
