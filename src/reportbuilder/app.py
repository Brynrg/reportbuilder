"""Application entry point and lifecycle management."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from .config import ConfigManager
from .warehouse.models import get_session_factory
from .ui.setup_wizard import SetupWizard
from .ui.main_window import MainWindow
from .ingestion.watcher import FolderWatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class ReportBuilderApp:
    """Main application orchestrator.

    Owns the service lifecycle: config -> DB session factory -> watcher -> UI.
    When critical config paths change, services are torn down and rebuilt.
    """

    def __init__(self):
        self._qt_app = QApplication(sys.argv)
        self._qt_app.setApplicationName("ReportBuilder")
        self._qt_app.setOrganizationName("ReportBuilder")
        self._qt_app.setStyle("Fusion")

        self._config = ConfigManager()
        self._config.load()
        self._config.settings.resolve_paths()
        self._config.settings.ensure_directories()

        self._session_factory = get_session_factory(self._config.settings.db_path)
        self._watcher: FolderWatcher | None = None
        self._main_window: MainWindow | None = None
        self._launched = False

    def run(self) -> int:
        if not self._config.is_setup_complete():
            wizard = SetupWizard(self._config)
            wizard.setup_completed.connect(self._on_setup_complete)
            wizard.exec()
            if not self._config.is_setup_complete():
                logger.info("Setup cancelled, exiting")
                return 0
            if not self._launched:
                self._rebuild_services()
                self._launch_main()
        else:
            self._launch_main()

        return self._qt_app.exec()

    def _on_setup_complete(self, should_scan: bool):
        """Called by wizard signal when setup finishes (before exec() returns)."""
        self._rebuild_services()
        if self._launched and self._main_window is not None:
            self._main_window.refresh_services(self._session_factory)
        else:
            self._launch_main()
        if should_scan and self._main_window is not None:
            self._main_window.run_initial_scan()

    def _rebuild_services(self):
        """Rebuild session factory and watcher from current authoritative config."""
        self._stop_watcher()
        self._config.settings.ensure_directories()
        self._session_factory = get_session_factory(self._config.settings.db_path)

    def _launch_main(self):
        if self._launched and self._main_window is not None:
            logger.debug("Main window already launched, skipping duplicate")
            return
        self._main_window = MainWindow(self._config, self._session_factory)
        self._main_window.rerun_setup_requested.connect(self._rerun_setup)
        self._main_window.show()
        self._start_watcher()
        self._launched = True

    def _rerun_setup(self):
        """Handle re-run setup request from main window."""
        wizard = SetupWizard(self._config)
        wizard.setup_completed.connect(self._on_rerun_setup_complete)
        wizard.exec()

    def _on_rerun_setup_complete(self, should_scan: bool):
        """Rebuild services after setup wizard rerun, refresh existing main window."""
        self._rebuild_services()
        if self._main_window is not None:
            self._main_window.refresh_services(self._session_factory)
            self._start_watcher()
            if should_scan:
                self._main_window.run_initial_scan()

    def _start_watcher(self):
        if not self._config.settings.watcher_enabled:
            return

        from .ingestion.scanner import IngestOrchestrator
        from .parsing.detector import create_default_registry

        parser_reg = create_default_registry()
        orchestrator = IngestOrchestrator(
            self._session_factory,
            self._config.settings.staging_dir,
            parser_reg,
        )

        self._watcher = FolderWatcher(
            self._config.settings.intake_folder,
            on_file_ready=orchestrator.process_file,
            stabilization_seconds=self._config.settings.file_stabilization_seconds,
            reconciliation_interval=self._config.settings.reconciliation_interval_minutes * 60,
        )
        self._watcher.start()
        logger.info("File watcher started on %s", self._config.settings.intake_folder)

    def _stop_watcher(self):
        if self._watcher is not None:
            try:
                self._watcher.stop()
            except Exception as e:
                logger.warning("Error stopping watcher: %s", e)
            self._watcher = None


def main():
    app = ReportBuilderApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
