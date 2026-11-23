"""The qualification eval (evals/qualification) runs offline with the fake provider."""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from types import ModuleType

import pytest

from lead_qualifier.infrastructure.llm.fake import FakeProvider
from lead_qualifier.infrastructure.llm.fake_handlers import FAKE_HANDLERS
from lead_qualifier.infrastructure.llm.pricing import PricingTable
from lead_qualifier.ports.llm import ChatMessage, LLMResult, TextRequest, Usage
from tests.helpers import REPO_ROOT

SCRIPT = REPO_ROOT / "evals" / "qualification" / "run.py"


@pytest.fixture(scope="module")
def evalrun() -> ModuleType:
    spec = importlib.util.spec_from_file_location("qualification_eval", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def test_the_fake_run_meets_the_bar(evalrun: ModuleType):
    import argparse

    namespace = argparse.Namespace(
        provider="fake",
        model=evalrun.DEFAULT_MODEL,
        budget_usd=0.2,
        dataset=str(SCRIPT.with_name("dataset.yaml")),
        min_accuracy=0.8,
        output=None,
    )
    assert await evalrun.main(namespace) == 0


def test_the_dataset_is_labelled_and_covers_every_tier(evalrun: ModuleType):
    import yaml

    leads = yaml.safe_load(SCRIPT.with_name("dataset.yaml").read_text())["leads"]
    assert len(leads) >= 10
    assert {c["expected"]["tier"] for c in leads} == {"hot", "warm", "cold"}
    assert any(c["expected"]["injection"] for c in leads)
    assert len({c["id"] for c in leads}) == len(leads)
    assert all(c["lead"]["email"].endswith("@example.com") for c in leads)


class _Priced:
    """A provider that reports a fixed usage so the cap's arithmetic is visible."""

    name = "anthropic"

    async def generate_text(self, req: TextRequest) -> LLMResult[str]:
        return LLMResult("ok", "ok", Usage(1_000_000, 0), 1, "anthropic", req.model)


async def test_the_cap_stops_a_real_run_before_it_overspends(evalrun: ModuleType):
    pricing = PricingTable.load()
    capped = evalrun.CappedProvider(_Priced(), pricing, Decimal("0.0001"))  # type: ignore[arg-type]
    request = TextRequest(
        task="draft",
        system="s",
        messages=[ChatMessage("user", "hello")],
        model=evalrun.DEFAULT_MODEL,
        max_tokens=4000,
    )
    with pytest.raises(evalrun.EvalBudgetExceeded):
        await capped.generate_text(request)
    assert capped.calls == 0 and capped.spent == 0


async def test_the_fake_provider_is_free_through_the_cap(evalrun: ModuleType):
    capped = evalrun.CappedProvider(
        FakeProvider(handlers=FAKE_HANDLERS), PricingTable.load(), Decimal("0.2")
    )
    assert capped.spent == 0
