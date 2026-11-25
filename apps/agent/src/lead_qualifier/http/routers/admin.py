"""Admin API: called only by the Next.js server (bearer token), never by browsers."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from datetime import date
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Query, Request, Response

from lead_qualifier.domain.errors import NotFound, Unavailable, UpstreamTimeout, ValidationFailed
from lead_qualifier.domain.lead import LeadStatus
from lead_qualifier.domain.workspace import Tier
from lead_qualifier.http.auth import require_admin
from lead_qualifier.http.deps import EngineDep, KbChatDep, KbDep, RegistryDep, SettingsDep
from lead_qualifier.http.schemas import (
    AgentRunOut,
    InstanceStatus,
    KbAskRequest,
    KbChatEntryOut,
    KbReindexResult,
    LeadDetail,
    LeadList,
    LeadListItem,
    LlmCallOut,
    MetricsOut,
    OutboxEventOut,
    RetriggerResult,
    ReviewRequest,
    ReviewResult,
    TierThresholds,
    WorkspaceSummary,
)
from lead_qualifier.http.views import interest_label, lead_detail
from lead_qualifier.infrastructure.db.repositories import (
    SORTS,
    AnswerRepository,
    LeadFilters,
    LeadRepository,
    OutboxRepository,
)
from lead_qualifier.infrastructure.db.tables import messages
from lead_qualifier.services import retrigger as operator
from lead_qualifier.services.kb import WorkspaceRetriever
from lead_qualifier.services.kb_chat import KbChatUnavailable
from lead_qualifier.services.metrics import MetricsWindow, compute_metrics
from lead_qualifier.workspaces.loader import LoadedWorkspace

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


@router.get("/status", response_model=InstanceStatus)
async def instance_status(settings: SettingsDep) -> InstanceStatus:
    return InstanceStatus(
        llm_provider=settings.llm_provider, demo_mode=settings.llm_provider == "fake"
    )


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
        kb_answers = await AnswerRepository(conn).for_lead(lead_id)
        drafts = [
            dict(m)
            for m in (
                await conn.execute(
                    sa.select(messages)
                    .where(messages.c.lead_id == lead_id)
                    .order_by(messages.c.version)
                )
            )
            .mappings()
            .all()
        ]
    ws = registry.get(lead["workspace_slug"])
    return lead_detail(lead, events, outbox, ws.config if ws else None, drafts, kb_answers)


@router.get("/leads/{lead_id}/runs", response_model=list[AgentRunOut])
async def lead_runs(lead_id: uuid.UUID, engine: EngineDep) -> list[AgentRunOut]:
    """Agent runs of a lead with their model calls (tokens, latency, cost, prompt version)."""
    async with engine.connect() as conn:
        repo = LeadRepository(conn)
        if await repo.get(lead_id) is None:
            raise NotFound("Unknown lead.")
        runs = await repo.runs_with_calls(lead_id)
    return [
        AgentRunOut(
            **{k: run[k] for k in AgentRunOut.model_fields if k != "calls"},
            calls=[
                LlmCallOut(
                    **{k: c[k] for k in LlmCallOut.model_fields if k != "prompt_version"},
                    prompt_version=(run["prompt_versions"] or {}).get(c["node"]),
                )
                for c in run["calls"]
            ],
        )
        for run in runs
    ]


@router.post("/leads/{lead_id}/retrigger", response_model=RetriggerResult, status_code=202)
async def retrigger_lead(
    lead_id: uuid.UUID, request: Request, engine: EngineDep
) -> RetriggerResult:
    result = await operator.retrigger(engine, lead_id, request.app.state.clock)
    return RetriggerResult(event_id=uuid.UUID(result["event_id"]), attempt=result["attempt"])


@router.delete("/leads/{lead_id}", status_code=204)
async def delete_lead(lead_id: uuid.UUID, engine: EngineDep, request: Request) -> Response:
    await operator.delete_lead(engine, lead_id, request.app.state.checkpointer)
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


@router.post("/leads/{lead_id}/review", response_model=ReviewResult)
async def review_lead(lead_id: uuid.UUID, payload: ReviewRequest, request: Request) -> ReviewResult:
    """Approve, edit, reject or regenerate the pending draft. 409 when the lead is not in review."""
    outcome = await request.app.state.reviewer.review(
        lead_id,
        payload.action,
        subject=getattr(payload, "subject", None),
        body=getattr(payload, "body", None),
        feedback=getattr(payload, "feedback", None),
        note=getattr(payload, "note", None),
        override=getattr(payload, "override", False),
    )
    return ReviewResult(**vars(outcome))


@router.get("/metrics", response_model=MetricsOut)
async def metrics(
    registry: RegistryDep,
    engine: EngineDep,
    settings: SettingsDep,
    request: Request,
    workspace: Annotated[str | None, Query(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)] = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> MetricsOut:
    """Counts, score distribution, time to qualify, spend and leads per day for a UTC day range
    (default: the last 30 days)."""
    ws = registry.get(workspace) if workspace else None
    if workspace and ws is None:
        raise ValidationFailed("Unknown workspace.")
    today = request.app.state.clock.now().date()
    window = MetricsWindow.resolve(from_, to, today)
    thresholds = None
    if ws is not None:
        tiers = ws.config.qualification.tiers
        thresholds = TierThresholds(hot_min=tiers.hot_min, warm_min=tiers.warm_min)
    return await compute_metrics(
        engine,
        window,
        workspace=workspace,
        budget_usd=settings.llm_budget_usd,
        tier_thresholds=thresholds,
    )


@router.post("/kb/{slug}/reindex", response_model=KbReindexResult)
async def reindex_knowledge_base(
    slug: str, registry: RegistryDep, kb: KbDep, settings: SettingsDep, force: bool = False
) -> KbReindexResult:
    """Re-read the workspace's Markdown files; unchanged documents are skipped unless forced."""
    workspace = registry.get(slug)
    if workspace is None or not workspace.enabled:
        raise NotFound("Unknown workspace.")
    if not workspace.config.knowledge_base.enabled:
        raise ValidationFailed("The knowledge base is disabled for this workspace.")
    kb_dir = workspace.path / workspace.config.knowledge_base.path
    try:
        async with asyncio.timeout(settings.kb_reindex_timeout_seconds):
            result = await kb.ingest(slug, kb_dir, force=force)
    except TimeoutError:
        raise UpstreamTimeout(
            "The reindex took too long; warm the embedding model first (see the README)."
        ) from None
    return KbReindexResult(workspace=slug, **result.as_dict())


def _kb_workspace(registry: RegistryDep, slug: str) -> LoadedWorkspace:
    workspace = registry.get(slug)
    if workspace is None or not workspace.enabled:
        raise NotFound("Unknown workspace.")
    if not workspace.config.knowledge_base.enabled:
        raise ValidationFailed("The knowledge base is disabled for this workspace.")
    return workspace


@router.post("/kb/{slug}/ask", response_model=KbChatEntryOut)
async def ask_knowledge_base(
    slug: str,
    body: KbAskRequest,
    registry: RegistryDep,
    chat: KbChatDep,
    kb: KbDep,
    settings: SettingsDep,
) -> KbChatEntryOut:
    """Answer one question from the workspace's documents, with sources or "not covered"."""
    workspace = _kb_workspace(registry, slug)
    retriever = WorkspaceRetriever(
        kb, slug, top_k=settings.kb_top_k, min_similarity=settings.kb_min_similarity
    )
    try:
        entry = await chat.ask(workspace.config, retriever, body.question.strip(), body.language)
    except KbChatUnavailable as exc:
        raise Unavailable(
            "The AI provider could not answer right now. Try again in a moment."
        ) from exc
    return KbChatEntryOut(**asdict(entry))


@router.get("/kb/{slug}/queries", response_model=list[KbChatEntryOut])
async def recent_kb_queries(
    slug: str,
    registry: RegistryDep,
    chat: KbChatDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[KbChatEntryOut]:
    _kb_workspace(registry, slug)
    return [KbChatEntryOut(**asdict(e)) for e in await chat.recent(slug, limit)]
