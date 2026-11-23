from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.infrastructure.llm.fake import FakeProvider
from lead_qualifier.infrastructure.llm.fake_handlers import FAKE_HANDLERS
from lead_qualifier.infrastructure.llm.pricing import PricingTable
from lead_qualifier.infrastructure.llm.recording import RecordingProvider
from lead_qualifier.ports.llm import BudgetExceeded, LLMTimeout
from tests.integration.test_admin_api import AUTH, N8N_AUTH, lead_id_for, submit

pytestmark = pytest.mark.integration


def recorded(db: AsyncEngine, **kw: object) -> RecordingProvider:
    return RecordingProvider(
        FakeProvider(handlers=FAKE_HANDLERS, **kw),  # type: ignore[arg-type]
        db,
        PricingTable.load(),
        budget_usd=Decimal(5),
        max_calls_per_run=12,
    )


async def one(db: AsyncEngine, sql: str, **params: object) -> sa.Row[tuple[object, ...]]:
    async with db.connect() as conn:
        return (await conn.execute(sa.text(sql), params)).one()


async def qualify(client, lead_id: str, headers=N8N_AUTH):  # type: ignore[no-untyped-def]
    return await client.post(f"/internal/leads/{lead_id}/qualify", headers=headers)


async def test_qualify_persists_score_run_and_llm_calls(make_client, db: AsyncEngine):
    async with make_client(llm_provider=recorded(db)) as client:
        await submit(client, "q1@example.com")
        lead_id = await lead_id_for(client, "q1@")
        response = await qualify(client, lead_id)
    data = response.json()
    assert response.status_code == 200
    assert data["status"] == "pending_review" and 0 <= data["score"] <= 100
    assert data["tier"] in {"hot", "warm", "cold"} and data["recommended_product"]

    lead = await one(db, "SELECT * FROM leads WHERE id = :i", i=lead_id)
    assert (lead.score, lead.tier) == (data["score"], data["tier"])
    assert lead.qualified_at is not None and lead.detected_language
    assert [c["id"] for c in lead.qualification["criteria"]] == [
        "goal_fit", "budget_fit", "availability_fit", "readiness", "reachable"
    ]  # fmt: skip
    assert lead.qualification["profile"]["detected_language"] == lead.detected_language
    assert "score" not in lead.qualification  # stored once, in the column

    run = await one(db, "SELECT * FROM agent_runs WHERE lead_id = :i", i=lead_id)
    assert run.status == "interrupted" and run.run_number == 1
    assert run.thread_id == f"lead:{lead_id}:run:1"
    assert run.prompt_versions == {
        "extract": "extract@1",
        "qualify": "qualify@1",
        "draft": "draft@1",
    }
    assert run.total_cost_usd == 0 and run.duration_ms is not None

    async with db.connect() as conn:
        calls = (
            await conn.execute(
                sa.text("SELECT node, provider, success FROM llm_calls ORDER BY created_at")
            )
        ).all()
    assert [(c.node, c.provider, c.success) for c in calls] == [
        ("extract", "fake", True),
        ("qualify", "fake", True),
        ("draft", "fake", True),
    ]


async def test_qualify_requires_the_n8n_token_and_a_known_qualifiable_lead(make_client, db):
    async with make_client(llm_provider=recorded(db)) as client:
        await submit(client, "q2@example.com")
        lead_id = await lead_id_for(client, "q2@")
        assert (await qualify(client, lead_id, headers={})).status_code == 401
        assert (await qualify(client, lead_id, headers=AUTH)).status_code == 403
        assert (await qualify(client, str(uuid.uuid4()))).status_code == 404
        assert (await qualify(client, lead_id)).status_code == 200
        # already qualifying: a duplicate delivery must not start a second run
        assert (await qualify(client, lead_id)).status_code == 409
    runs = await one(db, "SELECT count(*) AS n FROM agent_runs")
    assert runs.n == 1


async def test_llm_failure_marks_the_lead_error_and_retry_starts_a_new_run(make_client, db):
    provider = recorded(db, script=[LLMTimeout("provider too slow")])
    async with make_client(llm_provider=provider) as client:
        await submit(client, "q3@example.com")
        lead_id = await lead_id_for(client, "q3@")
        failed = (await qualify(client, lead_id)).json()
        assert failed["status"] == "error" and failed["error_reason"].startswith("llm_timeout")
        lead = await one(
            db, "SELECT status, error_reason, score FROM leads WHERE id = :i", i=lead_id
        )
        assert lead.status == "error" and lead.score is None
        assert lead.error_reason.startswith("llm_timeout")

        retried = (await qualify(client, lead_id)).json()
    assert retried["status"] == "pending_review" and retried["score"] is not None
    lead = await one(db, "SELECT status, error_reason FROM leads WHERE id = :i", i=lead_id)
    assert (lead.status, lead.error_reason) == ("pending_review", None)
    async with db.connect() as conn:
        runs = (
            await conn.execute(
                sa.text("SELECT run_number, status, thread_id FROM agent_runs ORDER BY run_number")
            )
        ).all()
        failed_call = (
            await conn.execute(
                sa.text("SELECT success, error_code FROM llm_calls WHERE NOT success")
            )
        ).one()
    assert [(r.run_number, r.status) for r in runs] == [(1, "failed"), (2, "interrupted")]
    assert runs[1].thread_id == f"lead:{lead_id}:run:2"
    assert (failed_call.success, failed_call.error_code) == (False, "llm_timeout")


async def test_budget_exceeded_becomes_a_retryable_lead_error(make_client, db):
    provider = recorded(db, script=[BudgetExceeded("cap reached")])
    async with make_client(llm_provider=provider) as client:
        await submit(client, "q4@example.com")
        lead_id = await lead_id_for(client, "q4@")
        outcome = (await qualify(client, lead_id)).json()
    assert outcome["status"] == "error" and outcome["error_reason"].startswith("budget_exceeded")


async def test_inline_orchestrator_qualifies_on_dispatch(make_client, db):
    async with make_client(orchestrator="inline", llm_provider=recorded(db)) as client:
        await submit(client, "q5@example.com")
        await client.app.state.dispatcher.run_once()
        lead_id = await lead_id_for(client, "q5@")
        # the event is delivered, the lead was qualified, and a redelivery is a harmless no-op
    lead = await one(db, "SELECT status, score FROM leads WHERE id = :i", i=lead_id)
    assert lead.status == "pending_review" and lead.score is not None
    event = await one(db, "SELECT status FROM outbox_events")
    assert event.status == "delivered"
