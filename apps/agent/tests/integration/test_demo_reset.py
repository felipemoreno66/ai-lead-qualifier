"""The nightly reset removes what visitors created and restores the fictional data, idempotently."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.scripts.demo_reset import reset_once
from lead_qualifier.scripts.seed import SeedRefused

pytestmark = pytest.mark.integration


async def scalar(db: AsyncEngine, sql: str) -> int:
    async with db.connect() as conn:
        return int((await conn.execute(sa.text(sql))).scalar_one())


def public_settings(make_settings):  # type: ignore[no-untyped-def]
    return make_settings(public_demo=True, smtp_host="mailpit", demo_seed=True)


async def test_it_refuses_to_run_outside_the_public_demo(make_settings, db):
    with pytest.raises(SeedRefused, match="PUBLIC_DEMO"):
        await reset_once(make_settings(demo_seed=True))


async def test_it_removes_visitor_data_and_restores_the_seed(make_settings, db):
    settings = public_settings(make_settings)
    await reset_once(settings)
    assert await scalar(db, "SELECT count(*) FROM leads") == 20

    async with db.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO leads (reference, workspace_slug, status, name, email, locale,"
                " answers,"
                " source, ip_hash, consent_at, consent_notice_version)"
                " VALUES ('NWA-VISITOR', 'northwind-academy', 'new', 'Visitor', 'v@example.com',"
                " 'en', '{}', 'hosted_form', 'h', now(), '1')"
            )
        )
        await conn.execute(sa.text("INSERT INTO rate_limit_hits VALUES ('ip:x:60', now(), 3)"))
        await conn.execute(
            sa.text(
                "INSERT INTO kb_queries (workspace_slug, question, answer, covered)"
                " VALUES ('northwind-academy', 'visitor question', 'a', true)"
            )
        )

    report = await reset_once(settings)
    assert report[0] == "leads: created 20, already present 0"
    assert await scalar(db, "SELECT count(*) FROM leads") == 20
    assert await scalar(db, "SELECT count(*) FROM leads WHERE reference = 'NWA-VISITOR'") == 0
    assert await scalar(db, "SELECT count(*) FROM rate_limit_hits") == 0
    assert (
        await scalar(db, "SELECT count(*) FROM kb_queries WHERE question = 'visitor question'") == 0
    )
    assert await scalar(db, "SELECT count(*) FROM kb_queries") == 3

    again = await reset_once(settings)
    assert again[0] == "leads: created 20, already present 0"
    assert await scalar(db, "SELECT count(*) FROM leads") == 20
    assert await scalar(db, "SELECT count(*) FROM messages") == 6
