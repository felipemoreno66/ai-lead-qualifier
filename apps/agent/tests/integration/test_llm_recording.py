from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.config import Settings
from lead_qualifier.infrastructure.db.engine import create_engine
from lead_qualifier.infrastructure.llm.fake import FakeProvider
from lead_qualifier.infrastructure.llm.pricing import PricingTable
from lead_qualifier.infrastructure.llm.recording import RecordingProvider
from lead_qualifier.infrastructure.llm.repository import LlmCallRepository
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
    run_id = await make_run(db)
    wire = Wire(ok('{"score": 999}'), ok(json.dumps(GOOD)))
    provider = recorder(provider_for(wire), db)
    result = await generate_validated(
        provider, verdict_request(node="qualify", agent_run_id=run_id)
    )
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
    run_id = await make_run(db)
    provider = recorder(FakeProvider(), db, budget="0")
    await provider.generate_structured(verdict_request(agent_run_id=run_id))
    await provider.generate_structured(verdict_request(agent_run_id=run_id))
    stored = await rows(db)
    assert [r.provider for r in stored] == ["fake", "fake"]
    assert all(r.cost_usd == 0 and not r.is_estimated for r in stored)


async def test_budget_exceeded_blocks_the_call_before_it_is_made(db: AsyncEngine):
    run_id = await make_run(db)
    wire = Wire(ok(json.dumps(GOOD)), ok(json.dumps(GOOD)))
    # worst case of one call is about 0.000266 (512 max tokens at 0.50/MTok plus input)
    provider = recorder(provider_for(wire), db, budget="0.000280")
    await provider.generate_structured(verdict_request(agent_run_id=run_id))  # 0.000028 spent
    with pytest.raises(BudgetExceeded):
        await provider.generate_structured(verdict_request(agent_run_id=run_id))
    assert len(wire.requests) == 1
    assert len(await rows(db)) == 1


async def test_concurrent_calls_cannot_jointly_overshoot_the_budget(db: AsyncEngine):
    run_id = await make_run(db)
    wire = Wire(*[ok(json.dumps(GOOD)) for _ in range(5)])
    provider = recorder(provider_for(wire), db, budget="0.000280")
    outcomes = await asyncio.gather(
        *[provider.generate_structured(verdict_request(agent_run_id=run_id)) for _ in range(5)],
        return_exceptions=True,
    )
    assert sum(isinstance(o, BudgetExceeded) for o in outcomes) >= 3
    assert len(wire.requests) <= 2


async def test_unknown_model_is_billed_at_the_highest_known_rate(db: AsyncEngine):
    run_id = await make_run(db)
    wire = Wire(ok(json.dumps(GOOD)))
    provider = recorder(provider_for(wire), db)
    req = dataclasses.replace(verdict_request(agent_run_id=run_id), model="claude-typo-9")
    await provider.generate_structured(req)
    (row,) = await rows(db)
    assert row.is_estimated
    assert row.cost_usd == Decimal("0.000554")  # Sonnet rates, 554.5 per million


async def spend(engine: AsyncEngine) -> Decimal:
    async with engine.connect() as conn:
        return Decimal(
            (await conn.execute(sa.text("SELECT spent_usd FROM llm_budget"))).scalar_one()
        )


async def test_reservation_is_settled_with_the_real_cost(db: AsyncEngine):
    run_id = await make_run(db)
    provider = recorder(provider_for(Wire(ok(json.dumps(GOOD)))), db)
    await provider.generate_structured(verdict_request(agent_run_id=run_id))
    assert await spend(db) == Decimal("0.000028")
    async with db.connect() as conn:
        states = (await conn.execute(sa.text("SELECT state FROM llm_spend"))).scalars().all()
    assert list(states) == ["settled"]


async def test_purge_and_lead_deletion_do_not_lower_the_spend(db: AsyncEngine):
    run_id = await make_run(db)
    provider = recorder(provider_for(Wire(ok(json.dumps(GOOD)), ok(json.dumps(GOOD)))), db)
    await provider.generate_structured(verdict_request(agent_run_id=run_id))
    async with db.begin() as conn:
        await conn.execute(sa.text("UPDATE llm_calls SET created_at = now() - interval '90 days'"))
        await LlmCallRepository(conn).purge_before(datetime.now(UTC) - timedelta(days=30))
    assert await rows(db) == [] and await spend(db) == Decimal("0.000028")
    await provider.generate_structured(verdict_request(agent_run_id=run_id))
    async with db.begin() as conn:
        await conn.execute(sa.text("DELETE FROM leads"))
    assert await rows(db) == [] and await spend(db) == Decimal("0.000056")


async def test_two_processes_share_reservations_through_the_database(db: AsyncEngine):
    run_id = await make_run(db)
    other_engine = create_engine(db.url.render_as_string(hide_password=False))
    try:
        wire_a, wire_b = Wire(ok(json.dumps(GOOD))), Wire(ok(json.dumps(GOOD)))
        # room for exactly one worst-case call (about 0.000266)
        a = recorder(provider_for(wire_a), db, budget="0.000280")
        b = recorder(provider_for(wire_b), other_engine, budget="0.000280")
        outcomes = await asyncio.gather(
            a.generate_structured(verdict_request(agent_run_id=run_id)),
            b.generate_structured(verdict_request(agent_run_id=run_id)),
            return_exceptions=True,
        )
    finally:
        await other_engine.dispose()
    assert sum(isinstance(o, BudgetExceeded) for o in outcomes) == 1
    assert len(wire_a.requests) + len(wire_b.requests) == 1


async def test_old_reservations_keep_counting_at_worst_case(db: AsyncEngine):
    run_id = await make_run(db)
    async with db.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO llm_spend (agent_run_id, provider, model, state, amount_usd,"
                " created_at) VALUES (:r, 'anthropic', 'm', 'reserved', 4.9999,"
                " now() - interval '3 days')"
            ),
            {"r": run_id},
        )
    provider = recorder(provider_for(Wire(ok(json.dumps(GOOD)))), db)
    with pytest.raises(BudgetExceeded):
        await provider.generate_structured(verdict_request(agent_run_id=run_id))
    assert await spend(db) == Decimal("4.9999")


async def test_a_failing_record_still_settles_at_least_the_actual_cost(
    db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    run_id = await make_run(db)
    provider = recorder(provider_for(Wire(ok(json.dumps(GOOD)))), db)

    async def broken(*_a: object, **_k: object) -> Decimal:
        raise RuntimeError("serialisation failed")

    monkeypatch.setattr(provider, "_record", broken)
    result = await provider.generate_structured(verdict_request(agent_run_id=run_id))
    assert result.value.score == 61
    assert await spend(db) >= Decimal("0.000028")  # fell back to the worst-case reservation


async def test_cancellation_leaves_the_worst_case_charged(db: AsyncEngine):
    run_id = await make_run(db)
    started = asyncio.Event()

    class Hanging(FakeProvider):
        name = "anthropic"

        async def generate_structured(self, req):  # type: ignore[no-untyped-def]
            started.set()
            await asyncio.sleep(60)

    provider = recorder(Hanging(), db)
    task = asyncio.create_task(provider.generate_structured(verdict_request(agent_run_id=run_id)))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await spend(db) > Decimal("0.0001")
    async with db.connect() as conn:
        state = (await conn.execute(sa.text("SELECT state FROM llm_spend"))).scalar_one()
    assert state == "settled"


async def test_settle_is_retried_once_then_the_reservation_stays_counted(
    db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    run_id = await make_run(db)
    provider = recorder(provider_for(Wire(ok(json.dumps(GOOD)))), db)

    class FlakyEngine:
        """Delegates to the real engine but fails every transaction after the second."""

        def __init__(self) -> None:
            self.n = 0

        def begin(self):  # type: ignore[no-untyped-def]
            self.n += 1  # 1 = reserve, 2 = record, 3 and 4 = the two settle attempts
            if self.n >= 3:
                raise RuntimeError("db down")
            return db.begin()

    flaky = FlakyEngine()
    monkeypatch.setattr(provider, "_engine", flaky)
    await provider.generate_structured(verdict_request(agent_run_id=run_id))
    monkeypatch.undo()
    assert flaky.n == 4
    assert await spend(db) > Decimal("0.0001")  # still the reserved worst case


async def test_calls_without_an_agent_run_are_refused(db: AsyncEngine):
    provider = recorder(FakeProvider(), db)
    with pytest.raises(ValueError, match="agent_run_id"):
        await provider.generate_structured(verdict_request())


async def test_max_tokens_is_clamped_to_the_ceiling(db: AsyncEngine):
    run_id = await make_run(db)
    wire = Wire(ok(json.dumps(GOOD)))
    provider = recorder(provider_for(wire), db)
    req = dataclasses.replace(verdict_request(agent_run_id=run_id), max_tokens=10**6)
    await provider.generate_structured(req)
    assert wire.body()["max_tokens"] == 8192


async def test_stored_payloads_are_redacted(db: AsyncEngine):
    run_id = await make_run(db)
    provider = recorder(FakeProvider(), db)
    req = verdict_request("Mail ana@example.com or call +57 300 123 4567", agent_run_id=run_id)
    await provider.generate_structured(req)
    (row,) = await rows(db)
    content = row.request["messages"][0]["content"]
    assert "ana@example.com" not in content and "300 123" not in content
    assert "[email]" in content and "[phone]" in content


async def test_a_failed_insert_does_not_lose_the_paid_result(db: AsyncEngine):
    provider = recorder(provider_for(Wire(ok(json.dumps(GOOD)))), db)
    missing_run = verdict_request(agent_run_id=uuid4())  # FK violation on insert
    # The guard passes (no rows to count); the insert fails afterwards and is only logged.
    result = await provider.generate_structured(missing_run)
    assert result.value.score == 61
    assert await rows(db) == []


async def test_unexpected_adapter_exceptions_are_recorded(db: AsyncEngine):
    run_id = await make_run(db)
    provider = recorder(FakeProvider(script=[RuntimeError("boom")]), db)
    with pytest.raises(RuntimeError):
        await provider.generate_structured(verdict_request(agent_run_id=run_id))
    (row,) = await rows(db)
    assert (row.success, row.error_code) == (False, "unexpected_error")


async def test_retention_purge_and_lead_delete_cascade(db: AsyncEngine):
    run_id = await make_run(db)
    provider = recorder(FakeProvider(), db)
    await provider.generate_structured(verdict_request(agent_run_id=run_id))
    async with db.begin() as conn:
        await conn.execute(sa.text("UPDATE llm_calls SET created_at = now() - interval '40 days'"))
    await provider.generate_structured(verdict_request("fresh", agent_run_id=run_id))
    async with db.begin() as conn:
        removed = await LlmCallRepository(conn).purge_before(datetime.now(UTC) - timedelta(days=30))
    assert removed == 1 and len(await rows(db)) == 1
    async with db.begin() as conn:
        await conn.execute(sa.text("DELETE FROM leads"))
    assert await rows(db) == []


async def test_call_limit_per_agent_run(db: AsyncEngine):
    run_id = await make_run(db)
    provider = recorder(
        provider_for(Wire(ok(json.dumps(GOOD)), ok(json.dumps(GOOD)))), db, max_calls=1
    )
    await provider.generate_structured(verdict_request(agent_run_id=run_id))
    with pytest.raises(CallLimitExceeded):
        await provider.generate_structured(verdict_request(agent_run_id=run_id))


async def test_failures_are_recorded_and_repair_loop_gives_up(db: AsyncEngine):
    run_id = await make_run(db)
    provider = recorder(FakeProvider(script=["x", "y", "z"]), db)
    with pytest.raises(LLMOutputInvalid):
        await generate_validated(provider, verdict_request(agent_run_id=run_id))
    assert [(r.attempt, r.success) for r in await rows(db)] == [(1, False), (2, False), (3, False)]


def test_router_builds_the_configured_provider_and_models(db: AsyncEngine):
    fake = Settings(app_env="test", llm_provider="fake")
    assert build_provider(fake, db).name == "fake"
    assert model_for(fake, "draft") == "claude-haiku-5-5"
    tuned = Settings(app_env="test", llm_model_draft="claude-sonnet-5-5")
    assert model_for(tuned, "draft") == "claude-sonnet-5-5"
    assert model_for(tuned, "qualify") == "claude-haiku-5-5"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"llm_provider": "anthropic"}, "ANTHROPIC_API_KEY"),
        ({"llm_provider": "openai"}, "OPENAI_API_KEY"),
        ({"llm_provider": "bedrock", "aws_region": ""}, "AWS_REGION"),
        (
            {"llm_provider": "anthropic", "anthropic_api_key": "k", "llm_model_default": "x-1"},
            "not in pricing.yaml",
        ),
        (
            {
                "llm_provider": "anthropic",
                "anthropic_api_key": "k",
                "llm_model_draft": "claude-sonnet-5-5-20260101",
            },
            "not in pricing.yaml",
        ),
    ],
)
def test_router_fails_fast_on_bad_config(
    db: AsyncEngine, overrides: dict[str, object], message: str
):
    with pytest.raises(ValueError, match=message):
        build_provider(Settings(app_env="test", **overrides), db)  # type: ignore[arg-type]
