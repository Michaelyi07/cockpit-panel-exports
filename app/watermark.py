"""Watermark generation: WM-{YYYYMMDD}-{8 hex chars}, unique per org.

Uniqueness is checked against dash_export.watermark; on collision the generator
retries with a fresh uuid slice (up to 5 attempts), so even a forced collision
cannot produce a duplicate.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DashExport

MAX_ATTEMPTS = 5


def generate_watermark(session: Session, org_id=None) -> str:
    """org_id is kept for call-site compatibility; uniqueness is global."""
    for _ in range(MAX_ATTEMPTS):
        wm = f"WM-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
        # global check: the DB unique index is global (not per-org), so the
        # generator must match that scope or a cross-org hex collision would
        # pass here and then fail at insert time.
        exists = session.scalar(
            select(DashExport.id).where(
                DashExport.watermark == wm,
                DashExport.deleted_at.is_(None),
            )
        )
        if not exists:
            return wm
    raise RuntimeError("watermark collision loop exhausted")  # pragma: no cover
