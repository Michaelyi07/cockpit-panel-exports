"""initial tables: dash_export, audit_log, dashboard_fact

Revision ID: 0001
Revises:
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dash_export",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("panel", sa.String(32), nullable=False),
        sa.Column("filters", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("include_detail", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("export_format", sa.String(8), nullable=False, server_default="xlsx"),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("watermark", sa.String(32), nullable=True),
        sa.Column("file_key", sa.String(160), nullable=True),
        sa.Column("link_issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.String(64), nullable=True),
        sa.Column("rejected_reason", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_dash_export_org_status", "dash_export", ["org_id", "status"])
    op.create_index("ix_dash_export_watermark", "dash_export", ["watermark"], unique=True,
                    postgresql_where=sa.text("watermark IS NOT NULL AND deleted_at IS NULL"))

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("detail", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_audit_resource", "audit_log", ["resource_type", "resource_id"])

    op.create_table(
        "dashboard_fact",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("panel", sa.String(32), nullable=False),
        sa.Column("metric_code", sa.String(48), nullable=False),
        sa.Column("dimension", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("period", sa.String(10), nullable=False),
        sa.Column("value_num", sa.Float, nullable=True),
        sa.Column("value_cents", sa.Integer, nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_fact_panel_metric_period", "dashboard_fact",
                    ["panel", "metric_code", "period"])


def downgrade() -> None:
    op.drop_table("dashboard_fact")
    op.drop_index("ix_audit_resource", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_dash_export_watermark", table_name="dash_export")
    op.drop_index("ix_dash_export_org_status", table_name="dash_export")
    op.drop_table("dash_export")
