"""The keyless demo's first-start setup: idempotent, fake-only and never for production."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.scripts.demo_init import run
from lead_qualifier.scripts.seed import SeedRefused

pytestmark = pytest.mark.integration


def demo_settings(make_settings, **overrides):  # type: ignore[no-untyped-def]
    return make_settings(
        demo_seed=True, embeddings_provider="fake", kb_min_similarity=0.1, **overrides
    )


async def scalar(db: AsyncEngine, sql: str) -> int:
    async with db.connect() as conn:
        return int((await conn.execute(sa.text(sql))).scalar_one())


async def test_it_does_nothing_unless_demo_seed_is_on(make_settings, db):
    report = await run(make_settings(demo_seed=False))
    assert "nothing to do" in report[0]
    assert await scalar(db, "SELECT count(*) FROM leads") == 0


async def test_it_loads_leads_drafts_runs_and_answers_once(make_settings, db):
    settings = demo_settings(make_settings)
    first = await run(settings)
    assert first[0].startswith("leads: created 20")
    assert first[1] == "drafts and run logs: 7 added"
    assert "knowledge base:" in first[2] and "3 demo questions answered" in first[2]

    assert await scalar(db, "SELECT count(*) FROM leads") == 20
    states = await scalar(
        db,
        "SELECT count(*) FROM messages m JOIN leads l ON l.id = m.lead_id "
        "WHERE (l.status = 'pending_review' AND m.status = 'draft') "
        "OR (l.status = 'sent' AND m.status = 'sent') "
        "OR (l.status = 'rejected' AND m.status = 'rejected')",
    )
    assert states == 6
    assert await scalar(db, "SELECT count(*) FROM llm_calls WHERE success = false") == 1
    assert await scalar(db, "SELECT count(*) FROM messages WHERE edited_by_operator") == 1
    # Every draft is clean text a reviewer can read: no placeholders, no links.
    assert await scalar(db, "SELECT count(*) FROM messages WHERE body ~ '\\[|\\{|https?://'") == 0
    assert await scalar(db, "SELECT count(*) FROM kb_queries") == 3
    assert await scalar(db, "SELECT count(*) FROM agent_runs WHERE kind = 'kb_chat'") == 3
    assert (
        await scalar(db, "SELECT count(*) FROM leads WHERE workspace_slug <> 'northwind-academy'")
        == 0
    )

    again = await run(settings)
    assert again[0] == "leads: created 0, already present 20"
    assert again[1] == "drafts and run logs: 0 added"
    assert "already present" in again[2]
    assert await scalar(db, "SELECT count(*) FROM messages") == 6
    assert await scalar(db, "SELECT count(*) FROM kb_queries") == 3


async def test_it_never_asks_a_real_provider(make_settings, db, monkeypatch):
    report = await run(
        demo_settings(make_settings, llm_provider="anthropic", anthropic_api_key="x" * 20)
    )
    assert "demo questions skipped" in report[2]
    assert await scalar(db, "SELECT count(*) FROM kb_queries") == 0


async def test_it_refuses_production(make_settings, db):
    with pytest.raises(SeedRefused, match="production"):
        await run(
            make_settings(
                demo_seed=True,
                app_env="production",
                admin_api_token="p" * 24,
                n8n_api_token="q" * 24,
                n8n_webhook_secret="r" * 24,
                ip_hash_secret="s" * 24,
                dashboard_user="u",
                dashboard_password="p" * 12,
            )
        )
    assert await scalar(db, "SELECT count(*) FROM leads") == 0


async def test_a_reset_recreates_the_seeded_leads_with_their_content(make_settings, db):
    settings = demo_settings(make_settings)
    await run(settings)
    report = await run(settings, reset=True)
    assert report[0].startswith("leads: created 20") and report[1] == "drafts and run logs: 7 added"
    assert await scalar(db, "SELECT count(*) FROM messages") == 6


async def test_the_status_endpoint_says_whether_this_is_a_demo(make_client):
    from tests.integration.test_admin_api import AUTH

    async with make_client() as client:
        fake = (await client.get("/admin/status", headers=AUTH)).json()
        assert (await client.get("/admin/status")).status_code == 401
    assert fake == {"llm_provider": "fake", "demo_mode": True}
