"""Event publishers: a signed webhook to n8n, or an in-process no-op for inline mode."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from lead_qualifier.logging import get_logger
from lead_qualifier.ports.events import AuthRejectedError, PermanentPublishError, PublishError

log = get_logger("publisher")

WEBHOOK_PATHS = {"lead.created": "lead-created", "message.approved": "message-approved"}


PERMANENT_STATUSES = frozenset({400, 403, 404, 410, 422})


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
        if response.status_code == 401:
            # Clock skew beyond the signature window or a secret rotated mid-flight heals itself.
            raise AuthRejectedError("n8n rejected the signature (HTTP 401)")
        if response.status_code in PERMANENT_STATUSES:
            # Retrying cannot help (for example a wrong shared secret): fail fast and visibly.
            raise PermanentPublishError(f"n8n rejected the event with HTTP {response.status_code}")
        if response.status_code >= 300:
            raise PublishError(f"n8n answered HTTP {response.status_code}")

    async def aclose(self) -> None:
        await self.client.aclose()


class InlinePublisher:
    """Inline orchestration: nothing external to call. Phase 1 only logs the event."""

    async def publish(self, event: dict[str, Any]) -> None:
        log.info("inline_event", event_id=event["event_id"], event_type=event["event_type"])
