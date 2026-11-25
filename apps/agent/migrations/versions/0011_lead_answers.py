"""Answers to a lead's questions and their citations (deleted with the lead).

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_answers",
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
        sa.Column(
            "agent_run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("position", sa.SmallInteger, nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("covered", sa.Boolean, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("lead_id", "position", name="uq_lead_answers_lead_position"),
    )
    op.create_table(
        "answer_citations",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "answer_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("lead_answers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.SmallInteger, nullable=False),
        sa.Column("chunk_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("document_path", sa.Text, nullable=False),
        sa.Column("document_title", sa.Text, nullable=False),
        sa.Column("heading_path", sa.Text, nullable=False),
        sa.Column("quote", sa.Text, nullable=False),
        sa.UniqueConstraint("answer_id", "position", name="uq_answer_citations_answer_position"),
    )


def downgrade() -> None:
    op.drop_table("answer_citations")
    op.drop_table("lead_answers")
