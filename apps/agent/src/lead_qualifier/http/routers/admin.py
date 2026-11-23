"""Admin API: called only by the Next.js server (bearer token), never by browsers."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from lead_qualifier.domain.errors import NotFound, ValidationFailed
from lead_qualifier.domain.lead import LeadStatus
from lead_qualifier.domain.workspace import Tier
from lead_qualifier.http.auth import require_admin
from lead_qualifier.http.deps import EngineDep, RegistryDep
from lead_qualifier.http.schemas import (
    LeadDetail,
    LeadList,
    LeadListItem,
    OutboxEventOut,
    RetriggerResult,
    WorkspaceSummary,
)
from lead_qualifier.http.views import interest_label, lead_detail
from lead_qualifier.infrastructure.db.repositories import (
    SORTS,
    LeadFilters,
    LeadRepository,
    OutboxRepository,
)
from lead_qualifier.services import retrigger as operator

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[require_admin])


def _split(values: list[str], allowed: set[str], name: str) -> list[str]:
    items = [v.strip() for raw in values for v in raw.split(",") if v.strip()]
    bad = sorted(set(items) - allowed)
    if bad:
        raise ValidationFailed(
            f"Unknown {name}: {', '.join(bad)}.",
            errors=[{"loc": ["query", name], "msg": "invalid"}],
        )
    return items


@router.get("/workspaces", response_model=list[WorkspaceSummary])
async def list_workspaces(registry: RegistryDep, engine: EngineDep) -> list[WorkspaceSummary]:
    async with engine.connect() as conn:
        counts = await LeadRepository(conn).counts_by_workspace()
    return [
        WorkspaceSummary(
            slug=w.slug,
            name=w.config.profile.name,
            enabled=w.enabled,
            draft=w.is_draft,
            lead_count=sum(counts.get(w.slug, {}).values()),
            by_status=counts.get(w.slug, {}),
        )
        for w in registry.all()
    ]


@router.get("/leads", response_model=LeadList)
async def list_leads(
    registry: RegistryDep,
    engine: EngineDep,
    workspace: str | None = None,
    status: Annotated[list[str] | None, Query()] = None,
    tier: Annotated[list[str] | None, Query()] = None,
    score_min: Annotated[int | None, Query(ge=0, le=100)] = None,
    score_max: Annotated[int | None, Query(ge=0, le=100)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    sort: str = "priority",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> LeadList:
    if sort not in SORTS:
        raise ValidationFailed(f"sort must be one of: {', '.join(SORTS)}.")
    filters = LeadFilters(
        workspace=workspace,
        statuses=_split(status or [], {s.value for s in LeadStatus}, "status"),
        tiers=_split(tier or [], {t.value for t in Tier}, "tier"),
        score_min=score_min,
        score_max=score_max,
        q=(q or "").strip() or None,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    async with engine.connect() as conn:
        result = await LeadRepository(conn).search(filters)
    items = []
    for row in result.items:
        ws = registry.get(row["workspace_slug"])
        items.append(
            LeadListItem(
                **{k: row[k] for k in LeadListItem.model_fields if k != "interest"},
                interest=interest_label(ws.config if ws else None, row["answers"]),
            )
        )
    return LeadList(items=items, page=page, page_size=page_size, total=result.total)


@router.get("/leads/{lead_id}", response_model=LeadDetail)
async def get_lead(lead_id: uuid.UUID, registry: RegistryDep, engine: EngineDep) -> LeadDetail:
    async with engine.connect() as conn:
        leads = LeadRepository(conn)
        lead = await leads.get(lead_id)
        if lead is None:
            raise NotFound("Unknown lead.")
        events = await leads.events(lead_id)
        outbox = await OutboxRepository(conn).for_lead(lead_id)
    ws = registry.get(lead["workspace_slug"])
    return lead_detail(lead, events, outbox, ws.config if ws else None)


@router.post("/leads/{lead_id}/retrigger", response_model=RetriggerResult, status_code=202)
async def retrigger_lead(
    lead_id: uuid.UUID, request: Request, engine: EngineDep
) -> RetriggerResult:
    result = await operator.retrigger(engine, lead_id, request.app.state.clock)
    return RetriggerResult(event_id=uuid.UUID(result["event_id"]), attempt=result["attempt"])


@router.delete("/leads/{lead_id}", status_code=204)
async def delete_lead(lead_id: uuid.UUID, engine: EngineDep) -> Response:
    await operator.delete_lead(engine, lead_id)
    return Response(status_code=204)


@router.get("/outbox", response_model=list[OutboxEventOut])
async def list_outbox(
    engine: EngineDep, status: str = "dead", limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> list[OutboxEventOut]:
    if status not in {"pending", "processing", "delivered", "dead"}:
        raise ValidationFailed("status must be pending, processing, delivered or dead.")
    async with engine.connect() as conn:
        rows = await OutboxRepository(conn).list_by_status(status, limit)
    return [OutboxEventOut(**{k: r[k] for k in OutboxEventOut.model_fields}) for r in rows]
