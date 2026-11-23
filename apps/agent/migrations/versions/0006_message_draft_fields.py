"""messages: short_body (channel-ready variant) and guard warnings for the operator.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("short_body", sa.Text))
    op.add_column(
        "messages",
        sa.Column(
            "guard_warnings", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "guard_warnings")
    op.drop_column("messages", "short_body")
