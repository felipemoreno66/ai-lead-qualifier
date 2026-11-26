from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from lead_qualifier.ports.clock import SystemClock
from lead_qualifier.scripts.seed import seed
from tests.integration.test_intake import URL, body

pytestmark = pytest.mark.integration
AUTH = {"Authorization": "Bearer test-admin-token-123456"}
N8N_AUTH = {"Authorization": "Bearer test-n8n-token-1234567"}


@pytest.fixture
async def seeded(db, registry):
    await seed(
        db,
        registry,
        workspace="northwind-academy",
        app_env="test",
        clock=SystemClock(),
        ip_hash_secret="s",
    )


async def test_admin_requires_a_valid_bearer_token(make_client):
    async with make_client() as client:
        assert (await client.get("/admin/leads")).status_code == 401
        assert (
            await client.get("/admin/leads", headers={"Authorization": "Basic abc"})
        ).status_code == 401
        wrong = await client.get("/admin/leads", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 403
        assert (await client.get("/admin/leads", headers=AUTH)).status_code == 200
        # the n8n token must not open the admin API, and vice versa
        assert (await client.get("/admin/leads", headers=N8N_AUTH)).status_code == 403
        assert (
            await client.post(f"/internal/events/{uuid.uuid4()}/ack", headers=AUTH)
        ).status_code == 403
        assert (await client.post(f"/internal/events/{uuid.uuid4()}/ack")).status_code == 401


async def test_admin_has_no_cors_headers(make_client):
    async with make_client() as client:
        response = await client.get(
            "/admin/leads", headers={**AUTH, "Origin": "http://localhost:3000"}
        )
    assert "access-control-allow-origin" not in response.headers


async def test_list_is_grouped_by_priority_and_paginated(make_client, seeded):
    async with make_client() as client:
        response = await client.get("/admin/leads", headers=AUTH, params={"page_size": 100})
        data = response.json()
        assert data["total"] == 20
        groups = [i["group"] for i in data["items"]]
        assert groups == sorted(groups, key=["attention", "hot", "warm", "scoring", "cold"].index)
        assert groups[0] == "attention" and groups[-1] == "cold"
        first = data["items"][1]
        assert first["tier"] == "hot" and first["interest"] and first["score"] >= 75

        page2 = (
            await client.get("/admin/leads", headers=AUTH, params={"page": 2, "page_size": 8})
        ).json()
        assert len(page2["items"]) == 8 and page2["page"] == 2


async def test_list_filters(make_client, seeded):
    async with make_client() as client:

        async def total(**params: Any) -> int:
            r = await client.get("/admin/leads", headers=AUTH, params=params)
            assert r.status_code == 200, r.text
            return int(r.json()["total"])

        assert await total(status="new") == 13
        assert await total(status="new,error") == 14
        assert await total(status=["pending_review", "sent"]) == 5
        assert await total(tier="hot") == 3
        assert await total(score_min=60, score_max=80) == 2
        assert await total(q="mateo") == 1
        assert await total(q="@example.org") > 0
        assert await total(workspace="northwind-academy", status="new") == 13
        assert await total(workspace="david-moreno") == 0
        bad = await client.get("/admin/leads", headers=AUTH, params={"status": "bogus"})
        assert bad.status_code == 422
        assert (
            await client.get("/admin/leads", headers=AUTH, params={"sort": "evil"})
        ).status_code == 422
        newest = (
            await client.get("/admin/leads", headers=AUTH, params={"sort": "-created_at"})
        ).json()
        dates = [i["created_at"] for i in newest["items"]]
        assert dates == sorted(dates, reverse=True)


async def test_detail_shows_answers_timeline_and_outbox(make_client, seeded):
    async with make_client() as client:
        listing = (await client.get("/admin/leads", headers=AUTH, params={"q": "Mateo"})).json()
        lead_id = listing["items"][0]["id"]
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
    assert detail["name"] == "Mateo Alvarez"
    assert detail["workspace_name"] == "Northwind Academy"
    assert detail["recommended_product_name"] == "Full Stack Bootcamp"
    answers = {a["id"]: a for a in detail["answers"]}
    assert answers["program"]["display"] == "Full Stack Bootcamp"
    assert answers["budget"]["display"] == "USD 2,500\u20135,000"
    assert [e["type"] for e in detail["events"]][:2] == ["submitted", "outbox_delivered"]
    assert detail["outbox"][0]["status"] == "delivered"
    assert detail["qualification"]["criteria"][0]["id"] == "goal_fit"
    assert "ip_hash" not in detail


async def test_unknown_lead_is_404(make_client, db):
    async with make_client() as client:
        assert (await client.get(f"/admin/leads/{uuid.uuid4()}", headers=AUTH)).status_code == 404
        assert (await client.get("/admin/leads/not-a-uuid", headers=AUTH)).status_code == 422
        assert (
            await client.delete(f"/admin/leads/{uuid.uuid4()}", headers=AUTH)
        ).status_code == 404


async def test_workspaces_listing(make_client, seeded):
    async with make_client(enabled_workspaces="northwind-academy,david-moreno") as client:
        data = (await client.get("/admin/workspaces", headers=AUTH)).json()
    by_slug = {w["slug"]: w for w in data}
    assert by_slug["northwind-academy"]["lead_count"] == 20
    assert by_slug["northwind-academy"]["by_status"]["new"] == 13
    assert by_slug["david-moreno"]["draft"] is True and by_slug["david-moreno"]["enabled"] is True


async def test_delete_removes_the_lead_and_everything_related(make_client, db, seeded):
    async with make_client() as client:
        lead_id = (await client.get("/admin/leads", headers=AUTH, params={"q": "Tomas"})).json()[
            "items"
        ][0]["id"]
        assert (await client.delete(f"/admin/leads/{lead_id}", headers=AUTH)).status_code == 204
        assert (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).status_code == 404
    from sqlalchemy import text

    async with db.connect() as conn:
        for table in ("lead_events", "outbox_events"):
            n = (
                await conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE lead_id = :i"),  # noqa: S608
                    {"i": lead_id},
                )
            ).scalar_one()
            assert n == 0


async def submit(client, email: str = "retry@example.com", **fields: str) -> str:
    response = await client.post(URL, json=body(fields={"email": email, **fields}))
    assert response.status_code == 202
    return response.json()["reference"]


async def lead_id_for(client, q: str) -> str:
    return (await client.get("/admin/leads", headers=AUTH, params={"q": q})).json()["items"][0][
        "id"
    ]


async def test_retrigger_requeues_a_dead_event_and_dispatcher_delivers_it(make_client, db):
    from lead_qualifier.infrastructure.db.repositories import OutboxRepository
    from tests.helpers import FakeClock

    clock = FakeClock()
    async with make_client(clock=clock, outbox_max_attempts=1) as client:
        await submit(client)
        lead_id = await lead_id_for(client, "retry@")
        clock.advance(seconds=1)

        class Down:
            async def publish(self, event: dict[str, Any]) -> None:
                raise RuntimeError("n8n down")

        client.app.state.dispatcher.publisher = Down()
        await client.app.state.dispatcher.run_once()
        clock.advance(seconds=1)

        dead = (await client.get("/admin/outbox", headers=AUTH, params={"status": "dead"})).json()
        assert [e["lead_id"] for e in dead] == [lead_id]

        again = await client.post(f"/admin/leads/{lead_id}/retrigger", headers=AUTH)
        clock.advance(seconds=1)
        assert again.status_code == 202 and again.json()["attempt"] == 2
        # a second click while one is queued is rejected
        assert (
            await client.post(f"/admin/leads/{lead_id}/retrigger", headers=AUTH)
        ).status_code == 409

        delivered: list[str] = []

        class Up:
            async def publish(self, event: dict[str, Any]) -> None:
                delivered.append(event["event_id"])

        client.app.state.dispatcher.publisher = Up()
        await client.app.state.dispatcher.run_once()
        assert len(delivered) == 1
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
    types = [e["type"] for e in detail["events"]]
    assert types == ["submitted", "outbox_failed", "retriggered", "outbox_delivered"]
    assert detail["status"] == "new"
    async with db.connect() as conn:
        assert [e["status"] for e in await OutboxRepository(conn).for_lead(uuid.UUID(lead_id))] == [
            "dead",
            "delivered",
        ]


async def test_retrigger_is_refused_for_other_statuses(make_client, seeded):
    async with make_client() as client:
        sent = await lead_id_for(client, "lucas.ferreira")
        response = await client.post(f"/admin/leads/{sent}/retrigger", headers=AUTH)
        assert response.status_code == 409
        err = await lead_id_for(client, "priya.nair")
        assert (await client.post(f"/admin/leads/{err}/retrigger", headers=AUTH)).status_code == 202
        assert (
            await client.post(f"/admin/leads/{uuid.uuid4()}/retrigger", headers=AUTH)
        ).status_code == 404


async def test_n8n_ack_delivers_the_event_once(make_client, db):
    from sqlalchemy import text

    async with make_client() as client:
        await submit(client, "ack@example.com")
        async with db.connect() as conn:
            event_id = (await conn.execute(text("SELECT id FROM outbox_events"))).scalar_one()
        first = await client.post(f"/internal/events/{event_id}/ack", headers=N8N_AUTH)
        second = await client.post(f"/internal/events/{event_id}/ack", headers=N8N_AUTH)
        missing = await client.post(f"/internal/events/{uuid.uuid4()}/ack", headers=N8N_AUTH)
        lead_id = await lead_id_for(client, "ack@")
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
    assert first.json()["changed"] is True and second.json()["changed"] is False
    assert missing.status_code == 404
    assert [e["type"] for e in detail["events"]] == ["submitted", "outbox_delivered"]
    assert detail["events"][1]["actor"] == "n8n"


async def test_end_to_end_inline_delivery_after_intake(make_client):
    async with make_client(orchestrator="inline") as client:
        await submit(client, "inline@example.com")
        await client.app.state.dispatcher.run_once()
        lead_id = await lead_id_for(client, "inline@")
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
    assert [e["type"] for e in detail["events"]] == [
        "submitted",
        "status_changed",
        "status_changed",
        "outbox_delivered",
    ]
    assert detail["status"] == "pending_review"  # graph ran inline and drafted a reply
    assert detail["messages"][0]["status"] == "draft"
    assert detail["score"] is not None and detail["tier"] in {"hot", "warm", "cold"}
    assert detail["outbox"][0]["status"] == "delivered"
    assert datetime.fromisoformat(detail["created_at"]).tzinfo is not None
    assert UTC


async def test_admin_and_internal_routers_can_be_left_unmounted(make_client):
    async with make_client(expose_admin_api=False) as client:
        assert (await client.get("/admin/leads", headers=AUTH)).status_code == 404
        assert (
            await client.post(f"/internal/events/{uuid.uuid4()}/ack", headers=N8N_AUTH)
        ).status_code == 404
        assert (await client.get("/healthz")).status_code == 200
        assert (
            await client.get("/api/workspaces/northwind-academy/public-config")
        ).status_code == 200


async def test_deleting_a_lead_is_refused_in_the_public_demo(make_client, seeded):
    async with make_client(public_demo=True, smtp_host="mailpit") as client:
        lead = (await client.get("/admin/leads", headers=AUTH)).json()["items"][0]
        response = await client.delete(f"/admin/leads/{lead['id']}", headers=AUTH)
        assert response.status_code == 403
        assert (await client.get(f"/admin/leads/{lead['id']}", headers=AUTH)).status_code == 200
