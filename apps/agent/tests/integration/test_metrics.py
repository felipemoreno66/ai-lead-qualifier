from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.integration.test_admin_api import AUTH, N8N_AUTH, seeded  # noqa: F401
from tests.integration.test_review import pending, provider

pytestmark = pytest.mark.integration


async def test_metrics_need_the_admin_token(make_client):
    async with make_client() as client:
        assert (await client.get("/admin/metrics")).status_code == 401
        assert (await client.get("/admin/metrics", headers=N8N_AUTH)).status_code == 403
        assert (await client.get("/admin/metrics", headers=AUTH)).status_code == 200


async def test_an_empty_database_gives_zeros_and_no_averages(make_client):
    async with make_client() as client:
        data = (await client.get("/admin/metrics", headers=AUTH)).json()
    assert data["total_leads"] == 0
    assert [s["count"] for s in data["by_status"]] == [0] * 7
    assert len(data["score_histogram"]) == 10 and len(data["leads_per_day"]) == 30
    assert data["time_to_qualify"] == {
        "count": 0,
        "avg_seconds": None,
        "p50_seconds": None,
        "p90_seconds": None,
    }
    assert data["cost"]["total_usd"] == 0 and data["cost"]["avg_per_lead_usd"] is None


async def test_the_seeded_demo_adds_up(make_client, seeded):  # noqa: F811
    async with make_client() as client:
        data = (
            await client.get(
                "/admin/metrics", headers=AUTH, params={"workspace": "northwind-academy"}
            )
        ).json()
    assert data["total_leads"] == 20
    assert sum(s["count"] for s in data["by_status"]) == 20
    assert sum(d["count"] for d in data["leads_per_day"]) == 20
    scored = sum(b["count"] for b in data["score_histogram"])
    assert scored == sum(t["count"] for t in data["tier_split"] if t["tier"] != "unscored")
    assert scored > 0
    assert [(b["min_score"], b["max_score"]) for b in data["score_histogram"]][-1] == (90, 100)
    assert data["tier_thresholds"] == {"hot_min": 75, "warm_min": 45}
    assert data["time_to_qualify"]["count"] > 0
    assert data["time_to_qualify"]["p50_seconds"] <= data["time_to_qualify"]["p90_seconds"]
    assert data["cost"]["total_usd"] == 0  # the seed carries no model calls


async def test_a_qualified_lead_reports_calls_time_and_a_free_provider(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        await pending(client, "m1@example.com")
        data = (await client.get("/admin/metrics", headers=AUTH)).json()
    assert data["total_leads"] == 1
    assert next(s["count"] for s in data["by_status"] if s["status"] == "pending_review") == 1
    assert data["time_to_qualify"]["count"] == 1 and data["time_to_qualify"]["avg_seconds"] >= 0
    cost = data["cost"]
    assert cost["llm_calls"] == 3 and cost["providers"] == ["fake"]
    assert cost["total_usd"] == 0 and cost["avg_per_lead_usd"] == 0
    assert cost["leads_with_runs"] == 1 and cost["budget_usd"] > 0


async def test_the_window_filters_by_creation_day(make_client, seeded):  # noqa: F811
    today = datetime.now(UTC).date()
    past = today - timedelta(days=200)
    async with make_client() as client:
        old = (
            await client.get(
                "/admin/metrics",
                headers=AUTH,
                params={"from": str(past - timedelta(days=5)), "to": str(past)},
            )
        ).json()
        today_only = (
            await client.get(
                "/admin/metrics", headers=AUTH, params={"from": str(today), "to": str(today)}
            )
        ).json()
    assert old["total_leads"] == 0 and len(old["leads_per_day"]) == 6
    assert len(today_only["leads_per_day"]) == 1


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-02-01", "to": "2026-01-01"},
        {"from": "2024-01-01", "to": "2026-01-01"},
        {"workspace": "nope"},
        {"from": "not-a-date"},
    ],
)
async def test_bad_ranges_and_workspaces_are_validation_errors(make_client, params):
    async with make_client() as client:
        response = await client.get("/admin/metrics", headers=AUTH, params=params)
    assert response.status_code == 422
