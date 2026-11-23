"""Dashboard KB chat: agent runs without a lead and the kb_queries log.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("agent_runs", "lead_id", existing_type=pg.UUID(), nullable=True)
    op.add_column(
        "agent_runs", sa.Column("kind", sa.Text, nullable=False, server_default="qualify")
    )
    op.add_column(
        "agent_runs", sa.Column("workspace_slug", sa.Text, sa.ForeignKey("workspaces.slug"))
    )
    op.create_check_constraint("ck_agent_runs_kind", "agent_runs", "kind IN ('qualify','kb_chat')")
    op.create_check_constraint(
        "ck_agent_runs_qualify_lead", "agent_runs", "kind <> 'qualify' OR lead_id IS NOT NULL"
    )
    op.create_table(
        "kb_queries",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_slug", sa.Text, sa.ForeignKey("workspaces.slug"), nullable=False),
        sa.Column(
            "agent_run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("covered", sa.Boolean, nullable=False),
        sa.Column("citations", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_kb_queries_workspace_created", "kb_queries", ["workspace_slug", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("kb_queries")
    op.execute("DELETE FROM agent_runs WHERE kind = 'kb_chat'")
    op.drop_constraint("ck_agent_runs_qualify_lead", "agent_runs")
    op.drop_constraint("ck_agent_runs_kind", "agent_runs")
    op.drop_column("agent_runs", "workspace_slug")
    op.drop_column("agent_runs", "kind")
    op.alter_column("agent_runs", "lead_id", existing_type=pg.UUID(), nullable=False)
