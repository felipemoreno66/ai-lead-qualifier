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


def signed(
    path: str, body: dict[str, object], *, secret: str = SECRET, age: int = 0
) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    ts = str(int(time.time()) - age)
    return raw, {
        **N8N_AUTH,
        "Content-Type": "application/json",
        "X-Timestamp": ts,
        "X-Signature": sign(raw, secret, ts, method="POST", path=path),
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


async def test_smtp_failure_makes_the_lead_error_and_it_can_be_retried(
    make_client, db, smtp_inbox: SmtpInbox
):
    smtp_inbox.replies = ["550 5.1.1 no such mailbox"]  # a permanent rejection fails at once
    sender = SmtpSender("127.0.0.1", smtp_inbox.port)
    async with make_client(llm_provider=llm(db), email_sender=sender) as client:
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
        assert (await client.post(f"{url}/claim")).status_code == 401
        assert (await client.post(f"{url}/claim", headers=AUTH)).status_code == 403
        content = (await client.post(f"{url}/claim", headers=N8N_AUTH)).json()
        assert content["deliverable"] is True and content["status"] == "sending"
        again = (await client.post(f"{url}/claim", headers=N8N_AUTH)).json()
        assert (
            again["deliverable"] is False and again["status"] == "sending"
        )  # not handed out twice
        assert content["channel"] == "email" and content["recipient"] == "n1@example.com"
        assert content["from_address"] == "admissions@northwind-academy.example"
        assert content["subject"] and content["body"] and content["message_id_header"]

        raw, headers = signed(
            f"{url}/sent", {"message_id": message_id, "provider_message_id": "<abc@smtp>"}
        )
        first = await client.post(f"{url}/sent", content=raw, headers=headers)
        again = await client.post(f"{url}/sent", content=raw, headers=headers)
        assert first.json() == {"message_id": message_id, "status": "sent", "changed": True}
        assert again.json()["changed"] is False  # idempotent
        raw, headers = signed(f"{url}/send-failed", {"message_id": message_id, "error": "boom"})
        late = await client.post(f"{url}/send-failed", content=raw, headers=headers)
        assert late.json()["status"] == "sent" and late.json()["changed"] is False
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
        gone = await client.post(f"{url}/claim", headers=N8N_AUTH)
    assert detail["status"] == "sent"
    assert gone.json()["deliverable"] is False and gone.json()["status"] == "sent"
    assert (await rows(db, "SELECT provider_message_id FROM messages"))[0].provider_message_id == (
        "<abc@smtp>"
    )


async def test_n8n_failure_callback_marks_the_lead_error(make_client, db):
    async with make_client(llm_provider=llm(db), orchestrator="n8n") as client:
        lead_id = await approved(client, "n2@example.com")
        message_id = str((await rows(db, "SELECT id FROM messages"))[0].id)
        path = f"/internal/messages/{message_id}/send-failed"
        raw, headers = signed(
            path, {"message_id": message_id, "error": "smtp down for n2@example.com"}
        )
        response = await client.post(
            f"/internal/messages/{message_id}/send-failed", content=raw, headers=headers
        )
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
    assert response.json()["status"] == "failed"
    assert detail["status"] == "error" and detail["error_reason"].startswith("send_failed")
    assert "smtp down" not in str(detail)


@pytest.mark.parametrize("kind", ["missing", "bad_signature", "stale", "wrong_secret"])
async def test_callbacks_need_a_fresh_valid_signature(make_client, db, kind: str):
    async with make_client(llm_provider=llm(db), orchestrator="n8n") as client:
        await approved(client, "n3@example.com")
        message_id = str((await rows(db, "SELECT id FROM messages"))[0].id)
        path = f"/internal/messages/{message_id}/sent"
        body = {"message_id": message_id, "provider_message_id": "x"}
        raw, headers = signed(path, body)
        if kind == "missing":
            headers = N8N_AUTH | {"Content-Type": "application/json"}
        elif kind == "bad_signature":
            headers["X-Signature"] = "sha256=" + "0" * 64
        elif kind == "stale":
            raw, headers = signed(path, body, age=3600)
        elif kind == "wrong_secret":
            raw, headers = signed(path, body, secret="another-secret-value")
        response = await client.post(path, content=raw, headers=headers)
        tampered = await client.post(
            path, content=raw.replace(b'"x"', b'"y"'), headers=signed(path, body)[1]
        )
    assert response.status_code == 401 and tampered.status_code == 401
    assert (await rows(db, "SELECT status FROM leads"))[0].status == "approved"


async def test_a_signed_callback_cannot_be_replayed_elsewhere(make_client, db):
    async with make_client(llm_provider=llm(db), orchestrator="n8n") as client:
        await approved(client, "n4@example.com")
        await approved(client, "n5@example.com")
        first, second = [
            str(r.id) for r in await rows(db, "SELECT id FROM messages ORDER BY version, id")
        ]
        sent_path = f"/internal/messages/{first}/sent"
        raw, headers = signed(sent_path, {"message_id": first, "provider_message_id": "x"})
        # same signature against the failure endpoint of the same message
        other_endpoint = await client.post(
            f"/internal/messages/{first}/send-failed", content=raw, headers=headers
        )
        # same signature against another message's endpoint
        other_message = await client.post(
            f"/internal/messages/{second}/sent", content=raw, headers=headers
        )
        statuses = [r.status for r in await rows(db, "SELECT status FROM leads")]
    assert other_endpoint.status_code == 401 and other_message.status_code == 401
    assert statuses == ["approved", "approved"]


async def test_the_body_must_name_the_message_in_the_path(make_client, db):
    async with make_client(llm_provider=llm(db), orchestrator="n8n") as client:
        await approved(client, "n6@example.com")
        message_id = str((await rows(db, "SELECT id FROM messages"))[0].id)
        path = f"/internal/messages/{message_id}/sent"
        raw, headers = signed(path, {"message_id": str(uuid.uuid4()), "provider_message_id": "x"})
        mismatch = await client.post(path, content=raw, headers=headers)
        raw, headers = signed(path, {"provider_message_id": "x"})
        missing = await client.post(path, content=raw, headers=headers)
    assert mismatch.status_code == 400 and missing.status_code == 422


async def test_the_claim_serves_only_the_validated_payload(make_client, db):
    async with make_client(llm_provider=llm(db), orchestrator="n8n") as client:
        await approved(client, "n7@example.com")
        message_id = str((await rows(db, "SELECT id FROM messages"))[0].id)
        url = f"/internal/messages/{message_id}/claim"
        async with db.begin() as conn:
            await conn.execute(sa.text("UPDATE messages SET channel_recipient = 'not an email'"))
        invalid = await client.post(url, headers=N8N_AUTH)
        async with db.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE messages SET channel_recipient = 'ok@example.com', channel = 'whatsapp'"
                )
            )
        unsupported = await client.post(url, headers=N8N_AUTH)
        async with db.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE messages SET channel = 'email',"
                    " subject = E'Hi\\r\\nBcc: boss@evil.test\\u200b'"
                )
            )
        content = (await client.post(url, headers=N8N_AUTH)).json()
    assert invalid.status_code == 422 and unsupported.status_code == 422
    assert "not an email" not in invalid.text
    assert content["deliverable"] is True and content["recipient"] == "ok@example.com"
    assert not any(c in content["subject"] for c in "\r\n\u200b")  # served from the payload
    # the failed validations claimed nothing: only the valid attempt moved it to sending
    assert (await rows(db, "SELECT status FROM messages"))[0].status == "sending"


async def test_unknown_message_is_404(make_client, db):
    async with make_client(llm_provider=llm(db)) as client:
        missing = str(uuid.uuid4())
        raw, headers = signed(
            f"/internal/messages/{missing}/sent",
            {"message_id": missing, "provider_message_id": "x"},
        )
        assert (
            await client.get(f"/internal/messages/{missing}", headers=N8N_AUTH)
        ).status_code == 404
        sent = await client.post(f"/internal/messages/{missing}/sent", content=raw, headers=headers)
        assert sent.status_code == 404


async def test_concurrent_deliveries_send_once(make_client, db, smtp_inbox: SmtpInbox):
    import asyncio

    sender = SmtpSender("127.0.0.1", smtp_inbox.port)
    async with make_client(llm_provider=llm(db), email_sender=sender) as client:
        await approved(client, "d1@example.com")
        message_id = uuid.UUID(str((await rows(db, "SELECT id FROM messages"))[0].id))
        results = await asyncio.gather(
            *[client.app.state.delivery.deliver(message_id) for _ in range(4)]
        )
    assert len(smtp_inbox.messages) == 1
    assert sorted(r.changed for r in results) == [False, False, False, True]
    assert (await rows(db, "SELECT status FROM messages"))[0].status == "sent"


async def test_a_claimed_message_is_not_sent_again_and_stale_claims_are_only_reported(
    make_client, db, smtp_inbox: SmtpInbox
):
    from datetime import timedelta

    from lead_qualifier.ports.clock import SystemClock
    from lead_qualifier.services.reaper import report_stale_sending

    sender = SmtpSender("127.0.0.1", smtp_inbox.port)
    async with make_client(llm_provider=llm(db), email_sender=sender) as client:
        await approved(client, "d2@example.com")
        message_id = uuid.UUID(str((await rows(db, "SELECT id FROM messages"))[0].id))
        await client.post(f"/internal/messages/{message_id}/claim", headers=N8N_AUTH)  # n8n took it
        await deliver_pending(client)  # the inline event is delivered meanwhile: no second send
        assert smtp_inbox.messages == []
        assert await report_stale_sending(db, SystemClock(), timedelta(minutes=15)) == 0
        async with db.begin() as conn:
            await conn.execute(
                sa.text("UPDATE messages SET send_started_at = now() - interval '1 hour'")
            )
        assert await report_stale_sending(db, SystemClock(), timedelta(minutes=15)) == 1
        await client.app.state.delivery.deliver(message_id)  # still not resent automatically
    assert smtp_inbox.messages == []
    assert (await rows(db, "SELECT status FROM messages"))[0].status == "sending"


async def test_a_late_sent_report_after_send_failed_wins(make_client, db):
    async with make_client(llm_provider=llm(db), orchestrator="n8n") as client:
        lead_id = await approved(client, "d3@example.com")
        message_id = uuid.UUID(str((await rows(db, "SELECT id FROM messages"))[0].id))
        delivery = client.app.state.delivery
        await delivery.mark_send_failed(message_id, "timeout")
        assert (await rows(db, "SELECT status FROM leads"))[0].status == "error"
        result = await delivery.mark_sent(message_id, "<late@smtp>")
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
        again = await delivery.mark_sent(message_id, "<late@smtp>")
    assert (result.status, result.changed, again.changed) == ("sent", True, False)
    assert detail["status"] == "sent" and detail["error_reason"] is None
    event = next(e for e in detail["events"] if e["type"] == "email_sent")
    assert event["payload"]["late_report"] is True and event["to_status"] == "sent"


async def test_a_late_sent_report_leaves_a_lead_that_moved_on_alone(make_client, db):
    async with make_client(llm_provider=llm(db), orchestrator="n8n") as client:
        await approved(client, "d4@example.com")
        message_id = uuid.UUID(str((await rows(db, "SELECT id FROM messages"))[0].id))
        delivery = client.app.state.delivery
        await delivery.mark_send_failed(message_id, "timeout")
        async with db.begin() as conn:  # an operator already retried the lead
            await conn.execute(
                sa.text("UPDATE leads SET status = 'qualifying', error_reason = NULL")
            )
        await delivery.mark_sent(message_id, "<late@smtp>")
    assert (await rows(db, "SELECT status FROM leads"))[0].status == "qualifying"
    assert (await rows(db, "SELECT status FROM messages"))[0].status == "sent"


async def test_transient_smtp_failures_retry_then_fail_and_permanent_ones_fail_at_once(
    make_client, db, smtp_inbox: SmtpInbox
):
    from lead_qualifier.ports.events import PublishError

    sender = SmtpSender("127.0.0.1", smtp_inbox.port)
    async with make_client(llm_provider=llm(db), email_sender=sender) as client:
        await approved(client, "t1@example.com")
        message_id = uuid.UUID(str((await rows(db, "SELECT id FROM messages"))[0].id))
        delivery = client.app.state.delivery
        smtp_inbox.replies = ["451 4.3.0 try again later"] * 3
        for attempt in (1, 2):
            with pytest.raises(PublishError):
                await delivery.deliver(message_id)  # the outbox would retry this event
            row = (await rows(db, "SELECT status, send_attempts FROM messages"))[0]
            assert (row.status, row.send_attempts) == ("approved", attempt)
        failed = await delivery.deliver(message_id)  # third transient failure: give up
        assert failed.status == "failed" and smtp_inbox.messages == []
        assert (await rows(db, "SELECT status FROM leads"))[0].status == "error"


async def test_a_transient_failure_that_recovers_sends_on_the_retry(
    make_client, db, smtp_inbox: SmtpInbox
):
    from lead_qualifier.ports.events import PublishError

    sender = SmtpSender("127.0.0.1", smtp_inbox.port)
    async with make_client(llm_provider=llm(db), email_sender=sender) as client:
        await approved(client, "t2@example.com")
        message_id = uuid.UUID(str((await rows(db, "SELECT id FROM messages"))[0].id))
        smtp_inbox.replies = ["421 4.7.0 busy"]
        with pytest.raises(PublishError):
            await client.app.state.delivery.deliver(message_id)
        result = await client.app.state.delivery.deliver(message_id)
    assert result.status == "sent" and len(smtp_inbox.messages) == 1


async def test_a_permanent_smtp_rejection_fails_immediately(make_client, db, smtp_inbox: SmtpInbox):
    sender = SmtpSender("127.0.0.1", smtp_inbox.port)
    async with make_client(llm_provider=llm(db), email_sender=sender) as client:
        await approved(client, "t3@example.com")
        message_id = uuid.UUID(str((await rows(db, "SELECT id FROM messages"))[0].id))
        smtp_inbox.replies = ["550 5.1.1 no such mailbox"]
        result = await client.app.state.delivery.deliver(message_id)
    assert result.status == "failed"
    assert (await rows(db, "SELECT send_attempts FROM messages"))[0].send_attempts == 0


async def test_the_dispatcher_keeps_the_event_pending_while_smtp_is_flaky(
    make_client, db, smtp_inbox: SmtpInbox
):
    sender = SmtpSender("127.0.0.1", smtp_inbox.port)
    async with make_client(llm_provider=llm(db), email_sender=sender) as client:
        await approved(client, "t4@example.com")
        smtp_inbox.replies = ["451 4.3.0 later"]
        await deliver_pending(client)
        event = (
            await rows(
                db,
                "SELECT status, attempts FROM outbox_events WHERE event_type = 'message.approved'",
            )
        )[0]
        assert (event.status, event.attempts) == (
            "pending",
            1,
        )  # not delivered, retried with backoff
        async with db.begin() as conn:
            await conn.execute(sa.text("UPDATE outbox_events SET next_attempt_at = now()"))
        await deliver_pending(client)
    assert len(smtp_inbox.messages) == 1
    assert (await rows(db, "SELECT status FROM leads"))[0].status == "sent"


def test_smtp_credentials_are_never_sent_in_clear_text():
    from lead_qualifier.config import Settings

    with pytest.raises(ValueError, match="STARTTLS or SSL"):
        SmtpSender("smtp.example.com", 587, username="u", password="p")
    SmtpSender("smtp.example.com", 587, username="u", password="p", starttls=True)
    SmtpSender("smtp.example.com", 465, username="u", password="p", use_ssl=True)
    SmtpSender("localhost", 1025)  # Mailpit: no credentials, no TLS
    with pytest.raises(ValueError, match="SMTP_USERNAME"):
        Settings(app_env="production", smtp_username="u", **_PROD)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="SMTP_USERNAME"):
        Settings(app_env="test", smtp_username="u")
    assert Settings(app_env="test", smtp_username="u", smtp_starttls=True).smtp_starttls


_PROD = {
    "admin_api_token": "a" * 20,
    "n8n_api_token": "b" * 20,
    "n8n_webhook_secret": "c" * 20,
    "ip_hash_secret": "d" * 20,
}


async def test_sent_mail_has_a_date_and_no_invisible_text(smtp_inbox: SmtpInbox):
    from lead_qualifier.domain.channel import EmailChannel
    from lead_qualifier.ports.channel import ChannelMessage

    payload = EmailChannel("admissions@northwind-academy.example").render(
        ChannelMessage(
            id="m-1",
            channel="email",
            recipient="ana@example.com",
            subject="Hi​ there",
            body="Visit us‮ now​\nsecond line",
            short_body=None,
            language="en",
        )
    )
    await SmtpSender("127.0.0.1", smtp_inbox.port).send(payload)
    text = smtp_inbox.messages[0].content.decode()
    assert "Date: " in text and "Subject: Hi there" in text
    assert "​" not in text and "‮" not in text and "second line" in text


@pytest.mark.parametrize(
    "recipient", ["ana@example.com\n", "ana@example.com\nBcc: x@evil.test", "A <ana@example.com>"]
)
def test_recipients_must_match_exactly(recipient: str):
    from lead_qualifier.domain.channel import EmailChannel

    with pytest.raises(ValueError, match="valid email"):
        EmailChannel("x@example.com").validate_recipient(recipient)


async def test_a_non_ascii_digit_timestamp_is_a_401_not_a_500(make_client, db):
    async with make_client(llm_provider=llm(db), orchestrator="n8n") as client:
        await approved(client, "ts@example.com")
        message_id = str((await rows(db, "SELECT id FROM messages"))[0].id)
        path = f"/internal/messages/{message_id}/sent"
        raw, headers = signed(path, {"message_id": message_id})
        raw_headers = [
            (k.lower().encode(), ("\u00b2\u00b3" if k == "X-Timestamp" else v).encode("latin-1"))
            for k, v in headers.items()  # superscripts: str.isdigit() is true, int() fails
        ]
        response = await client.post(path, content=raw, headers=raw_headers)
    assert response.status_code == 401
