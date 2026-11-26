"""The Resend adapter, with every HTTP call mocked (no real send, no network)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import ValidationError

from lead_qualifier.config import Settings
from lead_qualifier.domain.channel import EmailChannel
from lead_qualifier.infrastructure.email import build_email_sender
from lead_qualifier.infrastructure.email.resend import RESEND_URL, ResendSender
from lead_qualifier.infrastructure.email.smtp import SmtpSender
from lead_qualifier.ports.channel import EmailSendError
from tests.unit.test_channel import message

KEY = "re_test_key_that_must_never_leak"


def payload(**kw: object):
    return EmailChannel("David <hello@mail.example.com>", **kw).render(message())  # type: ignore[arg-type]


@respx.mock
async def test_posts_the_message_with_auth_and_an_idempotency_key():
    route = respx.post(RESEND_URL).mock(return_value=httpx.Response(200, json={"id": "re-123"}))
    sent = await ResendSender(KEY).send(payload(reply_to="david@example.com"))
    assert sent == "re-123"
    request = route.calls.last.request
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert (
        request.headers["idempotency-key"]
        == "7f9c0e7e-0000-4000-8000-000000000001@lead-qualifier.local"
    )
    body = json.loads(request.content)
    assert body == {
        "from": "David <hello@mail.example.com>",
        "to": ["ana@example.com"],
        "subject": "Hello",
        "text": "Body text",
        "reply_to": "david@example.com",
    }


@respx.mock
@pytest.mark.parametrize(
    ("status", "name", "transient"),
    [
        (429, "rate_limit_exceeded", True),
        (500, "internal_server_error", True),
        (503, None, True),
        (409, "concurrent_idempotent_requests", True),
        (409, "invalid_idempotent_request", False),
        (400, "invalid_idempotency_key", False),
        (401, "restricted_api_key", False),
        (403, "validation_error", False),
        (422, "invalid_from_address", False),
    ],
)
async def test_classifies_failures_as_transient_or_permanent(status, name, transient):
    body = {"name": name, "message": "ana@example.com is not allowed"} if name else "<html>"
    respx.post(RESEND_URL).mock(return_value=httpx.Response(status, json=body))
    with pytest.raises(EmailSendError) as exc:
        await ResendSender(KEY).send(payload())
    assert exc.value.transient is transient
    assert str(exc.value).startswith(f"Resend {status}")
    assert "ana@example.com" not in str(exc.value) and KEY not in str(exc.value)


@respx.mock
@pytest.mark.parametrize(
    "error", [httpx.ConnectTimeout("t"), httpx.ConnectError("c"), httpx.ReadError("r")]
)
async def test_network_failures_are_transient_and_leak_nothing(error):
    respx.post(RESEND_URL).mock(side_effect=error)
    with pytest.raises(EmailSendError) as exc:
        await ResendSender(KEY).send(payload())
    assert exc.value.transient is True
    assert KEY not in str(exc.value) and "api.resend.com" not in str(exc.value)


@respx.mock
async def test_a_success_without_an_id_is_a_permanent_error():
    respx.post(RESEND_URL).mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(EmailSendError) as exc:
        await ResendSender(KEY).send(payload())
    assert exc.value.transient is False


def test_the_key_is_required_and_not_printed():
    with pytest.raises(ValueError):
        ResendSender("")
    assert KEY not in repr(
        Settings(email_provider="resend", resend_api_key=KEY, email_from="a@b.co")
    )


def test_settings_pick_the_provider_and_require_its_inputs():
    assert isinstance(build_email_sender(Settings()), SmtpSender)
    ok = Settings(email_provider="resend", resend_api_key=KEY, email_from="hello@mail.example.com")
    assert isinstance(build_email_sender(ok), ResendSender)
    with pytest.raises(ValidationError, match="RESEND_API_KEY"):
        Settings(email_provider="resend", email_from="hello@mail.example.com")
    with pytest.raises(ValidationError, match="EMAIL_FROM"):
        Settings(email_provider="resend", resend_api_key=KEY)
    with pytest.raises(ValidationError):
        Settings(email_provider="sendgrid")  # type: ignore[arg-type]


@respx.mock
async def test_address_fields_cannot_carry_line_breaks():
    route = respx.post(RESEND_URL).mock(return_value=httpx.Response(200, json={"id": "re-1"}))
    bad = EmailChannel("a@b.co\r\nBcc: x@y.co", reply_to="r@b.co\nBcc: z@y.co").render(message())
    await ResendSender(KEY).send(bad)
    body = json.loads(route.calls.last.request.content)
    assert "\n" not in body["from"] and "\r" not in body["from"]
    assert "\n" not in body["reply_to"] and "\r" not in body["reply_to"]
