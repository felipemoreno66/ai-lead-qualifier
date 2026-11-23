"""Sending approved messages and recording the outcome (inline mode and n8n callbacks)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.domain.channel import channel_for
from lead_qualifier.domain.errors import Conflict, NotFound
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
from lead_qualifier.workspaces.loader import WorkspaceRegistry

log = get_logger("delivery")
SEND_FAILED_REASON = "send_failed: the message could not be delivered"


@dataclass(frozen=True)
class DeliveryResult:
    message_id: uuid.UUID
    status: str
    changed: bool


class DeliveryService:
    """``deliver`` sends in-process (inline mode); ``mark_sent`` and ``mark_send_failed`` record
    the outcome reported by n8n. All three are idempotent."""

    def __init__(
        self,
        engine: AsyncEngine,
        clock: Clock,
        registry: WorkspaceRegistry,
        sender: EmailSender,
    ) -> None:
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

    async def content(self, message_id: uuid.UUID) -> dict[str, Any]:
        """What n8n needs to send an approved message (served on the private internal API)."""
        row = await self._load(message_id)
        if row["status"] != "approved":
            raise Conflict(f"A message in status '{row['status']}' is not waiting to be sent.")
        try:
            payload = self.payload_for(row)
        except (UnsupportedChannel, ValueError) as exc:
            # Never serve raw columns around the validation the inline path applies.
            raise Conflict(f"The message cannot be sent: {type(exc).__name__}.") from exc
        return {
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
        """Send an approved message once. A redelivered event for a sent message does nothing."""
        try:
            row = await self._load(message_id)
        except NotFound:
            return DeliveryResult(message_id, "missing", False)
        if row["status"] != "approved":
            return DeliveryResult(message_id, row["status"], False)
        try:
            provider_id = await self.sender.send(self.payload_for(row))
        except (EmailSendError, UnsupportedChannel, ValueError) as exc:
            log.warning("send_failed", message_id=str(message_id), error_type=type(exc).__name__)
            return await self.mark_send_failed(message_id, type(exc).__name__)
        return await self.mark_sent(message_id, provider_id)

    async def mark_sent(
        self, message_id: uuid.UUID, provider_message_id: str | None
    ) -> DeliveryResult:
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
            if row["status"] != "approved":
                raise Conflict(f"A message in status '{row['status']}' cannot be marked as sent.")
            repo = LeadRepository(conn)
            await repo.update_status(
                row["lead_id"],
                LeadStatus.APPROVED,
                next_status(LeadStatus.APPROVED, LeadTrigger.SENT),
                now,
                sent_at=now,
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
                from_status=LeadStatus.APPROVED.value,
                to_status=LeadStatus.SENT.value,
                payload={"message_id": str(message_id), "channel": row["channel"]},
                at=now,
            )
        log.info("message_sent", message_id=str(message_id))
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
            if row["status"] != "approved":
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
