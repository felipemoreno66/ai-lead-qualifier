"""Reserved spend keeps counting at its worst-case amount until explicitly settled.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS llm_budget")
    op.execute(
        "CREATE VIEW llm_budget AS "
        "SELECT COALESCE(sum(amount_usd), 0)::numeric(14, 6) AS spent_usd, count(*) AS calls "
        "FROM llm_spend"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS llm_budget")
    op.execute(
        "CREATE VIEW llm_budget AS "
        "SELECT COALESCE(sum(amount_usd), 0)::numeric(14, 6) AS spent_usd, count(*) AS calls "
        "FROM llm_spend WHERE state = 'settled' "
        "OR (state = 'reserved' AND created_at > now() - interval '10 minutes')"
    )
