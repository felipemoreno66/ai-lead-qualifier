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
from tests.integration.test_admin_api import AUTH, N8N_AUTH, lead_id_for, submit

pytestmark = pytest.mark.integration


def provider(db: AsyncEngine) -> RecordingProvider:
    return RecordingProvider(
        FakeProvider(handlers=FAKE_HANDLERS),
        db,
        PricingTable.load(),
        budget_usd=Decimal(5),
        max_calls_per_run=12,
    )


async def pending(client, email: str) -> str:  # type: ignore[no-untyped-def]
    await submit(client, email)
    lead_id = await lead_id_for(client, email[:3])
    response = await client.post(f"/internal/leads/{lead_id}/qualify", headers=N8N_AUTH)
    assert response.json()["status"] == "pending_review"
    return lead_id


async def review(client, lead_id: str, **payload):  # type: ignore[no-untyped-def]
    return await client.post(f"/admin/leads/{lead_id}/review", headers=AUTH, json=payload)


async def rows(db: AsyncEngine, sql: str, **params: object) -> list[sa.Row[tuple[object, ...]]]:
    async with db.connect() as conn:
        return list((await conn.execute(sa.text(sql), params)).all())


async def test_a_pending_lead_exposes_its_draft(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "d1@example.com")
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
    (message,) = detail["messages"]
    assert message["status"] == "draft" and message["channel"] == "email"
    assert message["channel_recipient"] == "d1@example.com" and message["subject"]
    assert message["short_body"] and message["guard_warnings"] == []
    assert message["language"] in {"en", "es"}


async def test_approve_queues_message_approved_exactly_once(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "a1@example.com")
        response = await review(client, lead_id, action="approve")
        again = await review(client, lead_id, action="approve")
    assert response.status_code == 200 and response.json()["status"] == "approved"
    assert again.status_code == 409
    (outbox,) = await rows(db, "SELECT * FROM outbox_events WHERE event_type = 'message.approved'")
    assert outbox.status == "pending" and outbox.payload["message"]["channel"] == "email"
    assert outbox.idempotency_key.startswith("message:")
    assert "a1@example.com" not in str(outbox.payload)
    (message,) = await rows(db, "SELECT * FROM messages")
    assert message.status == "approved" and not message.edited_by_operator
    lead, run = (
        (await rows(db, "SELECT status FROM leads"))[0],
        (await rows(db, "SELECT status FROM agent_runs"))[0],
    )
    assert (lead.status, run.status) == ("approved", "completed")
    events = await rows(db, "SELECT type, actor FROM lead_events WHERE type = 'reviewed'")
    assert [(e.type, e.actor) for e in events] == [("reviewed", "operator")]


async def test_edit_keeps_the_original_body(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "e1@example.com")
        original = (await rows(db, "SELECT body FROM messages"))[0].body
        response = await review(
            client, lead_id, action="edit", subject="Hello!", body="A better, shorter reply."
        )
    assert response.json()["status"] == "approved"
    (message,) = await rows(db, "SELECT * FROM messages")
    assert message.body == "A better, shorter reply." and message.subject == "Hello!"
    assert message.original_body == original and message.edited_by_operator
    assert message.short_body is None  # the generated variant no longer matches the edit
    assert message.status == "approved"


async def test_reject_ends_the_lead_and_sends_nothing(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "r1@example.com")
        response = await review(client, lead_id, action="reject", note="not a fit")
    assert response.json()["status"] == "rejected"
    assert (await rows(db, "SELECT status FROM leads"))[0].status == "rejected"
    (message,) = await rows(db, "SELECT status, review_note FROM messages")
    assert (message.status, message.review_note) == ("rejected", "not a fit")
    assert await rows(db, "SELECT 1 FROM outbox_events WHERE event_type = 'message.approved'") == []


async def test_regenerate_creates_a_new_version_and_returns_to_review(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "g1@example.com")
        response = await review(client, lead_id, action="regenerate", feedback="shorter please")
        assert response.json()["status"] == "pending_review"
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
        # the new draft can be approved like the first one
        assert (await review(client, lead_id, action="approve")).status_code == 200
    assert [(m["version"], m["status"]) for m in detail["messages"]] == [
        (1, "rejected"),
        (2, "draft"),
    ]
    assert detail["messages"][0]["review_note"] == "shorter please"
    drafts = await rows(
        db, "SELECT request FROM llm_calls WHERE node = 'draft' ORDER BY created_at"
    )
    assert len(drafts) == 2
    assert "shorter please" in drafts[1].request["messages"][0]["content"]
    assert "operator_feedback" not in drafts[0].request["messages"][0]["content"]
    assert (await rows(db, "SELECT status FROM leads"))[0].status == "approved"


async def test_illegal_reviews_are_409_and_validation_is_422(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        await submit(client, "i1@example.com")
        new_id = await lead_id_for(client, "i1@")
        assert (await review(client, new_id, action="approve")).status_code == 409
        pending_id = await pending(client, "i2@example.com")
        assert (await review(client, pending_id, action="edit")).status_code == 422
        assert (await review(client, pending_id, action="launch")).status_code == 422
        assert (await review(client, str(uuid.uuid4()), action="approve")).status_code == 404
        assert (await review(client, pending_id, action="reject")).status_code == 200
        for action in ("approve", "reject", "regenerate", "edit"):
            extra = {"body": "x"} if action == "edit" else {}
            assert (await review(client, pending_id, action=action, **extra)).status_code == 409
        denied = await client.post(
            f"/admin/leads/{pending_id}/review", headers=N8N_AUTH, json={"action": "approve"}
        )
        assert denied.status_code == 403


async def test_request_send_is_idempotent_on_replay(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "k1@example.com")
        reviewer = client.app.state.reviewer
        message_id = (await rows(db, "SELECT id FROM messages"))[0].id
        decision = {"action": "approve", "message_id": str(message_id)}
        await reviewer.request_send(decision, {})
        await reviewer.request_send(decision, {})  # replay after a crash: a harmless no-op
    outbox = await rows(db, "SELECT 1 FROM outbox_events WHERE event_type = 'message.approved'")
    assert len(outbox) == 1
    assert (await rows(db, "SELECT status FROM leads WHERE id = :i", i=lead_id))[0].status == (
        "approved"
    )


async def test_review_resumes_after_an_agent_restart(make_client, db):
    llm = provider(db)
    async with make_client(llm_provider=llm) as first:
        lead_id = await pending(first, "z1@example.com")
        await first.app.state.checkpointer.aclose()  # the old process goes away
    async with make_client(llm_provider=llm) as second:  # new app, service and connection pool
        response = await review(second, lead_id, action="approve")
    assert response.status_code == 200 and response.json()["status"] == "approved"
    assert (
        len(await rows(db, "SELECT 1 FROM outbox_events WHERE event_type = 'message.approved'"))
        == 1
    )


async def test_deleting_a_lead_removes_its_checkpoints(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "x1@example.com")
        thread = f"lead:{lead_id}:run:1"
        count = "SELECT count(*) AS n FROM langgraph.checkpoints WHERE thread_id = :t"
        assert (await rows(db, count, t=thread))[0].n > 0
        assert (await client.delete(f"/admin/leads/{lead_id}", headers=AUTH)).status_code == 204
        assert (await rows(db, count, t=thread))[0].n == 0


async def test_a_draft_failure_is_a_generic_retryable_error(make_client, db):
    from lead_qualifier.ports.llm import LLMTimeout

    llm = RecordingProvider(
        FakeProvider(handlers=FAKE_HANDLERS, script=[None, None, LLMTimeout("secret detail")]),
        db,
        PricingTable.load(),
        budget_usd=Decimal(5),
        max_calls_per_run=12,
    )
    async with make_client(llm_provider=llm) as client:
        await submit(client, "f1@example.com")
        lead_id = await lead_id_for(client, "f1@")
        outcome = (await client.post(f"/internal/leads/{lead_id}/qualify", headers=N8N_AUTH)).json()
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
        retried = (await client.post(f"/internal/leads/{lead_id}/qualify", headers=N8N_AUTH)).json()
    assert outcome["status"] == "error" and outcome["error_reason"].startswith("llm_timeout:")
    assert "secret detail" not in str(detail) and detail["messages"] == []
    assert retried["status"] == "pending_review"
