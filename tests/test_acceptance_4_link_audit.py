# -*- coding: utf-8 -*-
"""Acceptance criterion 4: the download link expires after 24 hours and each
export has an audit record (incl. one per link issuance)."""
from __future__ import annotations

import time
import urllib.parse

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app import config
from app.models import AuditLog
from app.worker import process_pending

from tests.conftest import ANALYST

ENGINE = None


def _engine():
    global ENGINE
    if ENGINE is None:
        ENGINE = create_engine(__import__("os").environ["DATABASE_URL"])
    return ENGINE


def _create_and_generate(client, payload=None):
    resp = client.post("/api/dash/exports", json=payload or {
        "panel": "occupancy",
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers=ANALYST)
    export = resp.json()
    assert process_pending() >= 1
    return client.get(f"/api/dash/exports/{export['id']}", headers=ANALYST).json()


def _audit_count(export_id: str, action: str) -> int:
    with Session(_engine()) as session:
        rows = session.execute(
            select(AuditLog).where(AuditLog.resource_id == export_id,
                                   AuditLog.action == action)).scalars().all()
        return len(rows)


def test_link_issuance_writes_audit_row_per_request(client):
    detail = _create_and_generate(client)
    eid = detail["id"]
    before = _audit_count(eid, "export.link_issued")
    assert before == 1  # _create_and_generate already fetched detail once

    client.get(f"/api/dash/exports/{eid}", headers=ANALYST)
    client.get(f"/api/dash/exports/{eid}", headers=ANALYST)
    assert _audit_count(eid, "export.link_issued") == before + 2  # one per issuance

    # the request itself is also audited
    assert _audit_count(eid, "export.requested") == 1
    assert _audit_count(eid, "export.succeeded") == 1


def test_valid_link_downloads_file(client):
    detail = _create_and_generate(client)
    resp = client.get(detail["download_url"])
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert len(resp.content) > 500  # a real workbook, not an empty body


def test_expired_link_returns_410_with_hint(client):
    detail = _create_and_generate(client)
    parsed = urllib.parse.urlparse(detail["download_url"])
    query = dict(urllib.parse.parse_qsl(parsed.query))
    expired = int(query["expires"]) - (config.LINK_TTL_SECONDS + 10)
    # re-sign with the expired timestamp to simulate a link issued 24h+ ago
    from app import storage as storage_mod
    adapter = storage_mod.get_storage()
    sig = adapter._sign(parsed.path.removeprefix("/files/"), expired)
    resp = client.get(f"{parsed.path}?expires={expired}&sig={sig}")
    assert resp.status_code == 410
    body = resp.json()
    assert body["detail"]["error"] == "EXPIRED"
    assert "hint" in body["detail"]  # regeneration hint per brief


def test_tampered_signature_rejected(client):
    detail = _create_and_generate(client)
    parsed = urllib.parse.urlparse(detail["download_url"])
    query = dict(urllib.parse.parse_qsl(parsed.query))
    bad = query["sig"][:-4] + "0000"
    resp = client.get(f"{parsed.path}?expires={query['expires']}&sig={bad}")
    assert resp.status_code == 403


def test_link_ttl_is_24h(client):
    detail = _create_and_generate(client)
    parsed = urllib.parse.urlparse(detail["download_url"])
    query = dict(urllib.parse.parse_qsl(parsed.query))
    ttl = int(query["expires"]) - int(time.time())
    assert 86398 <= ttl <= 86400  # 24h per brief (env-overridable)


def test_status_endpoint_gives_fresh_link_after_expiry(client):
    """The regeneration path: after expiry the status endpoint issues a new
    valid link (the hint tells the reviewer to re-request status)."""
    detail = _create_and_generate(client)
    parsed = urllib.parse.urlparse(detail["download_url"])
    query = dict(urllib.parse.parse_qsl(parsed.query))
    expired = int(query["expires"]) - (config.LINK_TTL_SECONDS + 10)
    adapter = storage_mod_get()
    sig = adapter._sign(parsed.path.removeprefix("/files/"), expired)
    resp = client.get(f"{parsed.path}?expires={expired}&sig={sig}")
    assert resp.status_code == 410

    fresh = client.get(f"/api/dash/exports/{detail['id']}", headers=ANALYST).json()
    assert client.get(fresh["download_url"]).status_code == 200


def storage_mod_get():
    from app import storage as storage_mod
    return storage_mod.get_storage()
