from __future__ import annotations

import io

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from lead_qualifier.infrastructure.db.engine import create_engine
from lead_qualifier.logging import configure_logging, get_logger

EMAIL = "secret.person@example.com"
INSERT = "INSERT INTO leads (reference, workspace_slug, name, email) VALUES (:r, 'x', :n, :e)"


def test_exception_messages_never_reach_the_logs():
    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)
    try:
        raise ValueError(f"cannot store {EMAIL}")
    except ValueError:
        get_logger("t").error("boom", exc_info=True)
    out = stream.getvalue()
    assert "ValueError (message withheld)" in out and "test_exception_messages" in out
    assert EMAIL not in out


@pytest.mark.integration
async def test_database_errors_do_not_leak_bound_parameters(migrated_url: str):
    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)
    engine = create_engine(migrated_url)
    try:
        with pytest.raises(DBAPIError) as excinfo:
            async with engine.begin() as conn:
                # NOT NULL violations echo the failing row, parameters included, by default.
                await conn.execute(
                    text(INSERT),
                    {"r": "LEAK-1", "n": "Leaky Name", "e": EMAIL},
                )
        # PostgreSQL itself echoes the failing row in the message, so the log must drop messages.
        assert EMAIL in str(excinfo.value)
        get_logger("dispatcher").error(
            "dispatcher_error", error_type="DBAPIError", exc_info=excinfo.value
        )
    finally:
        await engine.dispose()
    out = stream.getvalue()
    assert "dispatcher_error" in out
    assert EMAIL not in out and "Leaky Name" not in out
