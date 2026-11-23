from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.domain.lead import LeadStatus
from lead_qualifier.infrastructure.db.repositories import (
    LeadFilters,
    LeadRepository,
    OutboxRepository,
    RateLimitRepository,
    StatusConflict,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def lead_values(n: int, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "reference": f"NW-T{n:04d}",
        "workspace_slug": "northwind-academy",
        "name": f"Person {n}",
        "email": f"person{n}@example.com",
        "country": "CO",
        "answers": {"program": "data-ai-course"},
        "source": "hosted_form",
        "ip_hash": "h",
        "consent_at": NOW,
        "consent_notice_version": "2026-11-01",
        "created_at": NOW + timedelta(minutes=n),
    }
    values.update(overrides)
    return values


async def test_insert_get_and_cascade_delete(db: AsyncEngine):
    async with db.begin() as conn:
        leads, outbox = LeadRepository(conn), OutboxRepository(conn)
        lead_id = await leads.insert(lead_values(1))
        await leads.add_event(lead_id, "submitted")
        await outbox.enqueue(
            event_type="lead.created",
            aggregate_id=lead_id,
            lead_id=lead_id,
            payload={},
            idempotency_key="k1",
            now=NOW,
        )
    async with db.begin() as conn:
        leads, outbox = LeadRepository(conn), OutboxRepository(conn)
        row = await leads.get(lead_id)
        assert row and row["status"] == "new" and row["email"] == "person1@example.com"
        assert len(await leads.events(lead_id)) == 1
        assert len(await outbox.for_lead(lead_id)) == 1
        assert await leads.delete(lead_id)
        assert await leads.get(lead_id) is None
        assert await leads.events(lead_id) == []
        assert await outbox.for_lead(lead_id) == []
        assert not await leads.delete(lead_id)


async def test_email_is_case_insensitive_and_duplicates_are_found(db: AsyncEngine):
    async with db.begin() as conn:
        leads = LeadRepository(conn)
        await leads.insert(lead_values(1, email="Ana@Example.com"))
        found = await leads.find_recent_duplicate("northwind-academy", "ana@example.com", NOW)
        assert found and found["reference"] == "NW-T0001"
        assert (
            await leads.find_recent_duplicate("northwind-academy", "other@example.com", NOW) is None
        )
        later = NOW + timedelta(hours=1)
        assert (
            await leads.find_recent_duplicate("northwind-academy", "ana@example.com", later) is None
        )


async def test_optimistic_status_update_conflicts_when_status_moved(db: AsyncEngine):
    async with db.begin() as conn:
        leads = LeadRepository(conn)
        lead_id = await leads.insert(lead_values(1))
        await leads.update_status(lead_id, LeadStatus.NEW, LeadStatus.QUALIFYING, NOW)
        with pytest.raises(StatusConflict) as excinfo:
            await leads.update_status(lead_id, LeadStatus.NEW, LeadStatus.QUALIFYING, NOW)
        assert excinfo.value.status == 409
        row = await leads.get(lead_id)
        assert row and row["status"] == "qualifying"


async def test_search_filters_sorting_and_groups(db: AsyncEngine):
    async with db.begin() as conn:
        leads = LeadRepository(conn)
        await leads.insert(lead_values(1, score=90, tier="hot", status="pending_review"))
        await leads.insert(lead_values(2, score=60, tier="warm", status="sent"))
        await leads.insert(lead_values(3))
        await leads.insert(lead_values(4, score=10, tier="cold", status="rejected"))
        await leads.insert(lead_values(5, status="error", error_reason="llm_timeout"))
        await leads.insert(lead_values(6, name="Zed O'Brien 100%", email="zed_o@example.org"))

        page = await leads.search(LeadFilters())
        assert page.total == 6
        assert [i["group"] for i in page.items] == [
            "attention", "hot", "warm", "scoring", "scoring", "cold",
        ]  # fmt: skip

        by_status = await leads.search(LeadFilters(statuses=["new"]))
        assert by_status.total == 2
        assert (await leads.search(LeadFilters(tiers=["hot", "warm"]))).total == 2
        assert (await leads.search(LeadFilters(score_min=50, score_max=95))).total == 2
        assert (await leads.search(LeadFilters(q="zed_o@"))).total == 1
        assert (await leads.search(LeadFilters(q="100%"))).total == 1
        assert (await leads.search(LeadFilters(q="%"))).total == 1
        newest_first = await leads.search(LeadFilters(sort="-created_at"))
        assert newest_first.items[0]["reference"] == "NW-T0006"
        paged = await leads.search(LeadFilters(page=2, page_size=4))
        assert len(paged.items) == 2 and paged.total == 6
        assert (await leads.search(LeadFilters(workspace="other"))).total == 0


async def test_outbox_claim_skips_locked_rows_and_respects_due_time(db: AsyncEngine):
    async with db.begin() as conn:
        leads, outbox = LeadRepository(conn), OutboxRepository(conn)
        lead_id = await leads.insert(lead_values(1))
        for i, due in enumerate([NOW, NOW + timedelta(minutes=5)]):
            await outbox.enqueue(
                event_type="lead.created",
                aggregate_id=lead_id,
                lead_id=lead_id,
                payload={},
                idempotency_key=f"k{i}",
                now=due,
            )
        assert await outbox.enqueue(
            event_type="lead.created", aggregate_id=lead_id, lead_id=lead_id, payload={},
            idempotency_key="k0", now=NOW,
        ) is None  # fmt: skip

    async with db.begin() as conn:
        claimed = await OutboxRepository(conn).claim_due(NOW, 10, 60)
        assert [c["idempotency_key"] for c in claimed] == ["k0"]
        assert claimed[0]["status"] == "processing"
    async with db.begin() as conn:
        assert await OutboxRepository(conn).claim_due(NOW, 10, 60) == []
        # An expired lock is claimable again (crashed dispatcher).
        again = await OutboxRepository(conn).claim_due(NOW + timedelta(minutes=2), 10, 60)
        assert [c["idempotency_key"] for c in again] == ["k0"]


async def test_outbox_failure_then_dead_and_delivery_is_idempotent(db: AsyncEngine):
    async with db.begin() as conn:
        leads, outbox = LeadRepository(conn), OutboxRepository(conn)
        lead_id = await leads.insert(lead_values(1))
        event_id = await outbox.enqueue(
            event_type="lead.created", aggregate_id=lead_id, lead_id=lead_id, payload={},
            idempotency_key="k", now=NOW,
        )  # fmt: skip
        assert event_id
        await outbox.claim_due(NOW, 1, 60)
        retry_at = NOW + timedelta(seconds=5)
        row = await outbox.mark_failed(event_id, error="boom", next_attempt_at=retry_at)
        assert row and row["status"] == "pending" and row["attempts"] == 1
        assert row["next_attempt_at"] == retry_at
        # Not processing any more: a second failure report is ignored.
        assert await outbox.mark_failed(event_id, error="x", next_attempt_at=None) is None
        await outbox.claim_due(retry_at, 1, 60)
        dead = await outbox.mark_failed(event_id, error="boom", next_attempt_at=None)
        assert dead and dead["status"] == "dead" and dead["attempts"] == 2
        assert [e["id"] for e in await outbox.list_by_status("dead")] == [event_id]
        assert await outbox.mark_delivered(event_id, NOW)
        assert await outbox.mark_delivered(event_id, NOW) is None


async def test_rate_limit_counter_increments_per_window(db: AsyncEngine):
    async with db.begin() as conn:
        repo = RateLimitRepository(conn)
        assert [await repo.hit("k", NOW) for _ in range(3)] == [1, 2, 3]
        assert await repo.hit("k", NOW + timedelta(minutes=1)) == 1
        assert await repo.hit("other", NOW) == 1
        assert await repo.purge_before(NOW + timedelta(seconds=30)) == 2


async def test_unknown_lead_id_returns_none(db: AsyncEngine):
    async with db.begin() as conn:
        assert await LeadRepository(conn).get(uuid.uuid4()) is None
