"""Qualify a lead: start an agent run, execute the graph, persist the outcome."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.agent.graph import GraphDeps, SendGateway, run_qualification
from lead_qualifier.agent.models import LeadInput
from lead_qualifier.agent.prompts import PROMPT_VERSIONS
from lead_qualifier.config import Settings
from lead_qualifier.domain.errors import Conflict, NotFound, RateLimited
from lead_qualifier.domain.lead import LeadStatus, LeadTrigger, next_status
from lead_qualifier.infrastructure.checkpoint import PostgresCheckpointer
from lead_qualifier.infrastructure.db.repositories import AnswerRepository, LeadRepository
from lead_qualifier.infrastructure.db.tables import agent_runs, llm_calls, messages
from lead_qualifier.infrastructure.llm.router import model_for
from lead_qualifier.logging import get_logger
from lead_qualifier.ports.clock import Clock
from lead_qualifier.ports.knowledge import KnowledgeRetriever
from lead_qualifier.ports.llm import LLMProvider
from lead_qualifier.services.kb import KnowledgeBaseService, WorkspaceRetriever
from lead_qualifier.workspaces.loader import WorkspaceRegistry

log = get_logger("qualify")
GRAPH_VERSION = "qualify-answer-draft-review@1"
STARTABLE = {LeadStatus.NEW: LeadTrigger.QUALIFY_STARTED, LeadStatus.ERROR: LeadTrigger.RETRY}


@dataclass(frozen=True)
class QualifyOutcome:
    lead_id: uuid.UUID
    agent_run_id: uuid.UUID
    status: str
    score: int | None = None
    tier: str | None = None
    recommended_product: str | None = None
    error_reason: str | None = None


class QualifyService:
    def __init__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        registry: WorkspaceRegistry,
        provider: LLMProvider,
        clock: Clock,
        checkpointer: PostgresCheckpointer,
        kb: KnowledgeBaseService | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.registry = registry
        self.provider = provider
        self.clock = clock
        self.checkpointer = checkpointer
        self.kb = kb
        self.send_gateway: SendGateway | None = None

    def attach_send_gateway(self, gateway: SendGateway) -> None:
        """Wire the review service in explicitly (it needs this service, so it cannot be a
        constructor argument)."""
        self.send_gateway = gateway

    async def qualify(self, lead_id: uuid.UUID) -> QualifyOutcome:
        """Run the graph up to the human-review interrupt for a ``new`` or ``error`` lead.

        Each call is a fresh run and thread. On success the draft is stored as a message and the
        lead moves to ``pending_review``; the graph stays paused in the Postgres checkpointer.
        """
        lead, workspace, run_id = await self._start(lead_id)
        deps = self.deps_for(workspace, run_id)
        thread_id = await self._thread_id(run_id)
        try:
            state = await run_qualification(
                _lead_input(lead),
                deps,
                checkpointer=await self.checkpointer.get(),
                thread_id=thread_id,
            )
        except Exception as exc:  # never leave a lead stuck in "qualifying"
            log.error("qualify_crashed", lead_id=str(lead_id), error_type=type(exc).__name__)
            state = {"error": f"internal_error: {type(exc).__name__}"}
        return await self.finish(lead_id, run_id, state)

    def deps_for(self, workspace: Any, run_id: uuid.UUID) -> GraphDeps:
        return GraphDeps(
            provider=self.provider,
            workspace=workspace,
            agent_run_id=run_id,
            model_for=lambda task: model_for(self.settings, task),
            send=self.send_gateway,
            knowledge=self._retriever(workspace),
        )

    def _retriever(self, workspace: Any) -> KnowledgeRetriever | None:
        if self.kb is None or not workspace.knowledge_base.enabled:
            return None
        return WorkspaceRetriever(
            self.kb,
            workspace.slug,
            top_k=self.settings.kb_top_k,
            min_similarity=self.settings.kb_min_similarity,
        )

    async def _thread_id(self, run_id: uuid.UUID) -> str:
        async with self.engine.connect() as conn:
            thread_id: str = (
                await conn.execute(
                    sa.select(agent_runs.c.thread_id).where(agent_runs.c.id == run_id)
                )
            ).scalar_one()
        return thread_id

    async def _start(self, lead_id: uuid.UUID) -> tuple[dict[str, Any], Any, uuid.UUID]:
        now = self.clock.now()
        async with self.engine.begin() as conn:
            leads = LeadRepository(conn)
            lead = await leads.get(lead_id)
            if lead is None:
                raise NotFound("Unknown lead.")
            status = LeadStatus(lead["status"])
            trigger = STARTABLE.get(status)
            if trigger is None:
                raise Conflict(f"A lead in status '{status.value}' cannot be qualified.")
            workspace = self.registry.get(lead["workspace_slug"])
            if workspace is None:
                raise NotFound("The lead's workspace is not loaded.")
            recent = (
                await conn.execute(
                    sa.select(sa.func.count())
                    .select_from(agent_runs)
                    .where(
                        agent_runs.c.lead_id == lead_id,
                        agent_runs.c.started_at > now - timedelta(days=1),
                    )
                )
            ).scalar_one()
            if recent >= self.settings.qualify_max_runs_per_day:
                raise RateLimited(
                    f"This lead was already qualified {recent} times in the last 24 hours."
                )
            new_status = next_status(status, trigger)
            await leads.update_status(lead_id, status, new_status, now, error_reason=None)
            await leads.add_event(
                lead_id,
                "status_changed",
                from_status=status.value,
                to_status=new_status.value,
                payload={"trigger": trigger.value},
                at=now,
            )
            run_number = (
                await conn.execute(
                    sa.select(sa.func.count())
                    .select_from(agent_runs)
                    .where(agent_runs.c.lead_id == lead_id)
                )
            ).scalar_one() + 1
            run_id = (
                await conn.execute(
                    sa.insert(agent_runs)
                    .values(
                        lead_id=lead_id,
                        thread_id=f"lead:{lead_id}:run:{run_number}",
                        run_number=run_number,
                        graph_version=GRAPH_VERSION,
                        prompt_versions=PROMPT_VERSIONS,
                        started_at=now,
                    )
                    .returning(agent_runs.c.id)
                )
            ).scalar_one()
        return dict(lead), workspace.config, run_id

    async def finish(
        self, lead_id: uuid.UUID, run_id: uuid.UUID, state: Mapping[str, Any]
    ) -> QualifyOutcome:
        now = self.clock.now()
        error: str | None = state.get("error")
        async with self.engine.begin() as conn:
            leads = LeadRepository(conn)
            cost = (
                await conn.execute(
                    sa.select(sa.func.coalesce(sa.func.sum(llm_calls.c.cost_usd), 0)).where(
                        llm_calls.c.agent_run_id == run_id
                    )
                )
            ).scalar_one()
            started = (
                await conn.execute(
                    sa.select(agent_runs.c.started_at).where(agent_runs.c.id == run_id)
                )
            ).scalar_one()
            await conn.execute(
                sa.update(agent_runs)
                .where(agent_runs.c.id == run_id)
                .values(
                    status="failed" if error else "interrupted",
                    finished_at=now if error else None,
                    duration_ms=int((now - started).total_seconds() * 1000),
                    total_cost_usd=Decimal(cost),
                    error=error,
                )
            )
            if error:
                await leads.update_status(
                    lead_id,
                    LeadStatus.QUALIFYING,
                    next_status(LeadStatus.QUALIFYING, LeadTrigger.FAILED),
                    now,
                    error_reason=error,
                )
                await leads.add_event(
                    lead_id,
                    "status_changed",
                    from_status=LeadStatus.QUALIFYING.value,
                    to_status=LeadStatus.ERROR.value,
                    payload={"trigger": LeadTrigger.FAILED.value, "reason": error},
                    at=now,
                )
                log.warning("qualify_failed", lead_id=str(lead_id), reason=error.split(":")[0])
                return QualifyOutcome(lead_id, run_id, LeadStatus.ERROR.value, error_reason=error)
            if "__interrupt__" not in state or "draft" not in state:
                raise RuntimeError("the graph ended without a draft to review")
            result = state["result"]
            draft = state["draft"]
            version = (
                await conn.execute(
                    sa.select(sa.func.coalesce(sa.func.max(messages.c.version), 0)).where(
                        messages.c.lead_id == lead_id
                    )
                )
            ).scalar_one() + 1
            lead_row = await leads.get(lead_id)
            assert lead_row is not None
            if "kb_answers" in state:
                await AnswerRepository(conn).replace_for_lead(
                    lead_id, run_id, state["kb_answers"], now
                )
            await conn.execute(
                sa.insert(messages).values(
                    lead_id=lead_id,
                    agent_run_id=run_id,
                    version=version,
                    language=state["draft_language"],
                    channel="email",
                    channel_recipient=lead_row["email"],
                    subject=draft.subject,
                    body=draft.body,
                    short_body=draft.short_body,
                    guard_warnings=state.get("guard_problems", []),
                    status="draft",
                )
            )
            await conn.execute(
                sa.update(agent_runs).where(agent_runs.c.id == run_id).values(status="interrupted")
            )
            await leads.update_status(
                lead_id,
                LeadStatus.QUALIFYING,
                next_status(LeadStatus.QUALIFYING, LeadTrigger.REVIEW_READY),
                now,
                score=result.score,
                tier=result.tier.value,
                recommended_product=result.recommended_product,
                detected_language=result.profile.detected_language,
                qualification=result.model_dump(mode="json", exclude={"score", "tier"}),
                qualified_at=now,
            )
            await leads.add_event(
                lead_id,
                "status_changed",
                from_status=LeadStatus.QUALIFYING.value,
                to_status=LeadStatus.PENDING_REVIEW.value,
                payload={"trigger": LeadTrigger.REVIEW_READY.value, "message_version": version},
                at=now,
            )
            if result.profile.injection_suspected:
                await leads.add_event(
                    lead_id,
                    "injection_suspected",
                    payload={"tier_capped": result.tier_capped},
                    at=now,
                )
        log.info("qualify_done", lead_id=str(lead_id), score=result.score, tier=result.tier.value)
        return QualifyOutcome(
            lead_id,
            run_id,
            LeadStatus.PENDING_REVIEW.value,
            score=result.score,
            tier=result.tier.value,
            recommended_product=result.recommended_product,
        )


def _lead_input(lead: dict[str, Any]) -> LeadInput:
    return LeadInput(
        name=lead["name"],
        email=lead["email"],
        country=lead["country"],
        locale=lead["locale"],
        answers=lead["answers"],
        free_text=lead["free_text"],
    )
