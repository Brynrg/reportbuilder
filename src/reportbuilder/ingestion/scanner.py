"""File scanner and ingest orchestrator: processes files through parse -> normalize -> warehouse."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from ..warehouse.models import SourceFile, IngestRun
from ..warehouse.repository import WarehouseRepository
from .watcher import file_hash, is_supported_file
from .zip_handler import extract_zip

logger = logging.getLogger(__name__)


class IngestOrchestrator:
    """Coordinates the full ingest pipeline: detect -> parse -> normalize -> store."""

    def __init__(self, session_factory, staging_dir: str, parser_registry=None):
        self._session_factory = session_factory
        self._staging_dir = staging_dir
        self._parser_registry = parser_registry
        self._processing: set[str] = set()
        self._lock = threading.Lock()

    def process_file(self, filepath: str) -> bool:
        """Process a single file through the full ingest pipeline."""
        with self._lock:
            if filepath in self._processing:
                return False
            self._processing.add(filepath)

        session = None
        try:
            path = Path(filepath)
            if not path.exists():
                logger.warning("File not found: %s", filepath)
                return False

            session = self._session_factory()
            repo = WarehouseRepository(session)

            try:
                fhash = file_hash(path)
                fsize = path.stat().st_size

                if path.suffix.lower() == ".zip":
                    return self._process_zip(filepath, fhash, fsize, session, repo)
                else:
                    return self._process_single(filepath, fhash, fsize, session, repo)
            except Exception:
                session.rollback()
                logger.exception("Failed to process file: %s", filepath)
                return False
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
            with self._lock:
                self._processing.discard(filepath)

    def _process_zip(self, filepath: str, fhash: str, fsize: int,
                     session: Session, repo: WarehouseRepository) -> bool:
        sf = repo.register_source_file(
            filepath=filepath, filename=Path(filepath).name,
            file_hash=fhash, file_size=fsize, is_archive=True,
        )
        if sf.ingest_status == "completed":
            logger.debug("ZIP already processed: %s", filepath)
            return True

        run = repo.start_ingest_run(trigger="zip_extract")
        extracted = extract_zip(filepath, self._staging_dir)

        files_ok = 0
        errors = 0
        total_obs = 0

        for extracted_path, member_path in extracted:
            member_sf = repo.register_source_file(
                filepath=extracted_path,
                filename=Path(extracted_path).name,
                file_hash=file_hash(Path(extracted_path)),
                file_size=Path(extracted_path).stat().st_size,
                parent_archive_id=sf.id,
                archive_member_path=member_path,
            )
            obs_count = self._parse_and_normalize(extracted_path, member_sf, session, repo, run.id)
            if obs_count >= 0:
                files_ok += 1
                total_obs += obs_count
            else:
                errors += 1

        if errors > 0 and files_ok == 0:
            zip_status = "error"
        elif errors > 0:
            zip_status = "partial"
        else:
            zip_status = "completed"

        run_status = "completed" if errors == 0 else ("error" if files_ok == 0 else "partial")
        repo.mark_file_processed(sf.id, status=zip_status,
                                 error=f"{errors} member(s) failed" if errors else None)
        repo.complete_ingest_run(run.id, files=files_ok, obs=total_obs,
                                errors=errors, status=run_status)
        session.commit()
        logger.info("ZIP %s: %s (%d ok, %d errors, %d observations)",
                    zip_status, Path(filepath).name, files_ok, errors, total_obs)
        return files_ok > 0 or errors == 0

    def _process_single(self, filepath: str, fhash: str, fsize: int,
                        session: Session, repo: WarehouseRepository) -> bool:
        sf = repo.register_source_file(
            filepath=filepath, filename=Path(filepath).name,
            file_hash=fhash, file_size=fsize,
        )
        if sf.ingest_status == "completed":
            logger.debug("File already processed (content hash match): %s", filepath)
            return True

        if sf.ingest_status not in ("pending", None):
            repo.delete_observations_for_source(sf.id)
            sf.ingest_status = "pending"

        run = repo.start_ingest_run(trigger="file_watch")
        obs_count = self._parse_and_normalize(filepath, sf, session, repo, run.id)
        status = "completed" if obs_count >= 0 else "error"
        repo.complete_ingest_run(run.id, files=1, obs=max(0, obs_count),
                                errors=1 if obs_count < 0 else 0, status=status)
        session.commit()
        return obs_count >= 0

    def _parse_and_normalize(self, filepath: str, source_file: SourceFile,
                             session: Session, repo: WarehouseRepository,
                             run_id: int) -> int:
        """Parse a file and normalize into warehouse observations.
        Returns observation count, or -1 on error."""
        if not self._parser_registry:
            logger.warning("No parser registry configured")
            repo.mark_file_processed(source_file.id, status="error",
                                    error="No parser registry")
            return -1

        try:
            parser = self._parser_registry.detect_and_get_parser(filepath)
            if parser is None:
                repo.mark_file_processed(source_file.id, status="skipped",
                                        error="No matching parser")
                logger.debug("No parser matched: %s", filepath)
                return 0

            family_name = parser.family_name
            records = parser.parse(filepath)

            if not records:
                repo.mark_file_processed(source_file.id, status="completed",
                                        family=family_name)
                return 0

            obs_count = parser.normalize_and_store(
                records, repo, source_file.id, run_id
            )
            repo.mark_file_processed(source_file.id, status="completed",
                                    family=family_name)
            return obs_count

        except Exception as e:
            logger.exception("Parse/normalize error for %s: %s", filepath, e)
            repo.mark_file_processed(source_file.id, status="error", error=str(e))
            return -1

    def run_initial_scan(self, folder_path: str) -> dict:
        """Scan a folder and process all supported files found."""
        folder = Path(folder_path)
        if not folder.exists():
            return {"files_found": 0, "processed": 0, "errors": 0}

        files = []
        for path in folder.rglob("*"):
            if path.is_file() and is_supported_file(path):
                files.append(str(path))

        processed = 0
        errors = 0
        for fp in files:
            try:
                if self.process_file(fp):
                    processed += 1
                else:
                    errors += 1
            except Exception:
                errors += 1
                logger.exception("Error in initial scan for: %s", fp)

        return {"files_found": len(files), "processed": processed, "errors": errors}
