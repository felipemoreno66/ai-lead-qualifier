"""OpenAI adapter skeleton (optional, not implemented, not run in CI).

To implement: add the official ``openai`` SDK, call ``client.chat.completions.parse`` (or the
Responses API) with ``response_format=req.output_model`` for structured output, map the SDK's
``APITimeoutError`` / ``APIError`` to ``LLMTimeout`` / ``LLMProviderError``, fill ``Usage`` from
``response.usage`` and add the model prices to ``pricing.yaml``. Adapters stay dumb: the validation
loop, recording and budget guard are shared and live outside the adapter.
"""

from __future__ import annotations

from pydantic import BaseModel

from lead_qualifier.ports.llm import LLMResult, StructuredRequest, TextRequest

_MSG = "The OpenAI adapter is a documented skeleton; see the module docstring"


class OpenAIProvider:
    name = "openai"

    def __init__(self, *, api_key: str) -> None:
        self._api_key = api_key

    async def generate_structured[T: BaseModel](self, req: StructuredRequest[T]) -> LLMResult[T]:
        raise NotImplementedError(
            "The OpenAI adapter is a documented skeleton; see module docstring"
        )

    async def generate_text(self, req: TextRequest) -> LLMResult[str]:
        raise NotImplementedError(
            "The OpenAI adapter is a documented skeleton; see module docstring"
        )
