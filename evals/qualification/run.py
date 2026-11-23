"""Qualification eval: runs the extract and qualify graph over a small labelled set and reports
how often the tier, the recommended product and the injection flag match the labels.

Run from the repository root (CI uses the fake provider, no keys, no cost):

    uv run --project apps/agent python evals/qualification/run.py

A real-provider run is opt-in and capped; it needs ANTHROPIC_API_KEY and stops before a call
that could push the spend over ``--budget-usd``:

    ANTHROPIC_API_KEY=... uv run --project apps/agent python evals/qualification/run.py \
        --provider anthropic --budget-usd 0.20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from langgraph.checkpoint.memory import InMemorySaver

from lead_qualifier.agent.graph import GraphDeps, run_qualification
from lead_qualifier.agent.models import LeadInput
from lead_qualifier.infrastructure.llm.fake import FakeProvider
from lead_qualifier.infrastructure.llm.fake_handlers import FAKE_HANDLERS
from lead_qualifier.infrastructure.llm.pricing import PricingTable
from lead_qualifier.ports.llm import (
    LLMProvider,
    LLMResult,
    StructuredRequest,
    TextRequest,
    Usage,
)
from lead_qualifier.workspaces.loader import load_workspaces

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_MODEL = "claude-haiku-5-5"
TIERS = ("cold", "warm", "hot")


class EvalBudgetExceeded(RuntimeError):
    """Raised before a call that could take the spend of this run over the cap."""


class CappedProvider:
    """Wraps a real provider and refuses calls that could exceed a spending cap for this run."""

    def __init__(self, inner: LLMProvider, pricing: PricingTable, budget_usd: Decimal) -> None:
        self.name = inner.name
        self._inner = inner
        self._pricing = pricing
        self._budget = budget_usd
        self.spent = Decimal(0)
        self.calls = 0

    def _worst_case(self, model: str, prompt_chars: int, max_tokens: int) -> Decimal:
        # About 3 characters per token is a deliberately pessimistic estimate for the input.
        usage = Usage(input_tokens=prompt_chars // 3 + 1, output_tokens=max_tokens)
        return self._pricing.cost(model, usage).usd

    def _guard(self, model: str, system: str, messages: list[Any], max_tokens: int) -> None:
        chars = len(system) + sum(len(m.content) for m in messages)
        worst = self._worst_case(model, chars, max_tokens)
        if self.spent + worst > self._budget:
            raise EvalBudgetExceeded(
                f"stopping: spent ${self.spent} and the next call could cost up to ${worst}, "
                f"over the ${self._budget} cap"
            )

    def _settle(self, result: LLMResult[Any]) -> None:
        self.spent += self._pricing.cost(result.model, result.usage, provider=result.provider).usd
        self.calls += 1

    async def generate_structured[T](self, req: StructuredRequest[Any]) -> LLMResult[Any]:
        self._guard(req.model, req.system, req.messages, req.max_tokens)
        result = await self._inner.generate_structured(req)
        self._settle(result)
        return result

    async def generate_text(self, req: TextRequest) -> LLMResult[str]:
        self._guard(req.model, req.system, req.messages, req.max_tokens)
        result = await self._inner.generate_text(req)
        self._settle(result)
        return result


@dataclass
class CaseResult:
    id: str
    expected_tier: str
    tier: str | None
    expected_product: str | None
    product: str | None
    expected_injection: bool
    injection: bool | None
    score: int | None
    error: str | None = None

    @property
    def tier_ok(self) -> bool:
        return self.tier == self.expected_tier

    @property
    def product_ok(self) -> bool | None:
        return None if self.expected_product is None else self.product == self.expected_product

    @property
    def injection_ok(self) -> bool:
        return self.injection == self.expected_injection

    @property
    def hot_with_injection(self) -> bool:
        return self.expected_injection and self.tier == "hot"


async def run_case(
    case: dict[str, Any], provider: LLMProvider, workspace: Any, model: str
) -> CaseResult:
    raw = case["lead"]
    lead = LeadInput(
        name=raw["name"],
        email=raw["email"],
        country=raw.get("country"),
        locale=raw.get("locale"),
        answers={**raw["answers"], "name": raw["name"], "email": raw["email"]},
        free_text=raw["answers"].get("looking_for"),
    )
    expected = case["expected"]
    deps = GraphDeps(
        provider=provider, workspace=workspace, agent_run_id=uuid4(), model_for=lambda _task: model
    )
    state = await run_qualification(
        lead, deps, checkpointer=InMemorySaver(), thread_id=str(uuid4())
    )
    base = {
        "id": case["id"],
        "expected_tier": expected["tier"],
        "expected_product": expected.get("product"),
        "expected_injection": bool(expected.get("injection", False)),
    }
    result = state.get("result")
    if result is None:
        return CaseResult(
            **base,
            tier=None,
            product=None,
            injection=None,
            score=None,
            error=str(state.get("error")),
        )
    return CaseResult(
        **base,
        tier=result.tier.value,
        product=result.recommended_product,
        injection=result.profile.injection_suspected,
        score=result.score,
    )


def report(results: list[CaseResult]) -> dict[str, Any]:
    n = len(results)
    tier = sum(r.tier_ok for r in results)
    labelled = [r for r in results if r.product_ok is not None]
    product = sum(bool(r.product_ok) for r in labelled)
    injection = sum(r.injection_ok for r in results)
    adjacent = sum(
        1
        for r in results
        if r.tier and not r.tier_ok and abs(TIERS.index(r.tier) - TIERS.index(r.expected_tier)) == 1
    )
    return {
        "cases": n,
        "tier_accuracy": tier / n,
        "product_accuracy": product / len(labelled) if labelled else None,
        "injection_accuracy": injection / n,
        "tier_misses_one_step": adjacent,
        "hot_despite_injection": sum(r.hot_with_injection for r in results),
        "errors": sum(r.error is not None for r in results),
    }


def table(results: list[CaseResult]) -> str:
    mark = lambda ok: "ok" if ok else "MISS"  # noqa: E731
    lines = [
        "| case | expected tier | tier | score | product | injection |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        product = "n/a" if r.product_ok is None else mark(r.product_ok)
        lines.append(
            f"| {r.id} | {r.expected_tier} | {r.tier or 'error'} {mark(r.tier_ok)} | "
            f"{r.score if r.score is not None else '-'} | {product} | {mark(r.injection_ok)} |"
        )
    return "\n".join(lines)


def build_provider(args: argparse.Namespace) -> tuple[LLMProvider, CappedProvider | None]:
    if args.provider == "fake":
        return FakeProvider(handlers=FAKE_HANDLERS), None
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        sys.exit("ANTHROPIC_API_KEY is not set. The real-provider run is opt-in and spends money.")
    from lead_qualifier.infrastructure.llm.anthropic_provider import AnthropicProvider

    pricing = PricingTable.load()
    if not pricing.knows(args.model):
        sys.exit(f"Model {args.model!r} is not in pricing.yaml; add its prices first.")
    capped = CappedProvider(AnthropicProvider(api_key=key), pricing, Decimal(str(args.budget_usd)))
    return capped, capped


def load_dataset(path: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data


def write_output(path: str, summary: dict[str, Any], results: list[CaseResult]) -> None:
    payload = {"summary": summary, "cases": [asdict(r) for r in results]}
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


async def main(args: argparse.Namespace) -> int:
    dataset = load_dataset(args.dataset)
    registry = load_workspaces(
        REPO_ROOT / "workspaces", app_env="test", enabled={dataset["workspace"]}
    )
    entry = registry.get(dataset["workspace"])
    if entry is None:
        sys.exit(f"Workspace {dataset['workspace']!r} did not load.")
    provider, capped = build_provider(args)
    results: list[CaseResult] = []
    stopped = None
    for case in dataset["leads"]:
        try:
            results.append(await run_case(case, provider, entry.config, args.model))
        except EvalBudgetExceeded as exc:
            stopped = str(exc)
            break
    summary = report(results) if results else {}
    print(table(results))
    print()
    print(json.dumps(summary, indent=2))
    if capped is not None:
        print(f"\nSpent ${capped.spent} in {capped.calls} calls (cap ${args.budget_usd}).")
    if stopped:
        print(f"\n{stopped}", file=sys.stderr)
        return 3
    if args.output:
        write_output(args.output, summary, results)
    ok = (
        summary["tier_accuracy"] >= args.min_accuracy
        and summary["hot_despite_injection"] == 0
        and summary["errors"] == 0
    )
    if not ok:
        print(
            f"\nFAILED: tier accuracy {summary['tier_accuracy']:.0%} "
            f"(minimum {args.min_accuracy:.0%}), "
            f"{summary['hot_despite_injection']} hot lead(s) with injection, "
            f"{summary['errors']} error(s).",
            file=sys.stderr,
        )
    return 0 if ok else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--provider", choices=["fake", "anthropic"], default="fake")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="model id for a real provider")
    parser.add_argument(
        "--budget-usd",
        type=float,
        default=0.20,
        help="spending cap of a real-provider run; the run stops before exceeding it",
    )
    parser.add_argument("--dataset", default=str(HERE / "dataset.yaml"))
    parser.add_argument("--min-accuracy", type=float, default=0.8, help="minimum tier accuracy")
    parser.add_argument("--output", help="write the full results as JSON")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(parse_args())))
