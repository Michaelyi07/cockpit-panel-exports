# -*- coding: utf-8 -*-
"""Acceptance criterion 2: no file is generated when include_detail=true and
the export is not approved. Aggregates-only bypass the gate; reject path never
produces a file either."""
from __future__ import annotations

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
