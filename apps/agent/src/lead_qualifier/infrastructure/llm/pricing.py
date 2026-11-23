"""Per-model pricing table and cost computation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import structlog
import yaml

from lead_qualifier.ports.llm import Usage

log = structlog.get_logger(__name__)
DEFAULT_PRICING_PATH = Path(__file__).with_name("pricing.yaml")
_MILLION = Decimal(1_000_000)
_QUANT = Decimal("0.000001")


@dataclass(frozen=True)
class ModelPrice:
    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal


@dataclass(frozen=True)
class Cost:
    usd: Decimal
    is_estimated: bool


class PricingTable:
    def __init__(self, verified_on: str, prices: dict[str, ModelPrice]) -> None:
        self.verified_on = verified_on
        self._prices = prices

    @classmethod
    def load(cls, path: Path = DEFAULT_PRICING_PATH) -> PricingTable:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        prices = {
            model: ModelPrice(**{k: Decimal(str(v)) for k, v in row.items()})
            for model, row in data["models"].items()
        }
        return cls(str(data["verified_on"]), prices)

    def knows(self, model: str) -> bool:
        return model in self._prices

    def _price_for(self, model: str) -> tuple[ModelPrice, bool]:
        """The model's price, or for unknown models the most expensive rate in the table."""
        known = self._prices.get(model)
        if known is not None:
            return known, False
        rows = list(self._prices.values())
        worst = ModelPrice(
            input=max(r.input for r in rows),
            output=max(r.output for r in rows),
            cache_read=max(r.cache_read for r in rows),
            cache_write=max(r.cache_write for r in rows),
        )
        return worst, True

    def cost(self, model: str, usage: Usage, *, provider: str = "") -> Cost:
        """USD for ``usage``. Fake calls are free; unknown models are billed at the highest known
        rate and flagged estimated, so the budget guard can never be bypassed by a new model id."""
        if provider == "fake":
            return Cost(Decimal(0), is_estimated=False)
        price, estimated = self._price_for(model)
        if estimated:
            log.warning("llm_pricing_unknown_model", model=model)
        total = (
            Decimal(usage.input_tokens) * price.input
            + Decimal(usage.output_tokens) * price.output
            + Decimal(usage.cache_read_tokens) * price.cache_read
            + Decimal(usage.cache_write_tokens) * price.cache_write
        ) / _MILLION
        return Cost(total.quantize(_QUANT), is_estimated=estimated)

    def worst_case(self, model: str, *, input_bytes: int, max_tokens: int) -> Decimal:
        """Upper bound of one call.

        A token always covers at least one UTF-8 byte (CJK and emoji included), so the input is
        priced at one token per byte plus a 25% margin, at the dearer of the input and cache-write
        rates, plus a full ``max_tokens`` of output.
        """
        price, _ = self._price_for(model)
        input_tokens = Decimal(input_bytes) * Decimal("1.25") + 1
        total = (
            input_tokens * max(price.input, price.cache_write) + Decimal(max_tokens) * price.output
        ) / _MILLION
        return total.quantize(_QUANT)
