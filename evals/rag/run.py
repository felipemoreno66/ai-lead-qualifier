"""RAG eval: does the answer node answer from the knowledge base, cite the right document, and
refuse what the documentation does not cover?

Offline and free (fake provider, fake embeddings; used by CI):

    uv run --project apps/agent python evals/rag/run.py

IMPORTANT: with the fake provider and fake embeddings the numbers only prove that the plumbing works
(chunking, retrieval, citation validation, scoring). The fake model quotes the top retrieved passage
and the fake embeddings are hashed bags of words, so they say nothing about real answer quality.

A real run is opt-in and capped (needs ANTHROPIC_API_KEY and downloads the fastembed model):

    ANTHROPIC_API_KEY=... uv run --project apps/agent python evals/rag/run.py \
        --provider anthropic --embeddings fastembed --budget-usd 0.10

Retrieval here is in memory (same chunker, same embedding input, cosine similarity, same top-k and
threshold as production); pgvector itself is covered by the integration tests.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import yaml

from lead_qualifier.agent.graph import GraphDeps, answer_node
from lead_qualifier.agent.models import LeadProfile
from lead_qualifier.domain.kb_chunker import chunk_markdown, document_title
from lead_qualifier.infrastructure.embeddings import FakeEmbeddings, FastEmbeddings
from lead_qualifier.infrastructure.llm.fake import FakeProvider
from lead_qualifier.infrastructure.llm.fake_handlers import FAKE_HANDLERS
from lead_qualifier.infrastructure.llm.pricing import PricingTable
from lead_qualifier.ports.embeddings import Embeddings
from lead_qualifier.ports.knowledge import RetrievedChunk
from lead_qualifier.ports.llm import LLMProvider
from lead_qualifier.services.kb import embedding_input, list_documents
from lead_qualifier.workspaces.loader import load_workspaces

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_TOP_K = 5
NOT_COVERED_PREFIX = "Not covered in our documentation"


def _load_qualification_eval() -> Any:
    """Reuse the spending cap of the qualification eval (one implementation of the cap)."""
    path = HERE.parent / "qualification" / "run.py"
    spec = importlib.util.spec_from_file_location("qualification_eval", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["qualification_eval"] = module
    spec.loader.exec_module(module)
    return module


class InMemoryRetriever:
    """Chunks the knowledge base like the ingest does and ranks them by cosine similarity."""

    def __init__(self, embeddings: Embeddings, top_k: int, min_similarity: float | None) -> None:
        self._embeddings = embeddings
        self._top_k = top_k
        self.min_similarity = (
            embeddings.default_min_similarity if min_similarity is None else min_similarity
        )
        self._chunks: list[tuple[RetrievedChunk, list[float]]] = []
        self._cache: dict[str, list[RetrievedChunk]] = {}

    def load(self, kb_dir: Path) -> int:
        paths, _ = list_documents(kb_dir)
        for path in paths:
            text = path.read_text(encoding="utf-8")
            title = document_title(text, path.stem)
            name = path.relative_to(kb_dir).as_posix()
            chunks = chunk_markdown(
                text,
                title=title,
                max_tokens=self._embeddings.max_chunk_tokens,
                overlap=self._embeddings.chunk_overlap_tokens,
            )
            vectors = self._embeddings.embed(
                [embedding_input(title, c.heading_path, c.content) for c in chunks]
            )
            for chunk, vector in zip(chunks, vectors, strict=True):
                item = RetrievedChunk(uuid4(), name, title, chunk.heading_path, chunk.content, 0.0)
                self._chunks.append((item, vector))
        return len(self._chunks)

    async def retrieve(self, question: str) -> list[RetrievedChunk]:
        """Cached per question: the eval retrieves once, and the answer node reuses the result."""
        if question not in self._cache:
            self._cache[question] = self._search(question)
        return self._cache[question]

    def _search(self, question: str) -> list[RetrievedChunk]:
        (query,) = self._embeddings.embed([question])
        scored = sorted(
            ((_cosine(query, vector), chunk) for chunk, vector in self._chunks),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return [
            RetrievedChunk(
                c.chunk_id, c.document_path, c.document_title, c.heading_path, c.content, score
            )
            for score, c in scored[: self._top_k]
            if score >= self.min_similarity
        ]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


@dataclass
class CaseResult:
    id: str
    question: str
    answerable: bool
    covered: bool | None = None
    answer: str = ""
    cited_sources: list[str] = field(default_factory=list)
    retrieved: int = 0
    keywords_ok: bool = False
    sources_ok: bool = False
    citation_precision: float | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        if self.error is not None:
            return False
        if not self.answerable:
            return self.covered is False
        return bool(self.covered) and self.keywords_ok and self.sources_ok


def rubric_ok(answer: str, groups: list[list[str]]) -> bool:
    low = answer.lower()
    return all(any(word.lower() in low for word in group) for group in groups)


async def run_case(
    case: dict[str, Any], deps: GraphDeps, retriever: InMemoryRetriever
) -> CaseResult:
    answerable = case.get("answerable", True)
    result = CaseResult(case["id"], case["question"], answerable)
    profile = LeadProfile(
        normalized_name="Eval",
        detected_language=case.get("language", "en"),
        goal_summary="Evaluation question.",
        questions=[case["question"]],
    )
    result.retrieved = len(await retriever.retrieve(case["question"]))
    update = await answer_node({"profile": profile}, SimpleNamespace(context=deps))  # type: ignore[arg-type]
    if "error" in update:
        result.error = str(update["error"])
        return result
    (answer,) = update["kb_answers"]
    result.covered = answer.covered
    result.answer = answer.answer
    result.cited_sources = [c.document_path for c in answer.citations]
    if answerable:
        expected = set(case["sources"])
        result.keywords_ok = answer.covered and rubric_ok(answer.answer, case["keywords"])
        result.sources_ok = bool(set(result.cited_sources) & expected)
        if result.cited_sources:
            hits = sum(source in expected for source in result.cited_sources)
            result.citation_precision = hits / len(result.cited_sources)
    return result


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    answerable = [r for r in results if r.answerable]
    unanswerable = [r for r in results if not r.answerable]
    cited = [r for r in answerable if r.citation_precision is not None]
    cites = sum(len(r.cited_sources) for r in cited)
    good_cites = sum(round((r.citation_precision or 0) * len(r.cited_sources)) for r in cited)
    return {
        "cases": len(results),
        "answer_accuracy": _ratio(sum(r.keywords_ok for r in answerable), len(answerable)),
        "source_cited": _ratio(sum(r.sources_ok for r in answerable), len(answerable)),
        "citation_precision": _ratio(good_cites, cites),
        "refusal_correctness": _ratio(
            sum(r.covered is False for r in unanswerable), len(unanswerable)
        ),
        "false_refusals": sum(r.covered is False for r in answerable),
        "errors": sum(r.error is not None for r in results),
    }


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def markdown(
    results: list[CaseResult], summary: dict[str, Any], *, provider: str, embeddings: str
) -> str:
    lines = [
        f"RAG eval: provider `{provider}`, embeddings `{embeddings}`, "
        f"{summary['cases']} questions.",
        "",
    ]
    if provider == "fake" or embeddings == "fake":
        lines += [
            "> Fake provider or fake embeddings: these numbers verify the plumbing, "
            "not answer quality.",
            "",
        ]
    lines += [
        f"Retrieval: top {summary['top_k']}, minimum similarity {summary['min_similarity']}. "
        "Refusal correctness partly measures that threshold: a question with nothing above it "
        "is refused without asking the model.",
        "",
    ]
    rows = [
        (
            "Answer accuracy (rubric keywords, answerable questions)",
            _pct(summary["answer_accuracy"]),
        ),
        ("Expected source cited", _pct(summary["source_cited"])),
        (
            "Citation precision (citations to an expected source)",
            _pct(summary["citation_precision"]),
        ),
        (
            "Refusal correctness (unanswerable questions refused)",
            _pct(summary["refusal_correctness"]),
        ),
        ("False refusals (answerable questions refused)", str(summary["false_refusals"])),
        ("Errors", str(summary["errors"])),
    ]
    lines += ["| Metric | Result |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    lines += [
        "",
        "| Case | Answerable | Covered | Rubric | Source | Cited documents | Result |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        covered = "-" if r.covered is None else ("yes" if r.covered else "no")
        rubric = "n/a" if not r.answerable else ("ok" if r.keywords_ok else "MISS")
        source = "n/a" if not r.answerable else ("ok" if r.sources_ok else "MISS")
        cited = ", ".join(sorted(set(r.cited_sources))) or "-"
        verdict = "error" if r.error else ("pass" if r.passed else "FAIL")
        lines.append(
            f"| {r.id} | {'yes' if r.answerable else 'no'} | {covered} | {rubric} | {source} | "
            f"{cited} | {verdict} |"
        )
    return "\n".join(lines) + "\n"


def build(args: argparse.Namespace, qual: Any) -> tuple[LLMProvider, Any, Embeddings]:
    embeddings: Embeddings
    if args.embeddings == "fake":
        embeddings = FakeEmbeddings()
    else:
        embeddings = FastEmbeddings(
            cache_dir=Path(os.environ.get("EMBEDDINGS_CACHE_DIR", ".cache/fastembed"))
        )
    if args.provider == "fake":
        return FakeProvider(handlers=FAKE_HANDLERS), None, embeddings
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        sys.exit("ANTHROPIC_API_KEY is not set. The real-provider run is opt-in and spends money.")
    from lead_qualifier.infrastructure.llm.anthropic_provider import AnthropicProvider

    pricing = PricingTable.load()
    if not pricing.knows(args.model):
        sys.exit(f"Model {args.model!r} is not in pricing.yaml; add its prices first.")
    capped = qual.CappedProvider(
        AnthropicProvider(api_key=key), pricing, Decimal(str(args.budget_usd))
    )
    return capped, capped, embeddings


def _read_yaml(path: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data


def _write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


async def main(args: argparse.Namespace) -> int:
    qual = _load_qualification_eval()
    dataset = _read_yaml(args.dataset)
    registry = load_workspaces(
        REPO_ROOT / "workspaces", app_env="test", enabled={dataset["workspace"]}
    )
    entry = registry.get(dataset["workspace"])
    if entry is None:
        sys.exit(f"Workspace {dataset['workspace']!r} did not load.")
    provider, capped, embeddings = build(args, qual)
    retriever = InMemoryRetriever(embeddings, args.top_k, args.min_similarity)
    kb_dir = entry.path / entry.config.knowledge_base.path
    chunks = await asyncio.to_thread(retriever.load, kb_dir)
    deps = GraphDeps(
        provider=provider,
        workspace=entry.config,
        agent_run_id=UUID(int=0),
        model_for=lambda _task: args.model,
        knowledge=retriever,
    )
    results: list[CaseResult] = []
    stopped = None
    for case in dataset["cases"]:
        try:
            results.append(await run_case(case, deps, retriever))
        except qual.EvalBudgetExceeded as exc:
            stopped = str(exc)
            break
    summary = summarize(results) | {"top_k": args.top_k, "min_similarity": retriever.min_similarity}
    report = markdown(results, summary, provider=args.provider, embeddings=args.embeddings)
    print(f"{chunks} chunks indexed.\n")
    print(report)
    if capped is not None:
        print(f"Spent ${capped.spent} in {capped.calls} calls (cap ${args.budget_usd}).")
    if args.output:
        _write(args.output, report)
    if args.json:
        payload = {"summary": summary, "cases": [asdict(r) for r in results]}
        _write(args.json, json.dumps(payload, indent=2) + "\n")
    if stopped:
        print(stopped, file=sys.stderr)
        return 3
    return _gate(summary, args)


def _gate(summary: dict[str, Any], args: argparse.Namespace) -> int:
    """Exit 1 on errors, or when a requested minimum is not met (no minimums by default: the fake
    run is a plumbing check)."""
    failures = []
    if summary["errors"]:
        failures.append(f"{summary['errors']} error(s)")
    for key, minimum in (
        ("answer_accuracy", args.min_accuracy),
        ("refusal_correctness", args.min_refusal),
        ("citation_precision", args.min_precision),
    ):
        value = summary[key]
        if minimum is not None and (value is None or value < minimum):
            failures.append(f"{key} {_pct(value)} below {minimum:.0%}")
    if failures:
        print("FAILED: " + "; ".join(failures), file=sys.stderr)
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--provider", choices=["fake", "anthropic"], default="fake")
    parser.add_argument("--embeddings", choices=["fake", "fastembed"], default="fake")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="model id for a real provider")
    parser.add_argument(
        "--budget-usd",
        type=float,
        default=0.10,
        help="spending cap of a real-provider run; the run stops before exceeding it",
    )
    parser.add_argument("--dataset", default=str(HERE / "northwind.yaml"))
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument(
        "--min-similarity",
        type=float,
        help="similarity threshold (default: the embedding model's own default)",
    )
    parser.add_argument("--min-accuracy", type=float, help="fail below this answer accuracy")
    parser.add_argument("--min-refusal", type=float, help="fail below this refusal correctness")
    parser.add_argument("--min-precision", type=float, help="fail below this citation precision")
    parser.add_argument("--output", help="write the markdown results table to this file")
    parser.add_argument("--json", help="write the per-case results as JSON")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(parse_args())))
