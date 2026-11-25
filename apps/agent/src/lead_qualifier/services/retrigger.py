"""Operator actions on a lead: re-trigger orchestration, delete (privacy request)."""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.domain.errors import Conflict, NotFound
from lead_qualifier.domain.lead import LeadStatus
from lead_qualifier.infrastructure.checkpoint import PostgresCheckpointer
from lead_qualifier.infrastructure.db.repositories import LeadRepository, OutboxRepository
from lead_qualifier.infrastructure.db.tables import agent_runs
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


async def delete_lead(
    engine: AsyncEngine, lead_id: uuid.UUID, checkpointer: PostgresCheckpointer | None = None
) -> None:
    """Hard-delete a lead, its agent runs and its paused graph checkpoints (they hold lead data)."""
    async with engine.begin() as conn:
        threads = (
            await conn.execute(
                sa.select(agent_runs.c.thread_id).where(agent_runs.c.lead_id == lead_id)
            )
        ).scalars()
        thread_ids = list(threads)
        if not await LeadRepository(conn).delete(lead_id):
            raise NotFound("Unknown lead.")
    if checkpointer is not None:
        saver = await checkpointer.get()
        for thread_id in thread_ids:
            for attempt in (1, 2):
                try:
                    await saver.adelete_thread(thread_id)
                    break
                except Exception as exc:  # the periodic sweep removes what is left
                    log.error(
                        "checkpoint_delete_failed", attempt=attempt, error_type=type(exc).__name__
                    )
    log.info("lead_deleted", lead_id=str(lead_id))
