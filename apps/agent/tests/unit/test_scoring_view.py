"""``score_breakdown`` turns stored judgments into points using the workspace weights."""

from __future__ import annotations

from lead_qualifier.http.views import score_breakdown
from lead_qualifier.workspaces.loader import WorkspaceRegistry


def test_breakdown_scores_known_criteria_and_skips_unknown_or_malformed_ones(
    registry: WorkspaceRegistry,
):
    config = registry.get("northwind-academy").config  # type: ignore[union-attr]
    qualification = {
        "criteria": [
            {"id": "goal_fit", "judgment": "met", "evidence": "clear"},
            {"id": "availability_fit", "judgment": "partial", "evidence": "tight"},
            {"id": "not_a_criterion", "judgment": "met", "evidence": "x"},
            {"id": "budget_fit", "judgment": "bogus", "evidence": "x"},
        ]
    }
    rows = score_breakdown(config, qualification)
    assert [r.id for r in rows] == ["goal_fit", "availability_fit"]
    assert (rows[0].points, rows[0].max_points) == (30.0, 30.0)
    assert (rows[1].points, rows[1].max_points) == (10.0, 20.0)


def test_breakdown_is_empty_without_config_or_qualification(registry: WorkspaceRegistry):
    config = registry.get("northwind-academy").config  # type: ignore[union-attr]
    assert score_breakdown(None, {"criteria": []}) == []
    assert score_breakdown(config, None) == []
    assert score_breakdown(config, {}) == []
