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
    assert again.status_code == 200 and again.json() == response.json()  # idempotent
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


EVIL_EDITS = [
    ("link with userinfo", {"body": "Pay at https://northwind-academy.example@evil.com now."}),
    ("bare domain", {"body": "Pay at evil.com/x now, it is quick."}),
    ("www domain", {"body": "Pay at www.evil.com now, it is quick."}),
    ("invented price", {"body": "The course costs USD 999 for you."}),
    ("invented price 2", {"body": "The course costs $1,200 for you."}),
    ("fullwidth dot", {"body": "Pay at evil。com now, it is quick."}),
    ("other currency", {"body": "The course costs 4000 pesos for you."}),
]


@pytest.mark.parametrize(("label", "fields"), EVIL_EDITS, ids=[e[0] for e in EVIL_EDITS])
async def test_an_edit_that_fails_the_draft_checks_is_refused_unless_overridden(
    make_client, db, label: str, fields: dict[str, str]
):
    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, f"v{abs(hash(label)) % 10**6}@example.com")
        refused = await review(client, lead_id, action="edit", subject="Hello", **fields)
        assert refused.status_code == 422
        assert refused.json()["errors"][0]["code"] in {
            "unsafe_link",
            "disallowed_link",
            "unknown_price",
        }
        assert (await rows(db, "SELECT status FROM leads"))[0].status == "pending_review"
        assert (
            await rows(db, "SELECT 1 FROM outbox_events WHERE event_type='message.approved'") == []
        )
        forced = await review(
            client, lead_id, action="edit", subject="Hello", override=True, **fields
        )
    assert forced.status_code == 200
    event = (await rows(db, "SELECT payload FROM lead_events WHERE type = 'reviewed'"))[0].payload
    assert event["override"] is True and event["problems"]


async def test_approving_a_draft_that_still_has_problems_needs_the_override(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "v2@example.com")
        async with db.begin() as conn:
            await conn.execute(
                sa.text("UPDATE messages SET body = body || ' Pay at https://evil.example now.'")
            )
        refused = await review(client, lead_id, action="approve")
        assert (
            refused.status_code == 422 and refused.json()["errors"][0]["code"] == "disallowed_link"
        )
        assert (await review(client, lead_id, action="approve", override=True)).status_code == 200


@pytest.mark.parametrize(
    "subject", ["Hi\r\nBcc: boss@evil.test", "Hi\nthere", "Hi‮txt", "Hi\x00", "Hi\u200bthere"]
)
async def test_a_subject_with_control_characters_is_a_validation_error(make_client, db, subject):
    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "v3@example.com")
        response = await review(client, lead_id, action="edit", subject=subject, body="Fine body.")
    assert response.status_code == 422
    assert (await rows(db, "SELECT status FROM leads"))[0].status == "pending_review"


async def test_concurrent_approvals_send_once_and_approve_races_reject(make_client, db):
    import asyncio

    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "c1@example.com")
        first, second = await asyncio.gather(
            review(client, lead_id, action="approve"), review(client, lead_id, action="approve")
        )
        assert (first.status_code, second.status_code) == (200, 200)  # the repeat is idempotent
        assert (
            len(await rows(db, "SELECT 1 FROM outbox_events WHERE event_type='message.approved'"))
            == 1
        )

        other = await pending(client, "c2@example.com")
        results = await asyncio.gather(
            review(client, other, action="approve"), review(client, other, action="reject")
        )
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409]
    final = (await rows(db, "SELECT status FROM leads WHERE id = :i", i=other))[0].status
    approved = len(
        await rows(
            db,
            "SELECT 1 FROM outbox_events WHERE lead_id = :i AND event_type = 'message.approved'",
            i=other,
        )
    )
    assert (final, approved) in {("approved", 1), ("rejected", 0)}


async def test_a_failing_resume_after_reject_discards_the_checkpoint(
    make_client, db, monkeypatch: pytest.MonkeyPatch
):
    from lead_qualifier.services import review as review_module

    async def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("checkpoint store down")

    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "c3@example.com")
        thread = f"lead:{lead_id}:run:1"
        count = "SELECT count(*) AS n FROM langgraph.checkpoints WHERE thread_id = :t"
        assert (await rows(db, count, t=thread))[0].n > 0
        monkeypatch.setattr(review_module, "resume_review", boom)
        response = await review(client, lead_id, action="reject")
        monkeypatch.undo()
        assert (await rows(db, count, t=thread))[0].n == 0
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    assert (await rows(db, "SELECT status FROM leads"))[0].status == "rejected"


async def test_regenerate_feedback_and_dedupe_do_not_break_the_flow(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "c4@example.com")
        assert (await review(client, lead_id, action="regenerate", feedback="x")).status_code == 200


async def test_the_sweep_removes_orphaned_and_old_finished_threads_only(make_client, db):
    from datetime import UTC, datetime, timedelta

    async with make_client(llm_provider=provider(db)) as client:
        waiting = await pending(client, "p1@example.com")
        done = await pending(client, "p2@example.com")
        gone = await pending(client, "p3@example.com")
        assert (await review(client, done, action="reject")).status_code == 200
        async with db.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE agent_runs SET finished_at = now() - interval '90 days'"
                    " WHERE lead_id = :i"
                ),
                {"i": done},
            )
            await conn.execute(sa.text("DELETE FROM leads WHERE id = :i"), {"i": gone})  # orphan
        checkpointer = client.app.state.checkpointer
        removed = await checkpointer.purge_stale_threads(db, datetime.now(UTC), timedelta(days=30))
        remaining = {
            r.thread_id
            for r in await rows(db, "SELECT DISTINCT thread_id FROM langgraph.checkpoints")
        }
    assert removed >= 2  # (threads left by other tests in this shared database are orphans too)
    assert f"lead:{waiting}:run:1" in remaining  # a lead waiting for a human keeps its thread
    assert not {f"lead:{done}:run:1", f"lead:{gone}:run:1"} & remaining


async def test_repeating_an_approval_after_an_edit_is_still_idempotent(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "e9@example.com")
        edited = await review(
            client, lead_id, action="edit", subject="Hello", body="Fine body here."
        )
        again = await review(client, lead_id, action="approve")
    assert edited.status_code == 200 and again.status_code == 200
    assert again.json()["message_id"] == edited.json()["message_id"]
    assert (
        len(await rows(db, "SELECT 1 FROM outbox_events WHERE event_type='message.approved'")) == 1
    )


async def test_the_sweep_survives_a_thread_that_cannot_be_deleted(make_client, db):
    from datetime import UTC, datetime, timedelta

    async with make_client(llm_provider=provider(db)) as client:
        for n in range(2):
            lead_id = await pending(client, f"w{n}@example.com")
            async with db.begin() as conn:
                await conn.execute(sa.text("DELETE FROM leads WHERE id = :i"), {"i": lead_id})
        checkpointer = client.app.state.checkpointer
        saver = await checkpointer.get()
        real = saver.adelete_thread
        calls: list[str] = []

        async def flaky(thread_id: str) -> None:
            calls.append(thread_id)
            if len(calls) == 1:
                raise RuntimeError("db hiccup")
            await real(thread_id)

        saver.adelete_thread = flaky  # type: ignore[method-assign]
        removed = await checkpointer.purge_stale_threads(db, datetime.now(UTC), timedelta(days=30))
        saver.adelete_thread = real  # type: ignore[method-assign]
    assert len(calls) >= 2 and removed == len(calls) - 1  # the failure did not stop the loop


async def test_a_crash_right_after_a_regenerate_claim_is_reaped_but_a_live_one_is_not(
    make_client, db, monkeypatch: pytest.MonkeyPatch
):
    import asyncio
    from datetime import timedelta

    from lead_qualifier.ports.clock import SystemClock
    from lead_qualifier.services import review as review_module
    from lead_qualifier.services.reaper import reap_stale_runs

    async def killed(*_a: object, **_k: object) -> None:
        raise asyncio.CancelledError  # the process dies after the claim is committed

    async with make_client(llm_provider=provider(db)) as client:
        lead_id = await pending(client, "r9@example.com")
        async with db.begin() as conn:  # the run is old, as in any run that waited for review
            await conn.execute(
                sa.text("UPDATE agent_runs SET started_at = now() - interval '5 days'")
            )
        monkeypatch.setattr(review_module, "resume_review", killed)
        with pytest.raises(asyncio.CancelledError):
            await client.app.state.reviewer.review(uuid.UUID(lead_id), "regenerate", feedback="x")
        monkeypatch.undo()
        state = await rows(db, "SELECT l.status, r.status AS run FROM leads l, agent_runs r")
        assert (state[0].status, state[0].run) == ("qualifying", "running")
        # the claim just refreshed the lead, so a regenerate in progress is left alone
        assert await reap_stale_runs(db, SystemClock(), timedelta(minutes=10)) == 0
        async with db.begin() as conn:
            await conn.execute(
                sa.text("UPDATE leads SET updated_at = now() - interval '30 minutes'")
            )
        assert await reap_stale_runs(db, SystemClock(), timedelta(minutes=10)) == 1
    final = await rows(db, "SELECT status, error_reason FROM leads")
    assert final[0].status == "error" and final[0].error_reason.startswith("interrupted")
