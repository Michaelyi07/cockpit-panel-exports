"""XLSX/CSV generation: Panel Data sheet + Caliber sheet, watermark in headers
and workbook properties. All numbers come from the fact query; the template
contains no hand-written values."""
from __future__ import annotations

import io
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import DashboardFact
from .panels import METRIC_MODE, PANEL_METRICS

WATERMARK_HEADER_PREFIX = "Watermark:"


def _tz() -> ZoneInfo:
    return ZoneInfo(config.TIMEZONE)


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(_tz()).strftime("%Y-%m-%d %H:%M:%S %Z")


def _apply_filters(query, *, panel: str, filters: dict):
    query = query.where(DashboardFact.panel == panel,
                        DashboardFact.deleted_at.is_(None))
    site_id = filters.get("site_id")
    if site_id:
        query = query.where(DashboardFact.site_id == site_id)
    date_from = filters.get("date_from")
    if date_from:
        query = query.where(DashboardFact.period >= str(date_from))
    date_to = filters.get("date_to")
    if date_to:
        query = query.where(DashboardFact.period <= str(date_to))
    for key, val in (filters.get("dimension") or {}).items():
        query = query.where(DashboardFact.dimension[key].astext == str(val))
    return query


def collect_rows(session: Session, *, panel: str, filters: dict) -> list[dict]:
    """Aggregate fact rows per (metric_code, period) in Python for deterministic
    rendering; aggregation modes follow the caliber registry."""
    rows = session.execute(_apply_filters(
        select(DashboardFact), panel=panel, filters=filters)).scalars().all()
    grouped: dict[tuple, dict] = {}
    for f in rows:
        key = (f.metric_code, f.period, json.dumps(f.dimension or {}, sort_keys=True))
        slot = grouped.setdefault(key, {"metric_code": f.metric_code,
                                        "period": f.period,
                                        "dimension": f.dimension or {},
                                        "sum_cents": 0, "sum_num": 0.0, "n": 0})
        if f.value_cents is not None:
            slot["sum_cents"] += f.value_cents
        if f.value_num is not None:
            slot["sum_num"] += float(f.value_num)
        slot["n"] += 1
    out = []
    for slot in sorted(grouped.values(), key=lambda s: (s["metric_code"], s["period"])):
        mode = METRIC_MODE.get(slot["metric_code"], "sum_num")
        if mode == "sum_cents":
            value = slot["sum_cents"]
        elif mode == "avg_num":
            value = round(slot["sum_num"] / slot["n"], 4) if slot["n"] else 0.0
        else:
            value = slot["sum_num"]
        out.append({"metric_code": slot["metric_code"], "period": slot["period"],
                    "dimension": slot["dimension"], "value": value})
    return out


def data_end_time(rows: list[dict]) -> str:
    if not rows:
        return _fmt_ts(datetime.now(_tz()))
    latest = max(r["period"] for r in rows)
    return _fmt_ts(datetime.strptime(latest, "%Y-%m-%d").replace(tzinfo=_tz()))


def _caliber_rows(panel: str, rows: list[dict], filters: dict) -> list[list[str]]:
    end = data_end_time(rows)
    echo = json.dumps(filters or {}, sort_keys=True, ensure_ascii=False)
    out = [["metric_code", "definition", "caliber_version", "data_end_time", "filters"]]
    for m in PANEL_METRICS[panel]:
        out.append([m["code"], m["definition"], config.CALIBER_VERSION, end, echo])
    return out


def render_xlsx(watermark: str, panel: str, rows: list[dict], filters: dict) -> bytes:
    wb = Workbook()
    data = wb.active
    data.title = "Panel Data"
    # watermark banner (row 1 on every sheet, per brief)
    data.cell(row=1, column=1, value=f"{WATERMARK_HEADER_PREFIX} {watermark}")
    headers = ["metric_code", "period", "dimension", "value"]
    for col, name in enumerate(headers, start=1):
        data.cell(row=2, column=col, value=name)
    for i, r in enumerate(rows, start=3):
        data.cell(row=i, column=1, value=r["metric_code"])
        data.cell(row=i, column=2, value=r["period"])
        data.cell(row=i, column=3, value=json.dumps(r["dimension"], sort_keys=True))
        data.cell(row=i, column=4, value=r["value"])

    caliber = wb.create_sheet("Caliber")
    caliber.cell(row=1, column=1, value=f"{WATERMARK_HEADER_PREFIX} {watermark}")
    for r_idx, row in enumerate(_caliber_rows(panel, rows, filters), start=2):
        for c_idx, cell_value in enumerate(row, start=1):
            caliber.cell(row=r_idx, column=c_idx, value=cell_value)

    # workbook properties carry the watermark (file attributes, per brief)
    wb.properties.title = watermark
    wb.properties.keywords = watermark
    wb.properties.category = "dash-export"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render_csv(watermark: str, panel: str, rows: list[dict], filters: dict) -> bytes:
    """CSV fallback for simple panels: caliber + watermark live in comment
    headers (CSV has no sheet structure)."""
    lines = [f"# {WATERMARK_HEADER_PREFIX} {watermark}"]
    for row in _caliber_rows(panel, rows, filters):
        lines.append("# caliber: " + " | ".join(str(c) for c in row))
    lines.append(",".join(["metric_code", "period", "dimension", "value"]))
    for r in rows:
        lines.append(",".join([
            r["metric_code"], r["period"],
            json.dumps(r["dimension"], sort_keys=True), str(r["value"]),
        ]))
    return ("\n".join(lines) + "\n").encode("utf-8")


def render(watermark: str, panel: str, rows: list[dict], filters: dict,
           export_format: str = "xlsx") -> bytes:
    if export_format == "csv":
        return render_csv(watermark, panel, rows, filters)
    return render_xlsx(watermark, panel, rows, filters)
