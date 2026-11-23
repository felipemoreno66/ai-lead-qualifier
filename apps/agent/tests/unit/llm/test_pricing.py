from __future__ import annotations

from decimal import Decimal

from lead_qualifier.infrastructure.llm.pricing import PricingTable
from lead_qualifier.ports.llm import Usage


def test_cost_math_with_all_token_kinds():
    table = PricingTable.load()
    usage = Usage(
        input_tokens=2_500, output_tokens=400, cache_read_tokens=1_000_000, cache_write_tokens=8_000
    )
    cost = table.cost("claude-haiku-5-5", usage)
    # 2500*0.10 + 400*0.50 + 1e6*0.01 + 8000*0.125 per million
    assert cost.usd == Decimal("0.011450")
    assert not cost.is_estimated


def test_plan_estimate_per_lead_is_about_two_tenths_of_a_cent():
    one_call = PricingTable.load().cost("claude-haiku-5-5", Usage(2_500, 400))
    assert one_call.usd == Decimal("0.000450")


def test_unknown_model_is_free_but_flagged_estimated():
    cost = PricingTable.load().cost("some-new-model", Usage(1000, 1000))
    assert cost.usd == 0
    assert cost.is_estimated


def test_fake_provider_is_always_free():
    cost = PricingTable.load().cost("claude-sonnet-5-5", Usage(10**6, 10**6), provider="fake")
    assert cost.usd == 0
    assert not cost.is_estimated


def test_pricing_file_records_when_it_was_verified():
    assert PricingTable.load().verified_on == "2026-11-23"
