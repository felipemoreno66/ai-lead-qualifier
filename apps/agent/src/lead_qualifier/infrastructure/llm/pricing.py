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

    def cost(self, model: str, usage: Usage, *, provider: str = "") -> Cost:
        """USD for ``usage``. Fake calls are free; unknown models are 0 and flagged estimated."""
        if provider == "fake":
            return Cost(Decimal(0), is_estimated=False)
        price = self._prices.get(model)
        if price is None:
            log.warning("llm_pricing_unknown_model", model=model)
            return Cost(Decimal(0), is_estimated=True)
        total = (
            Decimal(usage.input_tokens) * price.input
            + Decimal(usage.output_tokens) * price.output
            + Decimal(usage.cache_read_tokens) * price.cache_read
            + Decimal(usage.cache_write_tokens) * price.cache_write
        ) / _MILLION
        return Cost(total.quantize(_QUANT), is_estimated=False)
