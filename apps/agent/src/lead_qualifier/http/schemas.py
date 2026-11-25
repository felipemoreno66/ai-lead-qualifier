"""Response models for the admin API (the contract consumed by the Next.js BFF)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

from lead_qualifier.domain.draft_guard import has_unsafe_chars

Group = Literal["attention", "hot", "warm", "scoring", "cold"]


class WorkspaceSummary(BaseModel):
    slug: str
    name: str
    enabled: bool
    draft: bool
    lead_count: int
    by_status: dict[str, int]


class LeadListItem(BaseModel):
    id: uuid.UUID
    reference: str
    workspace_slug: str
    status: str
    name: str
    email: str
    country: str | None
    interest: str | None
    score: int | None
    tier: str | None
    recommended_product: str | None
    error_reason: str | None
    created_at: datetime
    group: Group


class LeadList(BaseModel):
    items: list[LeadListItem]
    page: int
    page_size: int
    total: int


class AnswerOut(BaseModel):
    id: str
    label: str
    value: str | int | float | bool
    display: str


class CitationOut(BaseModel):
    chunk_id: uuid.UUID
    document_path: str
    document_title: str
    heading_path: str
    quote: str


class KbAnswerOut(BaseModel):
    question: str
    answer: str
    covered: bool
    citations: list[CitationOut]


class KbAskRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")


class KbChatEntryOut(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    covered: bool
    citations: list[CitationOut]
    created_at: datetime


class LeadEventOut(BaseModel):
    id: uuid.UUID
    type: str
    from_status: str | None
    to_status: str | None
    actor: str
    payload: dict[str, Any]
    created_at: datetime


class OutboxEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    lead_id: uuid.UUID | None
    status: str
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None


class CriterionBreakdown(BaseModel):
    """One scored criterion: what was judged, the points it earned and the evidence."""

    id: str
    description: str
    judgment: Literal["met", "partial", "unmet"]
    points: float
    max_points: float
    evidence: str


class LeadDetail(BaseModel):
    id: uuid.UUID
    reference: str
    workspace_slug: str
    workspace_name: str
    status: str
    name: str
    email: str
    country: str | None
    locale: str | None
    source: str
    origin: str | None
    consent_at: datetime
    consent_notice_version: str
    score: int | None
    tier: str | None
    recommended_product: str | None
    recommended_product_name: str | None
    qualification: dict[str, Any] | None
    breakdown: list[CriterionBreakdown]
    reasons: list[str]
    tier_capped: bool = False
    injection_suspected: bool = False
    detected_language: str | None
    error_reason: str | None
    created_at: datetime
    updated_at: datetime
    qualified_at: datetime | None
    sent_at: datetime | None
    answers: list[AnswerOut]
    kb_answers: list[KbAnswerOut]
    events: list[LeadEventOut]
    outbox: list[OutboxEventOut]
    messages: list[MessageOut]


class LlmCallOut(BaseModel):
    id: uuid.UUID
    node: str
    provider: str
    model: str
    attempt: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float
    success: bool
    error_code: str | None
    prompt_version: str | None
    created_at: datetime


class AgentRunOut(BaseModel):
    id: uuid.UUID
    run_number: int
    status: str
    graph_version: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    total_cost_usd: float
    error: str | None
    calls: list[LlmCallOut]


class RetriggerResult(BaseModel):
    event_id: uuid.UUID
    attempt: int


class MessageOut(BaseModel):
    id: uuid.UUID
    version: int
    language: str
    channel: str
    channel_recipient: str
    subject: str | None
    body: str
    short_body: str | None
    status: str
    edited_by_operator: bool
    original_body: str | None
    review_note: str | None
    guard_warnings: list[str]
    created_at: datetime
    reviewed_at: datetime | None
    sent_at: datetime | None


class _ReviewBase(BaseModel):
    @model_validator(mode="after")
    def _safe_text(self) -> Self:
        subject = getattr(self, "subject", None)
        if subject is not None and has_unsafe_chars(subject, allow_newlines=False):
            raise ValueError("the subject must not contain control or bidirectional characters")
        for name in ("body", "feedback", "note"):
            text = getattr(self, name, None)
            if text is not None and has_unsafe_chars(text, allow_newlines=True):
                raise ValueError("the text must not contain control or bidirectional characters")
        return self


class ApproveReview(_ReviewBase):
    action: Literal["approve"]
    override: bool = False  # approve even though the draft checks found problems (recorded)


class EditReview(_ReviewBase):
    """Edit and approve: the operator's text replaces the draft (the original is kept)."""

    action: Literal["edit"]
    subject: str | None = Field(default=None, min_length=1, max_length=150)
    body: str = Field(min_length=1, max_length=4000)
    override: bool = False


class RejectReview(_ReviewBase):
    action: Literal["reject"]
    note: str | None = Field(default=None, max_length=500)


class RegenerateReview(_ReviewBase):
    action: Literal["regenerate"]
    feedback: str | None = Field(default=None, max_length=500)


ReviewRequest = Annotated[
    ApproveReview | EditReview | RejectReview | RegenerateReview, Field(discriminator="action")
]


class ReviewResult(BaseModel):
    lead_id: uuid.UUID
    status: str
    message_id: uuid.UUID
    error_reason: str | None = None


class QualifyResult(BaseModel):
    lead_id: uuid.UUID
    agent_run_id: uuid.UUID
    status: str
    score: int | None = None
    tier: str | None = None
    recommended_product: str | None = None
    error_reason: str | None = None


class MessageContent(BaseModel):
    """An approved message as n8n needs it to send. Served on the private, authenticated API."""

    id: uuid.UUID
    deliverable: bool
    status: str
    lead_id: uuid.UUID | None = None
    channel: str | None = None
    recipient: str | None = None
    subject: str | None = None
    body: str | None = None
    language: str | None = None
    from_address: str | None = None
    message_id_header: str | None = None


class SentCallback(BaseModel):
    message_id: uuid.UUID
    provider_message_id: str | None = Field(default=None, max_length=200)


class SendFailedCallback(BaseModel):
    message_id: uuid.UUID
    error: str | None = Field(default=None, max_length=200)  # accepted, never stored


class DeliveryOut(BaseModel):
    message_id: uuid.UUID
    status: str
    changed: bool


class AckResult(BaseModel):
    event_id: uuid.UUID
    status: Literal["delivered"] = "delivered"
    changed: bool


class StatusCount(BaseModel):
    status: str
    count: int


class ScoreBucket(BaseModel):
    """Leads scoring ``min_score..max_score``, split by the tier stored on each lead."""

    min_score: int
    max_score: int
    count: int
    hot: int
    warm: int
    cold: int


class TierCount(BaseModel):
    tier: Literal["hot", "warm", "cold", "unscored"]
    count: int


class TimeToQualify(BaseModel):
    """Seconds from application to the first qualification (``qualified_at - created_at``)."""

    count: int
    avg_seconds: float | None
    p50_seconds: float | None
    p90_seconds: float | None


class DayCount(BaseModel):
    day: date
    count: int


class CostMetrics(BaseModel):
    total_usd: float
    avg_per_lead_usd: float | None
    leads_with_runs: int
    llm_calls: int
    providers: list[str]
    ask_total_usd: float  # "Ask the docs" chat runs of the workspace, not tied to any lead
    ask_questions: int
    lifetime_spent_usd: float
    budget_usd: float


class TierThresholds(BaseModel):
    hot_min: int
    warm_min: int


class MetricsOut(BaseModel):
    workspace: str | None
    first_day: date
    last_day: date
    total_leads: int
    by_status: list[StatusCount]
    score_histogram: list[ScoreBucket]
    tier_split: list[TierCount]
    tier_thresholds: TierThresholds | None = None
    time_to_qualify: TimeToQualify
    leads_per_day: list[DayCount]
    cost: CostMetrics


class KbReindexResult(BaseModel):
    workspace: str
    added: int
    updated: int
    unchanged: int
    removed: int
    skipped: int
    chunks: int
