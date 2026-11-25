from __future__ import annotations

import pytest

from lead_qualifier.infrastructure.llm.fake import FakeProvider
from lead_qualifier.ports.llm import ChatMessage, LLMTimeout, TextRequest
from tests.unit.llm.helpers import Verdict, verdict_request


async def test_same_input_gives_identical_output():
    a = await FakeProvider().generate_structured(verdict_request())
    b = await FakeProvider().generate_structured(verdict_request())
    assert a.raw_text == b.raw_text
    assert isinstance(a.value, Verdict)
    assert a.provider == "fake"


async def test_different_input_changes_output():
    a = await FakeProvider().generate_structured(verdict_request("one"))
    b = await FakeProvider().generate_structured(verdict_request("two"))
    assert a.raw_text != b.raw_text


async def test_usage_is_synthetic_and_text_is_deterministic():
    req = TextRequest("answer", "sys", [ChatMessage("user", "hello there")], "m", 100)
    first = await FakeProvider().generate_text(req)
    assert first.value == (await FakeProvider().generate_text(req)).value
    assert first.usage.input_tokens > 0


async def test_registered_handler_wins_over_schema_synthesis():
    handler = {"qualify": lambda _req: {"score": 7, "tier": "cold", "reasons": ["rule"]}}
    result = await FakeProvider(handlers=handler).generate_structured(verdict_request())
    assert result.value == Verdict(score=7, tier="cold", reasons=["rule"])


async def test_script_injects_timeout_then_recovers():
    fake = FakeProvider(script=[LLMTimeout("slow")])
    with pytest.raises(LLMTimeout):
        await fake.generate_structured(verdict_request())
    assert (await fake.generate_structured(verdict_request())).value.tier in {"hot", "warm", "cold"}
