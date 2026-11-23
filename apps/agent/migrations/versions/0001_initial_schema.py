"""Initial schema: workspaces, leads, lead_events, outbox_events, rate_limit_hits.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

LEAD_STATUSES = "'new','qualifying','pending_review','approved','rejected','sent','error'"
LEAD_EVENT_TYPES = (
    "'submitted','status_changed','outbox_delivered','outbox_failed','reviewed',"
    "'retriggered','email_sent'"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "workspaces",
        sa.Column("slug", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("config_hash", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "leads",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("reference", sa.Text, nullable=False),
        sa.Column("workspace_slug", sa.Text, sa.ForeignKey("workspaces.slug"), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="new"),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("email", pg.CITEXT, nullable=False),
        sa.Column("country", sa.Text),
        sa.Column("locale", sa.Text),
        sa.Column("answers", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("free_text", sa.Text),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("origin", sa.Text),
        sa.Column("ip_hash", sa.Text, nullable=False),
        sa.Column("user_agent", sa.Text),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_notice_version", sa.Text, nullable=False),
        sa.Column("score", sa.SmallInteger),
        sa.Column("tier", sa.Text),
        sa.Column("recommended_product", sa.Text),
        sa.Column("qualification", pg.JSONB),
        sa.Column("detected_language", sa.Text),
        sa.Column("error_reason", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("qualified_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("reference", name="uq_leads_reference"),
        sa.CheckConstraint(f"status IN ({LEAD_STATUSES})", name="ck_leads_status"),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_leads_score"),
        sa.CheckConstraint("tier IS NULL OR tier IN ('hot','warm','cold')", name="ck_leads_tier"),
        sa.CheckConstraint(
            "source IN ('hosted_form','external_api','seed')", name="ck_leads_source"
        ),
    )
    op.create_index(
        "ix_leads_workspace_status_created", "leads", ["workspace_slug", "status", "created_at"]
    )
    op.create_index("ix_leads_workspace_email", "leads", ["workspace_slug", "email"])
    op.create_index("ix_leads_created_at", "leads", ["created_at"])

    op.create_table(
        "lead_events",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "lead_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("from_status", sa.Text),
        sa.Column("to_status", sa.Text),
        sa.Column("actor", sa.Text, nullable=False, server_default="system"),
        sa.Column("payload", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(f"type IN ({LEAD_EVENT_TYPES})", name="ck_lead_events_type"),
        sa.CheckConstraint("actor IN ('system','n8n','operator')", name="ck_lead_events_actor"),
    )
    op.create_index("ix_lead_events_lead_created", "lead_events", ["lead_id", "created_at"])

    op.create_table(
        "outbox_events",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("aggregate_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", pg.UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="CASCADE")),
        sa.Column("payload", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("idempotency_key", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_idempotency_key"),
        sa.CheckConstraint(
            "event_type IN ('lead.created','message.approved')", name="ck_outbox_event_type"
        ),
        sa.CheckConstraint(
            "status IN ('pending','processing','delivered','dead')", name="ck_outbox_status"
        ),
    )
    op.create_index(
        "ix_outbox_pending_due",
        "outbox_events",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_outbox_status", "outbox_events", ["status"])
    op.create_index("ix_outbox_lead", "outbox_events", ["lead_id"])

    op.create_table(
        "rate_limit_hits",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("count", sa.BigInteger, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("rate_limit_hits")
    op.drop_table("outbox_events")
    op.drop_table("lead_events")
    op.drop_table("leads")
    op.drop_table("workspaces")
