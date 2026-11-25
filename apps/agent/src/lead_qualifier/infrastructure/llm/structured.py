"""Shared structured-output helpers: parsing and the validate-and-repair loop."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from lead_qualifier.ports.llm import (
    ChatMessage,
    LLMOutputInvalid,
    LLMProvider,
    LLMResult,
    StructuredRequest,
    Usage,
)

MAX_REPAIRS = 2


def parse_output[T: BaseModel](
    raw_text: str,
    model: type[T],
    *,
    usage: Usage,
    latency_ms: int,
    provider: str,
    model_id: str,
) -> T:
    """Validate ``raw_text`` against ``model``; raise ``LLMOutputInvalid`` carrying usage."""
    try:
        return model.model_validate_json(raw_text)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()
        )
        raise LLMOutputInvalid(
            problems,
            raw_text=raw_text,
            usage=usage,
            latency_ms=latency_ms,
            provider=provider,
            model=model_id,
        ) from exc


def _repair_messages(
    messages: list[ChatMessage], raw_text: str, problems: str
) -> list[ChatMessage]:
    extra = [ChatMessage("assistant", raw_text)] if raw_text.strip() else []
    extra.append(
        ChatMessage(
            "user",
            "Your previous answer was rejected: "
            f"{problems}. Reply again with a corrected answer that follows the schema exactly.",
        )
    )
    return [*messages, *extra]


async def generate_validated[T: BaseModel](
    provider: LLMProvider,
    req: StructuredRequest[T],
    *,
    validate: Callable[[T], None] | None = None,
    max_repairs: int = MAX_REPAIRS,
) -> LLMResult[T]:
    """Call ``provider``; on schema or domain failure feed the errors back, up to ``max_repairs``.

    ``validate`` is the domain check (raise ``ValueError`` with a readable message). Every attempt
    goes through the provider separately, so a recording wrapper stores one row per attempt.
    """
    messages = list(req.messages)
    last: LLMOutputInvalid | None = None
    for attempt in range(1, max_repairs + 2):
        attempt_req = dataclasses.replace(req, messages=messages, attempt=attempt)
        try:
            result = await provider.generate_structured(attempt_req)
            if validate is not None:
                try:
                    validate(result.value)
                except ValueError as exc:
                    raise LLMOutputInvalid(
                        str(exc),
                        raw_text=result.raw_text,
                        usage=result.usage,
                        latency_ms=result.latency_ms,
                        provider=result.provider,
                        model=result.model,
                    ) from exc
            return result
        except LLMOutputInvalid as exc:
            if not exc.repairable:
                raise
            last = exc
            messages = _repair_messages(list(req.messages), exc.raw_text, str(exc))
    assert last is not None
    raise LLMOutputInvalid(
        f"output still invalid after {max_repairs} repairs: {last}",
        raw_text=last.raw_text,
        usage=last.usage,
        latency_ms=last.latency_ms,
        provider=last.provider,
        model=last.model,
    ) from last
