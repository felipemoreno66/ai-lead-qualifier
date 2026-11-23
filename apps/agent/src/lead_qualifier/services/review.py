"""Operator review of a drafted message: approve, edit, reject or regenerate."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from lead_qualifier.agent.graph import QualifyState, resume_review
from lead_qualifier.domain.errors import Conflict, NotFound
from lead_qualifier.domain.lead import LeadStatus, LeadTrigger, next_status
from lead_qualifier.infrastructure.db.repositories import LeadRepository, OutboxRepository
from lead_qualifier.infrastructure.db.tables import agent_runs, messages
from lead_qualifier.logging import get_logger
from lead_qualifier.ports.clock import Clock
from lead_qualifier.services.qualify import QualifyService

log = get_logger("review")
Action = Literal["approve", "edit", "reject", "regenerate"]


@dataclass(frozen=True)
class ReviewOutcome:
    lead_id: uuid.UUID
    status: str
    message_id: uuid.UUID
    error_reason: str | None = None


class ReviewService:
    """Drives the paused graph. Also the graph's ``SendGateway`` (``request_send``)."""

    def __init__(self, engine: AsyncEngine, clock: Clock, qualifier: QualifyService) -> None:
        self.engine = engine
        self.clock = clock
        self.qualifier = qualifier
        qualifier.send_gateway = self

    async def review(
        self,
        lead_id: uuid.UUID,
        action: Action,
        *,
        subject: str | None = None,
        body: str | None = None,
        feedback: str | None = None,
        note: str | None = None,
    ) -> ReviewOutcome:
        now = self.clock.now()
        async with self.engine.begin() as conn:
            leads = LeadRepository(conn)
            lead = await leads.get(lead_id)
            if lead is None:
                raise NotFound("Unknown lead.")
            if lead["status"] != LeadStatus.PENDING_REVIEW.value:
                raise Conflict(f"A lead in status '{lead['status']}' cannot be reviewed.")
            message = await _current_draft(conn, lead_id)
            if message is None:
                raise Conflict("The lead has no draft waiting for review.")
            run = (
                (
                    await conn.execute(
                        sa.select(agent_runs)
                        .where(agent_runs.c.lead_id == lead_id)
                        .order_by(agent_runs.c.run_number.desc())
                        .limit(1)
                    )
                )
                .mappings()
                .one()
            )
            if action in ("reject", "regenerate"):
                trigger = LeadTrigger.REJECT if action == "reject" else LeadTrigger.REGENERATE
                new_status = next_status(LeadStatus.PENDING_REVIEW, trigger)
                await leads.update_status(
                    lead_id, LeadStatus.PENDING_REVIEW, new_status, now, error_reason=None
                )
                await conn.execute(
                    sa.update(messages)
                    .where(messages.c.id == message["id"])
                    .values(
                        status="rejected",
                        review_note=(feedback if action == "regenerate" else note),
                        reviewed_at=now,
                    )
                )
                await leads.add_event(
                    lead_id,
                    "reviewed",
                    actor="operator",
                    from_status=LeadStatus.PENDING_REVIEW.value,
                    to_status=new_status.value,
                    payload={"action": action, "message_id": str(message["id"])},
                    at=now,
                )
                if action == "reject":
                    await conn.execute(
                        sa.update(agent_runs)
                        .where(agent_runs.c.id == run["id"])
                        .values(status="completed", finished_at=now)
                    )
                else:
                    await conn.execute(
                        sa.update(agent_runs)
                        .where(agent_runs.c.id == run["id"])
                        .values(status="running", finished_at=None)
                    )
        workspace = self.qualifier.registry.get(lead["workspace_slug"])
        if workspace is None:
            raise NotFound("The lead's workspace is not loaded.")
        decision: dict[str, Any] = {"action": action, "message_id": str(message["id"])}
        if action == "edit":
            decision |= {"subject": subject or message["subject"], "body": body}
        if action == "regenerate":
            decision["feedback"] = feedback or ""
        deps = self.qualifier.deps_for(workspace.config, run["id"])
        saver = await self.qualifier.checkpointer.get()
        try:
            state = await resume_review(
                decision, deps, checkpointer=saver, thread_id=run["thread_id"]
            )
        except Conflict:
            raise
        except Exception as exc:
            if action != "regenerate":
                raise
            log.error("regenerate_crashed", lead_id=str(lead_id), error_type=type(exc).__name__)
            state = {"error": f"internal_error: {type(exc).__name__}"}
        if action == "regenerate":
            outcome = await self.qualifier.finish(lead_id, run["id"], state)
            new = await _current_draft(self.engine, lead_id)
            return ReviewOutcome(
                lead_id, outcome.status, new["id"] if new else message["id"], outcome.error_reason
            )
        status = LeadStatus.REJECTED if action == "reject" else LeadStatus.APPROVED
        return ReviewOutcome(lead_id, status.value, message["id"])

    async def request_send(self, decision: dict[str, Any], state: QualifyState) -> None:
        """The graph's ``request_send`` node: one idempotent transaction that approves the message,
        queues ``message.approved`` (unique key per message) and moves the lead to ``approved``."""
        message_id = uuid.UUID(decision["message_id"])
        now = self.clock.now()
        async with self.engine.begin() as conn:
            row = (
                (await conn.execute(sa.select(messages).where(messages.c.id == message_id)))
                .mappings()
                .one()
            )
            if row["status"] == "approved":
                return  # replay after a crash: everything below already happened
            leads = LeadRepository(conn)
            lead = await leads.get(row["lead_id"])
            assert lead is not None
            await leads.update_status(
                row["lead_id"],
                LeadStatus.PENDING_REVIEW,
                next_status(LeadStatus.PENDING_REVIEW, LeadTrigger.APPROVE),
                now,
            )
            values: dict[str, Any] = {"status": "approved", "reviewed_at": now}
            if decision["action"] == "edit":
                values |= {
                    "original_body": row["original_body"] or row["body"],
                    "body": decision["body"],
                    "subject": decision.get("subject") or row["subject"],
                    "edited_by_operator": True,
                }
            await conn.execute(
                sa.update(messages).where(messages.c.id == message_id).values(**values)
            )
            await OutboxRepository(conn).enqueue(
                event_type="message.approved",
                aggregate_id=message_id,
                lead_id=row["lead_id"],
                payload={
                    "lead": {
                        "id": str(row["lead_id"]),
                        "workspace": lead["workspace_slug"],
                        "reference": lead["reference"],
                    },
                    "message": {
                        "id": str(message_id),
                        "channel": row["channel"],
                        "version": row["version"],
                    },
                },
                idempotency_key=f"message:{message_id}:send",
                now=now,
            )
            await leads.add_event(
                row["lead_id"],
                "reviewed",
                actor="operator",
                from_status=LeadStatus.PENDING_REVIEW.value,
                to_status=LeadStatus.APPROVED.value,
                payload={"action": decision["action"], "message_id": str(message_id)},
                at=now,
            )
            await conn.execute(
                sa.update(agent_runs)
                .where(agent_runs.c.id == row["agent_run_id"])
                .values(status="completed", finished_at=now)
            )
        log.info("message_approved", lead_id=str(row["lead_id"]), message_id=str(message_id))


async def _current_draft(
    conn: AsyncConnection | AsyncEngine, lead_id: uuid.UUID
) -> dict[str, Any] | None:
    stmt = (
        sa.select(messages)
        .where(messages.c.lead_id == lead_id, messages.c.status == "draft")
        .order_by(messages.c.version.desc())
        .limit(1)
    )
    if isinstance(conn, AsyncEngine):
        async with conn.connect() as c:
            row = (await c.execute(stmt)).mappings().first()
    else:
        row = (await conn.execute(stmt)).mappings().first()
    return dict(row) if row else None
