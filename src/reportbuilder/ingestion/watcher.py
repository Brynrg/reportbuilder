"""Folder watcher using watchdog for continuous file ingestion."""

from __future__ import annotations

import hashlib
import logging
import time
import threading
from pathlib import Path
from typing import Callable, Optional, Set

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".xlsb", ".csv", ".zip"}


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS and not path.name.startswith("~$")


class StabilizationTracker:
    """Wait for files to stop changing before processing."""

    def __init__(self, stabilization_seconds: float = 5.0):
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()
        self._stabilization = stabilization_seconds

    def touch(self, filepath: str) -> None:
        with self._lock:
            self._pending[filepath] = time.time()

    def get_stable_files(self) -> list[str]:
        now = time.time()
        stable = []
        with self._lock:
            to_remove = []
            for fp, ts in self._pending.items():
                if now - ts >= self._stabilization:
                    stable.append(fp)
                    to_remove.append(fp)
            for fp in to_remove:
                del self._pending[fp]
        return stable

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)


class IngestEventHandler(FileSystemEventHandler):
    """Handles file system events, tracks stabilization, and queues for ingestion."""

    def __init__(self, tracker: StabilizationTracker, on_stable: Callable[[str], None]):
        super().__init__()
        self._tracker = tracker
        self._on_stable = on_stable

    def on_created(self, event):
        if not event.is_directory:
            path = Path(event.src_path)
            if is_supported_file(path):
                logger.info("New file detected: %s", path.name)
                self._tracker.touch(str(path))

    def on_modified(self, event):
        if not event.is_directory:
            path = Path(event.src_path)
            if is_supported_file(path):
                self._tracker.touch(str(path))


class FolderWatcher:
    """Watches a folder for new/modified report files."""

    def __init__(self, folder_path: str, on_file_ready: Callable[[str], None],
                 stabilization_seconds: float = 5.0,
                 reconciliation_interval: float = 1800.0):
        self._folder = Path(folder_path)
        self._on_file_ready = on_file_ready
        self._tracker = StabilizationTracker(stabilization_seconds)
        self._observer: Optional[Observer] = None
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._reconciliation_interval = reconciliation_interval
        self._known_files: Set[str] = set()

    @property
    def folder(self) -> Path:
        return self._folder

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        if not self._folder.exists():
            logger.warning("Watched folder does not exist: %s", self._folder)
            return
        self._running = True
        handler = IngestEventHandler(self._tracker, self._on_file_ready)
        self._observer = Observer()
        self._observer.schedule(handler, str(self._folder), recursive=True)
        self._observer.start()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        logger.info("Watcher started on: %s", self._folder)

    def stop(self) -> None:
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        logger.info("Watcher stopped")

    def _poll_loop(self) -> None:
        last_reconcile = 0.0
        while self._running:
            stable = self._tracker.get_stable_files()
            for fp in stable:
                try:
                    self._on_file_ready(fp)
                except Exception:
                    logger.exception("Error processing stable file: %s", fp)
            now = time.time()
            if now - last_reconcile >= self._reconciliation_interval:
                self._reconcile()
                last_reconcile = now
            time.sleep(1.0)

    def _reconcile(self) -> None:
        """Scan folder for any files missed by event-based watching."""
        if not self._folder.exists():
            return
        logger.debug("Running reconciliation scan on %s", self._folder)
        for path in self._folder.rglob("*"):
            if path.is_file() and is_supported_file(path):
                fp = str(path)
                if fp not in self._known_files:
                    self._known_files.add(fp)
                    self._tracker.touch(fp)

    def scan_existing(self) -> list[str]:
        """Immediately scan and return all existing supported files."""
        found = []
        if not self._folder.exists():
            return found
        for path in self._folder.rglob("*"):
            if path.is_file() and is_supported_file(path):
                found.append(str(path))
                self._known_files.add(str(path))
        return found

    def mark_known(self, filepath: str) -> None:
        self._known_files.add(filepath)
