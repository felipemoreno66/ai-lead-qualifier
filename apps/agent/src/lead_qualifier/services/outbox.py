"""Outbox bookkeeping shared by the dispatcher and the n8n acknowledgement endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.domain.errors import NotFound
from lead_qualifier.infrastructure.db.repositories import LeadRepository, OutboxRepository


async def acknowledge(engine: AsyncEngine, event_id: uuid.UUID, now: datetime) -> bool:
    """n8n confirms it processed an event. Idempotent; returns True when this call delivered it."""
    async with engine.begin() as conn:
        outbox = OutboxRepository(conn)
        if await outbox.get(event_id) is None:
            raise NotFound("Unknown event.")
        row = await outbox.mark_delivered(event_id, now)
        if row is None:
            return False
        if row["lead_id"]:
            await LeadRepository(conn).add_event(
                row["lead_id"], "outbox_delivered", actor="n8n", payload={"via": "ack"}, at=now
            )
        return True


def envelope(row: dict[str, Any]) -> dict[str, Any]:
    """The JSON body sent to the orchestrator. IDs and references only, no personal data."""
    return {
        "event_id": str(row["id"]),
        "event_type": row["event_type"],
        "occurred_at": row["created_at"].isoformat(),
        **row["payload"],
    }
