"""HTTP routes: create / list / detail(+link) / approve / reject / download.

Identity stub: X-User-Id + X-Role headers (S2-IAM boundary per brief).
- any authenticated role may create exports and read status
- approve/reject require the ops_manager role (the approver may also not be
  the creator — enforced here)
- download is presigned-link only; expired/tampered links return 410/403
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .audit import get_audit
from .config import ROLE_OPS_MANAGER
from .db import get_session
from .models import DashExport, DashboardFact
from .schemas import ExportCreate, ExportDetailOut, ExportOut, RejectCreate
from .storage import get_storage

router = APIRouter(prefix="/api/dash", tags=["dash-exports"])

VALID_ROLES = {"analyst", "ops_manager", "admin"}


def get_actor(x_user_id: str | None = Header(default=None),
              x_role: str | None = Header(default=None)) -> tuple[str, str]:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="authentication required")
    role = x_role or "analyst"
    if role not in VALID_ROLES:
        raise HTTPException(status_code=403, detail="unknown role")
    return x_user_id, role


def _require_ops_manager(actor: tuple[str, str]) -> str:
    user, role = actor
    if role != ROLE_OPS_MANAGER and role != "admin":
        raise HTTPException(status_code=403, detail="ops_manager role required")
    return user


def _get_export(session: Session, export_id: uuid.UUID) -> DashExport:
    row = session.get(DashExport, export_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="export not found")
    return row


@router.post("/exports", response_model=ExportOut, status_code=201)
def create_export(payload: ExportCreate, session: Session = Depends(get_session),
                  actor: tuple[str, str] = Depends(get_actor)):
    user, role = actor
    # the Literal type already enforces the known panel set; the registry check
    # below is the service-level guard (kept for direct calls in tests/worker)
    from .panels import KNOWN_PANELS as _KNOWN
    if payload.panel not in _KNOWN:
        raise HTTPException(status_code=422, detail="unknown panel")

    status = "pending_approval" if payload.include_detail else "queued"
    row = DashExport(
        org_id=uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
        site_id=(uuid.UUID(payload.filters["site_id"])
                 if payload.filters.get("site_id") else None),
        panel=payload.panel,
        filters=payload.filters or {},
        include_detail=payload.include_detail,
        export_format=payload.export_format,
        status=status,
        created_by=user,
    )
    session.add(row)
    session.flush()
    get_audit().record(session, actor=user, action="export.requested",
                       resource_id=str(row.id), org_id=row.org_id,
                       site_id=row.site_id,
                       detail={"panel": row.panel, "include_detail": row.include_detail,
                               "format": row.export_format, "filters": row.filters})
    session.commit()
    session.refresh(row)
    return row


@router.get("/exports", response_model=list[ExportOut])
def list_exports(status: str | None = Query(default=None),
                 session: Session = Depends(get_session),
                 actor: tuple[str, str] = Depends(get_actor)):
    query = select(DashExport).where(DashExport.deleted_at.is_(None))
    if status:
        query = query.where(DashExport.status == status)
    rows = session.execute(query.order_by(DashExport.created_at.desc()).limit(50)).scalars().all()
    return rows


@router.get("/exports/{export_id}", response_model=ExportDetailOut)
def export_detail(export_id: uuid.UUID, session: Session = Depends(get_session),
                  actor: tuple[str, str] = Depends(get_actor)):
    row = _get_export(session, export_id)
    out = ExportDetailOut.model_validate(row)
    if row.status == "succeeded" and row.file_key:
        storage = get_storage()
        out.download_url = storage.presign(row.file_key)
        out.link_expires_at = datetime.fromtimestamp(
            time.time() + config.LINK_TTL_SECONDS, tz=timezone.utc)
        # every link issuance is audited (per brief)
        get_audit().record(session, actor=actor[0], action="export.link_issued",
                           resource_id=str(row.id), org_id=row.org_id,
                           site_id=row.site_id,
                           detail={"file_key": row.file_key,
                                   "ttl_seconds": config.LINK_TTL_SECONDS})
        session.commit()
    return out


@router.post("/exports/{export_id}/approve", response_model=ExportOut)
def approve_export(export_id: uuid.UUID, session: Session = Depends(get_session),
                   actor: tuple[str, str] = Depends(get_actor)):
    approver = _require_ops_manager(actor)
    row = _get_export(session, export_id)
    if row.status == "rejected":
        raise HTTPException(status_code=409, detail="export already rejected")
    if row.status in ("queued", "running", "succeeded"):
        raise HTTPException(status_code=409, detail="export already approved or past approval")
    if approver == row.created_by:
        raise HTTPException(status_code=403, detail="creator cannot approve own export")
    row.status = "queued"
    row.approved_by = approver
    row.approved_at = datetime.now(timezone.utc)
    get_audit().record(session, actor=approver, action="export.approved",
                       resource_id=str(row.id), org_id=row.org_id,
                       site_id=row.site_id, detail={})
    session.commit()
    session.refresh(row)
    return row


@router.post("/exports/{export_id}/reject", response_model=ExportOut)
def reject_export(export_id: uuid.UUID, payload: RejectCreate,
                  session: Session = Depends(get_session),
                  actor: tuple[str, str] = Depends(get_actor)):
    rejector = _require_ops_manager(actor)
    row = _get_export(session, export_id)
    if row.status != "pending_approval":
        raise HTTPException(status_code=409, detail="only pending_approval can be rejected")
    row.status = "rejected"
    row.rejected_by = rejector
    row.rejected_reason = payload.reason
    get_audit().record(session, actor=rejector, action="export.rejected",
                       resource_id=str(row.id), org_id=row.org_id,
                       site_id=row.site_id, detail={"reason": payload.reason})
    session.commit()
    session.refresh(row)
    return row


root_router = APIRouter(tags=["dash-exports-files"])


@root_router.get("/files/{key:path}")
def download_file(key: str, expires: str = Query(...), sig: str = Query(...)):
    storage = get_storage()
    ok, reason = storage.verify(key, expires, sig)
    if not ok:
        status_code = 403 if reason == "bad_signature" else 410
        detail = {"error": reason.upper()}
        if reason == "expired":
            detail["hint"] = ("request a fresh download link via "
                              "GET /api/dash/exports/{id}")
        raise HTTPException(status_code=status_code, detail=detail)
    data = storage.get(key)
    if data is None:
        raise HTTPException(status_code=404, detail="file missing")
    media = ("text/csv" if key.endswith(".csv")
             else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return Response(content=data, media_type=media)


@router.get("/facts/count")
def facts_count(session: Session = Depends(get_session),
                actor: tuple[str, str] = Depends(get_actor)):
    """Diagnostics: how many fictional fact rows exist (used by walkthrough)."""
    n = session.scalar(select(func_count()))
    return {"facts": n}


def func_count():
    from sqlalchemy import func
    return func.count(DashboardFact.id)
