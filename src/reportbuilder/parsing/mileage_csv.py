"""Parser for MCA Disbursed Mileage CSV report family.

Source layout (CSV):
  Headers: Name, Role, RVP, Team, Date, Status, Total Mileage, Total Amount
  Each row = one mileage disbursement for one technician on one date.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseParser
from ..warehouse.repository import WarehouseRepository

logger = logging.getLogger(__name__)

MILEAGE_FILENAME_PATTERN = re.compile(
    r"(mileage|disbursed)", re.IGNORECASE,
)

EXPECTED_HEADERS = {"name", "team", "date", "total mileage", "total amount"}

COLUMN_MAP = {
    "Name": "technician_name",
    "Role": "role",
    "RVP": "rvp",
    "Team": "team",
    "Date": "mileage_date",
    "Status": "status",
    "Total Mileage": "total_mileage",
    "Total Amount": "total_amount",
}


class MileageCSVParser(BaseParser):

    @property
    def family_name(self) -> str:
        return "mileage_disbursed"

    def can_parse(self, filepath: str) -> float:
        path = Path(filepath)

        if path.suffix.lower() != ".csv":
            return 0.0

        if MILEAGE_FILENAME_PATTERN.search(path.name):
            confidence = 0.7
        elif "mca" in path.name.lower():
            confidence = 0.5
        else:
            confidence = 0.0

        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                header_row = next(reader, None)
                if header_row:
                    headers = {h.strip().lower() for h in header_row}
                    if len(headers & EXPECTED_HEADERS) >= 3:
                        return max(confidence, 0.8)
        except Exception:
            pass

        return confidence

    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        records = []
        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row_num, row in enumerate(reader, start=2):
                    record = {"_source_file": filepath, "_sheet": "csv", "_row": row_num}
                    for orig_col, field in COLUMN_MAP.items():
                        val = row.get(orig_col, "").strip()
                        if val:
                            record[field] = val
                    self._clean_record(record)
                    if record.get("technician_name"):
                        records.append(record)
        except Exception as e:
            logger.error("Failed to parse mileage CSV %s: %s", filepath, e)

        logger.info("Parsed %d mileage records from %s", len(records), Path(filepath).name)
        return records

    def _clean_record(self, record: Dict) -> None:
        date_val = record.get("mileage_date")
        if isinstance(date_val, str):
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
                try:
                    record["mileage_date"] = datetime.strptime(date_val, fmt).date()
                    break
                except ValueError:
                    continue

        for field in ("total_mileage", "total_amount"):
            val = record.get(field)
            if isinstance(val, str):
                val = val.replace(",", "").replace("$", "").strip()
                try:
                    record[field] = float(val)
                except ValueError:
                    record[field] = 0.0

    def normalize_and_store(self, records: List[Dict], repo: WarehouseRepository,
                           source_file_id: int, run_id: int) -> int:
        family = repo.get_or_create_family(
            "mileage_disbursed",
            "MCA Disbursed Mileage - technician mileage reimbursements"
        )

        mileage_metric = repo.get_or_create_metric(
            "total_miles", "Total Miles", "miles", "sum"
        )
        amount_metric = repo.get_or_create_metric(
            "mileage_paid", "Mileage Paid", "dollars", "sum"
        )

        obs_count = 0
        for rec in records:
            mileage_date = rec.get("mileage_date")
            if not isinstance(mileage_date, date):
                continue

            tech_name = str(rec.get("technician_name", "")).strip()
            if not tech_name:
                continue

            tech_entity = repo.get_or_create_entity("technician", tech_name)

            team_id = None
            team_name = rec.get("team")
            if team_name:
                team_entity = repo.get_or_create_entity("team", str(team_name).strip())
                team_id = team_entity.id
                if tech_entity.parent_id != team_id:
                    tech_entity.parent_id = team_id

            rvp_name = rec.get("rvp")
            if rvp_name:
                repo.get_or_create_entity("rvp", str(rvp_name).strip())

            period = repo.get_or_create_period(
                "day", mileage_date, mileage_date,
                label=mileage_date.strftime("%Y-%m-%d"),
            )

            miles = rec.get("total_mileage")
            if miles is not None:
                try:
                    repo.add_observation(
                        entity_id=tech_entity.id, period_id=period.id,
                        metric_id=mileage_metric.id, value=float(miles),
                        parent_entity_id=team_id,
                        report_family_id=family.id,
                        source_file_id=source_file_id,
                        ingest_run_id=run_id,
                    )
                    obs_count += 1
                except (ValueError, TypeError):
                    pass

            amount = rec.get("total_amount")
            if amount is not None:
                try:
                    repo.add_observation(
                        entity_id=tech_entity.id, period_id=period.id,
                        metric_id=amount_metric.id, value=float(amount),
                        parent_entity_id=team_id,
                        report_family_id=family.id,
                        source_file_id=source_file_id,
                        ingest_run_id=run_id,
                    )
                    obs_count += 1
                except (ValueError, TypeError):
                    pass

        repo.session.flush()
        return obs_count
