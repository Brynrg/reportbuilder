#!/usr/bin/env python3
"""Build script for packaging ReportBuilder as a standalone desktop app.

Prerequisites:
    pip install pyinstaller>=6.0

Usage:
    python scripts/build.py

Output:
    dist/ReportBuilder/  (one-dir bundle)

Note: This does NOT perform code signing or notarization.
macOS Gatekeeper may quarantine the app on first launch.
"""

import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HIDDEN_IMPORTS = [
    "reportbuilder",
    "reportbuilder.app",
    "reportbuilder.config",
    "reportbuilder.warehouse",
    "reportbuilder.warehouse.models",
    "reportbuilder.warehouse.repository",
    "reportbuilder.warehouse.migrations",
    "reportbuilder.ingestion",
    "reportbuilder.ingestion.scanner",
    "reportbuilder.ingestion.watcher",
    "reportbuilder.ingestion.zip_handler",
    "reportbuilder.parsing",
    "reportbuilder.parsing.detector",
    "reportbuilder.parsing.daily_tech_performance",
    "reportbuilder.parsing.mca_snapshot",
    "reportbuilder.parsing.mileage_csv",
    "reportbuilder.analytics",
    "reportbuilder.analytics.engine",
    "reportbuilder.reports",
    "reportbuilder.reports.registry",
    "reportbuilder.reports.templates",
    "reportbuilder.reports.templates.team_efficiency_tenure",
    "reportbuilder.reports.templates.snapshot_vs_performance",
    "reportbuilder.reports.templates.trend_focus",
    "reportbuilder.reports.templates.executive_pdf",
    "reportbuilder.reports.pdf_renderer",
    "reportbuilder.ai",
    "reportbuilder.ai.planner",
    "reportbuilder.ai.model_manager",
    "reportbuilder.ai.schemas",
    "reportbuilder.normalization",
    "reportbuilder.normalization.resolvers",
    "reportbuilder.ui",
    "reportbuilder.ui.setup_wizard",
    "reportbuilder.ui.main_window",
    "PySide6",
    "sqlalchemy",
    "openpyxl",
    "xlsxwriter",
    "reportlab",
    "watchdog",
    "pandas",
]


def build_app():
    """Build the app using PyInstaller."""
    entry = ROOT / "run.py"
    dist = ROOT / "dist"
    sep = ";" if platform.system() == "Windows" else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "ReportBuilder",
        "--onedir",
        "--windowed",
        "--add-data", f"{ROOT / 'src'}{sep}src",
        "--distpath", str(dist),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT),
    ]
    for imp in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", imp])
    cmd.append(str(entry))

    print("Building ReportBuilder...")
    print(f"  Entry: {entry}")
    print(f"  Output: {dist / 'ReportBuilder'}")
    print()
    subprocess.run(cmd, check=True)
    print(f"\nBuild complete! App bundle in: {dist / 'ReportBuilder'}")
    print("NOTE: This build is NOT code-signed or notarized.")


if __name__ == "__main__":
    build_app()
