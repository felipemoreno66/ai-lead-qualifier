from __future__ import annotations

import itertools
import uuid

import pytest

from lead_qualifier.domain.errors import InvalidTransition
from lead_qualifier.domain.lead import (
    TERMINAL_STATUSES,
    TRANSITIONS,
    Lead,
    LeadStatus,
    LeadTrigger,
    next_status,
    transition,
)


def _lead(status: LeadStatus) -> Lead:
    return Lead(id=uuid.uuid4(), workspace_slug="northwind-academy", status=status)


@pytest.mark.parametrize(("source", "trigger", "target"), [(*k, v) for k, v in TRANSITIONS.items()])
def test_every_allowed_transition(source: LeadStatus, trigger: LeadTrigger, target: LeadStatus):
    assert transition(_lead(source), trigger).status is target


@pytest.mark.parametrize(
    ("source", "trigger"),
    [pair for pair in itertools.product(LeadStatus, LeadTrigger) if pair not in TRANSITIONS],
)
def test_every_other_combination_is_rejected(source: LeadStatus, trigger: LeadTrigger):
    with pytest.raises(InvalidTransition) as excinfo:
        transition(_lead(source), trigger)
    assert excinfo.value.status == 409


def test_terminal_statuses_have_no_way_out():
    for status in TERMINAL_STATUSES:
        assert not [t for (s, t) in TRANSITIONS if s is status]


def test_entering_error_keeps_the_reason_and_leaving_clears_it():
    failed = transition(_lead(LeadStatus.QUALIFYING), LeadTrigger.FAILED, reason="llm_timeout")
    assert failed.error_reason == "llm_timeout"
    retried = transition(failed, LeadTrigger.RETRY)
    assert retried.status is LeadStatus.QUALIFYING
    assert retried.error_reason is None


def test_next_status_does_not_mutate_input():
    lead = _lead(LeadStatus.NEW)
    transition(lead, LeadTrigger.QUALIFY_STARTED)
    assert lead.status is LeadStatus.NEW
    assert next_status(LeadStatus.NEW, LeadTrigger.QUALIFY_STARTED) is LeadStatus.QUALIFYING
