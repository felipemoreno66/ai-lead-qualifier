from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from lead_qualifier.infrastructure.db.tables import metadata
from tests.conftest import alembic_config, create_database

pytestmark = pytest.mark.integration

APP_TABLES = {"workspaces", "leads", "lead_events", "outbox_events", "rate_limit_hits"}


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
