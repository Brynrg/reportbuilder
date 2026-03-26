"""Data access layer for the warehouse."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import text, func, and_, or_
from sqlalchemy.orm import Session

from .models import (
    Entity, EntityAlias, Period, Metric, MetricAlias,
    Observation, ReportFamily, SourceFile, WatchedFolder,
    IngestRun, OutputArtifact, TrendSummary, ReportRequest,
)


class WarehouseRepository:
    """High-level data access methods for the warehouse."""

    def __init__(self, session: Session):
        self.session = session

    # -- Entities --

    def get_or_create_entity(self, entity_type: str, canonical_name: str,
                              parent_id: Optional[int] = None) -> Entity:
        entity = self.session.query(Entity).filter_by(
            entity_type=entity_type, canonical_name=canonical_name
        ).first()
        if not entity:
            entity = Entity(entity_type=entity_type, canonical_name=canonical_name,
                          parent_id=parent_id)
            self.session.add(entity)
            self.session.flush()
        return entity

    def add_entity_alias(self, entity_id: int, alias: str, source: str = None) -> None:
        existing = self.session.query(EntityAlias).filter_by(
            entity_id=entity_id, alias=alias
        ).first()
        if not existing:
            self.session.add(EntityAlias(entity_id=entity_id, alias=alias, source=source))

    def resolve_entity(self, name: str, entity_type: str = None) -> Optional[Entity]:
        q = self.session.query(Entity)
        if entity_type:
            q = q.filter(Entity.entity_type == entity_type)
        entity = q.filter(Entity.canonical_name == name).first()
        if entity:
            return entity
        alias = self.session.query(EntityAlias).filter(EntityAlias.alias == name).first()
        if alias:
            return alias.entity
        return None

    # -- Periods --

    def get_or_create_period(self, period_type: str, start_date: date,
                              end_date: date, label: str = None) -> Period:
        period = self.session.query(Period).filter_by(
            period_type=period_type, start_date=start_date, end_date=end_date
        ).first()
        if not period:
            period = Period(
                period_type=period_type, start_date=start_date, end_date=end_date,
                label=label, year=start_date.year, month=start_date.month,
                week=start_date.isocalendar()[1],
            )
            self.session.add(period)
            self.session.flush()
        return period

    def find_overlapping_periods(self, start: date, end: date) -> List[Period]:
        return self.session.query(Period).filter(
            and_(Period.start_date <= end, Period.end_date >= start)
        ).all()

    def find_adjacent_periods(self, period: Period, period_type: str = None) -> List[Period]:
        q = self.session.query(Period)
        if period_type:
            q = q.filter(Period.period_type == period_type)
        return q.filter(
            or_(
                Period.end_date == period.start_date,
                Period.start_date == period.end_date,
            )
        ).all()

    # -- Metrics --

    def get_or_create_metric(self, canonical_name: str, display_name: str = None,
                              unit: str = None, aggregation: str = "sum") -> Metric:
        metric = self.session.query(Metric).filter_by(canonical_name=canonical_name).first()
        if not metric:
            metric = Metric(
                canonical_name=canonical_name, display_name=display_name or canonical_name,
                unit=unit, aggregation=aggregation,
            )
            self.session.add(metric)
            self.session.flush()
        return metric

    def resolve_metric(self, name: str) -> Optional[Metric]:
        metric = self.session.query(Metric).filter_by(canonical_name=name).first()
        if metric:
            return metric
        alias = self.session.query(MetricAlias).filter(MetricAlias.alias == name).first()
        if alias:
            return alias.metric
        return None

    # -- Report Families --

    def get_or_create_family(self, name: str, description: str = None) -> ReportFamily:
        fam = self.session.query(ReportFamily).filter_by(name=name).first()
        if not fam:
            fam = ReportFamily(name=name, description=description)
            self.session.add(fam)
            self.session.flush()
        return fam

    # -- Observations --

    def add_observation(self, entity_id: int, period_id: int, metric_id: int,
                        value: float = None, text_value: str = None,
                        report_family_id: int = None, source_file_id: int = None,
                        source_sheet: str = None, source_row: int = None,
                        confidence: float = 1.0, ingest_run_id: int = None,
                        parent_entity_id: int = None) -> Observation:
        obs = Observation(
            entity_id=entity_id, period_id=period_id, metric_id=metric_id,
            parent_entity_id=parent_entity_id,
            value=value, text_value=text_value, report_family_id=report_family_id,
            source_file_id=source_file_id, source_sheet=source_sheet,
            source_row=source_row, confidence=confidence, ingest_run_id=ingest_run_id,
        )
        self.session.add(obs)
        return obs

    def query_observations(self, entity_type: str = None, entity_name: str = None,
                            metric_name: str = None, period_start: date = None,
                            period_end: date = None, family_name: str = None,
                            limit: int = 10000) -> List[Dict[str, Any]]:
        q = (
            self.session.query(
                Observation.value,
                Entity.canonical_name.label("entity"),
                Entity.entity_type,
                Metric.canonical_name.label("metric"),
                Period.start_date,
                Period.end_date,
                Period.label.label("period_label"),
                Observation.source_sheet,
                Observation.confidence,
            )
            .join(Entity, Observation.entity_id == Entity.id)
            .join(Metric)
            .join(Period)
        )
        if entity_type:
            q = q.filter(Entity.entity_type == entity_type)
        if entity_name:
            q = q.filter(Entity.canonical_name == entity_name)
        if metric_name:
            q = q.filter(Metric.canonical_name == metric_name)
        if period_start:
            q = q.filter(Period.start_date >= period_start)
        if period_end:
            q = q.filter(Period.end_date <= period_end)
        if family_name:
            q = q.join(ReportFamily).filter(ReportFamily.name == family_name)
        rows = q.limit(limit).all()
        return [dict(r._mapping) for r in rows]

    # -- Source Files --

    def register_source_file(self, filepath: str, filename: str,
                              watched_folder_id: int = None,
                              file_hash: str = None, file_size: int = None,
                              is_archive: bool = False,
                              parent_archive_id: int = None,
                              archive_member_path: str = None) -> SourceFile:
        if file_hash:
            by_hash = self.session.query(SourceFile).filter_by(
                file_hash=file_hash
            ).first()
            if by_hash:
                return by_hash
        existing = self.session.query(SourceFile).filter_by(
            filepath=filepath
        ).first()
        if existing:
            return existing
        sf = SourceFile(
            filepath=filepath, filename=filename,
            watched_folder_id=watched_folder_id, file_hash=file_hash,
            file_size=file_size, is_archive=is_archive,
            parent_archive_id=parent_archive_id,
            archive_member_path=archive_member_path,
        )
        self.session.add(sf)
        self.session.flush()
        return sf

    def delete_observations_for_source(self, source_file_id: int) -> int:
        """Delete all observations linked to a source file (for supersession)."""
        count = self.session.query(Observation).filter_by(
            source_file_id=source_file_id
        ).delete()
        return count

    def get_pending_files(self) -> List[SourceFile]:
        return self.session.query(SourceFile).filter_by(ingest_status="pending").all()

    def mark_file_processed(self, file_id: int, status: str = "completed",
                            error: str = None, family: str = None) -> None:
        sf = self.session.query(SourceFile).get(file_id)
        if sf:
            sf.ingest_status = status
            sf.ingest_error = error
            sf.detected_family = family
            sf.last_processed = datetime.utcnow()

    # -- Ingest Runs --

    def start_ingest_run(self, trigger: str = "manual") -> IngestRun:
        run = IngestRun(trigger=trigger)
        self.session.add(run)
        self.session.flush()
        return run

    def complete_ingest_run(self, run_id: int, files: int = 0, obs: int = 0,
                            errors: int = 0, status: str = "completed") -> None:
        run = self.session.query(IngestRun).get(run_id)
        if run:
            run.completed_at = datetime.utcnow()
            run.files_processed = files
            run.observations_created = obs
            run.errors = errors
            run.status = status

    # -- Artifacts --

    def record_artifact(self, filename: str, filepath: str, artifact_type: str,
                        template_name: str = None, report_plan: str = None,
                        period_label: str = None, obs_count: int = None) -> OutputArtifact:
        art = OutputArtifact(
            filename=filename, filepath=filepath, artifact_type=artifact_type,
            template_name=template_name, report_plan=report_plan,
            period_label=period_label, observation_count=obs_count,
        )
        self.session.add(art)
        self.session.flush()
        return art

    def list_artifacts(self, limit: int = 100) -> List[OutputArtifact]:
        return (
            self.session.query(OutputArtifact)
            .order_by(OutputArtifact.created_at.desc())
            .limit(limit)
            .all()
        )

    # -- Trends --

    def get_entity_trend(self, entity_id: int, metric_id: int,
                          limit: int = 20) -> List[TrendSummary]:
        return (
            self.session.query(TrendSummary)
            .filter_by(entity_id=entity_id, metric_id=metric_id)
            .order_by(TrendSummary.period_id.desc())
            .limit(limit)
            .all()
        )

    # -- Watched Folders --

    def get_or_create_watched_folder(self, path: str) -> WatchedFolder:
        wf = self.session.query(WatchedFolder).filter_by(path=path).first()
        if not wf:
            wf = WatchedFolder(path=path)
            self.session.add(wf)
            self.session.flush()
        return wf

    # -- Stats --

    def get_warehouse_stats(self) -> Dict[str, int]:
        return {
            "entities": self.session.query(Entity).count(),
            "periods": self.session.query(Period).count(),
            "metrics": self.session.query(Metric).count(),
            "observations": self.session.query(Observation).count(),
            "source_files": self.session.query(SourceFile).count(),
            "artifacts": self.session.query(OutputArtifact).count(),
        }
