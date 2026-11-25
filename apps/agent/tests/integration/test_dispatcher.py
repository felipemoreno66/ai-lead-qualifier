from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.infrastructure.db.repositories import LeadRepository, OutboxRepository
from lead_qualifier.infrastructure.outbox.dispatcher import OutboxDispatcher
from lead_qualifier.infrastructure.outbox.publishers import (
    InlinePublisher,
    N8nPublisher,
    sign,
)
from lead_qualifier.ports.events import PublishError
from tests.helpers import FakeClock

pytestmark = pytest.mark.integration
WEBHOOK = "http://n8n.test:5678/webhook/lead-created"
SECRET = "unit-test-secret-123456"


async def create_lead_with_event(db: AsyncEngine, clock: FakeClock, n: int = 1):
    async with db.begin() as conn:
        leads, outbox = LeadRepository(conn), OutboxRepository(conn)
        lead_id = await leads.insert(
            {
                "reference": f"NW-D{n:04d}",
                "workspace_slug": "northwind-academy",
                "name": "Ana",
                "email": f"a{n}@example.com",
                "source": "hosted_form",
                "ip_hash": "h",
                "consent_at": clock.now(),
                "consent_notice_version": "2026-11-01",
            }
        )
        event_id = await outbox.enqueue(
            event_type="lead.created",
            aggregate_id=lead_id,
            lead_id=lead_id,
            payload={
                "lead": {
                    "id": str(lead_id),
                    "workspace": "northwind-academy",
                    "reference": f"NW-D{n:04d}",
                }
            },
            idempotency_key=f"lead:{lead_id}:created:1",
            now=clock.now(),
        )
    return lead_id, event_id


def make_dispatcher(db, make_settings, clock, publisher, **overrides):
    return OutboxDispatcher(db, publisher, clock, make_settings(**overrides))


async def event_row(db: AsyncEngine, event_id) -> dict[str, Any]:
    async with db.connect() as conn:
        row = await OutboxRepository(conn).get(event_id)
    assert row
    return row


async def lead_event_types(db: AsyncEngine, lead_id) -> list[str]:
    async with db.connect() as conn:
        return [e["type"] for e in await LeadRepository(conn).events(lead_id)]


def n8n(client: httpx.AsyncClient | None = None) -> N8nPublisher:
    return N8nPublisher("http://n8n.test:5678", SECRET, client=client)


def test_signature_covers_the_timestamp():
    body = b"{}"
    assert sign(body, "s", "100") != sign(body, "s", "101")
    assert sign(body, "s", "100") != sign(body, "s")


def test_signature_is_hmac_sha256_over_the_raw_body():
    body = b'{"a":1}'
    assert sign(body, "s") == sign(body, "s")
    assert sign(body, "s").startswith("sha256=") and len(sign(body, "s")) == 7 + 64
    assert sign(body, "s") != sign(body, "t")
    assert sign(b'{"a":2}', "s") != sign(body, "s")


@respx.mock
async def test_success_marks_delivered_signs_the_body_and_sends_no_pii(db, make_settings):
    clock = FakeClock()
    lead_id, event_id = await create_lead_with_event(db, clock)
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(200, json={"ok": True}))

    handled = await make_dispatcher(db, make_settings, clock, n8n()).run_once()

    assert handled == 1 and route.call_count == 1
    request = route.calls.last.request
    assert request.headers["x-signature"] == sign(
        request.content,
        SECRET,
        request.headers["x-timestamp"],
        method="POST",
        path="/webhook/lead-created",
    )
    assert abs(int(request.headers["x-timestamp"]) - time.time()) < 60
    assert request.headers["x-event-id"] == str(event_id)
    sent = json.loads(request.content)
    assert sent["event_type"] == "lead.created"
    assert sent["event_id"] == str(event_id)
    assert sent["lead"]["workspace"] == "northwind-academy"
    assert "email" not in request.content.decode() and "Ana" not in request.content.decode()
    row = await event_row(db, event_id)
    assert row["status"] == "delivered" and row["delivered_at"] is not None
    assert await lead_event_types(db, lead_id) == ["outbox_delivered"]
    assert await make_dispatcher(db, make_settings, clock, n8n()).run_once() == 0


@respx.mock
async def test_server_error_backs_off_and_lead_stays_new(db, make_settings):
    clock = FakeClock()
    lead_id, event_id = await create_lead_with_event(db, clock)
    respx.post(WEBHOOK).mock(return_value=httpx.Response(503))
    dispatcher = make_dispatcher(db, make_settings, clock, n8n())

    delays = []
    for _ in range(3):
        assert await dispatcher.run_once() == 1
        row = await event_row(db, event_id)
        delays.append(int((row["next_attempt_at"] - clock.now()).total_seconds()))
        assert row["status"] == "pending" and "503" in row["last_error"]
        assert await dispatcher.run_once() == 0  # not due yet
        clock.advance(seconds=delays[-1])

    assert delays == [5, 30, 120]
    async with db.connect() as conn:
        lead = await LeadRepository(conn).get(lead_id)
    assert lead and lead["status"] == "new"
    assert await lead_event_types(db, lead_id) == ["outbox_failed"] * 3


@respx.mock
@pytest.mark.parametrize("status", [403, 404])
async def test_rejection_by_n8n_is_permanent_and_not_retried(db, make_settings, status):
    clock = FakeClock()
    lead_id, event_id = await create_lead_with_event(db, clock)
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(status))
    dispatcher = make_dispatcher(db, make_settings, clock, n8n())
    await dispatcher.run_once()
    clock.advance(hours=3)
    assert await dispatcher.run_once() == 0
    row = await event_row(db, event_id)
    assert row["status"] == "dead" and row["attempts"] == 1
    assert f"HTTP {status}" in row["last_error"]
    assert route.call_count == 1
    async with db.connect() as conn:
        last = (await LeadRepository(conn).events(lead_id))[-1]
    assert last["payload"]["dead"] is True


@respx.mock
async def test_401_is_retried_then_dead_lettered_with_a_clear_reason(db, make_settings):
    clock = FakeClock()
    _, event_id = await create_lead_with_event(db, clock)
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(401))
    dispatcher = make_dispatcher(db, make_settings, clock, n8n())
    for _ in range(2):
        await dispatcher.run_once()
        assert (await event_row(db, event_id))["status"] == "pending"
        clock.advance(hours=1)
    await dispatcher.run_once()
    row = await event_row(db, event_id)
    assert row["status"] == "dead" and row["attempts"] == 3 and route.call_count == 3
    assert "HTTP 401" in row["last_error"] and "NTP" in row["last_error"]


@respx.mock
async def test_401_that_clears_up_is_delivered(db, make_settings):
    clock = FakeClock()
    _, event_id = await create_lead_with_event(db, clock)
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(401))
    dispatcher = make_dispatcher(db, make_settings, clock, n8n())
    await dispatcher.run_once()
    route.mock(return_value=httpx.Response(200))
    clock.advance(seconds=5)
    await dispatcher.run_once()
    assert (await event_row(db, event_id))["status"] == "delivered"


@respx.mock
async def test_timeout_and_connection_errors_are_retried(db, make_settings):
    clock = FakeClock()
    _, event_id = await create_lead_with_event(db, clock)
    route = respx.post(WEBHOOK).mock(side_effect=httpx.ConnectTimeout("slow"))
    dispatcher = make_dispatcher(db, make_settings, clock, n8n())
    await dispatcher.run_once()
    row = await event_row(db, event_id)
    assert row["status"] == "pending" and "ConnectTimeout" in row["last_error"]
    clock.advance(seconds=5)
    route.mock(side_effect=None, return_value=httpx.Response(200))
    await dispatcher.run_once()
    assert (await event_row(db, event_id))["status"] == "delivered"


@respx.mock
async def test_recovers_when_n8n_comes_back(db, make_settings):
    clock = FakeClock()
    lead_id, event_id = await create_lead_with_event(db, clock)
    route = respx.post(WEBHOOK).mock(side_effect=httpx.ConnectError("down"))
    dispatcher = make_dispatcher(db, make_settings, clock, n8n())
    await dispatcher.run_once()
    route.mock(side_effect=None, return_value=httpx.Response(200))
    clock.advance(seconds=5)
    await dispatcher.run_once()
    assert (await event_row(db, event_id))["status"] == "delivered"
    assert await lead_event_types(db, lead_id) == ["outbox_failed", "outbox_delivered"]


@respx.mock
async def test_event_becomes_dead_after_max_attempts(db, make_settings):
    clock = FakeClock()
    lead_id, event_id = await create_lead_with_event(db, clock)
    respx.post(WEBHOOK).mock(return_value=httpx.Response(500))
    dispatcher = make_dispatcher(db, make_settings, clock, n8n(), outbox_max_attempts=3)
    for _ in range(3):
        await dispatcher.run_once()
        clock.advance(hours=1)
    row = await event_row(db, event_id)
    assert row["status"] == "dead" and row["attempts"] == 3
    assert await dispatcher.run_once() == 0
    types = await lead_event_types(db, lead_id)
    assert types == ["outbox_failed"] * 3
    async with db.connect() as conn:
        last = (await LeadRepository(conn).events(lead_id))[-1]
    assert last["payload"]["dead"] is True


async def test_inline_mode_marks_delivered_without_any_http_call(db, make_settings):
    clock = FakeClock()
    lead_id, event_id = await create_lead_with_event(db, clock)
    with respx.mock(assert_all_called=False) as router:
        await make_dispatcher(db, make_settings, clock, InlinePublisher()).run_once()
        assert router.calls.call_count == 0
    assert (await event_row(db, event_id))["status"] == "delivered"
    assert await lead_event_types(db, lead_id) == ["outbox_delivered"]


async def test_unexpected_publisher_errors_do_not_crash_the_dispatcher(db, make_settings):
    class Broken:
        async def publish(self, event: dict[str, Any]) -> None:
            raise RuntimeError("bug in publisher")

    clock = FakeClock()
    _, event_id = await create_lead_with_event(db, clock)
    await make_dispatcher(db, make_settings, clock, Broken()).run_once()
    assert "RuntimeError" in (await event_row(db, event_id))["last_error"]


async def test_two_concurrent_dispatchers_deliver_each_event_once(db, make_settings):
    clock = FakeClock()
    for n in range(1, 7):
        await create_lead_with_event(db, clock, n)
    delivered: list[str] = []

    class Slow:
        async def publish(self, event: dict[str, Any]) -> None:
            await asyncio.sleep(0.05)
            delivered.append(event["event_id"])

    d1 = make_dispatcher(db, make_settings, clock, Slow(), outbox_batch_size=3)
    d2 = make_dispatcher(db, make_settings, clock, Slow(), outbox_batch_size=3)
    await asyncio.gather(d1.run_once(), d2.run_once())
    await asyncio.gather(d1.run_once(), d2.run_once())
    assert len(delivered) == 6 and len(set(delivered)) == 6


async def test_crashed_dispatcher_lock_expires_and_event_is_retried(db, make_settings):
    clock = FakeClock()
    _, event_id = await create_lead_with_event(db, clock)
    async with db.begin() as conn:
        await OutboxRepository(conn).claim_due(clock.now(), 10, 60)  # claimed, never finished
    delivered = []

    class Ok:
        async def publish(self, event: dict[str, Any]) -> None:
            delivered.append(event["event_id"])

    dispatcher = make_dispatcher(db, make_settings, clock, Ok())
    assert await dispatcher.run_once() == 0
    clock.advance(seconds=61)
    assert await dispatcher.run_once() == 1
    assert delivered == [str(event_id)]


async def test_old_rate_limit_windows_are_purged(db, make_settings):
    clock = FakeClock()
    async with db.begin() as conn:
        await conn.execute(
            text("INSERT INTO rate_limit_hits (key, window_start, count) VALUES ('old', :t, 1)"),
            {"t": clock.now() - timedelta(days=3)},
        )
    dispatcher = make_dispatcher(db, make_settings, clock, InlinePublisher())
    clock.advance(hours=2)
    await dispatcher.purge_rate_limits()
    async with db.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM rate_limit_hits"))).scalar_one() == 0


async def test_unknown_event_type_is_a_publish_error():
    with pytest.raises(PublishError):
        await n8n().publish({"event_type": "nope", "event_id": "x"})


@respx.mock
async def test_message_approved_goes_to_its_own_webhook_with_ids_only(db, make_settings):
    clock = FakeClock()
    lead_id, _ = await create_lead_with_event(db, clock, n=7)
    message_id = uuid.uuid4()
    async with db.begin() as conn:
        await conn.execute(text("UPDATE outbox_events SET status = 'delivered'"))
        await OutboxRepository(conn).enqueue(
            event_type="message.approved",
            aggregate_id=message_id,
            lead_id=lead_id,
            payload={
                "lead": {
                    "id": str(lead_id),
                    "workspace": "northwind-academy",
                    "reference": "NW-D0007",
                },
                "message": {"id": str(message_id), "channel": "email", "version": 1},
            },
            idempotency_key=f"message:{message_id}:send",
            now=clock.now(),
        )
    route = respx.post("http://n8n.test:5678/webhook/message-approved").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert await make_dispatcher(db, make_settings, clock, n8n()).run_once() == 1
    request = route.calls.last.request
    sent = json.loads(request.content)
    assert sent["event_type"] == "message.approved" and sent["message"]["channel"] == "email"
    assert request.headers["x-signature"] == sign(
        request.content,
        SECRET,
        request.headers["x-timestamp"],
        method="POST",
        path="/webhook/message-approved",
    )
    assert "a7@example.com" not in request.content.decode()
