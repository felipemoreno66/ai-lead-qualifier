"""LLM provider port: request/response types, usage and errors shared by every adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

Effort = Literal["low", "medium", "high"]
Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class StructuredRequest[T: BaseModel]:
    """One structured-output call. ``node``/``agent_run_id``/``attempt`` feed the audit trail."""

    task: str  # "extract" | "qualify" | "draft" | "answer"
    system: str
    messages: list[ChatMessage]
    output_model: type[T]
    model: str
    max_tokens: int
    effort: Effort | None = None
    node: str | None = None
    agent_run_id: UUID | None = None
    attempt: int = 1


@dataclass(frozen=True)
class TextRequest:
    task: str
    system: str
    messages: list[ChatMessage]
    model: str
    max_tokens: int
    effort: Effort | None = None
    node: str | None = None
    agent_run_id: UUID | None = None
    attempt: int = 1


@dataclass(frozen=True)
class LLMResult[V]:
    value: V
    raw_text: str
    usage: Usage
    latency_ms: int
    provider: str
    model: str


class LLMError(Exception):
    """Base class. ``usage`` is set when the provider billed tokens for the failed call."""

    code = "llm_error"
    # True when the provider may have processed (and billed) the request although we got no usage.
    maybe_billed = False

    def __init__(
        self,
        message: str,
        *,
        usage: Usage | None = None,
        latency_ms: int = 0,
        provider: str = "",
        model: str = "",
    ) -> None:
        super().__init__(message)
        self.usage = usage or Usage()
        self.latency_ms = latency_ms
        self.provider = provider
        self.model = model


class LLMTimeout(LLMError):
    code = "llm_timeout"
    maybe_billed = True


class LLMProviderError(LLMError):
    """API failure after the SDK's own retries (an HTTP status the provider answered)."""

    code = "llm_provider_error"


class LLMConnectionError(LLMProviderError):
    """The connection broke mid-request: the provider may have processed it."""

    code = "llm_connection_error"
    maybe_billed = True


class LLMOutputInvalid(LLMError):
    """The model answered but the output failed schema or domain validation."""

    code = "llm_output_invalid"

    def __init__(
        self, message: str, *, raw_text: str = "", repairable: bool = True, **kwargs: object
    ) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.raw_text = raw_text
        # False for refusals and truncation: resending the same request cannot help.
        self.repairable = repairable


class BudgetExceeded(LLMError):
    code = "budget_exceeded"


class CallLimitExceeded(LLMError):
    code = "call_limit_exceeded"


class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def generate_structured[T: BaseModel](
        self, req: StructuredRequest[T]
    ) -> LLMResult[T]: ...

    async def generate_text(self, req: TextRequest) -> LLMResult[str]: ...
