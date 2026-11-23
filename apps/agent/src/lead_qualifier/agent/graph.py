"""The qualification graph: extract -> qualify, with a shared error exit (plan 2.3).

Control flow is code, never model-chosen, and no tools are exposed to any call that contains lead
text. Dependencies come through LangGraph's run context so nodes are unit-testable with fakes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, TypedDict
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from lead_qualifier.agent.models import (
    AnswerOutput,
    AnswerResult,
    DraftOutput,
    LeadInput,
    LeadProfile,
    QualificationOutput,
    QualificationResult,
    ResolvedCitation,
)
from lead_qualifier.agent.prompts import (
    ANSWER_SYSTEM,
    DRAFT_SYSTEM,
    EXTRACT_SYSTEM,
    QUALIFY_SYSTEM,
    render_draft_context,
    render_kb_answers,
    render_kb_context,
    render_lead_profile,
    render_lead_questions,
    render_lead_submission,
    render_operator_feedback,
    render_workspace_context,
)
from lead_qualifier.domain.draft_guard import answer_problems, check_draft_detailed
from lead_qualifier.domain.kb_chunker import plain_text
from lead_qualifier.domain.scoring import compute_score, tier_for
from lead_qualifier.domain.workspace import Tier, WorkspaceConfig
from lead_qualifier.infrastructure.llm.structured import generate_validated
from lead_qualifier.ports.knowledge import KnowledgeRetriever, RetrievedChunk
from lead_qualifier.ports.llm import ChatMessage, LLMError, LLMProvider, StructuredRequest

MAX_REASON_CHARS = 300


MAX_GUARD_REDRAFTS = 1


class QualifyState(TypedDict, total=False):
    lead: LeadInput
    profile: LeadProfile
    result: QualificationResult
    kb_answers: list[AnswerResult]
    draft: DraftOutput
    draft_language: str
    guard_problems: list[str]
    guard_codes: list[str]
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
    knowledge: KnowledgeRetriever | None = None


GENERIC_REASONS = {
    "llm_timeout": "the AI provider did not answer in time",
    "llm_provider_error": "the AI provider returned an error",
    "llm_connection_error": "the connection to the AI provider failed",
    "llm_output_invalid": "the AI output did not pass validation",
    "budget_exceeded": "the AI spending limit was reached",
    "call_limit_exceeded": "the per-run AI call limit was reached",
}


def _error(exc: LLMError) -> dict[str, str]:
    """A code and a fixed sentence. The exception text can echo model output (and so lead text),
    so it never reaches ``leads.error_reason``, events or the API; it stays in ``llm_calls``."""
    return {"error": f"{exc.code}: {GENERIC_REASONS.get(exc.code, 'the AI call failed')}"}


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
    profile = result.value
    # The same question can appear in the form text and the free text.
    questions = list({q.strip().lower(): q.strip() for q in profile.questions}.values())
    return {"profile": profile.model_copy(update={"questions": questions})}


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
    tier = tier_for(score, config.qualification.tiers)
    # A prospect who tried to instruct the model never lands in the top tier automatically.
    capped = state["profile"].injection_suspected and tier is Tier.HOT
    ordered = {c.id: c for c in output.criteria}
    return {
        "result": QualificationResult(
            score=score,
            tier=Tier.WARM if capped else tier,
            tier_capped=capped,
            recommended_product=output.recommended_product,
            criteria=[ordered[c.id] for c in config.qualification.criteria],
            reasons=output.reasons,
            profile=state["profile"],
        )
    }


NOT_COVERED = {
    "en": "Not covered in our documentation — the team will reply personally",
    "es": "No está cubierto en nuestra documentación — el equipo te responderá personalmente",
}


def not_covered_text(language: str) -> str:
    return NOT_COVERED.get(language, NOT_COVERED["en"])


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


MIN_QUOTE_CHARS = 15
MIN_QUOTE_WORDS = 3


def _answer_check(
    items: list[tuple[str, list[RetrievedChunk]]],
) -> Callable[[AnswerOutput], None]:
    """Domain check: one item per question; every citation names a chunk retrieved for that very
    question and quotes it verbatim, and a covered answer needs at least one citation."""

    def check(output: AnswerOutput) -> None:
        if len(output.answers) != len(items):
            raise ValueError(
                f"answers must have exactly {len(items)} items, got {len(output.answers)}"
            )
        for number, (item, (question, chunks)) in enumerate(
            zip(output.answers, items, strict=True), 1
        ):
            by_id = {str(c.chunk_id): c for c in chunks}
            if _squash(item.question) != _squash(question):
                raise ValueError(f"item {number}: question must be copied exactly as given")
            if item.covered and not (item.answer.strip() and item.citations):
                raise ValueError(f"item {number}: a covered answer needs text and a citation")
            if not item.covered and item.citations:
                raise ValueError(f"item {number}: an answer that is not covered has no citations")
            for citation in item.citations:
                chunk = by_id.get(citation.chunk_id)
                if chunk is None:
                    raise ValueError(
                        f"item {number}: chunk_id {citation.chunk_id!r} is not one of its excerpts"
                    )
                quote = _squash(citation.quote)
                if len(quote) < MIN_QUOTE_CHARS and len(quote.split()) < MIN_QUOTE_WORDS:
                    raise ValueError(
                        f"item {number}: a quote must be a meaningful passage "
                        f"(at least {MIN_QUOTE_CHARS} characters or {MIN_QUOTE_WORDS} words)"
                    )
                if quote not in _squash(plain_text(chunk.content)):
                    raise ValueError(
                        f"item {number}: the quote does not appear word for word in the excerpt"
                    )

    return check


def _resolve(item: Any, chunks: list[RetrievedChunk]) -> list[ResolvedCitation]:
    by_id = {str(c.chunk_id): c for c in chunks}
    return [
        ResolvedCitation(
            chunk_id=c.chunk_id,
            quote=c.quote,
            document_path=by_id[c.chunk_id].document_path,
            document_title=by_id[c.chunk_id].document_title,
            heading_path=by_id[c.chunk_id].heading_path,
        )
        for c in item.citations
    ]


async def answer_node(state: QualifyState, runtime: Runtime[GraphDeps]) -> dict[str, Any]:
    """Answer the lead's questions from the knowledge base, with validated citations.

    Questions with nothing retrieved above the similarity threshold never reach the model: they are
    answered with the fixed "not covered" text in code.
    """
    deps = runtime.context
    config = deps.workspace
    questions = state["profile"].questions
    language = state["profile"].detected_language
    retrieved: list[list[RetrievedChunk]] = []
    for question in questions:
        retrieved.append(await deps.knowledge.retrieve(question) if deps.knowledge else [])
    asked = [(q, chunks) for q, chunks in zip(questions, retrieved, strict=True) if chunks]
    items: list[Any] = []
    if asked:
        request = StructuredRequest(
            task="answer",
            system=ANSWER_SYSTEM,
            messages=[
                ChatMessage(
                    "user",
                    "\n".join(
                        [render_lead_questions([q for q, _ in asked]), render_kb_context(asked)]
                    ),
                )
            ],
            output_model=AnswerOutput,
            model=deps.model_for("answer"),
            max_tokens=2000,
            effort="low",
            node="answer",
            agent_run_id=deps.agent_run_id,
        )
        try:
            result = await generate_validated(deps.provider, request, validate=_answer_check(asked))
        except LLMError as exc:
            return _error(exc)
        items = list(result.value.answers)
    by_question = {q: (item, chunks) for (q, chunks), item in zip(asked, items, strict=True)}
    answers: list[AnswerResult] = []
    for question in questions:
        found = by_question.get(question)
        if found is not None and found[0].covered:
            item, chunks = found
            if answer_problems(config, item.answer):
                # a fact we may not put in an email (foreign link, unknown price...) is not used
                answers.append(
                    AnswerResult(
                        question=question, answer=not_covered_text(language), covered=False
                    )
                )
                continue
            answers.append(
                AnswerResult(
                    question=question,
                    answer=item.answer.strip(),
                    covered=True,
                    citations=_resolve(item, chunks),
                )
            )
        else:
            answers.append(
                AnswerResult(question=question, answer=not_covered_text(language), covered=False)
            )
    return {"kb_answers": answers}


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
    if state.get("kb_answers"):
        parts.append(render_kb_answers(state["kb_answers"]))
    # Only the fixed problem codes go back to the model, never text that may echo lead input.
    feedback = (
        [f"fix these problems: {', '.join(state['guard_codes'])}"]
        if state.get("guard_codes")
        else []
    )
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
    problems = check_draft_detailed(
        runtime.context.workspace,
        language=state["draft_language"],
        subject=draft.subject,
        body=draft.body,
        short_body=draft.short_body,
    )
    redrafts = state.get("guard_redrafts", 0)
    retry = bool(problems) and redrafts < MAX_GUARD_REDRAFTS
    return {
        "guard_problems": [p.message for p in problems],
        "guard_codes": list(dict.fromkeys(p.code for p in problems)),
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
            "guard_codes": [],
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


def _after_qualify(state: QualifyState) -> str:
    if "error" in state:
        return END
    return "answer" if state["profile"].questions else "draft"


@lru_cache(maxsize=8)
def build_graph(checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    graph = StateGraph(QualifyState, context_schema=GraphDeps)
    graph.add_node("extract", extract_node)
    graph.add_node("qualify", qualify_node)
    graph.add_node("answer", answer_node)
    graph.add_node("draft", draft_node)
    graph.add_node("validate_draft", validate_draft_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("request_send", request_send_node)
    graph.add_edge(START, "extract")
    graph.add_conditional_edges("extract", _after_node("qualify"), ["qualify", END])
    graph.add_conditional_edges("qualify", _after_qualify, ["answer", "draft", END])
    graph.add_conditional_edges("answer", _after_node("draft"), ["draft", END])
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
