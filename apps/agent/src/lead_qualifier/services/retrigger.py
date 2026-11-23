"""Operator actions on a lead: re-trigger orchestration, delete (privacy request)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.domain.errors import Conflict, NotFound
from lead_qualifier.domain.lead import LeadStatus
from lead_qualifier.infrastructure.db.repositories import LeadRepository, OutboxRepository
from lead_qualifier.logging import get_logger
from lead_qualifier.ports.clock import Clock

log = get_logger("operator")
RETRIGGERABLE = frozenset({LeadStatus.NEW.value, LeadStatus.ERROR.value})


async def retrigger(engine: AsyncEngine, lead_id: uuid.UUID, clock: Clock) -> dict[str, Any]:
    now = clock.now()
    async with engine.begin() as conn:
        leads, outbox = LeadRepository(conn), OutboxRepository(conn)
        lead = await leads.get(lead_id)
        if lead is None:
            raise NotFound("Unknown lead.")
        if lead["status"] not in RETRIGGERABLE:
            raise Conflict(
                f"A lead in status '{lead['status']}' cannot be re-triggered; "
                "only 'new' and 'error' leads can."
            )
        if any(e["status"] == "pending" for e in await outbox.for_lead(lead_id)):
            raise Conflict("An event for this lead is already queued.")
        attempt = await outbox.count_for_lead(lead_id, "lead.created") + 1
        event_id = await outbox.enqueue(
            event_type="lead.created",
            aggregate_id=lead_id,
            lead_id=lead_id,
            payload={
                "lead": {
                    "id": str(lead_id),
                    "workspace": lead["workspace_slug"],
                    "reference": lead["reference"],
                }
            },
            idempotency_key=f"lead:{lead_id}:created:{attempt}",
            now=now,
        )
        await leads.add_event(
            lead_id, "retriggered", actor="operator", payload={"attempt": attempt}, at=now
        )
    log.info("lead_retriggered", lead_id=str(lead_id), attempt=attempt)
    return {"event_id": str(event_id), "attempt": attempt}


async def delete_lead(engine: AsyncEngine, lead_id: uuid.UUID) -> None:
    async with engine.begin() as conn:
        if not await LeadRepository(conn).delete(lead_id):
            raise NotFound("Unknown lead.")
    log.info("lead_deleted", lead_id=str(lead_id))
