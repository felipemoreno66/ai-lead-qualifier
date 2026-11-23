"""Anthropic adapter (official SDK). Structured output via ``output_config.format`` JSON schema.

No temperature/top_p (rejected by current models) and no assistant prefill. The SDK retries
429/5xx/connection errors itself (``max_retries``); 400s are never retried.
"""

from __future__ import annotations

import time
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import Message
from pydantic import BaseModel

from lead_qualifier.infrastructure.llm.structured import parse_output
from lead_qualifier.ports.llm import (
    ChatMessage,
    LLMOutputInvalid,
    LLMProviderError,
    LLMResult,
    LLMTimeout,
    StructuredRequest,
    TextRequest,
    Usage,
)


def usage_from(message: Message) -> Usage:
    u = message.usage
    return Usage(
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_tokens=u.cache_read_input_tokens or 0,
        cache_write_tokens=u.cache_creation_input_tokens or 0,
    )


def _text_of(message: Message) -> str:
    return "".join(block.text for block in message.content if block.type == "text")


def _wire(messages: list[ChatMessage]) -> list[Any]:
    return [{"role": m.role, "content": m.content} for m in messages]


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        client: AsyncAnthropic | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        max_retries: int = 2,
        timeout: float = 60.0,
    ) -> None:
        self._client = client or AsyncAnthropic(
            api_key=api_key, base_url=base_url, max_retries=max_retries, timeout=timeout
        )

    async def _create(
        self, req: StructuredRequest[Any] | TextRequest, output_config: dict[str, Any]
    ) -> tuple[Message, int]:
        if req.effort is not None:
            output_config["effort"] = req.effort
        kwargs: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "system": req.system,
            "messages": _wire(req.messages),
        }
        if output_config:
            kwargs["output_config"] = output_config
        started = time.monotonic()
        try:
            message = await self._client.messages.create(**kwargs)
        except anthropic.APITimeoutError as exc:
            raise LLMTimeout(
                str(exc), provider=self.name, model=req.model, latency_ms=_ms(started)
            ) from exc
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise LLMProviderError(
                f"{type(exc).__name__}: {exc}",
                provider=self.name,
                model=req.model,
                latency_ms=_ms(started),
            ) from exc
        return message, _ms(started)

    async def generate_structured[T: BaseModel](self, req: StructuredRequest[T]) -> LLMResult[T]:
        schema = anthropic.transform_schema(req.output_model)
        message, latency = await self._create(
            req, {"format": {"type": "json_schema", "schema": schema}}
        )
        usage, raw = usage_from(message), _text_of(message)
        if message.stop_reason in ("refusal", "max_tokens"):
            raise LLMOutputInvalid(
                f"stop_reason={message.stop_reason}",
                raw_text=raw,
                usage=usage,
                latency_ms=latency,
                provider=self.name,
                model=req.model,
            )
        value = parse_output(
            raw,
            req.output_model,
            usage=usage,
            latency_ms=latency,
            provider=self.name,
            model_id=req.model,
        )
        return LLMResult(value, raw, usage, latency, self.name, req.model)

    async def generate_text(self, req: TextRequest) -> LLMResult[str]:
        message, latency = await self._create(req, {})
        text = _text_of(message)
        return LLMResult(text, text, usage_from(message), latency, self.name, req.model)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
