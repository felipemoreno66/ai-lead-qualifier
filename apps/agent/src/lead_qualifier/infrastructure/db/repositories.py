"""Repositories over SQLAlchemy Core. Each takes an ``AsyncConnection`` so that callers
control the transaction boundary (one transaction per use case)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from lead_qualifier.domain.errors import Conflict
from lead_qualifier.domain.lead import LeadStatus
from lead_qualifier.infrastructure.db.tables import (
    agent_runs,
    lead_events,
    leads,
    llm_calls,
    outbox_events,
    rate_limit_hits,
    workspaces,
)

Row = dict[str, Any]

GROUP_RANK = {"attention": 0, "hot": 1, "warm": 2, "scoring": 3, "cold": 4}
SORTS = ("priority", "-created_at", "created_at", "-score", "score", "name", "-name")


def _row(mapping: Mapping[Any, Any]) -> Row:
    return {str(k): v for k, v in mapping.items()}


class StatusConflict(Conflict):
    title = "Lead status changed"


@dataclass(frozen=True)
class LeadFilters:
    workspace: str | None = None
    statuses: Sequence[str] = ()
    tiers: Sequence[str] = ()
    score_min: int | None = None
    score_max: int | None = None
    q: str | None = None
    sort: str = "priority"
    page: int = 1
    page_size: int = 25


@dataclass
class LeadPage:
    items: list[Row] = field(default_factory=list)
    total: int = 0


class WorkspaceRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def upsert(
        self, slug: str, name: str, config_hash: str, enabled: bool, now: datetime
    ) -> None:
        stmt = pg_insert(workspaces).values(
            slug=slug, name=name, config_hash=config_hash, enabled=enabled, loaded_at=now
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[workspaces.c.slug],
            set_={
                "name": stmt.excluded.name,
                "config_hash": stmt.excluded.config_hash,
                "enabled": stmt.excluded.enabled,
                "loaded_at": stmt.excluded.loaded_at,
            },
        )
        await self.conn.execute(stmt)


class LeadRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def insert(self, values: Mapping[str, Any]) -> uuid.UUID:
        result = await self.conn.execute(leads.insert().values(**values).returning(leads.c.id))
        new_id: uuid.UUID = result.scalar_one()
        return new_id

    async def find_recent_duplicate(
        self, workspace_slug: str, email: str, since: datetime
    ) -> Row | None:
        stmt = (
            select(leads.c.id, leads.c.reference)
            .where(
                leads.c.workspace_slug == workspace_slug,
                leads.c.email == email,
                leads.c.created_at >= since,
            )
            .order_by(leads.c.created_at.desc())
            .limit(1)
        )
        row = (await self.conn.execute(stmt)).mappings().first()
        return _row(row) if row else None

    async def get(self, lead_id: uuid.UUID) -> Row | None:
        row = (
            (await self.conn.execute(select(leads).where(leads.c.id == lead_id))).mappings().first()
        )
        return _row(row) if row else None

    async def reference_exists(self, reference: str) -> bool:
        stmt = select(leads.c.id).where(leads.c.reference == reference)
        return (await self.conn.execute(stmt)).first() is not None

    async def update_status(
        self,
        lead_id: uuid.UUID,
        expected: LeadStatus,
        new: LeadStatus,
        now: datetime,
        **extra: Any,
    ) -> None:
        """Optimistic transition: only succeeds while the lead is still in ``expected``."""
        stmt = (
            update(leads)
            .where(leads.c.id == lead_id, leads.c.status == expected.value)
            .values(status=new.value, updated_at=now, **extra)
        )
        if (await self.conn.execute(stmt)).rowcount == 0:
            raise StatusConflict(
                f"Lead is no longer in status '{expected.value}'; reload and try again."
            )

    async def delete(self, lead_id: uuid.UUID) -> bool:
        result = await self.conn.execute(delete(leads).where(leads.c.id == lead_id))
        return result.rowcount > 0

    async def add_event(
        self,
        lead_id: uuid.UUID,
        type_: str,
        *,
        actor: str = "system",
        from_status: str | None = None,
        to_status: str | None = None,
        payload: Mapping[str, Any] | None = None,
        at: datetime | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "lead_id": lead_id,
            "type": type_,
            "actor": actor,
            "from_status": from_status,
            "to_status": to_status,
            "payload": dict(payload or {}),
        }
        if at is not None:
            values["created_at"] = at
        await self.conn.execute(lead_events.insert().values(**values))

    async def events(self, lead_id: uuid.UUID) -> list[Row]:
        stmt = (
            select(lead_events)
            .where(lead_events.c.lead_id == lead_id)
            .order_by(lead_events.c.created_at, lead_events.c.id)
        )
        return [_row(r) for r in (await self.conn.execute(stmt)).mappings()]

    async def runs_with_calls(self, lead_id: uuid.UUID) -> list[Row]:
        """Runs of a lead, oldest first, each with its model calls under ``calls``."""
        runs = [
            _row(r)
            for r in (
                await self.conn.execute(
                    select(agent_runs)
                    .where(agent_runs.c.lead_id == lead_id)
                    .order_by(agent_runs.c.run_number)
                )
            ).mappings()
        ]
        calls: dict[uuid.UUID, list[Row]] = {r["id"]: [] for r in runs}
        if runs:
            stmt = (
                select(llm_calls)
                .where(llm_calls.c.agent_run_id.in_(calls))
                .order_by(llm_calls.c.created_at, llm_calls.c.id)
            )
            for call in (await self.conn.execute(stmt)).mappings():
                calls[call["agent_run_id"]].append(_row(call))
        return [{**r, "calls": calls[r["id"]]} for r in runs]

    async def counts_by_workspace(self) -> dict[str, dict[str, int]]:
        stmt = select(leads.c.workspace_slug, leads.c.status, func.count()).group_by(
            leads.c.workspace_slug, leads.c.status
        )
        counts: dict[str, dict[str, int]] = {}
        for slug, status, count in (await self.conn.execute(stmt)).all():
            counts.setdefault(slug, {})[status] = count
        return counts

    async def search(self, f: LeadFilters) -> LeadPage:
        group = case(
            (leads.c.status == LeadStatus.ERROR.value, "attention"),
            (leads.c.tier == "hot", "hot"),
            (leads.c.tier == "warm", "warm"),
            (leads.c.tier == "cold", "cold"),
            else_="scoring",
        ).label("group")
        rank = case(
            *[(group.element == name, value) for name, value in GROUP_RANK.items()],
            else_=3,
        )
        conditions = self._conditions(f)
        total_stmt = select(func.count()).select_from(leads).where(*conditions)
        total = (await self.conn.execute(total_stmt)).scalar_one()

        stmt: Select[Any] = (
            select(
                leads.c.id,
                leads.c.reference,
                leads.c.workspace_slug,
                leads.c.status,
                leads.c.name,
                leads.c.email,
                leads.c.country,
                leads.c.answers,
                leads.c.score,
                leads.c.tier,
                leads.c.recommended_product,
                leads.c.error_reason,
                leads.c.created_at,
                group,
            )
            .where(*conditions)
            .order_by(*self._order(f.sort, rank))
            .limit(f.page_size)
            .offset((f.page - 1) * f.page_size)
        )
        rows = [_row(r) for r in (await self.conn.execute(stmt)).mappings()]
        return LeadPage(items=rows, total=total)

    @staticmethod
    def _conditions(f: LeadFilters) -> list[Any]:
        conditions: list[Any] = []
        if f.workspace:
            conditions.append(leads.c.workspace_slug == f.workspace)
        if f.statuses:
            conditions.append(leads.c.status.in_(list(f.statuses)))
        if f.tiers:
            conditions.append(leads.c.tier.in_(list(f.tiers)))
        if f.score_min is not None:
            conditions.append(leads.c.score >= f.score_min)
        if f.score_max is not None:
            conditions.append(leads.c.score <= f.score_max)
        if f.q:
            pattern = "%" + f.q.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
            conditions.append(
                or_(
                    leads.c.name.ilike(pattern, escape="\\"),
                    leads.c.email.ilike(pattern, escape="\\"),
                )
            )
        return conditions

    @staticmethod
    def _order(sort: str, rank: Any) -> list[Any]:
        match sort:
            case "created_at":
                return [leads.c.created_at.asc(), leads.c.id]
            case "-created_at":
                return [leads.c.created_at.desc(), leads.c.id]
            case "score":
                return [leads.c.score.asc().nulls_last(), leads.c.created_at.desc()]
            case "-score":
                return [leads.c.score.desc().nulls_last(), leads.c.created_at.desc()]
            case "name":
                return [func.lower(leads.c.name).asc(), leads.c.id]
            case "-name":
                return [func.lower(leads.c.name).desc(), leads.c.id]
            case _:
                return [
                    rank,
                    leads.c.score.desc().nulls_last(),
                    leads.c.created_at.desc(),
                    leads.c.id,
                ]


class OutboxRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def enqueue(
        self,
        *,
        event_type: str,
        aggregate_id: uuid.UUID,
        lead_id: uuid.UUID | None,
        payload: Mapping[str, Any],
        idempotency_key: str,
        now: datetime,
        status: str = "pending",
    ) -> uuid.UUID | None:
        """Insert an event; returns None when the idempotency key already exists."""
        stmt = (
            pg_insert(outbox_events)
            .values(
                event_type=event_type,
                aggregate_id=aggregate_id,
                lead_id=lead_id,
                payload=dict(payload),
                idempotency_key=idempotency_key,
                status=status,
                next_attempt_at=now,
                created_at=now,
                delivered_at=now if status == "delivered" else None,
            )
            .on_conflict_do_nothing(index_elements=[outbox_events.c.idempotency_key])
            .returning(outbox_events.c.id)
        )
        new_id: uuid.UUID | None = (await self.conn.execute(stmt)).scalar_one_or_none()
        return new_id

    async def count_for_lead(self, lead_id: uuid.UUID, event_type: str) -> int:
        stmt = (
            select(func.count())
            .select_from(outbox_events)
            .where(outbox_events.c.lead_id == lead_id, outbox_events.c.event_type == event_type)
        )
        return int((await self.conn.execute(stmt)).scalar_one())

    async def claim_due(self, now: datetime, limit: int, lock_seconds: int) -> list[Row]:
        """Atomically claim due events (pending, or processing with an expired lock)."""
        due = (
            select(outbox_events.c.id)
            .where(
                or_(
                    and_(
                        outbox_events.c.status == "pending", outbox_events.c.next_attempt_at <= now
                    ),
                    and_(
                        outbox_events.c.status == "processing", outbox_events.c.locked_until < now
                    ),
                )
            )
            .order_by(outbox_events.c.next_attempt_at, outbox_events.c.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            update(outbox_events)
            .where(outbox_events.c.id.in_(due))
            .values(status="processing", locked_until=now + timedelta(seconds=lock_seconds))
            .returning(*outbox_events.c)
        )
        return [_row(r) for r in (await self.conn.execute(stmt)).mappings()]

    async def mark_delivered(self, event_id: uuid.UUID, now: datetime) -> Row | None:
        """Mark delivered unless it already is. Returns the row when this call changed it."""
        stmt = (
            update(outbox_events)
            .where(outbox_events.c.id == event_id, outbox_events.c.status != "delivered")
            .values(status="delivered", delivered_at=now, locked_until=None, last_error=None)
            .returning(*outbox_events.c)
        )
        row = (await self.conn.execute(stmt)).mappings().first()
        return _row(row) if row else None

    async def mark_failed(
        self,
        event_id: uuid.UUID,
        *,
        error: str,
        next_attempt_at: datetime | None,
    ) -> Row | None:
        """Record a failed attempt while the event is still ``processing``.

        ``next_attempt_at=None`` marks the event dead.
        """
        values: dict[str, Any] = {
            "attempts": outbox_events.c.attempts + 1,
            "last_error": error[:500],
            "locked_until": None,
        }
        if next_attempt_at is None:
            values["status"] = "dead"
        else:
            values.update(status="pending", next_attempt_at=next_attempt_at)
        stmt = (
            update(outbox_events)
            .where(outbox_events.c.id == event_id, outbox_events.c.status == "processing")
            .values(**values)
            .returning(*outbox_events.c)
        )
        row = (await self.conn.execute(stmt)).mappings().first()
        return _row(row) if row else None

    async def get(self, event_id: uuid.UUID) -> Row | None:
        row = (
            (await self.conn.execute(select(outbox_events).where(outbox_events.c.id == event_id)))
            .mappings()
            .first()
        )
        return _row(row) if row else None

    async def for_lead(self, lead_id: uuid.UUID) -> list[Row]:
        stmt = (
            select(outbox_events)
            .where(outbox_events.c.lead_id == lead_id)
            .order_by(outbox_events.c.created_at)
        )
        return [_row(r) for r in (await self.conn.execute(stmt)).mappings()]

    async def list_by_status(self, status: str, limit: int = 100) -> list[Row]:
        stmt = (
            select(outbox_events)
            .where(outbox_events.c.status == status)
            .order_by(outbox_events.c.created_at.desc())
            .limit(limit)
        )
        return [_row(r) for r in (await self.conn.execute(stmt)).mappings()]


class RateLimitRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def hit(self, key: str, window_start: datetime) -> int:
        """Increment the fixed-window counter and return the new count (one round trip)."""
        stmt = (
            pg_insert(rate_limit_hits)
            .values(key=key, window_start=window_start, count=1)
            .on_conflict_do_update(
                index_elements=[rate_limit_hits.c.key, rate_limit_hits.c.window_start],
                set_={"count": rate_limit_hits.c.count + 1},
            )
            .returning(rate_limit_hits.c.count)
        )
        return int((await self.conn.execute(stmt)).scalar_one())

    async def purge_before(self, cutoff: datetime) -> int:
        result = await self.conn.execute(
            delete(rate_limit_hits).where(rate_limit_hits.c.window_start < cutoff)
        )
        return int(result.rowcount)


__all__ = [
    "GROUP_RANK",
    "SORTS",
    "LeadFilters",
    "LeadPage",
    "LeadRepository",
    "OutboxRepository",
    "RateLimitRepository",
    "StatusConflict",
    "WorkspaceRepository",
]
