from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from tests.helpers import WORKSPACES_DIR

RAG = Path(__file__).resolve().parents[4] / "evals" / "rag"


@pytest.fixture(scope="module")
def rag():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("rag_eval", RAG / "run.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["rag_eval"] = module
    spec.loader.exec_module(module)
    return module


def dataset() -> dict:  # type: ignore[type-arg]
    return yaml.safe_load((RAG / "northwind.yaml").read_text(encoding="utf-8"))


def test_dataset_shape_and_sources_exist():
    cases = dataset()["cases"]
    assert len(cases) >= 15
    assert sum(not c.get("answerable", True) for c in cases) == 3
    assert sum(c.get("language") == "es" for c in cases) == 2
    kb = WORKSPACES_DIR / "northwind-academy" / "knowledge-base"
    for case in cases:
        if case.get("answerable", True):
            assert case["keywords"] and all(isinstance(g, list) and g for g in case["keywords"])
            assert case["sources"] and all((kb / s).is_file() for s in case["sources"])
    assert len({c["id"] for c in cases}) == len(cases)


def test_rubric_needs_every_group_and_any_synonym(rag):  # type: ignore[no-untyped-def]
    groups = [["4,900", "4900"], ["6 monthly"]]
    assert rag.rubric_ok("It costs USD 4900 or 6 monthly payments", groups)
    assert not rag.rubric_ok("It costs USD 4,900", groups)


def test_summary_counts_refusals_and_citations(rag):  # type: ignore[no-untyped-def]
    ok = rag.CaseResult("a", "q", True, True, "x", ["d1.md", "d2.md"], 2, True, True, 0.5)
    refused = rag.CaseResult("b", "q", False, covered=False)
    leaked = rag.CaseResult("c", "q", False, covered=True)
    summary = rag.summarize([ok, refused, leaked])
    assert summary["answer_accuracy"] == 1.0 and summary["citation_precision"] == 0.5
    assert summary["refusal_correctness"] == 0.5 and summary["false_refusals"] == 0
    assert [r.passed for r in (ok, refused, leaked)] == [True, True, False]


async def test_the_offline_run_completes_without_errors_and_labels_itself(rag, tmp_path, capsys):  # type: ignore[no-untyped-def]
    out = tmp_path / "results.md"
    import argparse

    ns = argparse.Namespace(
        provider="fake",
        embeddings="fake",
        model="claude-haiku-5-5",
        budget_usd=0.1,
        dataset=str(RAG / "northwind.yaml"),
        top_k=5,
        min_similarity=0.3,
        min_accuracy=None,
        min_refusal=None,
        min_precision=None,
        output=str(out),
        json=None,
    )
    assert await rag.main(ns) == 0
    text = out.read_text(encoding="utf-8")
    assert "verify the plumbing, not answer quality" in text
    assert "| Errors | 0 |" in text
