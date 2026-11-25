"""llm_calls must belong to an agent run so deleting a lead cascades to its LLM payloads.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rows without a run cannot be tied to a lead (and so never cascade); none exist outside dev.
    op.execute("DELETE FROM llm_calls WHERE agent_run_id IS NULL")
    op.alter_column("llm_calls", "agent_run_id", nullable=False)


def downgrade() -> None:
    op.alter_column("llm_calls", "agent_run_id", nullable=True)
