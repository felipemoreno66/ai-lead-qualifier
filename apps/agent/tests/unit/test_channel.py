from __future__ import annotations

import pytest

from lead_qualifier.domain.channel import EmailChannel, channel_for
from lead_qualifier.infrastructure.email.smtp import SmtpSender
from lead_qualifier.ports.channel import ChannelMessage, EmailSendError, UnsupportedChannel
from tests.conftest import SmtpInbox


def message(**kw: object) -> ChannelMessage:
    base = {
        "id": "7f9c0e7e-0000-4000-8000-000000000001",
        "channel": "email",
        "recipient": "ana@example.com",
        "subject": "Hello",
        "body": "Body text",
        "short_body": None,
        "language": "en",
    }
    return ChannelMessage(**{**base, **kw})  # type: ignore[arg-type]


def test_email_channel_renders_a_stable_message_id():
    payload = EmailChannel("admissions@northwind-academy.example").render(message())
    assert payload.recipient == "ana@example.com" and payload.subject == "Hello"
    assert payload.message_id == "<7f9c0e7e-0000-4000-8000-000000000001@lead-qualifier.local>"
    assert payload.text == "Body text"


@pytest.mark.parametrize("recipient", ["", "not-an-email", "a@b", "+573001234567"])
def test_email_channel_rejects_bad_recipients(recipient: str):
    with pytest.raises(ValueError, match="valid email"):
        EmailChannel("x@example.com").render(message(recipient=recipient))


def test_email_needs_a_subject_and_other_channels_are_not_built():
    with pytest.raises(ValueError, match="subject"):
        EmailChannel("x@example.com").render(message(subject=None))
    with pytest.raises(UnsupportedChannel):
        channel_for("whatsapp", sender="x@example.com")


async def test_smtp_sender_delivers_through_a_real_smtp_server(smtp_inbox: SmtpInbox):
    payload = EmailChannel("admissions@northwind-academy.example").render(message())
    provider_id = await SmtpSender("127.0.0.1", smtp_inbox.port).send(payload)
    (received,) = smtp_inbox.messages
    assert provider_id == payload.message_id
    assert received.rcpt_tos == ["ana@example.com"]
    text = received.content.decode()
    assert "Subject: Hello" in text and f"Message-ID: {payload.message_id}" in text
    assert "Body text" in text


async def test_smtp_failure_raises_without_leaking_the_address():
    payload = EmailChannel("x@example.com").render(message())
    with pytest.raises(EmailSendError) as exc:
        await SmtpSender("127.0.0.1", 1, timeout=1).send(payload)  # nothing listens on port 1
    assert "ana@example.com" not in str(exc.value)
