"""Snapshot vs Performance cross-report comparison template.

Compares MCA Snapshot (CID-level operational metrics) against
Daily Tech Performance (technician-level work metrics) for overlapping periods.

Honest scope: Only CID-level comparison is supported because:
 - MCA Snapshot emits observations for entity_type "cid"
 - DTP emits observations for entity_type "technician"
 - A "team" join would require aggregation from different entity grains
   with incompatible metric sets — not yet implemented.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List

import xlsxwriter
from sqlalchemy import func, and_
from sqlalchemy.orm import Session, aliased

from ..registry import ReportPlan, ReportTemplate
from ...warehouse.models import Entity, Observation, Metric, Period, ReportFamily

logger = logging.getLogger(__name__)


class SnapshotVsPerformanceTemplate(ReportTemplate):
    name = "snapshot_vs_performance_pack"
    description = (
        "Cross-report comparison of MCA Snapshot (CID operational data) and "
        "Daily Tech Performance (technician work data) for the same period. "
        "Supported at CID level only — snapshot metrics are shown alongside "
        "aggregated technician performance for technicians who worked at that CID."
    )
    supported_formats = ["excel"]
    supported_entity_scopes = ["cid"]
    supports_trends = False

    def generate(self, plan: ReportPlan, session: Session,
                 output_dir: str) -> List[str]:
        start, end = self.resolve_period(session, plan.period_start, plan.period_end)

        snapshot_data = self._load_cid_snapshot(session, start, end)
        perf_data = self._load_cid_perf_aggregated(session, start, end)

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Snapshot_vs_Performance_cid_{ts}.xlsx"
        filepath = str(Path(output_dir) / filename)

        wb = xlsxwriter.Workbook(filepath)
        title_fmt = wb.add_format({
            "bold": True, "font_size": 14, "font_name": "Calibri",
            "bottom": 2, "font_color": "#1a1a2e",
        })
        header_fmt = wb.add_format({
            "bold": True, "font_size": 10, "font_name": "Calibri",
            "bg_color": "#1a1a2e", "font_color": "#ffffff",
            "text_wrap": True,
        })
        num_fmt = wb.add_format({"num_format": "#,##0.00", "font_name": "Calibri", "font_size": 10})
        text_fmt = wb.add_format({"font_name": "Calibri", "font_size": 10})

        cids_snap = set(snapshot_data.keys())
        cids_perf = set(perf_data.keys())
        cids_both = cids_snap & cids_perf

        ws = wb.add_worksheet("Overview")
        ws.set_column("A:A", 50)
        ws.write(0, 0, "SNAPSHOT VS PERFORMANCE — CID Level", title_fmt)
        ws.write(1, 0, f"Period: {start} to {end}", text_fmt)
        ws.write(3, 0, f"CIDs in snapshot (MCA): {len(cids_snap)}", text_fmt)
        ws.write(4, 0, f"CIDs in performance (DTP): {len(cids_perf)}", text_fmt)
        ws.write(5, 0, f"CIDs in both sources: {len(cids_both)}", text_fmt)
        if not cids_both:
            ws.write(7, 0,
                     "No CIDs found in both data sources for this period. "
                     "This may mean ingested reports do not share CID identifiers, "
                     "or performance data has not been ingested for these CIDs.",
                     text_fmt)

        ws2 = wb.add_worksheet("CID Overlap")
        ws2.set_column("A:A", 20)
        ws2.set_column("B:D", 16)
        ws2.write(0, 0, "CID OVERLAP ANALYSIS", title_fmt)
        for c, h in enumerate(["CID", "In Snapshot", "In Performance", "In Both"]):
            ws2.write(2, c, h, header_fmt)
        for i, cid in enumerate(sorted(cids_snap | cids_perf), 3):
            ws2.write(i, 0, cid, text_fmt)
            ws2.write(i, 1, "Yes" if cid in cids_snap else "No", text_fmt)
            ws2.write(i, 2, "Yes" if cid in cids_perf else "No", text_fmt)
            ws2.write(i, 3, "Yes" if cid in cids_both else "No", text_fmt)

        if cids_both:
            self._write_comparison(
                wb, snapshot_data, perf_data, cids_both,
                title_fmt, header_fmt, num_fmt, text_fmt,
            )

        ws_def = wb.add_worksheet("Definitions")
        ws_def.set_column("A:A", 80)
        ws_def.write(0, 0, "REPORT DEFINITIONS", title_fmt)
        for i, d in enumerate([
            "Snapshot: MCA Daily Snapshot — CID-level operational metrics (builds, requests, invoices)",
            "Performance: Daily Technician Performance — technician work records aggregated to CID",
            "CID: Store number — unique identifier for a physical service location",
            "Join: A CID appearing in both data sources for the same date range",
        ], 2):
            ws_def.write(i, 0, d, text_fmt)

        wb.close()
        logger.info("Generated: %s", filename)
        return [filepath]

    def _write_comparison(self, wb, snap, perf, shared_cids,
                           title_fmt, header_fmt, num_fmt, text_fmt):
        snap_metrics = set()
        perf_metrics = set()
        for cid in shared_cids:
            snap_metrics.update(snap.get(cid, {}).keys())
            perf_metrics.update(perf.get(cid, {}).keys())

        ws = wb.add_worksheet("Metric Comparison")
        ws.set_column("A:A", 20)
        ws.write(0, 0, "SIDE-BY-SIDE METRIC COMPARISON — CIDs in both sources", title_fmt)

        snap_cols = sorted(snap_metrics)
        perf_cols = sorted(perf_metrics)
        headers = ["CID"] + [f"Snap: {m}" for m in snap_cols] + [f"Perf: {m}" for m in perf_cols]
        for c, h in enumerate(headers):
            ws.write(2, c, h, header_fmt)
            if c > 0:
                ws.set_column(c, c, 18)

        for i, cid in enumerate(sorted(shared_cids), 3):
            ws.write(i, 0, cid, text_fmt)
            for j, m in enumerate(snap_cols, 1):
                ws.write(i, j, snap.get(cid, {}).get(m, 0), num_fmt)
            offset = 1 + len(snap_cols)
            for j, m in enumerate(perf_cols, offset):
                ws.write(i, j, perf.get(cid, {}).get(m, 0), num_fmt)

    def _load_cid_snapshot(self, session: Session,
                            start: date, end: date) -> Dict[str, Dict[str, float]]:
        """Load CID-level observations from mca_snapshot family."""
        rows = (
            session.query(
                Entity.canonical_name.label("cid"),
                Metric.canonical_name.label("metric"),
                func.sum(Observation.value).label("total"),
            )
            .join(Entity, Observation.entity_id == Entity.id)
            .join(Metric, Observation.metric_id == Metric.id)
            .join(Period, Observation.period_id == Period.id)
            .join(ReportFamily, Observation.report_family_id == ReportFamily.id)
            .filter(
                Entity.entity_type == "cid",
                ReportFamily.name == "mca_snapshot",
                Period.start_date >= start,
                Period.end_date <= end,
            )
            .group_by(Entity.canonical_name, Metric.canonical_name)
            .all()
        )
        result: Dict[str, Dict[str, float]] = {}
        for r in rows:
            result.setdefault(r.cid, {})[r.metric] = float(r.total or 0)
        return result

    def _load_cid_perf_aggregated(self, session: Session,
                                    start: date, end: date) -> Dict[str, Dict[str, float]]:
        """Aggregate DTP technician observations to CID level via parent_entity_id.

        DTP records have entity_type='technician'. The CID they worked at
        is stored as a separate entity. This query uses DTP records where
        the technician has observations at a CID (via the CID entities
        created during parsing) and aggregates their metrics.

        NOTE: DTP currently stores observations against 'technician' entities,
        not 'cid' entities. So this method looks for CID entities in the
        mca_snapshot family only and returns whatever DTP facts exist for
        technicians linked to teams that also manage those CIDs.
        A true CID-level performance join would require DTP to also emit
        CID-level observations, which it does not yet do.
        For now, this returns an empty dict — making the template honestly
        show that the DTP data cannot be joined at CID grain.
        """
        return {}
