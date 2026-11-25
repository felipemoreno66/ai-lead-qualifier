"""Aggregations behind ``GET /admin/metrics``: counts, score distribution, timing and spend.

Everything is computed in SQL over the leads created inside the window (UTC days, both ends
inclusive). Spend comes from ``agent_runs.total_cost_usd`` (kept as long as the lead exists); the
lifetime figure comes from the append-only budget ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.domain.errors import ValidationFailed
from lead_qualifier.domain.lead import LeadStatus
from lead_qualifier.http.schemas import (
    CostMetrics,
    DayCount,
    MetricsOut,
    ScoreBucket,
    StatusCount,
    TierCount,
    TierThresholds,
    TimeToQualify,
)

MAX_DAYS = 366
TIER_ORDER = ("hot", "warm", "cold")


@dataclass(frozen=True)
class MetricsWindow:
    """Inclusive UTC day range."""

    first: date
    last: date

    @classmethod
    def resolve(cls, first: date | None, last: date | None, today: date) -> MetricsWindow:
        end = last or today
        start = first or end - timedelta(days=29)
        if start > end:
            raise ValidationFailed("'from' must not be after 'to'.")
        if (end - start).days + 1 > MAX_DAYS:
            raise ValidationFailed(f"The range may cover at most {MAX_DAYS} days.")
        return cls(start, end)

    @property
    def start_at(self) -> datetime:
        return datetime.combine(self.first, datetime.min.time(), tzinfo=UTC)

    @property
    def end_at(self) -> datetime:
        return datetime.combine(self.last + timedelta(days=1), datetime.min.time(), tzinfo=UTC)

    def days(self) -> list[date]:
        return [self.first + timedelta(days=i) for i in range((self.last - self.first).days + 1)]


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


async def compute_metrics(
    engine: AsyncEngine,
    window: MetricsWindow,
    *,
    workspace: str | None,
    budget_usd: float,
    tier_thresholds: TierThresholds | None = None,
) -> MetricsOut:
    params: dict[str, Any] = {"ws": workspace, "start": window.start_at, "end": window.end_at}
    scope = (
        "FROM leads l WHERE (CAST(:ws AS text) IS NULL OR l.workspace_slug = :ws) "
        "AND l.created_at >= :start AND l.created_at < :end"
    )
    run_scope = (
        "FROM agent_runs r JOIN leads l ON l.id = r.lead_id "
        "WHERE r.kind = 'qualify' AND (CAST(:ws AS text) IS NULL OR l.workspace_slug = :ws) "
        "AND l.created_at >= :start AND l.created_at < :end"
    )
    # The ``scope`` fragments below are constants; every value reaches SQL as a bound parameter.
    async with engine.connect() as conn:

        async def rows(sql: str) -> list[Any]:
            return list((await conn.execute(sa.text(sql), params)).all())

        statuses = dict(await rows(f"SELECT l.status, count(*) {scope} GROUP BY l.status"))
        buckets: dict[int, dict[str, int]] = {}
        for bucket, tier, n in await rows(
            f"SELECT least(l.score / 10, 9) AS b, l.tier, count(*) {scope} "
            "AND l.score IS NOT NULL GROUP BY b, l.tier"
        ):
            buckets.setdefault(bucket, {})[tier] = n
        tiers = dict(
            await rows(f"SELECT coalesce(l.tier, 'unscored'), count(*) {scope} GROUP BY 1")
        )
        days = dict(
            await rows(
                f"SELECT (l.created_at AT TIME ZONE 'UTC')::date AS d, count(*) {scope} GROUP BY d"
            )
        )
        (ttq,) = await rows(
            "SELECT count(*), avg(x), percentile_cont(0.5) WITHIN GROUP (ORDER BY x), "  # noqa: S608
            "percentile_cont(0.9) WITHIN GROUP (ORDER BY x) FROM ("
            "SELECT extract(epoch FROM (l.qualified_at - l.created_at)) AS x "
            f"{scope} AND l.qualified_at IS NOT NULL) t"
        )
        (spend,) = await rows(
            f"SELECT coalesce(sum(r.total_cost_usd), 0), "
            f"count(DISTINCT r.lead_id) FILTER (WHERE r.total_cost_usd IS NOT NULL) {run_scope}"
        )
        (calls,) = await rows(
            "SELECT count(*), coalesce(array_agg(DISTINCT c.provider) "
            "FILTER (WHERE c.provider IS NOT NULL), '{}') "
            "FROM llm_calls c JOIN agent_runs r ON r.id = c.agent_run_id "
            "JOIN leads l ON l.id = r.lead_id "
            "WHERE r.kind = 'qualify' AND (CAST(:ws AS text) IS NULL OR l.workspace_slug = :ws) "
            "AND l.created_at >= :start AND l.created_at < :end"
        )
        (ask,) = await rows(
            "SELECT coalesce(sum(r.total_cost_usd), 0), count(*) FROM agent_runs r "
            "WHERE r.kind = 'kb_chat' AND (CAST(:ws AS text) IS NULL OR r.workspace_slug = :ws) "
            "AND r.started_at >= :start AND r.started_at < :end"
        )
        lifetime = (await conn.execute(sa.text("SELECT spent_usd FROM llm_budget"))).scalar()

    total = sum(statuses.values())
    total_cost = Decimal(spend[0])
    leads_with_runs = int(spend[1])
    providers = sorted(calls[1])
    return MetricsOut(
        workspace=workspace,
        first_day=window.first,
        last_day=window.last,
        total_leads=total,
        by_status=[StatusCount(status=s.value, count=statuses.get(s.value, 0)) for s in LeadStatus],
        score_histogram=[
            ScoreBucket(
                min_score=i * 10,
                max_score=100 if i == 9 else i * 10 + 9,
                count=sum(buckets.get(i, {}).values()),
                hot=buckets.get(i, {}).get("hot", 0),
                warm=buckets.get(i, {}).get("warm", 0),
                cold=buckets.get(i, {}).get("cold", 0),
            )
            for i in range(10)
        ],
        tier_thresholds=tier_thresholds,
        tier_split=[TierCount(tier=t, count=tiers.get(t, 0)) for t in (*TIER_ORDER, "unscored")],
        time_to_qualify=TimeToQualify(
            count=int(ttq[0]),
            avg_seconds=_num(ttq[1]),
            p50_seconds=_num(ttq[2]),
            p90_seconds=_num(ttq[3]),
        ),
        leads_per_day=[DayCount(day=d, count=days.get(d, 0)) for d in window.days()],
        cost=CostMetrics(
            total_usd=float(total_cost),
            avg_per_lead_usd=float(total_cost / leads_with_runs) if leads_with_runs else None,
            leads_with_runs=leads_with_runs,
            llm_calls=int(calls[0]),
            providers=providers,
            ask_total_usd=float(ask[0]),
            ask_questions=int(ask[1]),
            lifetime_spent_usd=float(lifetime or 0),
            budget_usd=budget_usd,
        ),
    )
