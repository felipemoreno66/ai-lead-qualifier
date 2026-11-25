"""Scoring in code: per-criterion judgments x workspace weights -> 0-100 score and tier.

The LLM only judges each criterion; it never produces the number (plan D8).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from lead_qualifier.domain.workspace import Criterion, Tier, Tiers


class Judgment(StrEnum):
    MET = "met"
    PARTIAL = "partial"
    UNMET = "unmet"


JUDGMENT_VALUE: dict[Judgment, float] = {
    Judgment.MET: 1.0,
    Judgment.PARTIAL: 0.5,
    Judgment.UNMET: 0.0,
}


def compute_score(criteria: list[Criterion], judgments: Mapping[str, Judgment]) -> int:
    """Weighted share of satisfied criteria, rounded half up to an integer 0-100."""
    total = sum(c.weight for c in criteria)
    earned = sum(c.weight * JUDGMENT_VALUE[judgments[c.id]] for c in criteria)
    return int(earned / total * 100 + 0.5)


def tier_for(score: int, tiers: Tiers) -> Tier:
    if score >= tiers.hot_min:
        return Tier.HOT
    if score >= tiers.warm_min:
        return Tier.WARM
    return Tier.COLD
