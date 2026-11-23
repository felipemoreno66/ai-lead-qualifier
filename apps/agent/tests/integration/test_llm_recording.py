from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.config import Settings
from lead_qualifier.infrastructure.llm.fake import FakeProvider
from lead_qualifier.infrastructure.llm.pricing import PricingTable
from lead_qualifier.infrastructure.llm.recording import RecordingProvider
from lead_qualifier.infrastructure.llm.router import build_provider, model_for
from lead_qualifier.infrastructure.llm.structured import generate_validated
from lead_qualifier.ports.llm import BudgetExceeded, CallLimitExceeded, LLMOutputInvalid
from tests.unit.llm.helpers import verdict_request
from tests.unit.llm.test_anthropic_provider import GOOD, Wire, ok, provider_for

pytestmark = pytest.mark.integration


def recorder(inner, engine: AsyncEngine, *, budget: str = "5", max_calls: int = 12):  # type: ignore[no-untyped-def]
    return RecordingProvider(
        inner,
        engine,
        PricingTable.load(),
        budget_usd=Decimal(budget),
        max_calls_per_run=max_calls,
    )


async def rows(engine: AsyncEngine) -> list[sa.Row[tuple[object, ...]]]:
    async with engine.connect() as conn:
        return list(
            (await conn.execute(sa.text("SELECT * FROM llm_calls ORDER BY created_at"))).all()
        )


async def make_run(engine: AsyncEngine) -> UUID:
    async with engine.begin() as conn:
        lead_id = (
            await conn.execute(
                sa.text(
                    "INSERT INTO leads (reference, workspace_slug, name, email, source, ip_hash,"
                    " consent_at, consent_notice_version) VALUES ('R-1', 'northwind-academy',"
                    " 'n', 'e@example.com', 'seed', 'h', now(), 'v') RETURNING id"
                )
            )
        ).scalar_one()
        run_id = (
            await conn.execute(
                sa.text(
                    "INSERT INTO agent_runs (lead_id, thread_id, run_number, graph_version)"
                    " VALUES (:l, 't-1', 1, 'test') RETURNING id"
                ),
                {"l": lead_id},
            )
        ).scalar_one()
    return UUID(str(run_id))


async def test_each_attempt_is_recorded_with_cost_and_tokens(db: AsyncEngine):
    wire = Wire(ok('{"score": 999}'), ok(json.dumps(GOOD)))
    provider = recorder(provider_for(wire), db)
    result = await generate_validated(provider, verdict_request(node="qualify"))
    assert result.value.score == 61
    first, second = await rows(db)
    assert (first.attempt, first.success, first.error_code) == (1, False, "llm_output_invalid")
    assert (second.attempt, second.success, second.node) == (2, True, "qualify")
    # 120 in, 30 out, 10 cache read, 5 cache write at Haiku 5.5 prices
    assert second.cost_usd == Decimal("0.000028")
    assert first.cost_usd == second.cost_usd  # the failed attempt was billed too
    assert second.response == GOOD
    assert second.request["messages"][0]["content"].startswith("Maria")


async def test_fake_calls_cost_nothing_and_never_hit_the_budget(db: AsyncEngine):
    provider = recorder(FakeProvider(), db, budget="0")
    await provider.generate_structured(verdict_request())
    await provider.generate_structured(verdict_request())
    stored = await rows(db)
    assert [r.provider for r in stored] == ["fake", "fake"]
    assert all(r.cost_usd == 0 and not r.is_estimated for r in stored)


async def test_budget_exceeded_blocks_the_call_before_it_is_made(db: AsyncEngine):
    wire = Wire(ok(json.dumps(GOOD)), ok(json.dumps(GOOD)))
    provider = recorder(provider_for(wire), db, budget="0.000050")
    await provider.generate_structured(verdict_request())  # 0.000028 spent
    await provider.generate_structured(verdict_request())  # 0.000056 spent, now over
    with pytest.raises(BudgetExceeded):
        await provider.generate_structured(verdict_request())
    assert len(wire.requests) == 2
    assert len(await rows(db)) == 2


async def test_call_limit_per_agent_run(db: AsyncEngine):
    run_id = await make_run(db)
    provider = recorder(
        provider_for(Wire(ok(json.dumps(GOOD)), ok(json.dumps(GOOD)))), db, max_calls=1
    )
    await provider.generate_structured(verdict_request(agent_run_id=run_id))
    with pytest.raises(CallLimitExceeded):
        await provider.generate_structured(verdict_request(agent_run_id=run_id))


async def test_failures_are_recorded_and_repair_loop_gives_up(db: AsyncEngine):
    provider = recorder(FakeProvider(script=["x", "y", "z"]), db)
    with pytest.raises(LLMOutputInvalid):
        await generate_validated(provider, verdict_request())
    assert [(r.attempt, r.success) for r in await rows(db)] == [(1, False), (2, False), (3, False)]


def test_router_builds_the_configured_provider_and_models(db: AsyncEngine):
    fake = Settings(app_env="test", llm_provider="fake")
    assert build_provider(fake, db).name == "fake"
    assert model_for(fake, "draft") == "claude-haiku-5-5"
    tuned = Settings(app_env="test", llm_model_draft="claude-sonnet-5-5")
    assert model_for(tuned, "draft") == "claude-sonnet-5-5"
    assert model_for(tuned, "qualify") == "claude-haiku-5-5"
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_provider(Settings(app_env="test", llm_provider="anthropic"), db)
