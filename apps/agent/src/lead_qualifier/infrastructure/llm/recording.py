"""Decorator that persists every provider call, prices it and enforces the budget."""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from collections.abc import Callable
from decimal import Decimal
from functools import partial
from typing import Any

import sqlalchemy as sa
import structlog
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.infrastructure.db.tables import llm_calls, llm_spend
from lead_qualifier.infrastructure.llm.pricing import PricingTable
from lead_qualifier.infrastructure.llm.redact import redact
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
BUDGET_LOCK_KEY = 7_201_001  # pg_advisory_xact_lock key shared by every process using the budget
MAX_TOKENS_CEILING = 8192


def _error_payload(exc: BaseException, *, detail: bool = True) -> dict[str, Any]:
    if not detail:
        return {"error": type(exc).__name__}
    return {"error": str(exc), "raw_text": getattr(exc, "raw_text", None)}


class RecordingProvider:
    """Wraps any adapter. Each call (including failed attempts) becomes one ``llm_calls`` row,
    written in its own transaction so it survives a rolled-back caller.

    The budget is a lifetime cap over the append-only ``llm_spend`` ledger (not ``llm_calls``, which
    is purged and cascades with leads). The guard runs under a Postgres advisory lock, compares
    ``spent + worst case of this call`` with the budget and persists a reservation that every
    process sees until it is settled with the real cost. Reservations never expire: only an
    explicit settle lowers them, so a crash leaves a conservative worst-case charge.
    """

    def __init__(
        self,
        inner: LLMProvider,
        engine: AsyncEngine,
        pricing: PricingTable,
        *,
        budget_usd: Decimal,
        max_calls_per_run: int,
        max_tokens_ceiling: int = MAX_TOKENS_CEILING,
    ) -> None:
        self._inner = inner
        self._engine = engine
        self._pricing = pricing
        self._budget = budget_usd
        self._max_calls = max_calls_per_run
        self._ceiling = max_tokens_ceiling

    @property
    def name(self) -> str:
        return self._inner.name

    async def _reserve(
        self, req: StructuredRequest[Any] | TextRequest
    ) -> tuple[uuid.UUID | None, Decimal]:
        """Check budget and call cap, then persist a reservation in the same locked transaction.

        The reservation counts in ``llm_budget`` for every process until it is settled (or expires
        after 10 minutes), so concurrent callers cannot jointly overshoot the cap.
        """
        assert req.agent_run_id is not None
        if self._inner.name == "fake":
            return None, Decimal(0)
        chars = len(req.system) + sum(len(m.content) for m in req.messages)
        worst = self._pricing.worst_case(req.model, input_chars=chars, max_tokens=req.max_tokens)
        async with self._engine.begin() as conn:
            await conn.execute(sa.text("SELECT pg_advisory_xact_lock(:k)"), {"k": BUDGET_LOCK_KEY})
            spent = Decimal(
                (await conn.execute(sa.text("SELECT spent_usd FROM llm_budget"))).scalar_one()
            )
            if spent + worst > self._budget:
                raise BudgetExceeded(
                    f"LLM budget of {self._budget} USD would be exceeded "
                    f"(spent or reserved {spent}, this call up to {worst})",
                    provider=self.name,
                    model=req.model,
                )
            used = (
                await conn.execute(
                    sa.select(sa.func.count())
                    .select_from(llm_spend)
                    .where(llm_spend.c.agent_run_id == req.agent_run_id)
                )
            ).scalar_one()
            if used >= self._max_calls:
                raise CallLimitExceeded(
                    f"agent run already made {used} LLM calls (limit {self._max_calls})",
                    provider=self.name,
                    model=req.model,
                )
            reservation: uuid.UUID = (
                await conn.execute(
                    sa.insert(llm_spend)
                    .values(
                        agent_run_id=req.agent_run_id,
                        provider=self.name,
                        model=req.model,
                        state="reserved",
                        amount_usd=worst,
                    )
                    .returning(llm_spend.c.id)
                )
            ).scalar_one()
            return reservation, worst

    async def _settle(self, reservation: uuid.UUID | None, amount: Decimal) -> None:
        """Replace the estimate with the real cost (retried once; otherwise worst case stays)."""
        if reservation is None:
            return
        for attempt in (1, 2):
            try:
                async with self._engine.begin() as conn:
                    await conn.execute(
                        sa.update(llm_spend)
                        .where(llm_spend.c.id == reservation)
                        .values(state="settled", amount_usd=amount, settled_at=sa.func.now())
                    )
                return
            except Exception as exc:
                log.error(
                    "llm_spend_settle_failed",
                    attempt=attempt,
                    cost_usd=str(amount),
                    error_type=type(exc).__name__,
                )
        # Both attempts failed: the row stays 'reserved' at its worst-case amount, which keeps
        # counting against the budget (reservations never expire).

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
    ) -> Decimal:
        cost = self._pricing.cost(model, usage, provider=provider)
        request = {
            "task": req.task,
            "system": req.system,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "effort": req.effort,
        }
        try:
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
                        request=redact(request),
                        response=redact(response),
                    )
                )
        except Exception as exc:
            # The provider already billed this call: never lose the cost silently.
            log.error(
                "llm_call_record_failed",
                provider=provider,
                model=model,
                cost_usd=str(cost.usd),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                agent_run_id=str(req.agent_run_id),
                error_type=type(exc).__name__,
            )
        return cost.usd

    async def _call[R](
        self, req: StructuredRequest[Any] | TextRequest, call: Any, to_json: Any
    ) -> LLMResult[R]:
        if req.agent_run_id is None:
            raise ValueError("agent_run_id is required: every LLM call belongs to an agent run")
        req = dataclasses.replace(req, max_tokens=min(req.max_tokens, self._ceiling))
        reservation, amount = await self._reserve(req)
        # Fail closed: ``amount`` stays at the worst case unless the real cost is known, and the
        # settle in ``finally`` also runs on cancellation and on any unexpected exception.
        try:
            try:
                result: LLMResult[R] = await call(req)
            except LLMError as exc:
                amount = await self._safe_record(
                    req,
                    amount,
                    usage=exc.usage,
                    latency_ms=exc.latency_ms,
                    provider=exc.provider or self.name,
                    model=exc.model or req.model,
                    success=False,
                    error_code=exc.code,
                    response=partial(_error_payload, exc),
                )
                raise
            except Exception as exc:
                # Unknown whether the provider billed anything: keep the worst case.
                await self._safe_record(
                    req,
                    amount,
                    usage=Usage(),
                    latency_ms=0,
                    provider=self.name,
                    model=req.model,
                    success=False,
                    error_code="unexpected_error",
                    response=partial(_error_payload, exc, detail=False),
                )
                raise
            amount = await self._safe_record(
                req,
                amount,
                usage=result.usage,
                latency_ms=result.latency_ms,
                provider=result.provider,
                model=result.model,
                success=True,
                error_code=None,
                response=lambda: to_json(result),
            )
            return result
        finally:
            await asyncio.shield(self._settle(reservation, amount))

    async def _safe_record(
        self,
        req: StructuredRequest[Any] | TextRequest,
        worst: Decimal,
        *,
        response: Callable[[], object],
        **fields: Any,
    ) -> Decimal:
        """Record the call; return its actual cost, or ``worst`` if pricing/serialisation failed."""
        try:
            return await self._record(req, response=response(), **fields)
        except Exception as exc:
            log.error(
                "llm_call_record_failed",
                provider=fields.get("provider"),
                model=fields.get("model"),
                error_type=type(exc).__name__,
            )
            return worst

    async def generate_structured[T: BaseModel](self, req: StructuredRequest[T]) -> LLMResult[T]:
        return await self._call(
            req,
            self._inner.generate_structured,
            lambda r: r.value.model_dump(mode="json"),
        )

    async def generate_text(self, req: TextRequest) -> LLMResult[str]:
        return await self._call(req, self._inner.generate_text, lambda r: {"text": r.value})
