"""Operator review of a drafted message: approve, edit, reject or regenerate."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from lead_qualifier.agent.graph import QualifyState, resume_review
from lead_qualifier.domain.draft_guard import Problem, check_draft_detailed
from lead_qualifier.domain.errors import Conflict, NotFound, ValidationFailed
from lead_qualifier.domain.lead import LeadStatus, LeadTrigger, next_status
from lead_qualifier.infrastructure.db.repositories import LeadRepository, OutboxRepository
from lead_qualifier.infrastructure.db.tables import agent_runs, messages
from lead_qualifier.infrastructure.db.tables import leads as leads_table
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
    """Drives the paused graph. Also the graph's ``SendGateway`` (``request_send``).

    The database is the source of truth. Every action is claimed first, in one transaction that
    holds a row lock on the lead; only then is the paused graph resumed to let its thread finish.
    A concurrent second request waits on the lock and then sees the new status.
    """

    def __init__(self, engine: AsyncEngine, clock: Clock, qualifier: QualifyService) -> None:
        self.engine = engine
        self.clock = clock
        self.qualifier = qualifier

    async def review(
        self,
        lead_id: uuid.UUID,
        action: Action,
        *,
        subject: str | None = None,
        body: str | None = None,
        feedback: str | None = None,
        note: str | None = None,
        override: bool = False,
    ) -> ReviewOutcome:
        now = self.clock.now()
        async with self.engine.begin() as conn:
            lead_row = (
                (
                    await conn.execute(
                        sa.select(leads_table).where(leads_table.c.id == lead_id).with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if lead_row is None:
                raise NotFound("Unknown lead.")
            lead = dict(lead_row)
            if lead["status"] != LeadStatus.PENDING_REVIEW.value:
                repeated = await self._repeat_of_approval(conn, lead, action)
                if repeated is not None:
                    return repeated
                raise Conflict(f"A lead in status '{lead['status']}' cannot be reviewed.")
            message = await _draft_on(conn, lead_id)
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
            workspace = self.qualifier.registry.get(lead["workspace_slug"])
            if workspace is None:
                raise NotFound("The lead's workspace is not loaded.")
            decision: dict[str, Any] = {"action": action, "message_id": str(message["id"])}
            if action in ("approve", "edit"):
                if action == "edit":
                    decision |= {
                        "subject": subject if subject is not None else message["subject"],
                        "body": body,
                    }
                final: dict[str, Any] = dict(message)
                final.update({k: decision[k] for k in ("subject", "body") if k in decision})
                if action == "edit":
                    final["short_body"] = None  # the generated variant no longer matches the edit
                problems = check_draft_detailed(
                    workspace.config,
                    language=final["language"],
                    subject=final["subject"] or "",
                    body=final["body"],
                    short_body=final["short_body"],
                )
                if problems and not override:
                    raise ValidationFailed(
                        "The message does not pass the draft checks. Fix it, or resend with "
                        "override: true to approve it anyway.",
                        errors=[{"code": p.code, "message": p.message} for p in problems],
                    )
                await _approve(
                    conn, lead, message, decision, now, overridden=problems if override else []
                )
            else:
                await self._reject_or_regenerate(
                    conn, lead, message, run, action, feedback, note, now
                )
            if action == "regenerate":
                decision["feedback"] = feedback or ""
        # The claim is committed; now let the paused thread finish (or redraft).
        deps = self.qualifier.deps_for(workspace.config, run["id"])
        saver = await self.qualifier.checkpointer.get()
        try:
            state = await resume_review(
                decision, deps, checkpointer=saver, thread_id=run["thread_id"]
            )
        except Exception as exc:
            log.error(
                "resume_failed", lead_id=str(lead_id), action=action, error_type=type(exc).__name__
            )
            if action == "regenerate":
                state = {"error": f"internal_error: {type(exc).__name__}"}
            else:
                # The database already says the review is done; do not leave a paused thread
                # behind that disagrees with it (and holds lead data).
                await _discard_thread(saver, run["thread_id"])
                return ReviewOutcome(lead_id, _final_status(action), message["id"])
        if action == "regenerate":
            outcome = await self.qualifier.finish(lead_id, run["id"], state)
            new = await _latest_draft(self.engine, lead_id)
            return ReviewOutcome(
                lead_id, outcome.status, new["id"] if new else message["id"], outcome.error_reason
            )
        return ReviewOutcome(lead_id, _final_status(action), message["id"])

    async def _repeat_of_approval(
        self, conn: AsyncConnection, lead: dict[str, Any], action: Action
    ) -> ReviewOutcome | None:
        """Approving an already-approved lead is idempotent, even after an operator edit: same
        answer, no second outbox event."""
        if action != "approve" or lead["status"] not in (
            LeadStatus.APPROVED.value,
            LeadStatus.SENT.value,
        ):
            return None
        row = (
            (
                await conn.execute(
                    sa.select(messages)
                    .where(
                        messages.c.lead_id == lead["id"],
                        messages.c.status.in_(("approved", "sent")),
                    )
                    .order_by(messages.c.version.desc())
                    .limit(1)
                )
            )
            .mappings()
            .first()
        )
        return ReviewOutcome(lead["id"], LeadStatus.APPROVED.value, row["id"]) if row else None

    async def _reject_or_regenerate(
        self,
        conn: AsyncConnection,
        lead: dict[str, Any],
        message: dict[str, Any],
        run: Any,
        action: Action,
        feedback: str | None,
        note: str | None,
        now: Any,
    ) -> None:
        lead_id = lead["id"]
        trigger = LeadTrigger.REJECT if action == "reject" else LeadTrigger.REGENERATE
        new_status = next_status(LeadStatus.PENDING_REVIEW, trigger)
        repo = LeadRepository(conn)
        await repo.update_status(
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
        await repo.add_event(
            lead_id,
            "reviewed",
            actor="operator",
            from_status=LeadStatus.PENDING_REVIEW.value,
            to_status=new_status.value,
            payload={"action": action, "message_id": str(message["id"])},
            at=now,
        )
        values: dict[str, Any] = (
            {"status": "completed", "finished_at": now}
            if action == "reject"
            else {"status": "running", "finished_at": None}
        )
        await conn.execute(
            sa.update(agent_runs).where(agent_runs.c.id == run["id"]).values(**values)
        )

    async def request_send(self, decision: dict[str, Any], state: QualifyState) -> None:
        """The graph's ``request_send`` node. The review already approved the message in its own
        transaction, so this is a replay-safe no-op; it still approves if it finds a draft (for
        example a graph resumed by other code)."""
        message_id = uuid.UUID(decision["message_id"])
        now = self.clock.now()
        async with self.engine.begin() as conn:
            row = (
                (
                    await conn.execute(
                        sa.select(messages).where(messages.c.id == message_id).with_for_update()
                    )
                )
                .mappings()
                .one()
            )
            if row["status"] != "draft":
                return
            lead = (
                (
                    await conn.execute(
                        sa.select(leads_table).where(leads_table.c.id == row["lead_id"])
                    )
                )
                .mappings()
                .one()
            )
            await _approve(conn, dict(lead), dict(row), decision, now, overridden=[])


def _final_status(action: Action) -> str:
    return LeadStatus.REJECTED.value if action == "reject" else LeadStatus.APPROVED.value


async def _approve(
    conn: AsyncConnection,
    lead: dict[str, Any],
    message: dict[str, Any],
    decision: dict[str, Any],
    now: Any,
    *,
    overridden: list[Problem],
) -> None:
    """Approve ``message``: the lead moves on, the outbox gets one ``message.approved`` event
    (unique key per message) and an edit keeps ``original_body``."""
    message_id = message["id"]
    repo = LeadRepository(conn)
    await repo.update_status(
        lead["id"],
        LeadStatus.PENDING_REVIEW,
        next_status(LeadStatus.PENDING_REVIEW, LeadTrigger.APPROVE),
        now,
    )
    values: dict[str, Any] = {"status": "approved", "reviewed_at": now}
    if decision["action"] == "edit":
        values |= {
            "original_body": message["original_body"] or message["body"],
            "body": decision["body"],
            "subject": decision["subject"],
            "edited_by_operator": True,
            # The operator's text replaces the draft; the generated plain-text variant would no
            # longer match it, so it is dropped rather than sent unreviewed.
            "short_body": None,
        }
    await conn.execute(sa.update(messages).where(messages.c.id == message_id).values(**values))
    await OutboxRepository(conn).enqueue(
        event_type="message.approved",
        aggregate_id=message_id,
        lead_id=lead["id"],
        payload={
            "lead": {
                "id": str(lead["id"]),
                "workspace": lead["workspace_slug"],
                "reference": lead["reference"],
            },
            "message": {
                "id": str(message_id),
                "channel": message["channel"],
                "version": message["version"],
            },
        },
        idempotency_key=f"message:{message_id}:send",
        now=now,
    )
    payload: dict[str, Any] = {"action": decision["action"], "message_id": str(message_id)}
    if overridden:
        payload |= {"override": True, "problems": [p.code for p in overridden]}
    await repo.add_event(
        lead["id"],
        "reviewed",
        actor="operator",
        from_status=LeadStatus.PENDING_REVIEW.value,
        to_status=LeadStatus.APPROVED.value,
        payload=payload,
        at=now,
    )
    await conn.execute(
        sa.update(agent_runs)
        .where(agent_runs.c.id == message["agent_run_id"])
        .values(status="completed", finished_at=now)
    )
    log.info("message_approved", lead_id=str(lead["id"]), message_id=str(message_id))


async def _discard_thread(saver: Any, thread_id: str) -> None:
    try:
        await saver.adelete_thread(thread_id)
    except Exception as exc:
        log.error("thread_discard_failed", error_type=type(exc).__name__)


async def _draft_on(conn: AsyncConnection, lead_id: uuid.UUID) -> dict[str, Any] | None:
    row = (
        (
            await conn.execute(
                sa.select(messages)
                .where(messages.c.lead_id == lead_id, messages.c.status == "draft")
                .order_by(messages.c.version.desc())
                .limit(1)
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def _latest_draft(engine: AsyncEngine, lead_id: uuid.UUID) -> dict[str, Any] | None:
    async with engine.connect() as conn:
        return await _draft_on(conn, lead_id)
