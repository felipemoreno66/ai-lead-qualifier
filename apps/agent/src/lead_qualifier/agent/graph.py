"""The qualification graph: extract -> qualify, with a shared error exit (plan 2.3).

Control flow is code, never model-chosen, and no tools are exposed to any call that contains lead
text. Dependencies come through LangGraph's run context so nodes are unit-testable with fakes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from lead_qualifier.agent.models import (
    LeadInput,
    LeadProfile,
    QualificationOutput,
    QualificationResult,
)
from lead_qualifier.agent.prompts import (
    EXTRACT_SYSTEM,
    QUALIFY_SYSTEM,
    render_lead_profile,
    render_lead_submission,
    render_workspace_context,
)
from lead_qualifier.domain.scoring import compute_score, tier_for
from lead_qualifier.domain.workspace import WorkspaceConfig
from lead_qualifier.infrastructure.llm.structured import generate_validated
from lead_qualifier.ports.llm import ChatMessage, LLMError, LLMProvider, StructuredRequest

MAX_REASON_CHARS = 300


class QualifyState(TypedDict, total=False):
    lead: LeadInput
    profile: LeadProfile
    result: QualificationResult
    error: str


@dataclass(frozen=True)
class GraphDeps:
    provider: LLMProvider
    workspace: WorkspaceConfig
    agent_run_id: UUID
    model_for: Callable[[str], str]


def _error(exc: LLMError) -> dict[str, str]:
    return {"error": f"{exc.code}: {str(exc)[:240]}"}


async def extract_node(state: QualifyState, runtime: Runtime[GraphDeps]) -> dict[str, Any]:
    deps = runtime.context
    request = StructuredRequest(
        task="extract",
        system=EXTRACT_SYSTEM,
        messages=[ChatMessage("user", render_lead_submission(state["lead"]))],
        output_model=LeadProfile,
        model=deps.model_for("extract"),
        max_tokens=800,
        effort="low",
        node="extract",
        agent_run_id=deps.agent_run_id,
    )
    try:
        result = await generate_validated(deps.provider, request)
    except LLMError as exc:
        return _error(exc)
    return {"profile": result.value}


def _domain_check(workspace: WorkspaceConfig) -> Callable[[QualificationOutput], None]:
    criterion_ids = [c.id for c in workspace.qualification.criteria]
    product_ids = {p.id for p in workspace.products}

    def check(output: QualificationOutput) -> None:
        given = [c.id for c in output.criteria]
        if sorted(given) != sorted(criterion_ids):
            raise ValueError(f"criteria must be exactly {criterion_ids} once each, got {given}")
        if output.recommended_product not in product_ids:
            raise ValueError(
                f"recommended_product must be one of {sorted(product_ids)}, "
                f"got {output.recommended_product!r}"
            )
        if any(len(r) > MAX_REASON_CHARS for r in output.reasons):
            raise ValueError(f"each reason must be at most {MAX_REASON_CHARS} characters")

    return check


async def qualify_node(state: QualifyState, runtime: Runtime[GraphDeps]) -> dict[str, Any]:
    deps = runtime.context
    config = deps.workspace
    content = "\n".join(
        [
            render_workspace_context(config),
            render_lead_submission(state["lead"]),
            render_lead_profile(state["profile"]),
        ]
    )
    request = StructuredRequest(
        task="qualify",
        system=QUALIFY_SYSTEM,
        messages=[ChatMessage("user", content)],
        output_model=QualificationOutput,
        model=deps.model_for("qualify"),
        max_tokens=1500,
        effort="low",
        node="qualify",
        agent_run_id=deps.agent_run_id,
    )
    try:
        result = await generate_validated(deps.provider, request, validate=_domain_check(config))
    except LLMError as exc:
        return _error(exc)
    output = result.value
    judgments = {c.id: c.judgment for c in output.criteria}
    score = compute_score(config.qualification.criteria, judgments)
    ordered = {c.id: c for c in output.criteria}
    return {
        "result": QualificationResult(
            score=score,
            tier=tier_for(score, config.qualification.tiers),
            recommended_product=output.recommended_product,
            criteria=[ordered[c.id] for c in config.qualification.criteria],
            reasons=output.reasons,
            profile=state["profile"],
        )
    }


def _after_node(next_node: str) -> Callable[[QualifyState], str]:
    def route(state: QualifyState) -> str:
        return END if "error" in state else next_node

    return route


def build_graph() -> Any:
    graph = StateGraph(QualifyState, context_schema=GraphDeps)
    graph.add_node("extract", extract_node)
    graph.add_node("qualify", qualify_node)
    graph.add_edge(START, "extract")
    graph.add_conditional_edges("extract", _after_node("qualify"), ["qualify", END])
    graph.add_edge("qualify", END)
    return graph.compile()


async def run_qualification(lead: LeadInput, deps: GraphDeps) -> QualifyState:
    final: QualifyState = await build_graph().ainvoke({"lead": lead}, context=deps)
    return final
