"""Fail agent runs that never finished (a crash between starting and finishing a run)."""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.domain.lead import LeadStatus, LeadTrigger, next_status
from lead_qualifier.infrastructure.db.repositories import LeadRepository, StatusConflict
from lead_qualifier.infrastructure.db.tables import agent_runs, leads, messages
from lead_qualifier.logging import get_logger
from lead_qualifier.ports.clock import Clock

log = get_logger("reaper")
REASON = "interrupted: the qualification run did not finish"


async def reap_stale_runs(engine: AsyncEngine, clock: Clock, max_age: timedelta) -> int:
    """Mark ``running`` runs whose ``qualifying`` lead has not been touched for ``max_age`` as
    failed and the lead as ``error`` (retryable).

    Staleness is the lead's ``updated_at``, which every claim (start of a run, operator
    regenerate) refreshes, so a long-lived run that is regenerating right now is not reaped, while
    a crash right after a regenerate claim is. Runs paused for a human (``interrupted``) are
    never touched."""
    now = clock.now()
    reaped = 0
    async with engine.connect() as conn:
        stale = (
            await conn.execute(
                sa.select(agent_runs.c.id, agent_runs.c.lead_id)
                .join(leads, leads.c.id == agent_runs.c.lead_id)
                .where(
                    agent_runs.c.status == "running",
                    leads.c.updated_at < now - max_age,
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


async def report_stale_sending(engine: AsyncEngine, clock: Clock, max_age: timedelta) -> int:
    """Log messages stuck in ``sending`` (a crash between the SMTP call and its report).

    They are deliberately NOT resent: the email may have gone out. An operator checks the mailbox
    or the provider and then settles the message (``POST /internal/messages/{id}/sent`` or
    ``/send-failed``, or an UPDATE of the row)."""
    async with engine.connect() as conn:
        stuck = (
            (
                await conn.execute(
                    sa.select(messages.c.id).where(
                        messages.c.status == "sending",
                        messages.c.send_started_at < clock.now() - max_age,
                    )
                )
            )
            .scalars()
            .all()
        )
    if stuck:
        log.error("stale_sending_messages", count=len(stuck), message_ids=[str(i) for i in stuck])
    return len(stuck)
