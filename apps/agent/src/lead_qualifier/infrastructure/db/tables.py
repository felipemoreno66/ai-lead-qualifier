"""SQLAlchemy Core table definitions (kept in sync with the Alembic migrations by a test)."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID

from lead_qualifier.domain.lead import LeadStatus

metadata = MetaData()

LEAD_STATUSES = tuple(s.value for s in LeadStatus)
TIERS = ("hot", "warm", "cold")
LEAD_SOURCES = ("hosted_form", "external_api", "seed")
LEAD_EVENT_TYPES = (
    "submitted",
    "status_changed",
    "outbox_delivered",
    "outbox_failed",
    "reviewed",
    "retriggered",
    "email_sent",
)
OUTBOX_STATUSES = ("pending", "processing", "delivered", "dead")
OUTBOX_EVENT_TYPES = ("lead.created", "message.approved")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


workspaces = Table(
    "workspaces",
    metadata,
    Column("slug", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("config_hash", Text, nullable=False),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("loaded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

leads = Table(
    "leads",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("reference", Text, nullable=False),
    Column("workspace_slug", Text, ForeignKey("workspaces.slug"), nullable=False),
    Column("status", Text, nullable=False, server_default="new"),
    Column("name", Text, nullable=False),
    Column("email", CITEXT, nullable=False),
    Column("country", Text),
    Column("locale", Text),
    Column("answers", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("free_text", Text),
    Column("source", Text, nullable=False),
    Column("origin", Text),
    Column("ip_hash", Text, nullable=False),
    Column("user_agent", Text),
    Column("consent_at", DateTime(timezone=True), nullable=False),
    Column("consent_notice_version", Text, nullable=False),
    Column("score", SmallInteger),
    Column("tier", Text),
    Column("recommended_product", Text),
    Column("qualification", JSONB),
    Column("detected_language", Text),
    Column("error_reason", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("qualified_at", DateTime(timezone=True)),
    Column("sent_at", DateTime(timezone=True)),
    UniqueConstraint("reference", name="uq_leads_reference"),
    CheckConstraint(_in("status", LEAD_STATUSES), name="ck_leads_status"),
    CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_leads_score"),
    CheckConstraint("tier IS NULL OR " + _in("tier", TIERS), name="ck_leads_tier"),
    CheckConstraint(_in("source", LEAD_SOURCES), name="ck_leads_source"),
    Index("ix_leads_workspace_status_created", "workspace_slug", "status", "created_at"),
    Index("ix_leads_workspace_email", "workspace_slug", "email"),
    Index("ix_leads_created_at", "created_at"),
)

lead_events = Table(
    "lead_events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "lead_id", UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    ),
    Column("type", Text, nullable=False),
    Column("from_status", Text),
    Column("to_status", Text),
    Column("actor", Text, nullable=False, server_default="system"),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(_in("type", LEAD_EVENT_TYPES), name="ck_lead_events_type"),
    CheckConstraint(_in("actor", ("system", "n8n", "operator")), name="ck_lead_events_actor"),
    Index("ix_lead_events_lead_created", "lead_id", "created_at"),
)

outbox_events = Table(
    "outbox_events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("event_type", Text, nullable=False),
    Column("aggregate_id", UUID(as_uuid=True), nullable=False),
    Column("lead_id", UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE")),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("idempotency_key", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("locked_until", DateTime(timezone=True)),
    Column("last_error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("delivered_at", DateTime(timezone=True)),
    UniqueConstraint("idempotency_key", name="uq_outbox_idempotency_key"),
    CheckConstraint(_in("event_type", OUTBOX_EVENT_TYPES), name="ck_outbox_event_type"),
    CheckConstraint(_in("status", OUTBOX_STATUSES), name="ck_outbox_status"),
    Index(
        "ix_outbox_pending_due",
        "next_attempt_at",
        postgresql_where=text("status = 'pending'"),
    ),
    Index("ix_outbox_status", "status"),
    Index("ix_outbox_lead", "lead_id"),
)

rate_limit_hits = Table(
    "rate_limit_hits",
    metadata,
    Column("key", Text, primary_key=True),
    Column("window_start", DateTime(timezone=True), primary_key=True),
    Column("count", BigInteger, nullable=False, server_default="0"),
)
