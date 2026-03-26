"""Local AI model manager: detect, install, validate, and manage model assets.

Handles the lifecycle of the local planner model to enable fully offline operation.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelStatus:
    installed: bool = False
    model_dir: str = ""
    model_name: str = ""
    model_size_mb: float = 0.0
    runtime_available: bool = False
    runtime_name: str = ""
    ready: bool = False
    error: Optional[str] = None


class ModelManager:
    """Manages local AI model installation and readiness."""

    DEFAULT_MODEL_NAME = "phi-4-mini-instruct-onnx"

    def __init__(self, model_dir: str):
        self._model_dir = Path(model_dir)
        self._model_dir.mkdir(parents=True, exist_ok=True)

    @property
    def model_dir(self) -> Path:
        return self._model_dir

    def check_status(self) -> ModelStatus:
        status = ModelStatus(model_dir=str(self._model_dir))

        onnx_files = list(self._model_dir.glob("*.onnx"))
        if onnx_files:
            status.installed = True
            status.model_name = onnx_files[0].stem
            status.model_size_mb = sum(f.stat().st_size for f in onnx_files) / (1024 * 1024)

        status.runtime_available = self._check_runtime()
        if status.runtime_available:
            status.runtime_name = "onnxruntime"

        status.ready = status.installed and status.runtime_available
        return status

    def _check_runtime(self) -> bool:
        try:
            import onnxruntime
            return True
        except ImportError:
            return False

    def install_model(self, source_path: str = None) -> ModelStatus:
        """Install model from a local source path or trigger download setup.

        For fully offline operation, model assets should be bundled or
        pre-installed. This method handles:
        1. Copying from a local source (USB, network share, bundled assets)
        2. Validating the installation
        """
        if source_path:
            src = Path(source_path)
            if src.is_dir():
                for f in src.iterdir():
                    shutil.copy2(f, self._model_dir / f.name)
                logger.info("Model installed from %s", source_path)
            elif src.is_file() and src.suffix == ".onnx":
                shutil.copy2(src, self._model_dir / src.name)
                logger.info("Model file installed: %s", src.name)

        status = self.check_status()
        self._write_manifest(status)
        return status

    def _write_manifest(self, status: ModelStatus) -> None:
        manifest = {
            "model_name": status.model_name,
            "installed": status.installed,
            "runtime": status.runtime_name,
            "size_mb": status.model_size_mb,
        }
        manifest_path = self._model_dir / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

    def get_model_info(self) -> dict:
        manifest_path = self._model_dir / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                return json.load(f)
        return {"installed": False, "note": "No model installed yet"}

    def create_placeholder(self) -> None:
        """Create a placeholder indicating where model should be installed."""
        readme = self._model_dir / "README.md"
        if not readme.exists():
            readme.write_text(
                "# AI Planner Model Directory\n\n"
                "Place your ONNX planner model files here.\n\n"
                "Recommended: Phi-4-mini-instruct ONNX format.\n\n"
                "The app will function without the AI model using a "
                "deterministic fallback parser.\n\n"
                "To install:\n"
                "1. Download the ONNX model files\n"
                "2. Place all .onnx and tokenizer files in this directory\n"
                "3. Restart the app\n"
            )
