"""Event publishers: a signed webhook to n8n, or an in-process no-op for inline mode."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from lead_qualifier.domain.errors import Conflict, NotFound
from lead_qualifier.logging import get_logger
from lead_qualifier.ports.events import PermanentPublishError, PublishError

log = get_logger("publisher")

WEBHOOK_PATHS = {"lead.created": "lead-created", "message.approved": "message-approved"}


PERMANENT_STATUSES = frozenset({400, 401, 403, 404, 410, 422})


def sign(body: bytes, secret: str, timestamp: str = "") -> str:
    """HMAC-SHA256 over ``"<timestamp>."`` + raw body (just the body when no timestamp)."""
    payload = f"{timestamp}.".encode() + body if timestamp else body
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class N8nPublisher:
    """POSTs the event to an n8n webhook, signed with HMAC-SHA256 over the raw body."""

    def __init__(
        self,
        base_url: str,
        secret: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.client = client or httpx.AsyncClient(timeout=timeout)

    async def publish(self, event: dict[str, Any]) -> None:
        path = WEBHOOK_PATHS.get(event["event_type"])
        if path is None:
            raise PublishError(f"no webhook for event type {event['event_type']!r}")
        body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
        timestamp = str(int(time.time()))
        try:
            response = await self.client.post(
                f"{self.base_url}/webhook/{path}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Event-ID": event["event_id"],
                    "X-Timestamp": timestamp,
                    "X-Signature": sign(body, self.secret, timestamp),
                },
            )
        except httpx.HTTPError as exc:
            raise PublishError(f"{type(exc).__name__}: {exc}"[:300]) from exc
        if response.status_code in PERMANENT_STATUSES:
            # Retrying cannot help (for example a wrong shared secret): fail fast and visibly.
            raise PermanentPublishError(f"n8n rejected the event with HTTP {response.status_code}")
        if response.status_code >= 300:
            raise PublishError(f"n8n answered HTTP {response.status_code}")

    async def aclose(self) -> None:
        await self.client.aclose()


class InlinePublisher:
    """Inline orchestration: ``lead.created`` runs the qualification graph in-process and
    ``message.approved`` sends the email in-process.

    A lead that is no longer qualifiable (already processed, or deleted) is not an error: the
    event is simply done, which keeps redelivery idempotent. A failed graph run is recorded on the
    lead (``error``, retryable) and does not fail the event.
    """

    def __init__(
        self,
        qualify: Callable[[uuid.UUID], Awaitable[object]] | None = None,
        deliver: Callable[[uuid.UUID], Awaitable[object]] | None = None,
    ) -> None:
        self._qualify = qualify
        self._deliver = deliver

    async def publish(self, event: dict[str, Any]) -> None:
        log.info("inline_event", event_id=event["event_id"], event_type=event["event_type"])
        if event["event_type"] == "message.approved" and self._deliver is not None:
            # Sending is idempotent: a sent message makes a redelivered event a no-op.
            await self._deliver(uuid.UUID(event["message"]["id"]))
            return
        if event["event_type"] != "lead.created" or self._qualify is None:
            return
        try:
            await self._qualify(uuid.UUID(event["lead"]["id"]))
        except (Conflict, NotFound) as exc:
            log.info("inline_qualify_skipped", reason=exc.detail)
