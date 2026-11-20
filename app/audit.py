"""Audit boundary (S2-AUDIT stub): every export-related event writes one row.

Swapping in the real audit service means implementing AuditSink; the platform
event names (export.requested / export.approved / export.rejected /
export.succeeded / export.failed / export.link_issued) stay identical.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AuditLog

RESOURCE_TYPE = "dash_export"


class AuditSink:
    def record(self, session: Session, *, actor: str, action: str,
               resource_id: str, org_id=None, site_id=None, detail: dict | None = None) -> None:
        session.add(AuditLog(
            org_id=org_id, site_id=site_id, actor=actor, action=action,
            resource_type=RESOURCE_TYPE, resource_id=resource_id,
            detail=detail or {},
        ))


_sink = AuditSink()


def get_audit() -> AuditSink:
    return _sink
