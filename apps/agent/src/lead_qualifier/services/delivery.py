"""Sending approved messages and recording the outcome (inline mode and n8n callbacks)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.domain.channel import channel_for
from lead_qualifier.domain.errors import Conflict, NotFound, ValidationFailed
from lead_qualifier.domain.lead import LeadStatus, LeadTrigger, next_status
from lead_qualifier.infrastructure.db.repositories import LeadRepository
from lead_qualifier.infrastructure.db.tables import leads, messages
from lead_qualifier.logging import get_logger
from lead_qualifier.ports.channel import (
    ChannelMessage,
    ChannelPayload,
    EmailSender,
    EmailSendError,
    UnsupportedChannel,
)
from lead_qualifier.ports.clock import Clock
from lead_qualifier.ports.events import PublishError
from lead_qualifier.workspaces.loader import WorkspaceRegistry

log = get_logger("delivery")
SEND_FAILED_REASON = "send_failed: the message could not be delivered"


@dataclass(frozen=True)
class DeliveryResult:
    message_id: uuid.UUID
    status: str
    changed: bool


class DeliveryService:
    """Sends approved messages. Delivery is at-least-once with a stable ``Message-ID``, but a
    message is **claimed** (``approved`` to ``sending`` under a row lock) before the SMTP call, so a
    redelivered event or a second worker never sends it again. A claim that is never settled
    (crash between the call and the report) stays ``sending`` and is reported for a manual check
    instead of being resent automatically.

    ``deliver`` sends in-process (inline mode); ``claim`` hands the content to n8n; ``mark_sent``
    and ``mark_send_failed`` record the outcome. All of them are idempotent."""

    def __init__(
        self,
        engine: AsyncEngine,
        clock: Clock,
        registry: WorkspaceRegistry,
        sender: EmailSender,
        *,
        max_attempts: int = 3,
    ) -> None:
        self.max_attempts = max_attempts
        self.engine = engine
        self.clock = clock
        self.registry = registry
        self.sender = sender

    async def _load(self, message_id: uuid.UUID) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        sa.select(messages, leads.c.workspace_slug)
                        .join(leads, leads.c.id == messages.c.lead_id)
                        .where(messages.c.id == message_id)
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise NotFound("Unknown message.")
        return dict(row)

    def payload_for(self, row: dict[str, Any]) -> ChannelPayload:
        """Render the stored message with its channel (``UnsupportedChannel`` for unbuilt ones)."""
        workspace = self.registry.get(row["workspace_slug"])
        sender = workspace.config.profile.contact_email if workspace else "noreply@localhost"
        channel = channel_for(row["channel"], sender=sender)
        return channel.render(
            ChannelMessage(
                id=str(row["id"]),
                channel=row["channel"],
                recipient=row["channel_recipient"],
                subject=row["subject"],
                body=row["body"],
                short_body=row["short_body"],
                language=row["language"],
            )
        )

    async def _claim(self, message_id: uuid.UUID) -> str:
        """``approved`` to ``sending`` under ``FOR UPDATE``; returns the status seen before."""
        now = self.clock.now()
        async with self.engine.begin() as conn:
            row = (
                (
                    await conn.execute(
                        sa.select(messages).where(messages.c.id == message_id).with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise NotFound("Unknown message.")
            if row["status"] == "approved":
                await conn.execute(
                    sa.update(messages)
                    .where(messages.c.id == message_id)
                    .values(status="sending", send_started_at=now)
                )
            status: str = row["status"]
        return status

    async def claim(self, message_id: uuid.UUID) -> dict[str, Any]:
        """What n8n needs to send an approved message, claiming it so it is sent only once.

        ``deliverable: false`` (already sending, sent or failed) tells n8n to do nothing. An
        invalid message (bad recipient, unsupported channel) is a 422 and nothing is claimed."""
        row = await self._load(message_id)
        if row["status"] in ("sending", "sent", "failed"):
            return {"deliverable": False, "status": row["status"], "id": str(message_id)}
        if row["status"] != "approved":
            raise Conflict(f"A message in status '{row['status']}' is not waiting to be sent.")
        try:
            payload = self.payload_for(row)
        except (UnsupportedChannel, ValueError) as exc:
            # Never serve raw columns around the validation the inline path applies.
            raise ValidationFailed(f"The message cannot be sent: {type(exc).__name__}.") from exc
        seen = await self._claim(message_id)
        if seen != "approved":  # lost a race with another delivery
            return {"deliverable": False, "status": seen, "id": str(message_id)}
        return {
            "deliverable": True,
            "status": "sending",
            "id": str(row["id"]),
            "lead_id": str(row["lead_id"]),
            "channel": payload.channel,
            "recipient": payload.recipient,
            "subject": payload.subject,
            "body": payload.text,
            "language": row["language"],
            "from_address": payload.sender,
            "message_id_header": payload.message_id,
        }

    async def deliver(self, message_id: uuid.UUID) -> DeliveryResult:
        """Send an approved message once (inline mode).

        Transient SMTP failures release the claim and raise ``PublishError`` so the outbox retries
        the event with backoff, up to ``max_attempts``; permanent ones fail the message at once."""
        try:
            row = await self._load(message_id)
        except NotFound:
            return DeliveryResult(message_id, "missing", False)
        if row["status"] != "approved":
            return DeliveryResult(message_id, row["status"], False)
        try:
            payload = self.payload_for(row)
        except (UnsupportedChannel, ValueError) as exc:
            return await self.mark_send_failed(message_id, type(exc).__name__)
        if await self._claim(message_id) != "approved":
            return DeliveryResult(message_id, "sending", False)  # another worker has it
        try:
            provider_id = await self.sender.send(payload)
        except EmailSendError as exc:
            log.warning("send_failed", message_id=str(message_id), error=str(exc)[:60])
            if exc.transient and await self._release_for_retry(message_id) < self.max_attempts:
                raise PublishError("transient email failure, will retry") from exc
            return await self.mark_send_failed(message_id, str(exc)[:60])
        return await self.mark_sent(message_id, provider_id)

    async def _release_for_retry(self, message_id: uuid.UUID) -> int:
        """Back to ``approved`` after a transient failure; returns the attempts used so far."""
        async with self.engine.begin() as conn:
            attempts: int = (
                await conn.execute(
                    sa.update(messages)
                    .where(messages.c.id == message_id, messages.c.status == "sending")
                    .values(status="approved", send_attempts=messages.c.send_attempts + 1)
                    .returning(messages.c.send_attempts)
                )
            ).scalar_one()
        return attempts

    async def mark_sent(
        self, message_id: uuid.UUID, provider_message_id: str | None
    ) -> DeliveryResult:
        """Record a delivery. A report that arrives after the message was marked failed (a slow
        callback) wins: the email did go out, so the message and the lead move on to ``sent``."""
        now = self.clock.now()
        async with self.engine.begin() as conn:
            row = (
                (
                    await conn.execute(
                        sa.select(messages).where(messages.c.id == message_id).with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise NotFound("Unknown message.")
            if row["status"] == "sent":
                return DeliveryResult(message_id, "sent", False)
            if row["status"] not in ("approved", "sending", "failed"):
                raise Conflict(f"A message in status '{row['status']}' cannot be marked as sent.")
            late = row["status"] == "failed"
            repo = LeadRepository(conn)
            lead = await repo.get(row["lead_id"])
            payload: dict[str, Any] = {"message_id": str(message_id), "channel": row["channel"]}
            if late:
                payload["late_report"] = True
            if late and not (
                lead
                and lead["status"] == LeadStatus.ERROR.value
                and (lead["error_reason"] or "").startswith("send_failed")
            ):
                # The lead has moved on (for example a retry started): only the message is fixed.
                payload["lead_unchanged"] = True
                lead_move = None
            else:
                lead_move = (
                    (LeadStatus.ERROR, LeadTrigger.LATE_SENT)
                    if late
                    else (LeadStatus.APPROVED, LeadTrigger.SENT)
                )
            if lead_move is not None:
                await repo.update_status(
                    row["lead_id"],
                    lead_move[0],
                    next_status(*lead_move),
                    now,
                    sent_at=now,
                    error_reason=None,
                )
            await conn.execute(
                sa.update(messages)
                .where(messages.c.id == message_id)
                .values(
                    status="sent",
                    sent_at=now,
                    provider_message_id=(provider_message_id or "")[:200] or None,
                )
            )
            await repo.add_event(
                row["lead_id"],
                "email_sent",
                from_status=lead_move[0].value if lead_move else None,
                to_status=LeadStatus.SENT.value if lead_move else None,
                payload=payload,
                at=now,
            )
        log.info("message_sent", message_id=str(message_id), late=late)
        return DeliveryResult(message_id, "sent", True)

    async def mark_send_failed(self, message_id: uuid.UUID, error_type: str) -> DeliveryResult:
        """Lead goes to ``error`` (retryable). Only the error type is kept: delivery errors can
        contain the recipient's address."""
        now = self.clock.now()
        async with self.engine.begin() as conn:
            row = (
                (
                    await conn.execute(
                        sa.select(messages).where(messages.c.id == message_id).with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise NotFound("Unknown message.")
            if row["status"] not in ("approved", "sending"):
                return DeliveryResult(message_id, row["status"], False)  # sent or already failed
            repo = LeadRepository(conn)
            await repo.update_status(
                row["lead_id"],
                LeadStatus.APPROVED,
                next_status(LeadStatus.APPROVED, LeadTrigger.SEND_FAILED),
                now,
                error_reason=SEND_FAILED_REASON,
            )
            await conn.execute(
                sa.update(messages).where(messages.c.id == message_id).values(status="failed")
            )
            await repo.add_event(
                row["lead_id"],
                "status_changed",
                from_status=LeadStatus.APPROVED.value,
                to_status=LeadStatus.ERROR.value,
                payload={
                    "trigger": LeadTrigger.SEND_FAILED.value,
                    "message_id": str(message_id),
                    "error_type": error_type[:60],
                },
                at=now,
            )
        return DeliveryResult(message_id, "failed", True)
