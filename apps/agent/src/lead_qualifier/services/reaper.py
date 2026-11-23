"""Fail agent runs that never finished (a crash between starting and finishing a run)."""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.domain.lead import LeadStatus, LeadTrigger, next_status
from lead_qualifier.infrastructure.db.repositories import LeadRepository, StatusConflict
from lead_qualifier.infrastructure.db.tables import agent_runs, leads
from lead_qualifier.logging import get_logger
from lead_qualifier.ports.clock import Clock

log = get_logger("reaper")
REASON = "interrupted: the qualification run did not finish"


async def reap_stale_runs(engine: AsyncEngine, clock: Clock, max_age: timedelta) -> int:
    """Mark ``running`` runs older than ``max_age`` as failed and their ``qualifying`` lead as
    ``error`` (retryable). Runs paused for a human (``interrupted``) are never touched."""
    now = clock.now()
    reaped = 0
    async with engine.connect() as conn:
        stale = (
            await conn.execute(
                sa.select(agent_runs.c.id, agent_runs.c.lead_id)
                .join(leads, leads.c.id == agent_runs.c.lead_id)
                .where(
                    agent_runs.c.status == "running",
                    agent_runs.c.started_at < now - max_age,
                    leads.c.status == LeadStatus.QUALIFYING.value,
                )
            )
        ).all()
    for run_id, lead_id in stale:
        try:
            async with engine.begin() as conn:
                repo = LeadRepository(conn)
                await repo.update_status(
                    lead_id,
                    LeadStatus.QUALIFYING,
                    next_status(LeadStatus.QUALIFYING, LeadTrigger.FAILED),
                    now,
                    error_reason=REASON,
                )
                await conn.execute(
                    sa.update(agent_runs)
                    .where(agent_runs.c.id == run_id, agent_runs.c.status == "running")
                    .values(status="failed", finished_at=now, error=REASON)
                )
                await repo.add_event(
                    lead_id,
                    "status_changed",
                    from_status=LeadStatus.QUALIFYING.value,
                    to_status=LeadStatus.ERROR.value,
                    payload={"trigger": LeadTrigger.FAILED.value, "reason": REASON},
                    at=now,
                )
            reaped += 1
        except StatusConflict:
            continue  # the run finished in the meantime
    if reaped:
        log.warning("stale_runs_reaped", count=reaped)
    return reaped
