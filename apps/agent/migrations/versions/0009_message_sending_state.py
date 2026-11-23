"""messages: a 'sending' state (claimed before the SMTP call), start time and attempt counter.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

OLD = "'draft','approved','rejected','sent','failed'"
NEW = "'draft','approved','sending','rejected','sent','failed'"


def upgrade() -> None:
    op.add_column("messages", sa.Column("send_started_at", sa.DateTime(timezone=True)))
    op.add_column(
        "messages", sa.Column("send_attempts", sa.Integer, nullable=False, server_default="0")
    )
    op.drop_constraint("ck_messages_status", "messages")
    op.create_check_constraint("ck_messages_status", "messages", f"status IN ({NEW})")


def downgrade() -> None:
    op.execute("UPDATE messages SET status = 'approved' WHERE status = 'sending'")
    op.drop_constraint("ck_messages_status", "messages")
    op.create_check_constraint("ck_messages_status", "messages", f"status IN ({OLD})")
    op.drop_column("messages", "send_attempts")
    op.drop_column("messages", "send_started_at")
