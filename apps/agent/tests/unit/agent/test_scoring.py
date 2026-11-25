from __future__ import annotations

import pytest

from lead_qualifier.domain.scoring import Judgment, compute_score, tier_for
from lead_qualifier.domain.workspace import Criterion, Tier, Tiers

CRITERIA = [
    Criterion(id="a", description="a", weight=30),
    Criterion(id="b", description="b", weight=10),
]
TIERS = Tiers(hot_min=75, warm_min=45)
M, P, U = Judgment.MET, Judgment.PARTIAL, Judgment.UNMET


@pytest.mark.parametrize(
    ("judgments", "score"),
    [
        ({"a": M, "b": M}, 100),
        ({"a": U, "b": U}, 0),
        ({"a": M, "b": U}, 75),
        ({"a": P, "b": P}, 50),
        ({"a": U, "b": M}, 25),
        ({"a": P, "b": M}, 63),
    ],
)
def test_score_is_the_weighted_share_of_judgments(judgments: dict[str, Judgment], score: int):
    assert compute_score(CRITERIA, judgments) == score


def test_weights_are_normalised_so_they_need_not_sum_to_100():
    scaled = [
        Criterion(id="a", description="a", weight=3),
        Criterion(id="b", description="b", weight=1),
    ]
    assert compute_score(scaled, {"a": M, "b": U}) == 75


@pytest.mark.parametrize(
    ("score", "tier"),
    [
        (100, Tier.HOT),
        (75, Tier.HOT),
        (74, Tier.WARM),
        (45, Tier.WARM),
        (44, Tier.COLD),
        (0, Tier.COLD),
    ],
)
def test_tier_boundaries(score: int, tier: Tier):
    assert tier_for(score, TIERS) == tier
