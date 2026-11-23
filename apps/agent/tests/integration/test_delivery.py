from __future__ import annotations

import json
import time
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.infrastructure.email.smtp import SmtpSender
from lead_qualifier.infrastructure.llm.fake import FakeProvider
from lead_qualifier.infrastructure.llm.fake_handlers import FAKE_HANDLERS
from lead_qualifier.infrastructure.llm.pricing import PricingTable
from lead_qualifier.infrastructure.llm.recording import RecordingProvider
from lead_qualifier.infrastructure.outbox.publishers import sign
from tests.conftest import SmtpInbox
from tests.integration.test_admin_api import AUTH, N8N_AUTH, lead_id_for, submit
from tests.integration.test_review import review

pytestmark = pytest.mark.integration
SECRET = "test-webhook-secret-1234"


def llm(db: AsyncEngine) -> RecordingProvider:
    return RecordingProvider(
        FakeProvider(handlers=FAKE_HANDLERS),
        db,
        PricingTable.load(),
        budget_usd=Decimal(5),
        max_calls_per_run=12,
    )


async def approved(client, email: str, **review_fields):  # type: ignore[no-untyped-def]
    await submit(client, email)
    lead_id = await lead_id_for(client, email[:3])
    await client.post(f"/internal/leads/{lead_id}/qualify", headers=N8N_AUTH)
    async with client.app.state.engine.begin() as conn:  # the lead.created event is long done
        await conn.execute(
            sa.text(
                "UPDATE outbox_events SET status = 'delivered' WHERE event_type = 'lead.created'"
            )
        )
    action = "edit" if review_fields else "approve"
    assert (await review(client, lead_id, action=action, **review_fields)).status_code == 200
    return lead_id


async def rows(db: AsyncEngine, sql: str, **params: object) -> list[sa.Row[tuple[object, ...]]]:
    async with db.connect() as conn:
        return list((await conn.execute(sa.text(sql), params)).all())


async def deliver_pending(client) -> None:  # type: ignore[no-untyped-def]
    await client.app.state.dispatcher.run_once()


def signed(body: dict[str, object], *, secret: str = SECRET, age: int = 0) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    ts = str(int(time.time()) - age)
    return raw, {
        **N8N_AUTH,
        "Content-Type": "application/json",
        "X-Timestamp": ts,
        "X-Signature": sign(raw, secret, ts),
    }


async def test_inline_approval_sends_the_email_and_marks_the_lead_sent(
    make_client, db, smtp_inbox: SmtpInbox
):
    sender = SmtpSender("127.0.0.1", smtp_inbox.port)
    async with make_client(llm_provider=llm(db), email_sender=sender) as client:
        lead_id = await approved(client, "s1@example.com")
        assert smtp_inbox.messages == []  # nothing is sent before the dispatcher runs
        await deliver_pending(client)
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
    (mail,) = smtp_inbox.messages
    text = mail.content.decode()
    assert mail.rcpt_tos == ["s1@example.com"]
    assert mail.mail_from == "admissions@northwind-academy.example"
    assert "Admissions Team" in text and "Message-ID: <" in text
    assert detail["status"] == "sent" and detail["sent_at"]
    assert detail["messages"][0]["status"] == "sent" and detail["messages"][0]["sent_at"]
    assert "email_sent" in [e["type"] for e in detail["events"]]
    (message,) = await rows(db, "SELECT provider_message_id FROM messages")
    assert message.provider_message_id.startswith("<")


async def test_an_edited_message_is_sent_as_edited(make_client, db, smtp_inbox: SmtpInbox):
    sender = SmtpSender("127.0.0.1", smtp_inbox.port)
    async with make_client(llm_provider=llm(db), email_sender=sender) as client:
        await approved(client, "s2@example.com", subject="Edited subject", body="Edited body.")
        await deliver_pending(client)
    (mail,) = smtp_inbox.messages
    assert "Subject: Edited subject" in mail.content.decode()
    assert "Edited body." in mail.content.decode()


async def test_redelivery_of_the_event_does_not_send_twice(make_client, db, smtp_inbox: SmtpInbox):
    sender = SmtpSender("127.0.0.1", smtp_inbox.port)
    async with make_client(llm_provider=llm(db), email_sender=sender) as client:
        await approved(client, "s3@example.com")
        await deliver_pending(client)
        async with db.begin() as conn:  # the outbox event is delivered again
            await conn.execute(
                sa.text(
                    "UPDATE outbox_events SET status = 'pending', next_attempt_at = now()"
                    " WHERE event_type = 'message.approved'"
                )
            )
        await deliver_pending(client)
        await client.app.state.delivery.deliver(
            uuid.UUID(str((await rows(db, "SELECT id FROM messages"))[0].id))
        )
    assert len(smtp_inbox.messages) == 1
    assert (await rows(db, "SELECT status FROM leads"))[0].status == "sent"


async def test_smtp_failure_makes_the_lead_error_and_it_can_be_retried(make_client, db):
    dead = SmtpSender("127.0.0.1", 1, timeout=1)  # nothing listens here
    async with make_client(llm_provider=llm(db), email_sender=dead) as client:
        lead_id = await approved(client, "s4@example.com")
        await deliver_pending(client)
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
        retried = (await client.post(f"/internal/leads/{lead_id}/qualify", headers=N8N_AUTH)).json()
    assert detail["status"] == "error"
    assert detail["error_reason"] == "send_failed: the message could not be delivered"
    assert detail["messages"][0]["status"] == "failed"
    assert "s4@example.com" not in str(detail["events"]) + detail["error_reason"]
    assert (await rows(db, "SELECT status FROM outbox_events WHERE event_type='message.approved'"))[
        0
    ].status == "delivered"
    assert retried["status"] == "pending_review"  # a new run drafts a new message


async def test_a_channel_without_an_implementation_fails_cleanly(
    make_client, db, smtp_inbox: SmtpInbox
):
    sender = SmtpSender("127.0.0.1", smtp_inbox.port)
    async with make_client(llm_provider=llm(db), email_sender=sender) as client:
        lead_id = await approved(client, "s5@example.com")
        async with db.begin() as conn:
            await conn.execute(sa.text("UPDATE messages SET channel = 'whatsapp'"))
        await deliver_pending(client)
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
    assert smtp_inbox.messages == [] and detail["status"] == "error"


async def test_n8n_fetches_the_message_and_reports_success(make_client, db):
    async with make_client(llm_provider=llm(db), orchestrator="n8n") as client:
        lead_id = await approved(client, "n1@example.com")
        message_id = str((await rows(db, "SELECT id FROM messages"))[0].id)
        url = f"/internal/messages/{message_id}"
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers=AUTH)).status_code == 403
        content = (await client.get(url, headers=N8N_AUTH)).json()
        assert content["channel"] == "email" and content["recipient"] == "n1@example.com"
        assert content["from_address"] == "admissions@northwind-academy.example"
        assert content["subject"] and content["body"] and content["message_id_header"]

        raw, headers = signed({"provider_message_id": "<abc@smtp>"})
        first = await client.post(f"{url}/sent", content=raw, headers=headers)
        again = await client.post(f"{url}/sent", content=raw, headers=headers)
        assert first.json() == {"message_id": message_id, "status": "sent", "changed": True}
        assert again.json()["changed"] is False  # idempotent
        raw, headers = signed({"error": "boom"})
        late = await client.post(f"{url}/send-failed", content=raw, headers=headers)
        assert late.json()["status"] == "sent" and late.json()["changed"] is False
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
        gone = await client.get(url, headers=N8N_AUTH)
    assert detail["status"] == "sent" and gone.status_code == 409  # no longer waiting to be sent
    assert (await rows(db, "SELECT provider_message_id FROM messages"))[0].provider_message_id == (
        "<abc@smtp>"
    )


async def test_n8n_failure_callback_marks_the_lead_error(make_client, db):
    async with make_client(llm_provider=llm(db), orchestrator="n8n") as client:
        lead_id = await approved(client, "n2@example.com")
        message_id = str((await rows(db, "SELECT id FROM messages"))[0].id)
        raw, headers = signed({"error": "smtp down for n2@example.com"})
        response = await client.post(
            f"/internal/messages/{message_id}/send-failed", content=raw, headers=headers
        )
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
    assert response.json()["status"] == "failed"
    assert detail["status"] == "error" and detail["error_reason"].startswith("send_failed")
    assert "smtp down" not in str(detail)


@pytest.mark.parametrize(
    ("kind", "status"),
    [("missing", 401), ("bad_signature", 401), ("stale", 401), ("wrong_secret", 401)],
)
async def test_callbacks_need_a_fresh_valid_signature(make_client, db, kind: str, status: int):
    async with make_client(llm_provider=llm(db), orchestrator="n8n") as client:
        await approved(client, "n3@example.com")
        message_id = str((await rows(db, "SELECT id FROM messages"))[0].id)
        raw, headers = signed({"provider_message_id": "x"})
        if kind == "missing":
            headers = N8N_AUTH | {"Content-Type": "application/json"}
        elif kind == "bad_signature":
            headers["X-Signature"] = "sha256=" + "0" * 64
        elif kind == "stale":
            raw, headers = signed({"provider_message_id": "x"}, age=3600)
        elif kind == "wrong_secret":
            raw, headers = signed({"provider_message_id": "x"}, secret="another-secret-value")
        response = await client.post(
            f"/internal/messages/{message_id}/sent", content=raw, headers=headers
        )
        tampered = await client.post(
            f"/internal/messages/{message_id}/sent",
            content=raw.replace(b"x", b"y"),
            headers=signed({"provider_message_id": "x"})[1],
        )
    assert response.status_code == status and tampered.status_code == 401
    assert (await rows(db, "SELECT status FROM leads"))[0].status == "approved"


async def test_unknown_message_is_404(make_client, db):
    async with make_client(llm_provider=llm(db)) as client:
        raw, headers = signed({"provider_message_id": "x"})
        missing = str(uuid.uuid4())
        assert (
            await client.get(f"/internal/messages/{missing}", headers=N8N_AUTH)
        ).status_code == 404
        sent = await client.post(f"/internal/messages/{missing}/sent", content=raw, headers=headers)
        assert sent.status_code == 404
