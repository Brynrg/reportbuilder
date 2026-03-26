"""Main application window with navigation and all views."""

from __future__ import annotations

import logging
import json
import subprocess
import sys
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QSplitter,
    QTextEdit, QLineEdit, QComboBox, QDateEdit, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QFileDialog, QMessageBox, QFrame, QScrollArea, QTabWidget,
    QSpinBox, QCheckBox, QPlainTextEdit, QMenuBar, QMenu,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QDate
from PySide6.QtGui import QFont, QColor, QIcon, QAction

from ..config import ConfigManager
from ..warehouse.models import get_session_factory
from ..warehouse.repository import WarehouseRepository
from ..analytics.engine import AnalyticsEngine, TrendEngine
from ..reports.registry import ReportPlan, TemplateRegistry
from ..reports.templates.team_efficiency_tenure import TeamEfficiencyTenureTemplate
from ..reports.templates.snapshot_vs_performance import SnapshotVsPerformanceTemplate
from ..reports.templates.trend_focus import TrendFocusTemplate
from ..reports.templates.executive_pdf import ExecutiveInfographicTemplate
from ..ai.planner import ReportPlanner
from ..ai.model_manager import ModelManager
from ..ingestion.scanner import IngestOrchestrator
from ..parsing.detector import create_default_registry

logger = logging.getLogger(__name__)


class IngestWorker(QThread):
    """Background thread for file ingestion."""
    progress = Signal(str)
    finished = Signal(dict)

    def __init__(self, orchestrator, folder_path):
        super().__init__()
        self._orchestrator = orchestrator
        self._folder = folder_path

    def run(self):
        self.progress.emit(f"Scanning {self._folder}...")
        result = self._orchestrator.run_initial_scan(self._folder)
        self.finished.emit(result)


class ReportWorker(QThread):
    """Background thread for report generation."""
    progress = Signal(str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, registry, plan, session_factory, output_dir):
        super().__init__()
        self._registry = registry
        self._plan = plan
        self._session_factory = session_factory
        self._output_dir = output_dir

    def run(self):
        session = None
        try:
            self.progress.emit("Generating report...")
            session = self._session_factory()
            outputs = self._registry.execute_plan(self._plan, session, self._output_dir)
            self.finished.emit(outputs)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass


class DashboardView(QWidget):
    """Home dashboard showing ingestion health and quick stats."""

    def __init__(self, config: ConfigManager, session_factory):
        super().__init__()
        self._config = config
        self._sf = session_factory
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Dashboard")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        layout.addWidget(title)

        self._stats_frame = QFrame()
        self._stats_frame.setFrameShape(QFrame.StyledPanel)
        stats_layout = QVBoxLayout(self._stats_frame)
        self._stats_label = QLabel("Loading...")
        self._stats_label.setFont(QFont("Segoe UI", 11))
        stats_layout.addWidget(self._stats_label)
        layout.addWidget(self._stats_frame)

        self._intake_label = QLabel(f"Intake Folder: {config.settings.intake_folder}")
        self._intake_label.setFont(QFont("Segoe UI", 10))
        layout.addWidget(self._intake_label)

        layout.addStretch()

    def refresh(self):
        self._intake_label.setText(f"Intake Folder: {self._config.settings.intake_folder}")
        session = None
        try:
            session = self._sf()
            repo = WarehouseRepository(session)
            stats = repo.get_warehouse_stats()
            self._stats_label.setText(
                f"Entities: {stats['entities']}  |  "
                f"Periods: {stats['periods']}  |  "
                f"Metrics: {stats['metrics']}  |  "
                f"Observations: {stats['observations']:,}  |  "
                f"Source Files: {stats['source_files']}  |  "
                f"Artifacts: {stats['artifacts']}"
            )
        except Exception as e:
            self._stats_label.setText(f"Error loading stats: {e}")
        finally:
            if session is not None:
                session.close()


class SourcesView(QWidget):
    """Ingestion management view."""

    ingest_requested = Signal()

    def __init__(self, config: ConfigManager, session_factory):
        super().__init__()
        self._config = config
        self._sf = session_factory
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Sources & Ingestion")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        layout.addWidget(title)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel(f"Watched Folder: {config.settings.intake_folder}"))
        scan_btn = QPushButton("Scan Now")
        scan_btn.clicked.connect(self.ingest_requested.emit)
        folder_row.addWidget(scan_btn)
        layout.addLayout(folder_row)

        self._file_table = QTableWidget()
        self._file_table.setColumnCount(5)
        self._file_table.setHorizontalHeaderLabels(
            ["Filename", "Status", "Family", "Size", "Processed"]
        )
        self._file_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self._file_table)

    def refresh(self):
        session = None
        try:
            from ..warehouse.models import SourceFile
            session = self._sf()
            files = session.query(SourceFile).order_by(
                SourceFile.first_seen.desc()
            ).limit(200).all()
            self._file_table.setRowCount(len(files))
            for i, f in enumerate(files):
                self._file_table.setItem(i, 0, QTableWidgetItem(f.filename))
                self._file_table.setItem(i, 1, QTableWidgetItem(f.ingest_status or ""))
                self._file_table.setItem(i, 2, QTableWidgetItem(f.detected_family or ""))
                size_str = f"{f.file_size / 1024:.0f} KB" if f.file_size else ""
                self._file_table.setItem(i, 3, QTableWidgetItem(size_str))
                ts = f.last_processed.strftime("%Y-%m-%d %H:%M") if f.last_processed else ""
                self._file_table.setItem(i, 4, QTableWidgetItem(ts))
        except Exception as e:
            logger.error("Failed to refresh sources: %s", e)
        finally:
            if session is not None:
                session.close()


class DataExplorerView(QWidget):
    """Browse warehouse entities, periods, metrics, and observations."""

    def __init__(self, session_factory):
        super().__init__()
        self._sf = session_factory
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Data Explorer")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        layout.addWidget(title)

        tabs = QTabWidget()

        self._entity_table = QTableWidget()
        self._entity_table.setColumnCount(3)
        self._entity_table.setHorizontalHeaderLabels(["Type", "Name", "Parent"])
        self._entity_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tabs.addTab(self._entity_table, "Entities")

        self._obs_table = QTableWidget()
        self._obs_table.setColumnCount(5)
        self._obs_table.setHorizontalHeaderLabels(
            ["Entity", "Metric", "Value", "Period", "Source"]
        )
        self._obs_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tabs.addTab(self._obs_table, "Observations")

        layout.addWidget(tabs)

    def refresh(self):
        session = None
        try:
            from ..warehouse.models import Entity, Observation, Metric, Period
            session = self._sf()
            entities = session.query(Entity).order_by(
                Entity.entity_type, Entity.canonical_name
            ).limit(500).all()
            self._entity_table.setRowCount(len(entities))
            for i, e in enumerate(entities):
                self._entity_table.setItem(i, 0, QTableWidgetItem(e.entity_type))
                self._entity_table.setItem(i, 1, QTableWidgetItem(e.canonical_name))
                parent = ""
                if e.parent:
                    parent = e.parent.canonical_name
                self._entity_table.setItem(i, 2, QTableWidgetItem(parent))

            obs = (
                session.query(Observation, Entity, Metric, Period)
                .join(Entity, Observation.entity_id == Entity.id)
                .join(Metric, Observation.metric_id == Metric.id)
                .join(Period, Observation.period_id == Period.id)
                .order_by(Observation.id.desc())
                .limit(500).all()
            )
            self._obs_table.setRowCount(len(obs))
            for i, (o, ent, met, per) in enumerate(obs):
                self._obs_table.setItem(i, 0, QTableWidgetItem(ent.canonical_name))
                self._obs_table.setItem(i, 1, QTableWidgetItem(met.canonical_name))
                val = f"{o.value:.2f}" if o.value is not None else o.text_value or ""
                self._obs_table.setItem(i, 2, QTableWidgetItem(val))
                self._obs_table.setItem(i, 3, QTableWidgetItem(per.label or ""))
                self._obs_table.setItem(i, 4, QTableWidgetItem(o.source_sheet or ""))
        except Exception as e:
            logger.error("Failed to refresh explorer: %s", e)
        finally:
            if session is not None:
                session.close()


class AskTheDataView(QWidget):
    """Ask the Data panel: natural language -> report plan -> execution."""

    report_generated = Signal(list)

    def __init__(self, config: ConfigManager, session_factory, template_registry):
        super().__init__()
        self._config = config
        self._sf = session_factory
        self._registry = template_registry
        self._planner = ReportPlanner(config.settings.ai_model_dir)
        self._report_worker: ReportWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Ask the Data")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        layout.addWidget(title)

        layout.addWidget(QLabel("Describe the report you want:"))
        self._query_input = QTextEdit()
        self._query_input.setMaximumHeight(80)
        self._query_input.setPlaceholderText(
            "e.g., Build me the team efficiency report"
        )
        layout.addWidget(self._query_input)

        btn_row = QHBoxLayout()
        self._plan_btn = QPushButton("Generate Plan")
        self._plan_btn.clicked.connect(self._generate_plan)
        btn_row.addWidget(self._plan_btn)

        self._run_btn = QPushButton("Execute Plan")
        self._run_btn.clicked.connect(self._execute_plan)
        btn_row.addWidget(self._run_btn)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("Report Plan (editable JSON):"))
        self._plan_display = QPlainTextEdit()
        self._plan_display.setFont(QFont("Consolas", 10))
        layout.addWidget(self._plan_display)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status = QLabel("")
        layout.addWidget(self._status)

    def _generate_plan(self):
        query = self._query_input.toPlainText().strip()
        if not query:
            self._status.setText("Please enter a request.")
            return
        try:
            plan = self._planner.plan(query)
            self._plan_display.setPlainText(json.dumps(plan, indent=2, default=str))
            provider = plan.get("_provider", "unknown")

            check = self._registry.validate_plan(ReportPlan.from_dict(plan))
            if check.supported:
                msg = f"Plan generated via {provider} — ready to execute."
                if check.warnings:
                    msg += f" ({'; '.join(check.warnings)})"
                self._status.setText(msg)
            else:
                self._status.setText(f"Plan NOT executable: {check.message}")
        except Exception as e:
            self._status.setText(f"Error: {e}")

    def _execute_plan(self):
        if self._report_worker is not None and self._report_worker.isRunning():
            self._status.setText("A report is already being generated.")
            return

        plan_text = self._plan_display.toPlainText().strip()
        if not plan_text:
            self._status.setText("No plan to execute. Generate one first.")
            return
        try:
            plan_dict = json.loads(plan_text)
            plan = ReportPlan.from_dict(plan_dict)

            check = self._registry.validate_plan(plan)
            if not check.supported:
                self._status.setText(f"Cannot execute: {check.message}")
                return

            self._run_btn.setEnabled(False)
            self._progress.setVisible(True)
            self._status.setText("Generating report...")

            self._report_worker = ReportWorker(
                self._registry, plan, self._sf, self._config.settings.output_dir,
            )
            self._report_worker.progress.connect(self._on_report_progress)
            self._report_worker.finished.connect(self._on_report_finished)
            self._report_worker.error.connect(self._on_report_error)
            self._report_worker.start()
        except Exception as e:
            self._run_btn.setEnabled(True)
            self._progress.setVisible(False)
            self._status.setText(f"Error: {e}")
            logger.exception("Plan execution failed")

    def _on_report_progress(self, msg: str):
        self._status.setText(msg)

    def _on_report_finished(self, outputs: list):
        self._run_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._status.setText(
            f"Generated {len(outputs)} file(s): "
            f"{', '.join(Path(o).name for o in outputs)}"
        )
        self.report_generated.emit(outputs)

    def _on_report_error(self, error_msg: str):
        self._run_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._status.setText(f"Error: {error_msg}")
        logger.error("Report worker error: %s", error_msg)


class ArtifactsView(QWidget):
    """View generated report artifacts."""

    def __init__(self, config: ConfigManager, session_factory):
        super().__init__()
        self._config = config
        self._sf = session_factory
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Generated Reports")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        layout.addWidget(title)

        btn_row = QHBoxLayout()
        open_btn = QPushButton("Open Output Folder")
        open_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(open_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Filename", "Type", "Template", "Created"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self._table)

    def _open_folder(self):
        folder = self._config.settings.output_dir
        if sys.platform == "darwin":
            subprocess.run(["open", folder])
        elif sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.run(["xdg-open", folder])

    def refresh(self):
        session = None
        try:
            from ..warehouse.models import OutputArtifact
            session = self._sf()
            artifacts = session.query(OutputArtifact).order_by(
                OutputArtifact.created_at.desc()
            ).limit(100).all()
            self._table.setRowCount(len(artifacts))
            for i, a in enumerate(artifacts):
                self._table.setItem(i, 0, QTableWidgetItem(a.filename))
                self._table.setItem(i, 1, QTableWidgetItem(a.artifact_type))
                self._table.setItem(i, 2, QTableWidgetItem(a.template_name or ""))
                ts = a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else ""
                self._table.setItem(i, 3, QTableWidgetItem(ts))
        except Exception as e:
            logger.error("Failed to refresh artifacts: %s", e)
        finally:
            if session is not None:
                session.close()


class TrendsView(QWidget):
    """Trend exploration view."""

    def __init__(self, session_factory):
        super().__init__()
        self._sf = session_factory
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Trend Analysis")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        layout.addWidget(title)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Entity Type:"))
        self._entity_type = QComboBox()
        self._entity_type.addItems(["team", "technician", "cid"])
        controls.addWidget(self._entity_type)

        controls.addWidget(QLabel("Metric:"))
        self._metric = QComboBox()
        self._metric.addItems([
            "gross_revenue", "hours", "units", "gross_dollars_per_hour",
            "mileage_paid", "total_miles",
        ])
        controls.addWidget(self._metric)

        run_btn = QPushButton("Compute Trends")
        run_btn.clicked.connect(self._compute)
        controls.addWidget(run_btn)
        layout.addLayout(controls)

        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "Entity", "Current", "Previous", "Change", "% Change",
            "Rank", "Rank Change", "Volatility",
        ])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self._table)

    def _compute(self):
        entity_type = self._entity_type.currentText()
        metric_name = self._metric.currentText()
        session = None

        try:
            session = self._sf()
            trend_engine = TrendEngine(session)

            from ..warehouse.models import Period
            from sqlalchemy import func as sa_func
            row = session.query(
                sa_func.min(Period.start_date), sa_func.max(Period.end_date)
            ).first()
            if not row or not row[0] or not row[1]:
                self._table.setRowCount(0)
                return

            start, end = row[0], row[1]
            import calendar
            periods = []
            cur = start.replace(day=1)
            while cur <= end:
                last = calendar.monthrange(cur.year, cur.month)[1]
                m_end = cur.replace(day=last)
                if m_end > end:
                    m_end = end
                periods.append((cur, m_end))
                if cur.month == 12:
                    cur = cur.replace(year=cur.year + 1, month=1)
                else:
                    cur = cur.replace(month=cur.month + 1)

            trends = trend_engine.compute_period_trends(entity_type, metric_name, periods)
            trends.sort(key=lambda t: t.current_value or 0, reverse=True)

            self._table.setRowCount(len(trends))
            for i, t in enumerate(trends):
                self._table.setItem(i, 0, QTableWidgetItem(t.entity_name))
                self._table.setItem(i, 1, QTableWidgetItem(f"{t.current_value:,.2f}" if t.current_value else ""))
                self._table.setItem(i, 2, QTableWidgetItem(f"{t.previous_value:,.2f}" if t.previous_value else ""))
                self._table.setItem(i, 3, QTableWidgetItem(f"{t.absolute_change:,.2f}" if t.absolute_change else ""))
                self._table.setItem(i, 4, QTableWidgetItem(f"{t.percent_change:.1f}%" if t.percent_change else ""))
                self._table.setItem(i, 5, QTableWidgetItem(str(t.current_rank or "")))
                self._table.setItem(i, 6, QTableWidgetItem(str(t.rank_change or "")))
                self._table.setItem(i, 7, QTableWidgetItem(f"{t.volatility:,.2f}" if t.volatility else ""))
        except Exception as e:
            logger.error("Trend computation failed: %s", e)
        finally:
            if session is not None:
                session.close()


class SettingsView(QWidget):
    """Settings and diagnostics view.  Refreshes from live config on every show."""

    def __init__(self, config: ConfigManager):
        super().__init__()
        self._config = config
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Settings")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        layout.addWidget(title)

        self._paths_group = QGroupBox("Paths")
        self._paths_layout = QVBoxLayout(self._paths_group)
        self._path_fields: dict[str, QLineEdit] = {}
        for name in ["Intake Folder", "App Data", "Output Dir", "Database", "AI Model Dir"]:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{name}:"))
            le = QLineEdit()
            le.setReadOnly(True)
            row.addWidget(le)
            self._paths_layout.addLayout(row)
            self._path_fields[name] = le
        layout.addWidget(self._paths_group)

        self._model_group = QGroupBox("AI Model")
        mg_layout = QVBoxLayout(self._model_group)
        self._model_status_label = QLabel()
        self._model_status_label.setWordWrap(True)
        mg_layout.addWidget(self._model_status_label)
        self._model_instructions = QLabel()
        self._model_instructions.setWordWrap(True)
        self._model_instructions.setStyleSheet("color: #555; font-size: 10px;")
        mg_layout.addWidget(self._model_instructions)
        layout.addWidget(self._model_group)

        layout.addStretch()
        self.refresh()

    def refresh(self):
        s = self._config.settings
        values = {
            "Intake Folder": s.intake_folder,
            "App Data": s.app_data_dir,
            "Output Dir": s.output_dir,
            "Database": s.db_path,
            "AI Model Dir": s.ai_model_dir,
        }
        for name, le in self._path_fields.items():
            le.setText(values.get(name, ""))

        mm = ModelManager(s.ai_model_dir)
        status = mm.check_status()
        if status.ready:
            self._model_status_label.setText(
                f"Status: Installed and ready  |  Model: {status.model_name}  |  "
                f"Size: {status.model_size_mb:.1f} MB"
            )
            self._model_instructions.setText("")
        elif status.installed and not status.runtime_available:
            self._model_status_label.setText(
                "Status: Model files present but ONNX Runtime not installed"
            )
            self._model_instructions.setText(
                "Install onnxruntime: pip install onnxruntime"
            )
        else:
            self._model_status_label.setText(
                "Status: Not installed — using deterministic fallback (fully functional)"
            )
            self._model_instructions.setText(
                f"To enable AI planning, place ONNX model files in:\n{s.ai_model_dir}\n\n"
                "The app works fully without a model. The deterministic parser handles "
                "all common report requests."
            )


class MainWindow(QMainWindow):
    """Main application window."""

    rerun_setup_requested = Signal()

    def __init__(self, config: ConfigManager, session_factory):
        super().__init__()
        self._config = config
        self._sf = session_factory

        self.setWindowTitle("ReportBuilder")
        self.setMinimumSize(1100, 700)

        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        rerun_action = QAction("Re-run Setup Wizard...", self)
        rerun_action.triggered.connect(self._request_rerun_setup)
        file_menu.addAction(rerun_action)

        self._template_registry = TemplateRegistry()
        self._template_registry.register(TeamEfficiencyTenureTemplate())
        self._template_registry.register(SnapshotVsPerformanceTemplate())
        self._template_registry.register(TrendFocusTemplate())
        self._template_registry.register(ExecutiveInfographicTemplate())

        parser_registry = create_default_registry()
        self._orchestrator = IngestOrchestrator(
            session_factory, config.settings.staging_dir, parser_registry
        )

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        nav = QListWidget()
        nav.setFixedWidth(180)
        nav.setFont(QFont("Segoe UI", 11))
        nav.setStyleSheet("""
            QListWidget {
                background-color: #1a1a2e;
                color: white;
                border: none;
                padding: 8px 0;
            }
            QListWidget::item {
                padding: 12px 16px;
                border-bottom: 1px solid #16213e;
            }
            QListWidget::item:selected {
                background-color: #0f3460;
            }
            QListWidget::item:hover {
                background-color: #16213e;
            }
        """)
        for label in ["Dashboard", "Sources", "Data Explorer", "Ask the Data",
                       "Trends", "Reports", "Settings"]:
            nav.addItem(label)
        nav.currentRowChanged.connect(self._switch_view)
        main_layout.addWidget(nav)

        self._stack = QStackedWidget()

        self._dashboard = DashboardView(config, session_factory)
        self._sources = SourcesView(config, session_factory)
        self._explorer = DataExplorerView(session_factory)
        self._ask = AskTheDataView(config, session_factory, self._template_registry)
        self._trends = TrendsView(session_factory)
        self._artifacts = ArtifactsView(config, session_factory)
        self._settings = SettingsView(config)

        self._stack.addWidget(self._dashboard)
        self._stack.addWidget(self._sources)
        self._stack.addWidget(self._explorer)
        self._stack.addWidget(self._ask)
        self._stack.addWidget(self._trends)
        self._stack.addWidget(self._artifacts)
        self._stack.addWidget(self._settings)

        main_layout.addWidget(self._stack)

        self._sources.ingest_requested.connect(self._run_ingest)
        self._ask.report_generated.connect(self._on_report_generated)

        nav.setCurrentRow(0)
        self._dashboard.refresh()

    def _request_rerun_setup(self):
        confirm = QMessageBox.question(
            self,
            "Re-run Setup Wizard",
            "This will open the setup wizard so you can reconfigure paths "
            "and settings.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirm == QMessageBox.Yes:
            self.rerun_setup_requested.emit()

    def _switch_view(self, index: int):
        self._stack.setCurrentIndex(index)
        views = [self._dashboard, self._sources, self._explorer,
                 self._ask, self._trends, self._artifacts, self._settings]
        if index < len(views) and hasattr(views[index], "refresh"):
            views[index].refresh()

    def _run_ingest(self):
        self._worker = IngestWorker(self._orchestrator, self._config.settings.intake_folder)
        self._worker.finished.connect(self._on_ingest_done)
        self._worker.start()

    def _on_ingest_done(self, result: dict):
        self._sources.refresh()
        self._dashboard.refresh()
        logger.info("Ingest complete: %s", result)

    def _on_report_generated(self, outputs: list):
        self._artifacts.refresh()

    def refresh_services(self, session_factory):
        """Rebind to a new session factory after config changes."""
        self._sf = session_factory
        self._dashboard._sf = session_factory
        self._sources._sf = session_factory
        self._explorer._sf = session_factory
        self._ask._sf = session_factory
        self._trends._sf = session_factory
        self._artifacts._sf = session_factory

        parser_registry = create_default_registry()
        self._orchestrator = IngestOrchestrator(
            session_factory, self._config.settings.staging_dir, parser_registry
        )

        self._settings.refresh()
        self._dashboard.refresh()

    def run_initial_scan(self):
        self._run_ingest()
