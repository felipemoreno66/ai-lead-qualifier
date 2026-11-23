"""Event publishers: a signed webhook to n8n, or an in-process no-op for inline mode."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx
import structlog

from lead_qualifier.ports.events import PublishError

log = structlog.get_logger("publisher")

WEBHOOK_PATHS = {"lead.created": "lead-created", "message.approved": "message-approved"}


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


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
        try:
            response = await self.client.post(
                f"{self.base_url}/webhook/{path}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Event-ID": event["event_id"],
                    "X-Signature": sign(body, self.secret),
                },
            )
        except httpx.HTTPError as exc:
            raise PublishError(f"{type(exc).__name__}: {exc}"[:300]) from exc
        if response.status_code >= 300:
            raise PublishError(f"n8n answered HTTP {response.status_code}")

    async def aclose(self) -> None:
        await self.client.aclose()


class InlinePublisher:
    """Inline orchestration: nothing external to call. Phase 1 only logs the event."""

    async def publish(self, event: dict[str, Any]) -> None:
        log.info("inline_event", event_id=event["event_id"], event_type=event["event_type"])
