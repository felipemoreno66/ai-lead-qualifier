"""Append-only spend ledger: budget accounting independent of llm_calls retention and cascades.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_spend",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Deliberately no foreign keys: deleting a lead or purging llm_calls must not lower spend.
        sa.Column("agent_run_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("amount_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("state IN ('reserved', 'settled')", name="ck_llm_spend_state"),
    )
    op.create_index("ix_llm_spend_run", "llm_spend", ["agent_run_id"])
    op.execute(
        "INSERT INTO llm_spend (agent_run_id, provider, model, state, amount_usd, created_at,"
        " settled_at) SELECT agent_run_id, provider, model, 'settled', cost_usd, created_at,"
        " created_at FROM llm_calls WHERE provider <> 'fake'"
    )
    op.execute("DROP VIEW IF EXISTS llm_budget")
    op.execute(
        "CREATE VIEW llm_budget AS "
        "SELECT COALESCE(sum(amount_usd), 0)::numeric(14, 6) AS spent_usd, count(*) AS calls "
        "FROM llm_spend WHERE state = 'settled' "
        "OR (state = 'reserved' AND created_at > now() - interval '10 minutes')"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS llm_budget")
    op.execute(
        "CREATE VIEW llm_budget AS "
        "SELECT COALESCE(sum(cost_usd), 0)::numeric(14, 6) AS spent_usd, count(*) AS calls "
        "FROM llm_calls WHERE provider <> 'fake'"
    )
    op.drop_table("llm_spend")
