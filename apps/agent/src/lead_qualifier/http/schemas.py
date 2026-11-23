"""Response models for the admin API (the contract consumed by the Next.js BFF)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

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
    detected_language: str | None
    error_reason: str | None
    created_at: datetime
    updated_at: datetime
    qualified_at: datetime | None
    sent_at: datetime | None
    answers: list[AnswerOut]
    events: list[LeadEventOut]
    outbox: list[OutboxEventOut]
    messages: list[MessageOut]


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


class ReviewRequest(BaseModel):
    action: Literal["approve", "edit", "reject", "regenerate"]
    subject: str | None = Field(default=None, min_length=1, max_length=150)
    body: str | None = Field(default=None, min_length=1, max_length=4000)
    feedback: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _edit_needs_a_body(self) -> ReviewRequest:
        if self.action == "edit" and not self.body:
            raise ValueError("an edit needs the new body")
        return self


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


class AckResult(BaseModel):
    event_id: uuid.UUID
    status: Literal["delivered"] = "delivered"
    changed: bool
