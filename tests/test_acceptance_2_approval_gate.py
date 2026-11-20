# -*- coding: utf-8 -*-
"""Acceptance criterion 2: no file is generated when include_detail=true and
the export is not approved. Aggregates-only bypass the gate; reject path never
produces a file either."""
from __future__ import annotations

import io

from openpyxl import load_workbook

from app.worker import process_pending

from tests.conftest import ANALYST, MANAGER


def test_detail_export_pending_approval_generates_no_file(client):
    resp = client.post("/api/dash/exports", json={
        "panel": "revenue", "include_detail": True,
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers=ANALYST)
    assert resp.status_code == 201
    export = resp.json()
    assert export["status"] == "pending_approval"

    process_pending()  # worker must skip pending_approval entirely

    detail = client.get(f"/api/dash/exports/{export['id']}", headers=ANALYST).json()
    assert detail["status"] == "pending_approval"
    assert detail["file_key"] is None
    assert detail["download_url"] is None  # no file -> no link


def test_aggregates_only_export_bypasses_gate(client):
    resp = client.post("/api/dash/exports", json={
        "panel": "occupancy", "include_detail": False,
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers=ANALYST)
    export = resp.json()
    assert export["status"] == "queued"  # straight to queue
    process_pending()
    detail = client.get(f"/api/dash/exports/{export['id']}", headers=ANALYST).json()
    assert detail["status"] == "succeeded"
    assert detail["file_key"]


def test_approve_then_generate_file(client):
    resp = client.post("/api/dash/exports", json={
        "panel": "revenue", "include_detail": True,
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers=ANALYST)
    export = resp.json()

    denied = client.post(f"/api/dash/exports/{export['id']}/approve",
                         headers=ANALYST).status_code
    assert denied == 403  # analyst lacks the approval role

    ok = client.post(f"/api/dash/exports/{export['id']}/approve", headers=MANAGER)
    assert ok.status_code == 200
    assert ok.json()["status"] == "queued"

    process_pending()
    detail = client.get(f"/api/dash/exports/{export['id']}", headers=ANALYST).json()
    assert detail["status"] == "succeeded"
    assert detail["file_key"]


def test_reject_never_generates_file(client):
    resp = client.post("/api/dash/exports", json={
        "panel": "revenue", "include_detail": True,
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers=ANALYST)
    export = resp.json()
    ok = client.post(f"/api/dash/exports/{export['id']}/reject",
                     json={"reason": "numbers need re-checking"}, headers=MANAGER)
    assert ok.status_code == 200
    assert ok.json()["status"] == "rejected"

    process_pending()
    detail = client.get(f"/api/dash/exports/{export['id']}", headers=ANALYST).json()
    assert detail["status"] == "rejected"
    assert detail["file_key"] is None
    assert detail["download_url"] is None


def test_creator_cannot_approve_own_export(client):
    resp = client.post("/api/dash/exports", json={
        "panel": "revenue", "include_detail": True,
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers={"X-User-Id": "manager-2", "X-Role": "ops_manager"})
    export = resp.json()
    denied = client.post(f"/api/dash/exports/{export['id']}/approve",
                         headers={"X-User-Id": "manager-2", "X-Role": "ops_manager"})
    assert denied.status_code == 403  # creator self-approval blocked


def test_approved_detail_file_contains_detail_rows(client):
    """After approval the generated file must actually carry the detail
    roster (enterprises/employees), not just a copy of the aggregate export."""
    from app.generator import DETAIL_SHEET_NAME

    resp = client.post("/api/dash/exports", json={
        "panel": "revenue", "include_detail": True,
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers=ANALYST)
    export = resp.json()
    client.post(f"/api/dash/exports/{export['id']}/approve", headers=MANAGER)
    process_pending()

    detail = client.get(f"/api/dash/exports/{export['id']}", headers=ANALYST).json()
    assert detail["status"] == "succeeded"
    wb = load_workbook(io.BytesIO(client.get(detail["download_url"]).content))
    assert DETAIL_SHEET_NAME in wb.sheetnames
    sheet = wb[DETAIL_SHEET_NAME]
    kinds = {sheet.cell(row=r, column=1).value
             for r in range(3, sheet.max_row + 1)}
    assert {"enterprise", "employee"} <= kinds  # real detail rows present


def test_aggregate_file_has_no_detail_sheet(client):
    """include_detail=false must NOT leak the detail roster into the file."""
    from app.generator import DETAIL_SHEET_NAME

    resp = client.post("/api/dash/exports", json={
        "panel": "revenue", "include_detail": False,
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers=ANALYST)
    export = resp.json()
    process_pending()

    detail = client.get(f"/api/dash/exports/{export['id']}", headers=ANALYST).json()
    assert detail["status"] == "succeeded"
    wb = load_workbook(io.BytesIO(client.get(detail["download_url"]).content))
    assert DETAIL_SHEET_NAME not in wb.sheetnames
    assert wb.sheetnames == ["Panel Data", "Caliber"]


def test_approve_requires_ops_manager_role(client):
    resp = client.post("/api/dash/exports", json={
        "panel": "revenue", "include_detail": True,
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers=ANALYST)
    export = resp.json()
    for role in ("analyst", "intern", ""):
        code = client.post(f"/api/dash/exports/{export['id']}/approve",
                           headers={"X-User-Id": "someone", "X-Role": role}).status_code
        assert code == 403, role
