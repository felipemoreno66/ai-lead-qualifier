"""lead_events: allow the injection_suspected event type.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

OLD = (
    "'submitted','status_changed','outbox_delivered','outbox_failed','reviewed',"
    "'retriggered','email_sent'"
)
NEW = OLD + ",'injection_suspected'"


def _swap(types: str) -> None:
    op.execute("ALTER TABLE lead_events DROP CONSTRAINT ck_lead_events_type")
    op.execute(
        f"ALTER TABLE lead_events ADD CONSTRAINT ck_lead_events_type CHECK (type IN ({types}))"
    )


def upgrade() -> None:
    _swap(NEW)


def downgrade() -> None:
    op.execute("DELETE FROM lead_events WHERE type = 'injection_suspected'")
    _swap(OLD)
