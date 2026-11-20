# -*- coding: utf-8 -*-
"""Edge cases beyond the four acceptance criteria: auth, validation, list
filters, async worker semantics, audit coverage of every event."""
from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog
from app.worker import process_pending

from tests.conftest import ANALYST


def test_anonymous_create_returns_401(client):
    resp = client.post("/api/dash/exports", json={"panel": "occupancy"})
    assert resp.status_code == 401


def test_unknown_role_returns_403(client):
    resp = client.post("/api/dash/exports", json={"panel": "occupancy"},
                       headers={"X-User-Id": "u1", "X-Role": "wizard"})
    assert resp.status_code == 403


def test_unknown_panel_rejected(client):
    resp = client.post("/api/dash/exports", json={"panel": "weather"},
                       headers=ANALYST)
    assert resp.status_code == 422


def test_bad_filter_date_rejected(client):
    resp = client.post("/api/dash/exports", json={
        "panel": "occupancy", "filters": {"date_from": "not-a-date"}},
        headers=ANALYST)
    assert resp.status_code == 422


def test_unknown_site_filter_yields_empty_data_sheet(client):
    """Filter with a site that has no facts: file still succeeds, zero data
    rows, caliber sheet intact (honest empty report)."""
    resp = client.post("/api/dash/exports", json={
        "panel": "occupancy",
        "filters": {"site_id": "00000000-0000-0000-0000-00000000ffff"}},
        headers=ANALYST)
    export = resp.json()
    process_pending()
    detail = client.get(f"/api/dash/exports/{export['id']}", headers=ANALYST).json()
    assert detail["status"] == "succeeded"
    import io
    from openpyxl import load_workbook
    data = client.get(detail["download_url"]).content
    wb = load_workbook(io.BytesIO(data))
    data_sheet = wb["Panel Data"]
    assert data_sheet.max_row == 2  # watermark + headers only
    assert wb["Caliber"].max_row >= 3  # caliber rows still present


def test_list_filters_by_status(client):
    client.post("/api/dash/exports", json={"panel": "occupancy"}, headers=ANALYST)
    client.post("/api/dash/exports", json={
        "panel": "revenue", "include_detail": True,
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers=ANALYST)
    queued = client.get("/api/dash/exports?status=queued", headers=ANALYST).json()
    pending = client.get("/api/dash/exports?status=pending_approval",
                         headers=ANALYST).json()
    assert queued and all(x["status"] == "queued" for x in queued)
    assert pending and all(x["status"] == "pending_approval" for x in pending)


def test_worker_processes_all_queued_in_batch(client):
    ids = set()
    for _ in range(3):
        resp = client.post("/api/dash/exports", json={"panel": "leads"},
                           headers=ANALYST)
        ids.add(resp.json()["id"])
    n = process_pending()
    assert n >= 3
    for eid in ids:
        detail = client.get(f"/api/dash/exports/{eid}", headers=ANALYST).json()
        assert detail["status"] == "succeeded"


def test_every_export_event_audited(client):
    resp = client.post("/api/dash/exports", json={
        "panel": "revenue", "include_detail": True,
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers=ANALYST)
    eid = resp.json()["id"]
    client.post(f"/api/dash/exports/{eid}/approve", headers={
        "X-User-Id": "manager-1", "X-Role": "ops_manager"})
    process_pending()
    client.get(f"/api/dash/exports/{eid}", headers=ANALYST)

    with __import__("app.db", fromlist=["SessionLocal"]).SessionLocal() as session:
        actions = {r.action for r in session.execute(
            select(AuditLog).where(AuditLog.resource_id == eid)).scalars().all()}
    assert {"export.requested", "export.approved", "export.succeeded",
            "export.link_issued"} <= actions
    assert all(a.startswith("export.") for a in actions)


def test_generate_failure_recorded(client, monkeypatch):
    """Generator failure -> status=failed + audit, not a silent hang."""
    from app import generator as gen_mod
    from app import worker as worker_mod

    resp = client.post("/api/dash/exports", json={"panel": "occupancy"},
                       headers=ANALYST)
    eid = resp.json()["id"]

    def boom(*a, **kw):
        raise RuntimeError("simulated renderer crash")

    monkeypatch.setattr(worker_mod, "render", boom)
    process_pending()
    detail = client.get(f"/api/dash/exports/{eid}", headers=ANALYST).json()
    assert detail["status"] == "failed"
    assert "simulated renderer crash" in detail["error"]
    with __import__("app.db", fromlist=["SessionLocal"]).SessionLocal() as session:
        n = len(session.execute(
            select(AuditLog).where(AuditLog.resource_id == eid,
                                   AuditLog.action == "export.failed")).scalars().all())
        assert n == 1
