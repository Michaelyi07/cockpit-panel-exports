# -*- coding: utf-8 -*-
"""Acceptance criterion 1: the exported XLSX contains a data sheet and a
caliber worksheet, with caliber instructions (metric code, definition,
version, data end time, filter conditions). CSV fallback documented too."""
from __future__ import annotations

import io
import json

from openpyxl import load_workbook

from app.worker import process_pending


def _create(client, payload=None):
    payload = payload or {"panel": "occupancy",
                          "filters": {"site_id": "00000000-0000-0000-0000-000000000001",
                                      "date_from": "2026-11-01", "date_to": "2026-12-31"}}
    resp = client.post("/api/dash/exports", json=payload, headers=_hdr())
    assert resp.status_code == 201, resp.text
    return resp.json()


def _hdr():
    from tests.conftest import ANALYST
    return ANALYST


def _succeeded(client, payload=None):
    export = _create(client, payload)
    assert process_pending() >= 1
    detail = client.get(f"/api/dash/exports/{export['id']}", headers=_hdr()).json()
    assert detail["status"] == "succeeded", detail
    return detail


def test_xlsx_has_panel_data_and_caliber_sheets(client):
    detail = _succeeded(client)
    data = client.get(detail["download_url"]).content
    wb = load_workbook(io.BytesIO(data))
    # sheet order: data first, caliber second (per brief)
    assert wb.sheetnames == ["Panel Data", "Caliber"]

    data_sheet = wb["Panel Data"]
    headers = [data_sheet.cell(row=2, column=c).value
               for c in range(1, data_sheet.max_column + 1)]
    assert headers == ["metric_code", "period", "dimension", "value"]
    # data rows actually present (seeded occupancy facts for site 1)
    assert data_sheet.max_row >= 3

    caliber = wb["Caliber"]
    # row 2 = column headers; data rows start at row 3
    rows = [[caliber.cell(row=r, column=c).value
             for c in range(1, 6)] for r in range(3, caliber.max_row + 1)]
    codes = {row[0] for row in rows}
    assert {"rentable_workstations", "leased_workstations", "occ_rate"} <= codes
    for row in rows:
        # caliber instruction fields per brief: code, definition, version,
        # data end time, filter conditions
        assert row[1], "definition must be present"
        assert row[2], "caliber version must be present"
        assert row[3], "data end time must be present"
        echo = json.loads(row[4])
        assert echo["date_from"] == "2026-11-01"
        assert echo["date_to"] == "2026-12-31"


def test_data_end_time_reflects_dataset(client):
    detail = _succeeded(client)
    data = client.get(detail["download_url"]).content
    wb = load_workbook(io.BytesIO(data))
    caliber = wb["Caliber"]
    end_time = caliber.cell(row=3, column=4).value
    # seeded occupancy facts end at 2026-12-31 (period)
    assert "2026-12-31" in end_time


def test_caliber_versions_consistent(client):
    detail = _succeeded(client)
    data = client.get(detail["download_url"]).content
    wb = load_workbook(io.BytesIO(data))
    caliber = wb["Caliber"]
    versions = {caliber.cell(row=r, column=3).value
                for r in range(3, caliber.max_row + 1)}
    assert len(versions) == 1  # single caliber version across the report


def test_csv_fallback_contains_caliber_and_watermark(client):
    detail = _succeeded(client, payload={
        "panel": "leads", "export_format": "csv",
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}})
    data = client.get(detail["download_url"]).content.decode("utf-8")
    assert detail["watermark"] in data
    assert "# caliber: metric_code" in data
    assert "data_end_time" in data
    assert "leads_new" in data
