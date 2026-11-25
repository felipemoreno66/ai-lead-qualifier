from __future__ import annotations

import pytest

from lead_qualifier.infrastructure.llm.fake import FakeProvider
from lead_qualifier.infrastructure.llm.structured import generate_validated
from lead_qualifier.ports.llm import LLMOutputInvalid, LLMProviderError
from tests.unit.llm.helpers import Verdict, verdict_request

GOOD = {"score": 80, "tier": "hot", "reasons": ["fits budget"]}


async def test_valid_output_needs_no_repair():
    fake = FakeProvider(script=[GOOD])
    result = await generate_validated(fake, verdict_request())
    assert result.value.score == 80
    assert fake.calls == 1


async def test_invalid_json_is_repaired_with_the_errors_fed_back():
    seen: list[list[tuple[str, str]]] = []
    fake = FakeProvider(script=["not json", {"score": 500, "tier": "hot", "reasons": ["x"]}, GOOD])
    original = fake.generate_structured

    async def spy(req):  # type: ignore[no-untyped-def]
        seen.append([(m.role, m.content) for m in req.messages])
        return await original(req)

    fake.generate_structured = spy  # type: ignore[method-assign]
    result = await generate_validated(fake, verdict_request())
    assert result.value == Verdict(**GOOD)
    assert len(seen) == 3
    assert seen[1][-1][0] == "user" and "rejected" in seen[1][-1][1]
    assert seen[2][-2] == ("assistant", '{"reasons":["x"],"score":500,"tier":"hot"}')
    assert "score" in seen[2][-1][1]


async def test_domain_validation_failure_triggers_repair():
    def only_hot(v: Verdict) -> None:
        if v.tier != "hot":
            raise ValueError("tier must be hot")

    fake = FakeProvider(script=[{**GOOD, "tier": "warm"}, GOOD])
    result = await generate_validated(fake, verdict_request(), validate=only_hot)
    assert result.value.tier == "hot"
    assert fake.calls == 2


async def test_gives_up_after_two_repairs():
    fake = FakeProvider(script=["bad", "bad", "bad", GOOD])
    with pytest.raises(LLMOutputInvalid, match="after 2 repairs"):
        await generate_validated(fake, verdict_request())
    assert fake.calls == 3


async def test_provider_errors_are_not_retried_here():
    fake = FakeProvider(script=[LLMProviderError("boom")])
    with pytest.raises(LLMProviderError):
        await generate_validated(fake, verdict_request())
    assert fake.calls == 1
