"""llm_spend is append-only: DELETE and TRUNCATE are blocked by triggers.

An operator who really must reset it (for example a test database) sets
``SET LOCAL app.allow_spend_reset = 'on'`` inside the transaction.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION llm_spend_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('app.allow_spend_reset', true) = 'on' THEN
                RETURN COALESCE(OLD, NEW);
            END IF;
            RAISE EXCEPTION 'llm_spend is append-only (the LLM budget ledger)';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER llm_spend_no_delete BEFORE DELETE ON llm_spend "
        "FOR EACH ROW EXECUTE FUNCTION llm_spend_guard()"
    )
    op.execute(
        "CREATE TRIGGER llm_spend_no_truncate BEFORE TRUNCATE ON llm_spend "
        "FOR EACH STATEMENT EXECUTE FUNCTION llm_spend_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER llm_spend_no_truncate ON llm_spend")
    op.execute("DROP TRIGGER llm_spend_no_delete ON llm_spend")
    op.execute("DROP FUNCTION llm_spend_guard()")
