"""The dashboard's "Ask the docs": one question answered from a workspace's knowledge base.

Each question is its own agent run (``kind = 'kb_chat'``, no lead) so its model call is recorded
and counted by the same budget and per-run call caps as the qualification agent, and the answer is
logged in ``kb_queries``. Retrieval, citation validation and escaping are the answer node's.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from lead_qualifier.agent.graph import NOT_COVERED_CHAT, GraphDeps, answer_questions
from lead_qualifier.agent.models import AnswerResult
from lead_qualifier.agent.prompts import ANSWER_VERSION
from lead_qualifier.config import Settings
from lead_qualifier.domain.draft_guard import guess_language
from lead_qualifier.domain.workspace import WorkspaceConfig
from lead_qualifier.infrastructure.db.tables import agent_runs, kb_queries, llm_calls
from lead_qualifier.infrastructure.llm.router import model_for
from lead_qualifier.ports.clock import Clock
from lead_qualifier.ports.knowledge import KnowledgeRetriever
from lead_qualifier.ports.llm import LLMError, LLMProvider
from lead_qualifier.services.rate_limit import Limit, RateLimiter

GRAPH_VERSION = "kb-chat@1"
LOG_LIMIT = 50


@dataclass(frozen=True)
class KbChatEntry:
    id: uuid.UUID
    question: str
    answer: str
    covered: bool
    citations: list[dict[str, Any]]
    created_at: datetime


class KbChatUnavailable(Exception):
    """The model call failed; ``code`` is the stable LLM error code (no provider text)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class KbChatService:
    def __init__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        provider: LLMProvider,
        clock: Clock,
        limiter: RateLimiter,
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._provider = provider
        self._clock = clock
        self._limiter = limiter

    async def ask(
        self,
        workspace: WorkspaceConfig,
        retriever: KnowledgeRetriever | None,
        question: str,
        language: str | None = None,
    ) -> KbChatEntry:
        # One bucket per workspace: the operator credential is shared and every request comes from
        # the dashboard server, so a per-IP key would tell nothing. Failed calls count too, and the
        # fixed window can let through up to twice the limit around a window boundary.
        await self._limiter.hit(
            [Limit(f"kb_ask:{workspace.slug}", self._settings.kb_ask_per_hour, 3600)]
        )
        lang = language or guess_language(question) or workspace.languages.default
        if lang not in workspace.languages.supported:
            lang = workspace.languages.default
        started = self._clock.now()
        run_id = await self._start(workspace.slug, started)
        deps = GraphDeps(
            provider=self._provider,
            workspace=workspace,
            agent_run_id=run_id,
            model_for=lambda task: model_for(self._settings, task),
            knowledge=retriever,
        )
        try:
            (answer,) = await answer_questions(deps, [question], lang, NOT_COVERED_CHAT)
        except LLMError as exc:
            await self._fail(run_id, started, exc.code)
            raise KbChatUnavailable(exc.code) from exc
        except BaseException as exc:  # includes cancellation: the run must never stay "running"
            await asyncio.shield(
                self._fail(run_id, started, f"internal_error: {type(exc).__name__}")
            )
            raise
        return await self._complete(run_id, started, workspace.slug, answer)

    async def recent(self, workspace_slug: str, limit: int = 10) -> list[KbChatEntry]:
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    sa.select(kb_queries)
                    .where(kb_queries.c.workspace_slug == workspace_slug)
                    .order_by(kb_queries.c.created_at.desc())
                    .limit(min(limit, LOG_LIMIT))
                )
            ).mappings()
            return [_entry(r) for r in rows]

    async def _start(self, slug: str, now: datetime) -> uuid.UUID:
        run_id = uuid.uuid4()
        async with self._engine.begin() as conn:
            await conn.execute(
                sa.insert(agent_runs).values(
                    id=run_id,
                    kind="kb_chat",
                    workspace_slug=slug,
                    thread_id=f"kbchat:{run_id}",
                    run_number=1,
                    graph_version=GRAPH_VERSION,
                    prompt_versions={"answer": ANSWER_VERSION},
                    started_at=now,
                )
            )
        return run_id

    async def _close(
        self, conn: AsyncConnection, run_id: uuid.UUID, started: datetime, error: str | None
    ) -> datetime:
        now = self._clock.now()
        cost = (
            await conn.execute(
                sa.select(sa.func.coalesce(sa.func.sum(llm_calls.c.cost_usd), 0)).where(
                    llm_calls.c.agent_run_id == run_id
                )
            )
        ).scalar_one()
        await conn.execute(
            sa.update(agent_runs)
            .where(agent_runs.c.id == run_id)
            .values(
                status="failed" if error else "completed",
                finished_at=now,
                duration_ms=int((now - started).total_seconds() * 1000),
                total_cost_usd=Decimal(cost),
                error=error,
            )
        )
        return now

    async def _fail(self, run_id: uuid.UUID, started: datetime, code: str) -> None:
        async with self._engine.begin() as conn:
            await self._close(conn, run_id, started, code)

    async def _complete(
        self, run_id: uuid.UUID, started: datetime, workspace: str, answer: AnswerResult
    ) -> KbChatEntry:
        citations = [c.model_dump() for c in answer.citations]
        async with self._engine.begin() as conn:
            now = await self._close(conn, run_id, started, None)
            entry_id = (
                await conn.execute(
                    sa.insert(kb_queries)
                    .values(
                        workspace_slug=workspace,
                        agent_run_id=run_id,
                        question=answer.question,
                        answer=answer.answer,
                        covered=answer.covered,
                        citations=citations,
                        created_at=now,
                    )
                    .returning(kb_queries.c.id)
                )
            ).scalar_one()
        return KbChatEntry(entry_id, answer.question, answer.answer, answer.covered, citations, now)


def _entry(row: Any) -> KbChatEntry:
    return KbChatEntry(
        row["id"],
        row["question"],
        row["answer"],
        row["covered"],
        row["citations"],
        row["created_at"],
    )
