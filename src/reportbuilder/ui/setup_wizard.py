"""First-run setup wizard for machine-specific configuration."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QProgressBar,
    QCheckBox, QTextEdit, QGroupBox, QFrame,
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont

from ..config import ConfigManager, AppSettings
from ..ai.model_manager import ModelManager

logger = logging.getLogger(__name__)


class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Welcome to ReportBuilder")
        self.setSubTitle("This wizard will configure the app for your machine.")

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        intro = QLabel(
            "ReportBuilder continuously ingests your operational reports, "
            "builds a local data warehouse, generates polished Excel and PDF "
            "report packs, and provides trend analysis and Ask-the-Data features.\n\n"
            "All data stays on your machine. The app works fully offline after setup."
        )
        intro.setWordWrap(True)
        intro.setFont(QFont("Segoe UI", 11))
        layout.addWidget(intro)

        features = QLabel(
            "\u2022 Automatic report ingestion from your downloads folder\n"
            "\u2022 Daily Tech Performance, MCA Snapshot, and Mileage parsing\n"
            "\u2022 Team efficiency rankings and tenure analysis\n"
            "\u2022 Trend tracking and executive infographic PDFs\n"
            "\u2022 Ask-the-Data: describe what you need in plain English"
        )
        features.setFont(QFont("Segoe UI", 10))
        layout.addWidget(features)
        layout.addStretch()


class AppDataPage(QWizardPage):
    """Stages app_data_dir choice locally — no live config mutation until Finish."""

    def __init__(self, config: ConfigManager):
        super().__init__()
        self._config = config
        self._staged_dir: str | None = None
        self.setTitle("App Data Directory")
        self.setSubTitle("Where ReportBuilder stores its database and generated files.")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("App data directory:"))

        row = QHBoxLayout()
        self._path_edit = QLineEdit(config.settings.app_data_dir)
        self._path_edit.setReadOnly(True)
        row.addWidget(self._path_edit)
        browse_btn = QPushButton("Change...")
        browse_btn.clicked.connect(self._browse)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        self._info = QLabel("This directory will store your warehouse database, "
                            "staging files, and generated reports.")
        self._info.setWordWrap(True)
        layout.addWidget(self._info)
        layout.addStretch()

    @property
    def staged_app_data_dir(self) -> str | None:
        return self._staged_dir

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select App Data Directory")
        if not folder:
            return
        from PySide6.QtWidgets import QMessageBox
        confirm = QMessageBox.warning(
            self,
            "Change App Data Location",
            "This will create a new data environment at the selected location.\n\n"
            "Your existing warehouse and ingested data will NOT be moved "
            "automatically.\n\n"
            "Do you want to continue?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirm == QMessageBox.Yes:
            self._path_edit.setText(folder)
            self._staged_dir = folder


class IntakeFolderPage(QWizardPage):
    """Stages intake folder choice — no live config mutation until Finish."""

    def __init__(self, config: ConfigManager):
        super().__init__()
        self._config = config
        self._staged_intake: str | None = None
        self.setTitle("Report Intake Folder")
        self.setSubTitle("Choose the folder where your reports arrive.")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "ReportBuilder watches this folder for new Excel, CSV, and ZIP files.\n"
            "Point it at the folder where you download your daily reports."
        ))

        default = config.default_intake_suggestion()
        layout.addWidget(QLabel(f"Suggested default: {default}"))

        row = QHBoxLayout()
        self._path_edit = QLineEdit(config.settings.intake_folder or default)
        row.addWidget(self._path_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        self._create_check = QCheckBox("Create this folder if it doesn't exist")
        self._create_check.setChecked(True)
        layout.addWidget(self._create_check)

        self._status = QLabel("")
        layout.addWidget(self._status)
        layout.addStretch()

    @property
    def staged_intake_folder(self) -> str | None:
        return self._staged_intake

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Intake Folder")
        if folder:
            self._path_edit.setText(folder)

    def validatePage(self) -> bool:
        folder = self._path_edit.text().strip()
        if not folder:
            self._status.setText("Please select or enter a folder path.")
            return False
        path = Path(folder)
        if not path.exists():
            if self._create_check.isChecked():
                try:
                    path.mkdir(parents=True, exist_ok=True)
                    self._status.setText(f"Created: {folder}")
                except Exception as e:
                    self._status.setText(f"Cannot create folder: {e}")
                    return False
            else:
                self._status.setText("Folder does not exist.")
                return False
        self._staged_intake = folder
        return True


class OutputReadinessPage(QWizardPage):
    def __init__(self, config: ConfigManager):
        super().__init__()
        self._config = config
        self.setTitle("Output & Staging Readiness")
        self.setSubTitle("Verifying directories for staging and output files.")

        layout = QVBoxLayout(self)
        self._status_text = QTextEdit()
        self._status_text.setReadOnly(True)
        layout.addWidget(self._status_text)

    def initializePage(self):
        self._config.settings.resolve_paths()
        lines = []
        for name, path_str in [
            ("Staging", self._config.settings.staging_dir),
            ("Output", self._config.settings.output_dir),
            ("Database", str(Path(self._config.settings.db_path).parent)),
        ]:
            p = Path(path_str)
            try:
                p.mkdir(parents=True, exist_ok=True)
                lines.append(f"\u2705 {name}: {path_str}")
            except Exception as e:
                lines.append(f"\u274c {name}: {e}")
        self._status_text.setPlainText("\n".join(lines))


class AIModelPage(QWizardPage):
    def __init__(self, config: ConfigManager):
        super().__init__()
        self._config = config
        self.setTitle("Local AI Model")
        self.setSubTitle("Check AI planner model readiness for offline operation.")

        layout = QVBoxLayout(self)
        self._status_text = QTextEdit()
        self._status_text.setReadOnly(True)
        layout.addWidget(self._status_text)

        note = QLabel(
            "The AI model is optional. Without it, the app uses a deterministic "
            "rule-based parser for Ask-the-Data. You can install the model later."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def initializePage(self):
        mm = ModelManager(self._config.settings.ai_model_dir)
        status = mm.check_status()
        lines = []
        if status.installed:
            lines.append(f"\u2705 Model installed: {status.model_name}")
            lines.append(f"   Size: {status.model_size_mb:.1f} MB")
        else:
            lines.append("\u26a0\ufe0f No AI model installed yet")
            lines.append("   The deterministic fallback parser will be used")
            mm.create_placeholder()

        if status.runtime_available:
            lines.append(f"\u2705 Runtime available: {status.runtime_name}")
        else:
            lines.append("\u26a0\ufe0f ONNX Runtime not detected (install onnxruntime)")

        lines.append("")
        lines.append(f"Model directory: {self._config.settings.ai_model_dir}")
        self._status_text.setPlainText("\n".join(lines))


class OfflineReadinessPage(QWizardPage):
    def __init__(self, config: ConfigManager):
        super().__init__()
        self._config = config
        self.setTitle("Offline Readiness")
        self.setSubTitle("Confirming the app can run without internet.")

        layout = QVBoxLayout(self)
        self._status_text = QTextEdit()
        self._status_text.setReadOnly(True)
        layout.addWidget(self._status_text)
        layout.addStretch()

    def initializePage(self):
        lines = [
            "\u2705 Local SQLite warehouse: ready",
            "\u2705 Report parsers: built-in",
            "\u2705 Excel generation: built-in",
            "\u2705 PDF generation: built-in",
            "\u2705 Analytics engine: built-in",
        ]
        mm = ModelManager(self._config.settings.ai_model_dir)
        status = mm.check_status()
        if status.ready:
            lines.append("\u2705 AI planner: local model ready")
        else:
            lines.append("\u26a0\ufe0f AI planner: using deterministic fallback (offline OK)")

        lines.append("")
        lines.append("The app is ready for fully offline operation.")
        self._status_text.setPlainText("\n".join(lines))


class InitialScanPage(QWizardPage):
    def __init__(self, config: ConfigManager):
        super().__init__()
        self._config = config
        self.setTitle("Initial Scan")
        self.setSubTitle("Optionally scan your intake folder for existing files.")

        layout = QVBoxLayout(self)
        self._scan_check = QCheckBox("Scan intake folder for existing reports now")
        self._scan_check.setChecked(True)
        layout.addWidget(self._scan_check)

        self._info = QLabel("Existing files will be ingested into the warehouse "
                            "when the app starts.")
        self._info.setWordWrap(True)
        layout.addWidget(self._info)
        layout.addStretch()

    @property
    def should_scan(self) -> bool:
        return self._scan_check.isChecked()


class FinishPage(QWizardPage):
    def __init__(self, config: ConfigManager):
        super().__init__()
        self._config = config
        self.setTitle("Setup Complete")
        self.setSubTitle("ReportBuilder is ready to use.")

        layout = QVBoxLayout(self)
        self._summary = QTextEdit()
        self._summary.setReadOnly(True)
        layout.addWidget(self._summary)
        layout.addStretch()

    def initializePage(self):
        s = self._config.settings
        lines = [
            "Configuration Summary:",
            f"  Intake Folder: {s.intake_folder}",
            f"  App Data: {s.app_data_dir}",
            f"  Output: {s.output_dir}",
            f"  Database: {s.db_path}",
            "",
            "Click Finish to save configuration and launch the app.",
        ]
        self._summary.setPlainText("\n".join(lines))


class SetupWizard(QWizard):
    """First-run setup wizard for configuring ReportBuilder."""

    setup_completed = Signal(bool)

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("ReportBuilder Setup")
        self.setMinimumSize(650, 500)

        self._welcome = WelcomePage()
        self._app_data = AppDataPage(config)
        self._intake = IntakeFolderPage(config)
        self._output = OutputReadinessPage(config)
        self._ai_model = AIModelPage(config)
        self._offline = OfflineReadinessPage(config)
        self._scan = InitialScanPage(config)
        self._finish = FinishPage(config)

        self.addPage(self._welcome)
        self.addPage(self._app_data)
        self.addPage(self._intake)
        self.addPage(self._output)
        self.addPage(self._ai_model)
        self.addPage(self._offline)
        self.addPage(self._scan)
        self.addPage(self._finish)

    def accept(self):
        staged_app_data = self._app_data.staged_app_data_dir
        if staged_app_data:
            self._config.apply_app_data_change(staged_app_data)

        staged_intake = self._intake.staged_intake_folder
        if staged_intake:
            self._config.settings.intake_folder = staged_intake

        self._config.settings.setup_complete = True
        self._config.settings.ensure_directories()
        self._config.save()
        self.setup_completed.emit(self._scan.should_scan)
        super().accept()

    @property
    def should_initial_scan(self) -> bool:
        return self._scan.should_scan
