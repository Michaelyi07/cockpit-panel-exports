"""Tables: dash_export + audit_log, following the platform unified-column convention
(id UUID, org_id, site_id, created_at, created_by, updated_at, deleted_at)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DashExport(Base, SoftDeleteMixin):
    __tablename__ = "dash_export"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    panel: Mapped[str] = mapped_column(String(32), nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    include_detail: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    export_format: Mapped[str] = mapped_column(String(8), nullable=False, default="xlsx")

    # pending_approval -> queued -> running -> succeeded | failed
    # pending_approval -> rejected (never produces a file)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    watermark: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    link_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_dash_export_org_status", "org_id", "status"),
        Index("ix_dash_export_watermark", "watermark", unique=True,
              postgresql_where=text("watermark IS NOT NULL AND deleted_at IS NULL")),
    )


class AuditLog(Base, SoftDeleteMixin):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )


class DashboardFact(Base, SoftDeleteMixin):
    """Fictional fact store backing the cockpit panels (eval/demo data)."""

    __tablename__ = "dashboard_fact"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    panel: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(48), nullable=False)
    dimension: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    period: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    value_num: Mapped[float | None] = mapped_column(nullable=True)
    value_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (Index("ix_fact_panel_metric_period", "panel", "metric_code", "period"),)
