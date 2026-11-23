from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from anthropic import AsyncAnthropic

from lead_qualifier.infrastructure.llm.anthropic_provider import AnthropicProvider
from lead_qualifier.infrastructure.llm.structured import generate_validated
from lead_qualifier.ports.llm import (
    ChatMessage,
    LLMOutputInvalid,
    LLMProviderError,
    TextRequest,
)
from tests.unit.llm.helpers import verdict_request

# The Anthropic SDK talks through httpx2, which respx cannot patch: mock its transport instead.
GOOD = {"score": 61, "tier": "warm", "reasons": ["budget ok"]}


def reply(text: str, *, stop: str = "end_turn") -> dict[str, object]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 120,
            "output_tokens": 30,
            "cache_read_input_tokens": 10,
            "cache_creation_input_tokens": 5,
        },
    }


class Wire:
    """Scripted HTTP transport: pops one response per request and records the requests."""

    def __init__(self, *responses: httpx2.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.responses.pop(0)

    def body(self, index: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[index].content)  # type: ignore[no-any-return]


def provider_for(wire: Wire, *, max_retries: int = 0) -> AnthropicProvider:
    client = AsyncAnthropic(
        api_key="test-key-not-real",
        base_url="https://api.anthropic.test",
        max_retries=max_retries,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(wire)),
    )
    return AnthropicProvider(client)


def ok(text: str, **kw: str) -> httpx2.Response:
    return httpx2.Response(200, json=reply(text, **kw))


def err(status: int, kind: str, message: str, **headers: str) -> httpx2.Response:
    return httpx2.Response(
        status, headers=headers, json={"type": "error", "error": {"type": kind, "message": message}}
    )


async def test_structured_request_shape_and_parsed_result():
    wire = Wire(ok(json.dumps(GOOD)))
    result = await provider_for(wire).generate_structured(verdict_request(effort="low"))
    body = wire.body()
    assert body["model"] == "claude-haiku-5-5"
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "score" in body["output_config"]["format"]["schema"]["properties"]
    assert "temperature" not in body and "top_p" not in body
    assert body["messages"][-1]["role"] == "user"
    assert result.value.tier == "warm"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (120, 30)
    assert (result.usage.cache_read_tokens, result.usage.cache_write_tokens) == (10, 5)
    assert "api.anthropic.test" in str(wire.requests[-1].url)
    assert wire.requests[-1].headers.get("anthropic-version")


async def test_invalid_output_is_repaired_through_the_wire():
    wire = Wire(ok('{"score": 999}'), ok(json.dumps(GOOD)))
    result = await generate_validated(provider_for(wire), verdict_request())
    assert result.value.score == 61
    assert [m["role"] for m in wire.body(1)["messages"]] == ["user", "assistant", "user"]


async def test_refusal_is_reported_as_invalid_output_with_usage():
    wire = Wire(ok("", stop="refusal"))
    with pytest.raises(LLMOutputInvalid) as exc:
        await provider_for(wire).generate_structured(verdict_request())
    assert exc.value.usage.input_tokens == 120


async def test_400_is_not_retried_and_maps_to_provider_error():
    wire = Wire(err(400, "invalid_request_error", "bad"), err(400, "invalid_request_error", "bad"))
    with pytest.raises(LLMProviderError, match="status=400 type=invalid_request_error"):
        await provider_for(wire, max_retries=2).generate_structured(verdict_request())
    assert len(wire.requests) == 1


async def test_429_is_retried_by_the_sdk():
    wire = Wire(err(429, "rate_limit_error", "slow", **{"retry-after": "0"}), ok(json.dumps(GOOD)))
    result = await provider_for(wire, max_retries=1).generate_structured(verdict_request())
    assert len(wire.requests) == 2
    assert result.value.score == 61


async def test_text_generation():
    wire = Wire(ok("Hello Maria"))
    req = TextRequest("answer", "sys", [ChatMessage("user", "hi")], "claude-haiku-5-5", 100)
    assert (await provider_for(wire).generate_text(req)).value == "Hello Maria"


async def test_provider_error_text_never_echoes_the_provider_message():
    wire = Wire(err(401, "authentication_error", "invalid key sk-ant-api03-SECRET and prompt text"))
    with pytest.raises(LLMProviderError) as exc:
        await provider_for(wire).generate_structured(verdict_request())
    assert "SECRET" not in str(exc.value) and "prompt text" not in str(exc.value)


async def test_refusal_is_not_resent_by_the_repair_loop():
    wire = Wire(ok("", stop="refusal"), ok(json.dumps(GOOD)))
    with pytest.raises(LLMOutputInvalid):
        await generate_validated(provider_for(wire), verdict_request())
    assert len(wire.requests) == 1


async def test_truncated_output_is_not_resent_with_the_same_max_tokens():
    wire = Wire(ok('{"score": 5', stop="max_tokens"), ok(json.dumps(GOOD)))
    with pytest.raises(LLMOutputInvalid):
        await generate_validated(provider_for(wire), verdict_request())
    assert len(wire.requests) == 1
