"""Lead lifecycle: a pure state machine with an explicit allowed-transitions table."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from enum import StrEnum

from lead_qualifier.domain.errors import InvalidTransition


class LeadStatus(StrEnum):
    NEW = "new"
    QUALIFYING = "qualifying"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"
    ERROR = "error"


class LeadTrigger(StrEnum):
    QUALIFY_STARTED = "qualify_started"
    REVIEW_READY = "review_ready"
    FAILED = "failed"
    RETRY = "retry"
    REGENERATE = "regenerate"
    APPROVE = "approve"
    REJECT = "reject"
    SENT = "sent"
    SEND_FAILED = "send_failed"


S = LeadStatus
T = LeadTrigger

TRANSITIONS: dict[tuple[LeadStatus, LeadTrigger], LeadStatus] = {
    (S.NEW, T.QUALIFY_STARTED): S.QUALIFYING,
    (S.QUALIFYING, T.REVIEW_READY): S.PENDING_REVIEW,
    (S.QUALIFYING, T.FAILED): S.ERROR,
    (S.ERROR, T.RETRY): S.QUALIFYING,
    (S.PENDING_REVIEW, T.REGENERATE): S.QUALIFYING,
    (S.PENDING_REVIEW, T.APPROVE): S.APPROVED,
    (S.PENDING_REVIEW, T.REJECT): S.REJECTED,
    (S.APPROVED, T.SENT): S.SENT,
    (S.APPROVED, T.SEND_FAILED): S.ERROR,
}

TERMINAL_STATUSES = frozenset({S.REJECTED, S.SENT})


@dataclass(frozen=True)
class Lead:
    id: uuid.UUID
    workspace_slug: str
    status: LeadStatus = LeadStatus.NEW
    error_reason: str | None = None


def next_status(status: LeadStatus, trigger: LeadTrigger) -> LeadStatus:
    try:
        return TRANSITIONS[(status, trigger)]
    except KeyError:
        raise InvalidTransition(
            f"A lead in status '{status.value}' cannot handle '{trigger.value}'."
        ) from None


def transition(lead: Lead, trigger: LeadTrigger, *, reason: str | None = None) -> Lead:
    """Return the lead in its new status. ``reason`` is stored when entering ``error``."""
    new_status = next_status(lead.status, trigger)
    error_reason = reason if new_status is LeadStatus.ERROR else None
    return replace(lead, status=new_status, error_reason=error_reason)
