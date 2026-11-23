"""Metrics over fixed timestamps and an injected clock (no dependence on today's date)."""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import FakeClock
from tests.integration.test_admin_api import AUTH, N8N_AUTH
from tests.integration.test_review import pending, provider

pytestmark = pytest.mark.integration

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
NW = "northwind-academy"
_refs = itertools.count(1)


def clock() -> FakeClock:
    return FakeClock(NOW)


async def add_lead(
    db: AsyncEngine,
    created: datetime,
    *,
    ws: str = NW,
    qualified_after: float | None = None,
    score: int | None = None,
    tier: str | None = None,
    status: str = "new",
) -> uuid.UUID:
    async with db.begin() as conn:
        return (
            await conn.execute(
                sa.text(
                    "INSERT INTO leads (reference, workspace_slug, status, name, email, source,"
                    " ip_hash, consent_at, consent_notice_version, score, tier, created_at,"
                    " qualified_at) VALUES (:ref, :ws, :status, 'Test Lead', :email, 'seed', 'h',"
                    " :created, 'v1', :score, :tier, :created, :qualified) RETURNING id"
                ),
                {
                    "ref": f"MT-{next(_refs):05d}",
                    "ws": ws,
                    "status": status,
                    "email": f"lead{next(_refs)}@example.com",
                    "score": score,
                    "tier": tier,
                    "created": created,
                    "qualified": None
                    if qualified_after is None
                    else created + timedelta(seconds=qualified_after),
                },
            )
        ).scalar_one()


async def add_run(
    db: AsyncEngine, lead_id: uuid.UUID, cost: str, provider_name: str = "anthropic"
) -> None:
    async with db.begin() as conn:
        run_id = (
            await conn.execute(
                sa.text(
                    "INSERT INTO agent_runs (lead_id, thread_id, run_number, graph_version,"
                    " total_cost_usd) VALUES (:lead, :thread, 1, 'g1', :cost) RETURNING id"
                ),
                {"lead": lead_id, "thread": str(uuid.uuid4()), "cost": Decimal(cost)},
            )
        ).scalar_one()
        await conn.execute(
            sa.text(
                "INSERT INTO llm_calls (agent_run_id, node, provider, model, success, cost_usd)"
                " VALUES (:run, 'qualify', :provider, 'm', true, :cost)"
            ),
            {"run": run_id, "provider": provider_name, "cost": Decimal(cost)},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO llm_spend (agent_run_id, provider, model, state, amount_usd)"
                " VALUES (:run, :provider, 'm', 'settled', :cost)"
            ),
            {"run": run_id, "provider": provider_name, "cost": Decimal(cost)},
        )


async def get(client: Any, **params: str) -> dict[str, Any]:
    response = await client.get("/admin/metrics", headers=AUTH, params=params)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


async def test_metrics_need_the_admin_token(make_client):
    async with make_client(clock=clock()) as client:
        assert (await client.get("/admin/metrics")).status_code == 401
        assert (await client.get("/admin/metrics", headers=N8N_AUTH)).status_code == 403
        assert (await client.get("/admin/metrics", headers=AUTH)).status_code == 200


async def test_an_empty_database_gives_zeros_and_no_averages(make_client):
    async with make_client(clock=clock()) as client:
        data = await get(client)
    assert (data["first_day"], data["last_day"]) == ("2026-05-17", "2026-06-15")
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
    assert data["cost"]["lifetime_spent_usd"] == 0  # an empty ledger is zero, not an error


async def test_time_to_qualify_is_exact(make_client, db):
    for seconds in (10, 20, 30, 100):
        await add_lead(
            db, NOW - timedelta(days=2), qualified_after=seconds, status="pending_review"
        )
    await add_lead(db, NOW - timedelta(days=2))  # never qualified: not part of the timing
    async with make_client(clock=clock()) as client:
        t = (await get(client))["time_to_qualify"]
    assert t["count"] == 4
    assert t["avg_seconds"] == pytest.approx(40)
    assert t["p50_seconds"] == pytest.approx(25)  # between 20 and 30
    assert t["p90_seconds"] == pytest.approx(79)  # 30 + 0.7 * (100 - 30)


async def test_days_are_utc_and_the_window_is_inclusive(make_client, db):
    await add_lead(db, datetime(2026, 6, 14, 23, 59, 59, tzinfo=UTC))
    await add_lead(db, datetime(2026, 6, 15, 0, 0, 0, tzinfo=UTC))
    async with make_client(clock=clock()) as client:
        before = await get(client, **{"from": "2026-06-14", "to": "2026-06-14"})
        after = await get(client, **{"from": "2026-06-15", "to": "2026-06-15"})
        both = await get(client, **{"from": "2026-06-14", "to": "2026-06-15"})
        gap = await get(client, **{"from": "2026-05-01", "to": "2026-05-03"})
    assert before["total_leads"] == 1 and before["leads_per_day"] == [
        {"day": "2026-06-14", "count": 1}
    ]
    assert after["total_leads"] == 1 and after["leads_per_day"] == [
        {"day": "2026-06-15", "count": 1}
    ]
    assert [d["count"] for d in both["leads_per_day"]] == [1, 1]
    assert gap["total_leads"] == 0 and len(gap["leads_per_day"]) == 3


async def test_the_workspace_filter_separates_businesses(make_client, db):
    async with db.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO workspaces (slug, name, config_hash) VALUES ('other-biz', 'O', 'x')"
            )
        )
    await add_lead(db, NOW - timedelta(days=1))
    await add_lead(db, NOW - timedelta(days=1))
    await add_lead(db, NOW - timedelta(days=1), ws="other-biz")
    async with make_client(clock=clock()) as client:
        everyone = await get(client)
        northwind = await get(client, workspace=NW)
    assert everyone["total_leads"] == 3 and everyone["tier_thresholds"] is None
    assert northwind["total_leads"] == 2
    assert northwind["tier_thresholds"] == {"hot_min": 75, "warm_min": 45}


async def test_scores_land_in_ten_point_buckets_split_by_stored_tier(make_client, db):
    # 70 to 79 straddles the hot threshold (75): the stored tier decides, not the bucket start.
    await add_lead(db, NOW, score=72, tier="warm")
    await add_lead(db, NOW, score=75, tier="hot")
    await add_lead(db, NOW, score=79, tier="hot")
    await add_lead(db, NOW, score=100, tier="hot")
    await add_lead(db, NOW, score=0, tier="cold")
    await add_lead(db, NOW)  # unscored
    async with make_client(clock=clock()) as client:
        data = await get(client)
    buckets = {b["min_score"]: b for b in data["score_histogram"]}
    assert (buckets[70]["count"], buckets[70]["hot"], buckets[70]["warm"]) == (3, 2, 1)
    assert (buckets[90]["max_score"], buckets[90]["count"], buckets[90]["hot"]) == (100, 1, 1)
    assert (buckets[0]["count"], buckets[0]["cold"]) == (1, 1)
    assert sum(b["count"] for b in buckets.values()) == 5
    assert {t["tier"]: t["count"] for t in data["tier_split"]} == {
        "hot": 3,
        "warm": 1,
        "cold": 1,
        "unscored": 1,
    }


async def test_cost_counts_priced_runs_and_lifetime_keeps_deleted_leads(make_client, db):
    kept = await add_lead(db, NOW - timedelta(days=1))
    gone = await add_lead(db, NOW - timedelta(days=1))
    await add_run(db, kept, "0.300000")
    await add_run(db, gone, "0.100000")
    async with make_client(clock=clock()) as client:
        both = (await get(client))["cost"]
        async with db.begin() as conn:
            await conn.execute(sa.text("DELETE FROM leads WHERE id = :id"), {"id": gone})
        after = (await get(client))["cost"]
    assert both["total_usd"] == pytest.approx(0.4) and both["avg_per_lead_usd"] == pytest.approx(
        0.2
    )
    assert both["leads_with_runs"] == 2 and both["llm_calls"] == 2
    assert both["providers"] == ["anthropic"]
    # The range total follows the leads; the lifetime ledger does not forget a deleted lead.
    assert after["total_usd"] == pytest.approx(0.3) and after["leads_with_runs"] == 1
    assert after["lifetime_spent_usd"] == pytest.approx(0.4)
    assert after["budget_usd"] > 0


async def test_ask_the_docs_spend_is_its_own_figure(make_client, db):
    lead = await add_lead(db, NOW - timedelta(days=1))
    await add_run(db, lead, "0.300000")
    async with db.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO agent_runs (thread_id, run_number, graph_version, kind,"
                " workspace_slug, total_cost_usd, started_at) VALUES"
                " (:t1, 1, 'kb', 'kb_chat', :ws, 0.05, :inside),"
                " (:t2, 1, 'kb', 'kb_chat', :ws, 0.02, :outside)"
            ),
            {
                "t1": str(uuid.uuid4()),
                "t2": str(uuid.uuid4()),
                "ws": NW,
                "inside": NOW - timedelta(days=2),
                "outside": NOW - timedelta(days=90),
            },
        )
    async with make_client(clock=clock()) as client:
        cost = (await get(client, workspace=NW))["cost"]
    # Lead figures count qualification runs only; chat runs have no lead and are listed apart.
    assert cost["total_usd"] == pytest.approx(0.3) and cost["leads_with_runs"] == 1
    assert cost["ask_total_usd"] == pytest.approx(0.05) and cost["ask_questions"] == 1


async def test_a_qualified_lead_reports_calls_and_a_free_provider(make_client, db):
    async with make_client(llm_provider=provider(db)) as client:
        await pending(client, "m1@example.com")
        data = await get(client)
    assert data["total_leads"] == 1
    assert next(s["count"] for s in data["by_status"] if s["status"] == "pending_review") == 1
    assert data["time_to_qualify"]["count"] == 1 and data["time_to_qualify"]["avg_seconds"] >= 0
    cost = data["cost"]
    assert cost["llm_calls"] == 3 and cost["providers"] == ["fake"]
    assert cost["total_usd"] == 0 and cost["avg_per_lead_usd"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-02-01", "to": "2026-01-01"},
        {"from": "2024-01-01", "to": "2026-01-01"},
        {"workspace": "nope"},
        {"workspace": "Bad Slug"},
        {"workspace": "a" * 65},
        {"from": "not-a-date"},
    ],
)
async def test_bad_ranges_and_workspaces_are_validation_errors(make_client, params):
    async with make_client(clock=clock()) as client:
        response = await client.get("/admin/metrics", headers=AUTH, params=params)
    assert response.status_code == 422
