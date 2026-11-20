# -*- coding: utf-8 -*-
"""Acceptance criterion 3: each file's watermark number is unique and written
into file attributes (workbook properties) as well as sheet headers."""
from __future__ import annotations

import io

from openpyxl import load_workbook

from app.worker import process_pending

from tests.conftest import ANALYST


def _create_and_generate(client, payload=None):
    resp = client.post("/api/dash/exports", json=payload or {
        "panel": "occupancy",
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers=ANALYST)
    export = resp.json()
    assert process_pending() >= 1
    return client.get(f"/api/dash/exports/{export['id']}", headers=ANALYST).json()


def test_watermarks_unique_across_exports(client):
    details = [_create_and_generate(client) for _ in range(3)]
    watermarks = [d["watermark"] for d in details]
    assert len(set(watermarks)) == 3, watermarks  # uniqueness
    for wm in watermarks:
        assert wm.startswith("WM-")
        assert len(wm) == len("WM-YYYYMMDD-") + 8


def test_watermark_written_to_workbook_properties(client):
    detail = _create_and_generate(client)
    data = client.get(detail["download_url"]).content
    wb = load_workbook(io.BytesIO(data))
    props = wb.properties
    assert props.title == detail["watermark"]
    assert props.keywords == detail["watermark"]


def test_watermark_written_to_every_sheet_header(client):
    detail = _create_and_generate(client)
    data = client.get(detail["download_url"]).content
    wb = load_workbook(io.BytesIO(data))
    for sheet_name in wb.sheetnames:
        sheet = wb[sheet_name]
        # cell banner (kept) ...
        assert sheet.cell(row=1, column=1).value == f"Watermark: {detail['watermark']}"
        # ... and the real print header (oddHeader), per the brief
        assert detail["watermark"] in (sheet.oddHeader.center.text or "")


def test_watermark_written_to_print_header_when_detail_sheet_present(client):
    """Every sheet — including the detail roster — must carry the watermark
    in its print header, not only in cells/properties."""
    from app.worker import process_pending as _process
    from tests.conftest import MANAGER

    resp = client.post("/api/dash/exports", json={
        "panel": "revenue", "include_detail": True,
        "filters": {"site_id": "00000000-0000-0000-0000-000000000001"}},
        headers=ANALYST)
    export = resp.json()
    client.post(f"/api/dash/exports/{export['id']}/approve", headers=MANAGER)
    assert _process() >= 1

    detail = client.get(f"/api/dash/exports/{export['id']}", headers=ANALYST).json()
    wb = load_workbook(io.BytesIO(client.get(detail["download_url"]).content))
    assert "Detail List" in wb.sheetnames
    for sheet_name in wb.sheetnames:
        assert detail["watermark"] in (wb[sheet_name].oddHeader.center.text or "")


def test_duplicate_watermark_rejected_by_db_index(client):
    """The partial unique index on dash_export.watermark rejects duplicates."""
    from sqlalchemy import create_engine, text

    detail = _create_and_generate(client)
    existing = detail["watermark"]

    # extract the generator's deterministic prefix (WM-YYYYMMDD-) and inject a
    # collision candidate with the same prefix but a known suffix we can force:
    # simplest robust approach — insert a row whose watermark equals the
    # generator's NEXT uuid? UUIDs aren't predictable; instead verify the
    # uniqueness check at DB level: attempt to insert a duplicate watermark row
    # and confirm the partial unique index rejects it.
    engine = create_engine(
        __import__("os").environ["DATABASE_URL"], isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "INSERT INTO dash_export (id, org_id, panel, filters, status, watermark, created_at, updated_at)"
                " VALUES (gen_random_uuid(), '00000000-0000-0000-0000-0000000000aa',"
                " 'occupancy', '{}', 'succeeded', :wm, now(), now())"),
                {"wm": existing})
            duplicate_inserted = True
        except Exception as exc:  # noqa: BLE001
            assert "ix_dash_export_watermark" in str(exc), exc
            duplicate_inserted = False
    assert duplicate_inserted is False  # DB-level uniqueness held

    # and a fresh export still gets its own distinct watermark
    second = _create_and_generate(client)
    assert second["watermark"] != existing


def test_generate_watermark_retries_on_collision(client, monkeypatch):
    """The generator's MAX_ATTEMPTS retry loop really regenerates when a
    candidate watermark already exists in the DB (not just the DB index)."""
    import types

    from app import watermark as wm_mod
    from app.db import SessionLocal

    detail = _create_and_generate(client)
    taken = detail["watermark"]
    taken_suffix = taken.rsplit("-", 1)[1]

    class _FakeUUID:
        def __init__(self, hex_value):
            self.hex = hex_value  # real uuid.UUID.hex is a str attribute

    # force a deterministic collision: first call yields the already-used
    # suffix, subsequent calls yield a fresh one.
    calls = {"n": 0}

    def fake_uuid4():
        calls["n"] += 1
        suffix = taken_suffix if calls["n"] == 1 else "abcdef12"
        # generate_watermark slices hex[:8], so put the suffix up front
        return _FakeUUID(suffix + "0" * 24)

    monkeypatch.setattr(wm_mod.uuid, "uuid4", fake_uuid4)
    with SessionLocal() as session:
        result = wm_mod.generate_watermark(session)

    assert calls["n"] == 2, "generator must retry after the first collision"
    assert result.endswith("abcdef12")
    assert result != taken
