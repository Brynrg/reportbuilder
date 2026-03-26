"""Tests for warehouse models and repository."""

from datetime import date
from reportbuilder.warehouse.repository import WarehouseRepository


class TestWarehouseRepository:

    def test_create_entity(self, repo):
        entity = repo.get_or_create_entity("team", "Test Team Alpha")
        assert entity.id is not None
        assert entity.entity_type == "team"
        assert entity.canonical_name == "Test Team Alpha"

    def test_entity_dedup(self, repo):
        e1 = repo.get_or_create_entity("team", "Duplicate Team")
        e2 = repo.get_or_create_entity("team", "Duplicate Team")
        assert e1.id == e2.id

    def test_entity_alias(self, repo):
        entity = repo.get_or_create_entity("cid", "1234")
        repo.add_entity_alias(entity.id, "Store Alpha", "test")
        repo.session.flush()
        resolved = repo.resolve_entity("Store Alpha")
        assert resolved is not None
        assert resolved.id == entity.id

    def test_create_period(self, repo):
        period = repo.get_or_create_period(
            "day", date(2025, 10, 1), date(2025, 10, 1), "2025-10-01"
        )
        assert period.id is not None
        assert period.start_date == date(2025, 10, 1)

    def test_period_overlap(self, repo):
        repo.get_or_create_period("week", date(2025, 10, 1), date(2025, 10, 7))
        repo.get_or_create_period("week", date(2025, 10, 8), date(2025, 10, 14))
        repo.session.flush()
        overlapping = repo.find_overlapping_periods(date(2025, 10, 5), date(2025, 10, 10))
        assert len(overlapping) == 2

    def test_create_metric(self, repo):
        metric = repo.get_or_create_metric("hours", "Hours Worked", "hours", "sum")
        assert metric.id is not None
        assert metric.canonical_name == "hours"

    def test_add_observation(self, repo):
        entity = repo.get_or_create_entity("technician", "John Doe")
        period = repo.get_or_create_period("day", date(2025, 10, 1), date(2025, 10, 1))
        metric = repo.get_or_create_metric("hours", "Hours")
        obs = repo.add_observation(entity.id, period.id, metric.id, value=8.5)
        repo.session.flush()
        assert obs.id is not None
        assert obs.value == 8.5

    def test_query_observations(self, repo):
        entity = repo.get_or_create_entity("technician", "Jane Smith")
        period = repo.get_or_create_period("day", date(2025, 10, 1), date(2025, 10, 1))
        metric = repo.get_or_create_metric("gross_revenue", "Revenue")
        repo.add_observation(entity.id, period.id, metric.id, value=500.0)
        repo.session.flush()
        results = repo.query_observations(
            entity_type="technician", metric_name="gross_revenue"
        )
        assert len(results) == 1
        assert results[0]["value"] == 500.0

    def test_warehouse_stats(self, repo):
        repo.get_or_create_entity("team", "Stats Team")
        repo.session.flush()
        stats = repo.get_warehouse_stats()
        assert stats["entities"] >= 1

    def test_register_source_file(self, repo):
        sf = repo.register_source_file(
            filepath="/test/file.xlsx", filename="file.xlsx",
            file_hash="abc123", file_size=1024,
        )
        assert sf.id is not None
        assert sf.filename == "file.xlsx"

    def test_report_family(self, repo):
        fam = repo.get_or_create_family("daily_tech_performance", "DTP")
        assert fam.id is not None
        fam2 = repo.get_or_create_family("daily_tech_performance")
        assert fam2.id == fam.id

    def test_ingest_run(self, repo):
        run = repo.start_ingest_run("test")
        assert run.id is not None
        repo.complete_ingest_run(run.id, files=5, obs=100)
        repo.session.flush()

    def test_artifact_recording(self, repo):
        art = repo.record_artifact(
            "test.xlsx", "/output/test.xlsx", "excel",
            template_name="team_efficiency_tenure_pack",
        )
        repo.session.flush()
        artifacts = repo.list_artifacts()
        assert len(artifacts) == 1
        assert artifacts[0].filename == "test.xlsx"
