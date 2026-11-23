from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.domain.lead_form import validate_answers
from lead_qualifier.ports.clock import SystemClock
from lead_qualifier.scripts.seed import DEFAULT_SEED_FILE, SeedRefused, seed
from lead_qualifier.workspaces.loader import WorkspaceRegistry

pytestmark = pytest.mark.integration


async def _run(db: AsyncEngine, registry: WorkspaceRegistry, **kw: str):
    return await seed(
        db,
        registry,
        workspace=kw.get("workspace", "northwind-academy"),
        app_env=kw.get("app_env", "local"),
        clock=SystemClock(),
        ip_hash_secret="test-secret",
    )


async def test_seed_creates_twenty_leads_and_is_idempotent(
    db: AsyncEngine, registry: WorkspaceRegistry
):
    first = await _run(db, registry)
    assert (first.created, first.skipped) == (20, 0)
    second = await _run(db, registry)
    assert (second.created, second.skipped) == (0, 20)
    async with db.connect() as conn:
        statuses = dict(
            (await conn.execute(text("SELECT status, count(*) FROM leads GROUP BY 1"))).all()
        )
        assert sum(statuses.values()) == 20
        assert statuses["new"] >= 10
        assert {"pending_review", "sent", "rejected", "error"} <= set(statuses)
        events = (
            await conn.execute(text("SELECT count(*) FROM lead_events WHERE type='submitted'"))
        ).scalar_one()
        assert events == 20
        delivered = (
            await conn.execute(text("SELECT count(*) FROM outbox_events WHERE status='delivered'"))
        ).scalar_one()
        assert delivered == 20
        tiers = {
            r[0]
            for r in await conn.execute(
                text("SELECT DISTINCT tier FROM leads WHERE tier IS NOT NULL")
            )
        }
        assert tiers == {"hot", "warm", "cold"}


async def test_seed_refuses_other_workspaces_and_production(
    db: AsyncEngine, registry: WorkspaceRegistry
):
    with pytest.raises(SeedRefused, match="david-moreno"):
        await _run(db, registry, workspace="david-moreno")
    with pytest.raises(SeedRefused, match="production"):
        await _run(db, registry, app_env="production")


def test_seed_answers_are_valid_for_the_northwind_form(registry: WorkspaceRegistry):
    config = registry.get("northwind-academy").config  # type: ignore[union-attr]
    data = json.loads(DEFAULT_SEED_FILE.read_text())
    assert data["workspace"] == "northwind-academy"
    assert len(data["leads"]) == 20
    for lead in data["leads"]:
        _clean, errors = validate_answers(config.form.fields, lead["answers"])
        assert not errors, (lead["reference"], errors)
        assert lead["email"].endswith(("@example.com", "@example.org", "@example.net"))
