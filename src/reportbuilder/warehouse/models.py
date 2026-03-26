"""SQLAlchemy models for the local data warehouse.

Two conceptual layers:
1. Raw / Lineage Layer: tracks files, archives, sheets, ingest runs, parse regions
2. Canonical / Analytical Layer: normalized entities, periods, metrics, observations
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Float, Text, Boolean, DateTime, Date,
    ForeignKey, Index, UniqueConstraint, CheckConstraint,
    create_engine, event,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session, sessionmaker


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# RAW / LINEAGE LAYER
# ---------------------------------------------------------------------------

class WatchedFolder(Base):
    __tablename__ = "watched_folders"
    id = Column(Integer, primary_key=True)
    path = Column(Text, nullable=False, unique=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    files = relationship("SourceFile", back_populates="watched_folder")


class SourceFile(Base):
    __tablename__ = "source_files"
    id = Column(Integer, primary_key=True)
    watched_folder_id = Column(Integer, ForeignKey("watched_folders.id"), nullable=True)
    filename = Column(Text, nullable=False)
    filepath = Column(Text, nullable=False)
    file_hash = Column(String(64), nullable=True)
    file_size = Column(Integer, nullable=True)
    file_modified = Column(DateTime, nullable=True)
    is_archive = Column(Boolean, default=False)
    parent_archive_id = Column(Integer, ForeignKey("source_files.id"), nullable=True)
    archive_member_path = Column(Text, nullable=True)
    detected_family = Column(String(100), nullable=True)
    ingest_status = Column(String(30), default="pending")
    ingest_error = Column(Text, nullable=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_processed = Column(DateTime, nullable=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    watched_folder = relationship("WatchedFolder", back_populates="files")
    parent_archive = relationship("SourceFile", remote_side="SourceFile.id")
    sheets = relationship("SourceSheet", back_populates="source_file")
    observations = relationship("Observation", back_populates="source_file")

    __table_args__ = (
        Index("ix_source_files_hash", "file_hash"),
        Index("ix_source_files_status", "ingest_status"),
    )


class SourceSheet(Base):
    __tablename__ = "source_sheets"
    id = Column(Integer, primary_key=True)
    source_file_id = Column(Integer, ForeignKey("source_files.id"), nullable=False)
    sheet_name = Column(Text, nullable=False)
    sheet_index = Column(Integer, nullable=True)
    row_count = Column(Integer, nullable=True)
    col_count = Column(Integer, nullable=True)
    header_row = Column(Integer, nullable=True)
    data_start_row = Column(Integer, nullable=True)
    detected_family = Column(String(100), nullable=True)
    parse_confidence = Column(Float, nullable=True)
    parse_warnings = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    source_file = relationship("SourceFile", back_populates="sheets")


class IngestRun(Base):
    __tablename__ = "ingest_runs"
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    trigger = Column(String(50), nullable=True)
    files_processed = Column(Integer, default=0)
    observations_created = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    status = Column(String(30), default="running")
    notes = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# CANONICAL / ANALYTICAL LAYER
# ---------------------------------------------------------------------------

class ReportFamily(Base):
    __tablename__ = "report_families"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    source_pattern = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Entity(Base):
    __tablename__ = "entities"
    id = Column(Integer, primary_key=True)
    entity_type = Column(String(50), nullable=False)
    canonical_name = Column(Text, nullable=False)
    parent_id = Column(Integer, ForeignKey("entities.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    parent = relationship("Entity", remote_side="Entity.id", foreign_keys="Entity.parent_id")
    aliases = relationship("EntityAlias", back_populates="entity")
    observations = relationship("Observation", back_populates="entity",
                                foreign_keys="Observation.entity_id")

    __table_args__ = (
        Index("ix_entities_type_name", "entity_type", "canonical_name"),
        UniqueConstraint("entity_type", "canonical_name", name="uq_entity_type_name"),
    )


class EntityAlias(Base):
    __tablename__ = "entity_aliases"
    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    alias = Column(Text, nullable=False)
    source = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    entity = relationship("Entity", back_populates="aliases")
    __table_args__ = (Index("ix_entity_aliases_alias", "alias"),)


class Period(Base):
    __tablename__ = "periods"
    id = Column(Integer, primary_key=True)
    period_type = Column(String(30), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    label = Column(String(100), nullable=True)
    year = Column(Integer, nullable=True)
    month = Column(Integer, nullable=True)
    week = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    observations = relationship("Observation", back_populates="period")

    __table_args__ = (
        Index("ix_periods_dates", "start_date", "end_date"),
        UniqueConstraint("period_type", "start_date", "end_date", name="uq_period"),
    )


class Metric(Base):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True)
    canonical_name = Column(String(100), nullable=False, unique=True)
    display_name = Column(Text, nullable=True)
    unit = Column(String(30), nullable=True)
    aggregation = Column(String(30), default="sum")
    description = Column(Text, nullable=True)
    trend_eligible = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    aliases = relationship("MetricAlias", back_populates="metric")


class MetricAlias(Base):
    __tablename__ = "metric_aliases"
    id = Column(Integer, primary_key=True)
    metric_id = Column(Integer, ForeignKey("metrics.id"), nullable=False)
    alias = Column(Text, nullable=False)
    source = Column(String(100), nullable=True)

    metric = relationship("Metric", back_populates="aliases")
    __table_args__ = (Index("ix_metric_aliases_alias", "alias"),)


class Observation(Base):
    """Core fact table: one metric value for one entity in one period from one source.

    parent_entity_id captures the entity's parent (e.g. team) at the time the
    observation was recorded, providing time-stable historical attribution.
    Analytics should use this column — not Entity.parent_id — for rollups.
    """
    __tablename__ = "observations"
    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    period_id = Column(Integer, ForeignKey("periods.id"), nullable=False)
    metric_id = Column(Integer, ForeignKey("metrics.id"), nullable=False)
    parent_entity_id = Column(Integer, ForeignKey("entities.id"), nullable=True)
    value = Column(Float, nullable=True)
    text_value = Column(Text, nullable=True)
    report_family_id = Column(Integer, ForeignKey("report_families.id"), nullable=True)
    source_file_id = Column(Integer, ForeignKey("source_files.id"), nullable=True)
    source_sheet = Column(Text, nullable=True)
    source_row = Column(Integer, nullable=True)
    confidence = Column(Float, default=1.0)
    ingest_run_id = Column(Integer, ForeignKey("ingest_runs.id"), nullable=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    entity = relationship("Entity", back_populates="observations", foreign_keys=[entity_id])
    parent_entity = relationship("Entity", foreign_keys=[parent_entity_id])
    period = relationship("Period", back_populates="observations")
    metric = relationship("Metric")
    source_file = relationship("SourceFile", back_populates="observations")

    __table_args__ = (
        Index("ix_obs_entity_period", "entity_id", "period_id"),
        Index("ix_obs_metric", "metric_id"),
        Index("ix_obs_family", "report_family_id"),
        Index("ix_obs_source", "source_file_id"),
        Index("ix_obs_parent", "parent_entity_id"),
    )


class TrendSummary(Base):
    """Materialized trend cache for fast period-over-period analysis."""
    __tablename__ = "trend_summaries"
    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    metric_id = Column(Integer, ForeignKey("metrics.id"), nullable=False)
    period_id = Column(Integer, ForeignKey("periods.id"), nullable=False)
    prev_period_id = Column(Integer, ForeignKey("periods.id"), nullable=True)
    current_value = Column(Float, nullable=True)
    previous_value = Column(Float, nullable=True)
    absolute_change = Column(Float, nullable=True)
    percent_change = Column(Float, nullable=True)
    current_rank = Column(Integer, nullable=True)
    previous_rank = Column(Integer, nullable=True)
    rank_change = Column(Integer, nullable=True)
    rolling_4_avg = Column(Float, nullable=True)
    rolling_8_avg = Column(Float, nullable=True)
    volatility = Column(Float, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_trend_entity_metric", "entity_id", "metric_id"),
    )


class OutputArtifact(Base):
    __tablename__ = "output_artifacts"
    id = Column(Integer, primary_key=True)
    filename = Column(Text, nullable=False)
    filepath = Column(Text, nullable=False)
    artifact_type = Column(String(30), nullable=False)
    template_name = Column(String(100), nullable=True)
    report_plan = Column(Text, nullable=True)
    period_label = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    source_file_ids = Column(Text, nullable=True)
    observation_count = Column(Integer, nullable=True)


class ReportRequest(Base):
    __tablename__ = "report_requests"
    id = Column(Integer, primary_key=True)
    user_query = Column(Text, nullable=True)
    parsed_plan = Column(Text, nullable=True)
    status = Column(String(30), default="pending")
    artifact_id = Column(Integer, ForeignKey("output_artifacts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# FTS virtual table setup (created via raw SQL after table creation)
# ---------------------------------------------------------------------------

FTS_SETUP_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
    entity_name,
    metric_name,
    period_label,
    report_family,
    content='',
    tokenize='porter'
);
"""


# ---------------------------------------------------------------------------
# Engine / Session factory
# ---------------------------------------------------------------------------

def create_warehouse_engine(db_path: str, echo: bool = False):
    engine = create_engine(f"sqlite:///{db_path}", echo=echo)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def get_session_factory(db_path: str, echo: bool = False):
    engine = create_warehouse_engine(db_path, echo=echo)
    Base.metadata.create_all(engine)

    from .migrations import run_migrations
    run_migrations(engine)

    try:
        with engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text(FTS_SETUP_SQL))
            conn.commit()
    except Exception:
        pass
    return sessionmaker(bind=engine)
