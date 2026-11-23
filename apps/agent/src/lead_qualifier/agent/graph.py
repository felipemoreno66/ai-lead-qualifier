"""The qualification graph: extract -> qualify, with a shared error exit (plan 2.3).

Control flow is code, never model-chosen, and no tools are exposed to any call that contains lead
text. Dependencies come through LangGraph's run context so nodes are unit-testable with fakes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from lead_qualifier.agent.models import (
    DraftOutput,
    LeadInput,
    LeadProfile,
    QualificationOutput,
    QualificationResult,
)
from lead_qualifier.agent.prompts import (
    DRAFT_SYSTEM,
    EXTRACT_SYSTEM,
    QUALIFY_SYSTEM,
    render_draft_context,
    render_lead_profile,
    render_lead_submission,
    render_operator_feedback,
    render_workspace_context,
)
from lead_qualifier.domain.draft_guard import check_draft
from lead_qualifier.domain.scoring import compute_score, tier_for
from lead_qualifier.domain.workspace import WorkspaceConfig
from lead_qualifier.infrastructure.llm.structured import generate_validated
from lead_qualifier.ports.llm import ChatMessage, LLMError, LLMProvider, StructuredRequest

MAX_REASON_CHARS = 300


MAX_GUARD_REDRAFTS = 1


class QualifyState(TypedDict, total=False):
    lead: LeadInput
    profile: LeadProfile
    result: QualificationResult
    draft: DraftOutput
    draft_language: str
    guard_problems: list[str]
    guard_redrafts: int
    guard_retry: bool
    operator_feedback: str
    decision: dict[str, Any]
    error: str


class SendGateway(Protocol):
    """Side effect of approval, implemented by the review service (one idempotent transaction)."""

    async def request_send(self, decision: dict[str, Any], state: QualifyState) -> None: ...


@dataclass(frozen=True)
class GraphDeps:
    provider: LLMProvider
    workspace: WorkspaceConfig
    agent_run_id: UUID
    model_for: Callable[[str], str]
    send: SendGateway | None = None


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


def _draft_language(state: QualifyState, workspace: WorkspaceConfig) -> str:
    detected = state["profile"].detected_language
    return detected if detected in workspace.languages.supported else workspace.languages.default


async def draft_node(state: QualifyState, runtime: Runtime[GraphDeps]) -> dict[str, Any]:
    deps = runtime.context
    config = deps.workspace
    language = _draft_language(state, config)
    parts = [
        render_draft_context(config, state["result"], language),
        render_lead_submission(state["lead"]),
        render_lead_profile(state["profile"]),
    ]
    feedback = [*state.get("guard_problems", [])]
    if state.get("operator_feedback"):
        feedback.append(state["operator_feedback"])
    if feedback:
        parts.append(render_operator_feedback("; ".join(feedback)))
    request = StructuredRequest(
        task="draft",
        system=DRAFT_SYSTEM,
        messages=[ChatMessage("user", "\n".join(parts))],
        output_model=DraftOutput,
        model=deps.model_for("draft"),
        max_tokens=1500,
        effort="medium",
        node="draft",
        agent_run_id=deps.agent_run_id,
    )
    try:
        result = await generate_validated(deps.provider, request)
    except LLMError as exc:
        return _error(exc)
    return {"draft": result.value, "draft_language": language}


def validate_draft_node(state: QualifyState, runtime: Runtime[GraphDeps]) -> dict[str, Any]:
    draft = state["draft"]
    problems = check_draft(
        runtime.context.workspace,
        language=state["draft_language"],
        subject=draft.subject,
        body=draft.body,
        short_body=draft.short_body,
    )
    redrafts = state.get("guard_redrafts", 0)
    retry = bool(problems) and redrafts < MAX_GUARD_REDRAFTS
    return {
        "guard_problems": problems,
        "guard_redrafts": redrafts + 1 if retry else redrafts,
        "guard_retry": retry,
    }


def _after_validate(state: QualifyState) -> str:
    return "draft" if state.get("guard_retry") else "human_review"


def human_review_node(state: QualifyState) -> dict[str, Any]:
    """Only the interrupt and the mapping of the resume payload (the node re-runs on resume)."""
    decision = interrupt({"kind": "review", "language": state["draft_language"]})
    update: dict[str, Any] = {"decision": decision}
    if decision.get("action") == "regenerate":
        update |= {
            "operator_feedback": str(decision.get("feedback") or ""),
            "guard_redrafts": 0,
            "guard_problems": [],
        }
    return update


def _after_review(state: QualifyState) -> str:
    action = state["decision"]["action"]
    if action in ("approve", "edit"):
        return "request_send"
    return "draft" if action == "regenerate" else END


async def request_send_node(state: QualifyState, runtime: Runtime[GraphDeps]) -> dict[str, Any]:
    gateway = runtime.context.send
    if gateway is None:
        raise RuntimeError("request_send needs GraphDeps.send")
    await gateway.request_send(state["decision"], state)
    return {}


def _after_node(next_node: str) -> Callable[[QualifyState], str]:
    def route(state: QualifyState) -> str:
        return END if "error" in state else next_node

    return route


def build_graph(checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    graph = StateGraph(QualifyState, context_schema=GraphDeps)
    graph.add_node("extract", extract_node)
    graph.add_node("qualify", qualify_node)
    graph.add_node("draft", draft_node)
    graph.add_node("validate_draft", validate_draft_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("request_send", request_send_node)
    graph.add_edge(START, "extract")
    graph.add_conditional_edges("extract", _after_node("qualify"), ["qualify", END])
    graph.add_conditional_edges("qualify", _after_node("draft"), ["draft", END])
    graph.add_conditional_edges("draft", _after_node("validate_draft"), ["validate_draft", END])
    graph.add_conditional_edges("validate_draft", _after_validate, ["draft", "human_review"])
    graph.add_conditional_edges("human_review", _after_review, ["request_send", "draft", END])
    graph.add_edge("request_send", END)
    return graph.compile(checkpointer=checkpointer)


def thread_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


async def run_qualification(
    lead: LeadInput,
    deps: GraphDeps,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    thread_id: str = "ephemeral",
) -> dict[str, Any]:
    """Run until the human_review interrupt (``__interrupt__`` in the result) or an error."""
    final: dict[str, Any] = await build_graph(checkpointer).ainvoke(
        {"lead": lead}, thread_config(thread_id), context=deps
    )
    return final


async def resume_review(
    decision: dict[str, Any],
    deps: GraphDeps,
    *,
    checkpointer: BaseCheckpointSaver[Any],
    thread_id: str,
) -> dict[str, Any]:
    final: dict[str, Any] = await build_graph(checkpointer).ainvoke(
        Command(resume=decision), thread_config(thread_id), context=deps
    )
    return final
