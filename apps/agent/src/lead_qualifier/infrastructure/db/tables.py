"""SQLAlchemy Core table definitions (kept in sync with the Alembic migrations by a test)."""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
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
    Numeric,
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
    "injection_suspected",
)
OUTBOX_STATUSES = ("pending", "processing", "delivered", "dead")
OUTBOX_EVENT_TYPES = ("lead.created", "message.approved")
AGENT_RUN_STATUSES = ("running", "interrupted", "completed", "failed")
MESSAGE_STATUSES = ("draft", "approved", "sending", "rejected", "sent", "failed")
MESSAGE_CHANNELS = ("email", "whatsapp")


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

agent_runs = Table(
    "agent_runs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "lead_id", UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    ),
    Column("thread_id", Text, nullable=False),
    Column("run_number", Integer, nullable=False),
    Column("status", Text, nullable=False, server_default="running"),
    Column("graph_version", Text, nullable=False),
    Column("prompt_versions", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    Column("duration_ms", Integer),
    Column("total_cost_usd", Numeric(10, 6), nullable=False, server_default="0"),
    Column("error", Text),
    UniqueConstraint("thread_id", name="uq_agent_runs_thread_id"),
    UniqueConstraint("lead_id", "run_number", name="uq_agent_runs_lead_run"),
    CheckConstraint(_in("status", AGENT_RUN_STATUSES), name="ck_agent_runs_status"),
)

llm_calls = Table(
    "llm_calls",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "agent_run_id",
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("node", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("attempt", SmallInteger, nullable=False, server_default="1"),
    Column("input_tokens", Integer, nullable=False, server_default="0"),
    Column("output_tokens", Integer, nullable=False, server_default="0"),
    Column("cache_read_tokens", Integer, nullable=False, server_default="0"),
    Column("cache_write_tokens", Integer, nullable=False, server_default="0"),
    Column("latency_ms", Integer, nullable=False, server_default="0"),
    Column("cost_usd", Numeric(10, 6), nullable=False, server_default="0"),
    Column("is_estimated", Boolean, nullable=False, server_default=text("false")),
    Column("success", Boolean, nullable=False),
    Column("error_code", Text),
    Column("request", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("response", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_llm_calls_run", "agent_run_id"),
)

messages = Table(
    "messages",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "lead_id", UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    ),
    Column("agent_run_id", UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL")),
    Column("version", Integer, nullable=False),
    Column("language", Text, nullable=False),
    Column("channel", Text, nullable=False, server_default="email"),
    Column("channel_recipient", Text, nullable=False),
    Column("subject", Text),
    Column("body", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="draft"),
    Column("edited_by_operator", Boolean, nullable=False, server_default=text("false")),
    Column("original_body", Text),
    Column("review_note", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("reviewed_at", DateTime(timezone=True)),
    Column("sent_at", DateTime(timezone=True)),
    Column("provider_message_id", Text),
    Column("short_body", Text),
    Column("send_started_at", DateTime(timezone=True)),
    Column("send_attempts", Integer, nullable=False, server_default="0"),
    Column("guard_warnings", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    UniqueConstraint("lead_id", "version", name="uq_messages_lead_version"),
    CheckConstraint(_in("status", MESSAGE_STATUSES), name="ck_messages_status"),
    CheckConstraint(_in("channel", MESSAGE_CHANNELS), name="ck_messages_channel"),
    Index("ix_messages_lead", "lead_id"),
)

# Append-only budget ledger. No foreign keys on purpose: neither lead deletion nor the llm_calls
# retention purge may lower the lifetime spend that ``llm_budget`` reports.
llm_spend = Table(
    "llm_spend",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("agent_run_id", UUID(as_uuid=True), nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("amount_usd", Numeric(14, 6), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("settled_at", DateTime(timezone=True)),
    CheckConstraint(_in("state", ("reserved", "settled")), name="ck_llm_spend_state"),
    Index("ix_llm_spend_run", "agent_run_id"),
)

KB_EMBEDDING_MODELS = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "openai/text-embedding-3-small@384",
    "fake-hash-384",
)

kb_documents = Table(
    "kb_documents",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("workspace_slug", Text, ForeignKey("workspaces.slug"), nullable=False),
    Column("path", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("content_sha256", Text, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("workspace_slug", "path", name="uq_kb_documents_workspace_path"),
)

kb_chunks = Table(
    "kb_chunks",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "document_id",
        UUID(as_uuid=True),
        ForeignKey("kb_documents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("chunk_index", Integer, nullable=False),
    Column("heading_path", Text, nullable=False, server_default=""),
    Column("content", Text, nullable=False),
    Column("token_count", Integer, nullable=False),
    Column("embedding", Vector(384), nullable=False),
    Column("embedding_model", Text, nullable=False),
    UniqueConstraint("document_id", "chunk_index", name="uq_kb_chunks_document_index"),
    CheckConstraint(
        _in("embedding_model", KB_EMBEDDING_MODELS), name="ck_kb_chunks_embedding_model"
    ),
    Index(
        "ix_kb_chunks_embedding_hnsw",
        "embedding",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    ),
)

lead_answers = Table(
    "lead_answers",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "lead_id", UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    ),
    Column("agent_run_id", UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL")),
    Column("position", SmallInteger, nullable=False),
    Column("question", Text, nullable=False),
    Column("answer", Text, nullable=False),
    Column("covered", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("lead_id", "position", name="uq_lead_answers_lead_position"),
)

# chunk_id has no foreign key on purpose: re-ingesting the knowledge base replaces its chunks, and
# the citation keeps the source path, heading and quote as they were when the answer was given.
answer_citations = Table(
    "answer_citations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "answer_id",
        UUID(as_uuid=True),
        ForeignKey("lead_answers.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("position", SmallInteger, nullable=False),
    Column("chunk_id", UUID(as_uuid=True), nullable=False),
    Column("document_path", Text, nullable=False),
    Column("document_title", Text, nullable=False),
    Column("heading_path", Text, nullable=False),
    Column("quote", Text, nullable=False),
    UniqueConstraint("answer_id", "position", name="uq_answer_citations_answer_position"),
)
