"""ZIP archive inspector and extractor with lineage tracking."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".xlsb", ".csv"}


def inspect_zip(zip_path: str) -> List[dict]:
    """List supported members in a ZIP archive."""
    members = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                ext = Path(info.filename).suffix.lower()
                if ext in SUPPORTED_EXTENSIONS:
                    members.append({
                        "member_path": info.filename,
                        "filename": Path(info.filename).name,
                        "extension": ext,
                        "compressed_size": info.compress_size,
                        "uncompressed_size": info.file_size,
                    })
    except (zipfile.BadZipFile, Exception) as e:
        logger.error("Failed to inspect ZIP %s: %s", zip_path, e)
    return members


def extract_zip(zip_path: str, staging_dir: str,
                prefix: str = "") -> List[Tuple[str, str]]:
    """Extract supported files from ZIP to staging directory.
    
    Returns list of (extracted_path, original_member_path) tuples.
    """
    extracted = []
    staging = Path(staging_dir)
    staging.mkdir(parents=True, exist_ok=True)

    zip_stem = Path(zip_path).stem
    target_dir = staging / zip_stem
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                ext = Path(info.filename).suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                member_path = info.filename
                safe_name = member_path.replace("/", "__").replace("\\", "__")
                if prefix:
                    safe_name = f"{prefix}__{safe_name}"

                dest = target_dir / safe_name
                counter = 0
                while dest.exists():
                    counter += 1
                    dest = target_dir / f"{dest.stem}_{counter}{dest.suffix}"

                with zf.open(info) as src, open(dest, "wb") as dst:
                    dst.write(src.read())

                extracted.append((str(dest), member_path))
                logger.debug("Extracted: %s -> %s", member_path, dest)

    except (zipfile.BadZipFile, Exception) as e:
        logger.error("Failed to extract ZIP %s: %s", zip_path, e)

    logger.info("Extracted %d files from %s", len(extracted), Path(zip_path).name)
    return extracted
