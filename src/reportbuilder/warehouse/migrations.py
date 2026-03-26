"""Minimal schema migration for existing SQLite databases.

Runs idempotently on startup before normal app use.  Each migration
checks whether the change is already present before applying it, so
running the same migration set against a fresh or already-migrated
database is always safe.
"""

from __future__ import annotations

import logging
from sqlalchemy import text, inspect
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS _schema_version (
    version INTEGER NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def _get_current_version(engine: Engine) -> int:
    with engine.connect() as conn:
        conn.execute(text(SCHEMA_VERSION_TABLE))
        conn.commit()
        row = conn.execute(
            text("SELECT MAX(version) FROM _schema_version")
        ).fetchone()
        return row[0] if row and row[0] is not None else 0


def _set_version(engine: Engine, version: int) -> None:
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO _schema_version (version) VALUES (:v)"),
            {"v": version},
        )
        conn.commit()


def _column_exists(engine: Engine, table: str, column: str) -> bool:
    insp = inspect(engine)
    columns = {c["name"] for c in insp.get_columns(table)}
    return column in columns


def _index_exists(engine: Engine, table: str, index_name: str) -> bool:
    insp = inspect(engine)
    indexes = {idx["name"] for idx in insp.get_indexes(table)}
    return index_name in indexes


def _table_exists(engine: Engine, table: str) -> bool:
    insp = inspect(engine)
    return table in insp.get_table_names()


# ---------------------------------------------------------------------------
# Individual migrations
# ---------------------------------------------------------------------------

def _migrate_001_parent_entity_id(engine: Engine) -> None:
    """Add parent_entity_id column and index to observations table."""
    if not _table_exists(engine, "observations"):
        return

    with engine.connect() as conn:
        if not _column_exists(engine, "observations", "parent_entity_id"):
            conn.execute(text(
                "ALTER TABLE observations ADD COLUMN parent_entity_id INTEGER "
                "REFERENCES entities(id)"
            ))
            logger.info("Migration 001: added parent_entity_id column")
            conn.commit()

        if not _index_exists(engine, "observations", "ix_obs_parent"):
            conn.execute(text(
                "CREATE INDEX ix_obs_parent ON observations (parent_entity_id)"
            ))
            logger.info("Migration 001: created ix_obs_parent index")
            conn.commit()


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------

MIGRATIONS = [
    (1, _migrate_001_parent_entity_id),
]


def run_migrations(engine: Engine) -> int:
    """Run all pending migrations.  Returns the number of migrations applied."""
    current = _get_current_version(engine)
    applied = 0

    for version, migration_fn in MIGRATIONS:
        if version <= current:
            continue
        try:
            migration_fn(engine)
            _set_version(engine, version)
            applied += 1
            logger.info("Applied migration %d", version)
        except Exception:
            logger.exception("Migration %d failed", version)
            raise

    if applied:
        logger.info("Schema migrations complete: %d applied (now at v%d)",
                    applied, current + applied)
    return applied
