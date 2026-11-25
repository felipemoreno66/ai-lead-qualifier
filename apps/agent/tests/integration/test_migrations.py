from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from lead_qualifier.infrastructure.db.tables import metadata
from tests.conftest import alembic_config, create_database

pytestmark = pytest.mark.integration

APP_TABLES = {
    "workspaces",
    "leads",
    "lead_events",
    "outbox_events",
    "rate_limit_hits",
    "agent_runs",
    "llm_calls",
    "messages",
    "llm_spend",
    "kb_documents",
    "kb_chunks",
}


def _tables(url: str) -> set[str]:
    eng = sa.create_engine(url)
    with eng.connect() as conn:
        names = set(sa.inspect(conn).get_table_names())
    eng.dispose()
    return names


def test_upgrade_head_and_downgrade_base_on_an_empty_database(pg_base_url: str):
    url = create_database(pg_base_url, "leadq_migration_roundtrip")
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    assert _tables(url) >= APP_TABLES
    command.downgrade(cfg, "base")
    assert not (APP_TABLES & _tables(url))
    command.upgrade(cfg, "head")
    assert _tables(url) >= APP_TABLES


def test_table_definitions_match_the_migration(migrated_url: str):
    eng = sa.create_engine(migrated_url)
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), metadata)
    eng.dispose()
    assert diff == []


def test_check_constraints_reject_bad_values(migrated_url: str):
    eng = sa.create_engine(migrated_url)
    with eng.begin() as conn:
        conn.execute(sa.text("DELETE FROM workspaces WHERE slug = 'ck-test'"))
        conn.execute(
            sa.text("INSERT INTO workspaces (slug, name, config_hash) VALUES ('ck-test','x','h')")
        )
    insert = sa.text(
        "INSERT INTO leads (reference, workspace_slug, status, name, email, source, ip_hash,"
        " consent_at, consent_notice_version, score)"
        " VALUES (:ref, 'ck-test', :status, 'n', 'e@example.com', 'seed', 'h', now(), 'v', :score)"
    )
    for status, score in (("bogus", None), ("new", 101)):
        with pytest.raises(sa.exc.IntegrityError), eng.begin() as conn:
            conn.execute(insert, {"ref": f"CK-{status}-{score}", "status": status, "score": score})
    with eng.begin() as conn:
        conn.execute(sa.text("DELETE FROM workspaces WHERE slug = 'ck-test'"))
    eng.dispose()


def test_phase_two_migration_steps_down_and_up_alone(pg_base_url: str):
    url = create_database(pg_base_url, "leadq_migration_0002")
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")
    assert not ({"agent_runs", "llm_calls", "messages"} & _tables(url))
    assert "leads" in _tables(url)
    command.upgrade(cfg, "head")


def test_messages_are_channel_ready_and_budget_view_counts_live_reservations(migrated_url: str):
    eng = sa.create_engine(migrated_url)
    with eng.begin() as conn:
        conn.execute(sa.text("DELETE FROM leads WHERE workspace_slug = 'm-test'"))
        conn.execute(sa.text("DELETE FROM workspaces WHERE slug = 'm-test'"))
        conn.execute(
            sa.text("INSERT INTO workspaces (slug, name, config_hash) VALUES ('m-test','x','h')")
        )
        lead_id = conn.execute(
            sa.text(
                "INSERT INTO leads (reference, workspace_slug, name, email, source, ip_hash,"
                " consent_at, consent_notice_version)"
                " VALUES ('M-1','m-test','n','e@example.com','seed','h', now(), 'v') RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO messages (lead_id, version, language, channel_recipient, body)"
                " VALUES (:l, 1, 'en', 'e@example.com', 'hi')"
            ),
            {"l": lead_id},
        )
        row = conn.execute(sa.text("SELECT channel, subject FROM messages")).one()
        assert row.channel == "email"
        assert row.subject is None
    with pytest.raises(sa.exc.IntegrityError), eng.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO messages (lead_id, version, language, channel, channel_recipient,"
                " body) VALUES (:l, 2, 'en', 'sms', '+1', 'hi')"
            ),
            {"l": lead_id},
        )
    with eng.begin() as conn:
        conn.execute(sa.text("SET LOCAL app.allow_spend_reset = 'on'"))
        conn.execute(sa.text("DELETE FROM llm_spend"))  # other tests share this database
        for state, amount, age in (
            ("settled", "0.5", "0 minutes"),
            ("reserved", "0.25", "1 minute"),
            ("reserved", "9", "11 minutes"),  # old reservations keep counting
        ):
            conn.execute(
                sa.text(
                    "INSERT INTO llm_spend (agent_run_id, provider, model, state, amount_usd,"
                    " created_at) VALUES (gen_random_uuid(), 'anthropic', 'm', :s, :a,"
                    " now() - CAST(:age AS interval))"
                ),
                {"s": state, "a": amount, "age": age},
            )
        assert conn.execute(sa.text("SELECT spent_usd FROM llm_budget")).scalar_one() == 9.75
        conn.execute(sa.text("SET LOCAL app.allow_spend_reset = 'on'"))
        conn.execute(sa.text("DELETE FROM llm_spend"))
        conn.execute(sa.text("DELETE FROM leads WHERE workspace_slug = 'm-test'"))
        conn.execute(sa.text("DELETE FROM workspaces WHERE slug = 'm-test'"))
    eng.dispose()
