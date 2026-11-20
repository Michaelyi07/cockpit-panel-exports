"""Async generation worker: DB-backed queue with FOR UPDATE SKIP LOCKED, so
multiple app instances can run workers concurrently with no double-generation."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from . import config
from .audit import get_audit
from .db import SessionLocal
from .generator import collect_rows, render
from .models import DashExport
from .storage import get_storage
from .watermark import generate_watermark

log = logging.getLogger("dash.worker")


def process_pending(max_batch: int = 10) -> int:
    """Process up to max_batch queued exports. Returns the number processed.
    Called by the background loop in production and directly in tests."""
    processed = 0
    while processed < max_batch:
        with SessionLocal() as session:
            row = session.execute(
                select(DashExport)
                .where(DashExport.status == "queued",
                       DashExport.deleted_at.is_(None))
                .with_for_update(skip_locked=True)
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                break
            _generate(session, row)
            session.commit()
            processed += 1
    return processed


def _generate(session, row: DashExport) -> None:
    audit = get_audit()
    row.status = "running"
    session.flush()
    try:
        rows = collect_rows(session, panel=row.panel, filters=row.filters or {})
        watermark = generate_watermark(session, row.org_id)
        data = render(watermark, row.panel, rows, row.filters or {},
                      row.export_format, row.include_detail)
        ext = "csv" if row.export_format == "csv" else "xlsx"
        key = f"dash-exports/{row.org_id}/{row.id}.{ext}"
        get_storage().put(key, data)
        row.watermark = watermark
        row.file_key = key
        row.status = "succeeded"
        audit.record(session, actor="system", action="export.succeeded",
                     resource_id=str(row.id), org_id=row.org_id,
                     site_id=row.site_id,
                     detail={"watermark": watermark, "file_key": key,
                             "rows": len(rows),
                             "include_detail": row.include_detail})
    except Exception as exc:  # noqa: BLE001 - worker must record and continue
        row.status = "failed"
        row.error = str(exc)[:500]
        audit.record(session, actor="system", action="export.failed",
                     resource_id=str(row.id), org_id=row.org_id,
                     site_id=row.site_id, detail={"error": row.error})
        log.exception("export %s failed", row.id)


async def worker_loop() -> None:
    """Background loop started from app lifespan when WORKER_ENABLED."""
    while True:
        try:
            process_pending()
        except Exception:  # noqa: BLE001
            log.exception("worker loop iteration failed")
        await asyncio.sleep(config.WORKER_POLL_SECONDS)
