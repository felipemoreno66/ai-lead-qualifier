"""Decorator that persists every provider call, prices it and enforces the budget."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
import structlog
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.infrastructure.db.tables import llm_calls
from lead_qualifier.infrastructure.llm.pricing import PricingTable
from lead_qualifier.ports.llm import (
    BudgetExceeded,
    CallLimitExceeded,
    LLMError,
    LLMProvider,
    LLMResult,
    StructuredRequest,
    TextRequest,
    Usage,
)

log = structlog.get_logger(__name__)


class RecordingProvider:
    """Wraps any adapter. Each call (including failed attempts) becomes one ``llm_calls`` row,
    written in its own transaction so it survives a rolled-back caller."""

    def __init__(
        self,
        inner: LLMProvider,
        engine: AsyncEngine,
        pricing: PricingTable,
        *,
        budget_usd: Decimal,
        max_calls_per_run: int,
    ) -> None:
        self._inner = inner
        self._engine = engine
        self._pricing = pricing
        self._budget = budget_usd
        self._max_calls = max_calls_per_run

    @property
    def name(self) -> str:
        return self._inner.name

    async def _guard(self, req: StructuredRequest[Any] | TextRequest) -> None:
        if self._inner.name == "fake":
            return
        async with self._engine.connect() as conn:
            spent = (await conn.execute(sa.text("SELECT spent_usd FROM llm_budget"))).scalar_one()
            if Decimal(spent) >= self._budget:
                raise BudgetExceeded(
                    f"LLM budget of {self._budget} USD reached (spent {spent})",
                    provider=self.name,
                    model=req.model,
                )
            if req.agent_run_id is not None:
                used = (
                    await conn.execute(
                        sa.select(sa.func.count())
                        .select_from(llm_calls)
                        .where(llm_calls.c.agent_run_id == req.agent_run_id)
                    )
                ).scalar_one()
                if used >= self._max_calls:
                    raise CallLimitExceeded(
                        f"agent run already made {used} LLM calls (limit {self._max_calls})",
                        provider=self.name,
                        model=req.model,
                    )

    async def _record(
        self,
        req: StructuredRequest[Any] | TextRequest,
        *,
        usage: Usage,
        latency_ms: int,
        provider: str,
        model: str,
        success: bool,
        error_code: str | None,
        response: object,
    ) -> None:
        cost = self._pricing.cost(model, usage, provider=provider)
        request = {
            "task": req.task,
            "system": req.system,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "effort": req.effort,
        }
        async with self._engine.begin() as conn:
            await conn.execute(
                sa.insert(llm_calls).values(
                    agent_run_id=req.agent_run_id,
                    node=req.node or req.task,
                    provider=provider,
                    model=model,
                    attempt=req.attempt,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_write_tokens=usage.cache_write_tokens,
                    latency_ms=latency_ms,
                    cost_usd=cost.usd,
                    is_estimated=cost.is_estimated,
                    success=success,
                    error_code=error_code,
                    request=request,
                    response=response,
                )
            )

    async def _call[R](
        self, req: StructuredRequest[Any] | TextRequest, call: Any, to_json: Any
    ) -> LLMResult[R]:
        await self._guard(req)
        try:
            result: LLMResult[R] = await call(req)
        except LLMError as exc:
            await self._record(
                req,
                usage=exc.usage,
                latency_ms=exc.latency_ms,
                provider=exc.provider or self.name,
                model=exc.model or req.model,
                success=False,
                error_code=exc.code,
                response={"error": str(exc), "raw_text": getattr(exc, "raw_text", None)},
            )
            raise
        await self._record(
            req,
            usage=result.usage,
            latency_ms=result.latency_ms,
            provider=result.provider,
            model=result.model,
            success=True,
            error_code=None,
            response=to_json(result),
        )
        return result

    async def generate_structured[T: BaseModel](self, req: StructuredRequest[T]) -> LLMResult[T]:
        return await self._call(
            req,
            self._inner.generate_structured,
            lambda r: json.loads(r.value.model_dump_json()),
        )

    async def generate_text(self, req: TextRequest) -> LLMResult[str]:
        return await self._call(req, self._inner.generate_text, lambda r: {"text": r.value})
