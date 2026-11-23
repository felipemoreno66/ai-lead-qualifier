"""Phase 2 tables: agent_runs, llm_calls, messages and the llm_budget view.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UUID_PK = {"primary_key": True, "server_default": sa.text("gen_random_uuid()")}


def _ts(name: str, *, default: bool = False) -> sa.Column[sa.DateTime]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=not default,
        server_default=sa.func.now() if default else None,
    )


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column(
            "lead_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("thread_id", sa.Text, nullable=False),
        sa.Column("run_number", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.Column("graph_version", sa.Text, nullable=False),
        sa.Column(
            "prompt_versions", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        _ts("started_at", default=True),
        _ts("finished_at"),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("total_cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        sa.UniqueConstraint("thread_id", name="uq_agent_runs_thread_id"),
        sa.UniqueConstraint("lead_id", "run_number", name="uq_agent_runs_lead_run"),
        sa.CheckConstraint(
            "status IN ('running', 'interrupted', 'completed', 'failed')",
            name="ck_agent_runs_status",
        ),
    )

    op.create_table(
        "llm_calls",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column(
            "agent_run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
        ),
        sa.Column("node", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("attempt", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("is_estimated", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("error_code", sa.Text),
        sa.Column("request", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response", pg.JSONB),
        _ts("created_at", default=True),
    )
    op.create_index("ix_llm_calls_run", "llm_calls", ["agent_run_id"])

    op.create_table(
        "messages",
        sa.Column("id", pg.UUID(as_uuid=True), **UUID_PK),
        sa.Column(
            "lead_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("language", sa.Text, nullable=False),
        sa.Column("channel", sa.Text, nullable=False, server_default="email"),
        sa.Column("channel_recipient", sa.Text, nullable=False),
        sa.Column("subject", sa.Text),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column(
            "edited_by_operator", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column("original_body", sa.Text),
        sa.Column("review_note", sa.Text),
        _ts("created_at", default=True),
        _ts("reviewed_at"),
        _ts("sent_at"),
        sa.Column("provider_message_id", sa.Text),
        sa.UniqueConstraint("lead_id", "version", name="uq_messages_lead_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'rejected', 'sent', 'failed')",
            name="ck_messages_status",
        ),
        sa.CheckConstraint("channel IN ('email', 'whatsapp')", name="ck_messages_channel"),
    )
    op.create_index("ix_messages_lead", "messages", ["lead_id"])

    op.execute(
        "CREATE VIEW llm_budget AS "
        "SELECT COALESCE(sum(cost_usd), 0)::numeric(14, 6) AS spent_usd, count(*) AS calls "
        "FROM llm_calls WHERE provider <> 'fake'"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS llm_budget")
    op.drop_table("messages")
    op.drop_table("llm_calls")
    op.drop_table("agent_runs")
