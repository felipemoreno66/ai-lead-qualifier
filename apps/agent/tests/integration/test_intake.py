from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.logging import configure_logging

pytestmark = pytest.mark.integration

URL = "/api/leads/northwind-academy"
REFERENCE_RE = re.compile(r"^NW-[A-HJ-NP-Z2-9]{6}$")


def body(**overrides: Any) -> dict[str, Any]:
    fields = {
        "name": "Ana Torres",
        "email": "ana@example.com",
        "country": "CO",
        "program": "data-ai-course",
        "career_goal": "Move from accounting to data work.",
        "budget": "500-2500",
        "availability": "5-10h",
        "looking_for": "Is there a payment plan?",
    }
    fields.update(overrides.pop("fields", {}))
    payload: dict[str, Any] = {
        "fields": fields,
        "consent": True,
        "consent_notice_version": "2026-11-01",
        "locale": "es",
        "hp_company_website": "",
        "form_rendered_at": (datetime.now(UTC) - timedelta(seconds=30)).isoformat(),
    }
    payload.update(overrides)
    return payload


async def count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())  # noqa: S608


async def test_valid_submission_is_accepted_and_stored_atomically(make_client, db):
    async with make_client() as client:
        response = await client.post(URL, json=body(), headers={"User-Agent": "pytest"})
    assert response.status_code == 202
    data = response.json()
    assert data["received"] is True
    assert REFERENCE_RE.match(data["reference"])

    async with db.connect() as conn:
        lead = (await conn.execute(text("SELECT * FROM leads"))).mappings().one()
        events = (await conn.execute(text("SELECT type FROM lead_events"))).scalars().all()
        outbox = (await conn.execute(text("SELECT * FROM outbox_events"))).mappings().one()
    assert lead["status"] == "new"
    assert lead["reference"] == data["reference"]
    assert lead["email"] == "ana@example.com"
    assert lead["country"] == "CO"
    assert lead["locale"] == "es"
    assert lead["source"] == "external_api"
    assert lead["free_text"] == "Is there a payment plan?"
    assert len(lead["ip_hash"]) == 64 and "127.0.0.1" not in lead["ip_hash"]
    assert lead["answers"]["program"] == "data-ai-course"
    assert events == ["submitted"]
    assert outbox["event_type"] == "lead.created"
    assert outbox["status"] == "pending"
    assert outbox["lead_id"] == lead["id"]
    assert outbox["payload"]["lead"]["reference"] == data["reference"]


async def test_failure_while_enqueuing_rolls_everything_back(make_client, db, monkeypatch):
    from lead_qualifier.infrastructure.db.repositories import OutboxRepository

    async def boom(self, **kwargs):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(OutboxRepository, "enqueue", boom)
    async with make_client() as client:
        response = await client.post(URL, json=body())
    assert response.status_code == 500
    assert await count(db, "leads") == 0
    assert await count(db, "lead_events") == 0


async def test_requests_from_the_web_origin_are_marked_hosted_form(make_client, db):
    async with make_client() as client:
        response = await client.post(URL, json=body(), headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 202
    async with db.connect() as conn:
        assert (await conn.execute(text("SELECT source FROM leads"))).scalar_one() == "hosted_form"


# --- CORS ------------------------------------------------------------------------------------


async def test_preflight_from_an_allowed_origin_gets_cors_headers(make_client):
    async with make_client() as client:
        for origin in ("https://northwind-academy.example", "http://localhost:3000"):
            response = await client.options(
                URL,
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            assert response.status_code == 204
            assert response.headers["access-control-allow-origin"] == origin
            assert response.headers["access-control-allow-methods"] == "GET, POST, OPTIONS"
            assert response.headers["access-control-allow-headers"] == "content-type"
            assert response.headers["access-control-max-age"] == "600"
            assert "Origin" in response.headers["vary"]
            assert "access-control-allow-credentials" not in response.headers


async def test_preflight_and_post_from_other_origins_are_forbidden(make_client, db):
    async with make_client() as client:
        preflight = await client.options(
            URL,
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        post = await client.post(URL, json=body(), headers={"Origin": "https://evil.example"})
    for response in (preflight, post):
        assert response.status_code == 403
        assert "access-control-allow-origin" not in response.headers
    assert await count(db, "leads") == 0


async def test_actual_response_carries_cors_headers_for_allowed_origin(make_client):
    async with make_client() as client:
        response = await client.post(
            URL, json=body(), headers={"Origin": "https://northwind-academy.example"}
        )
    assert response.status_code == 202
    assert response.headers["access-control-allow-origin"] == "https://northwind-academy.example"


async def test_error_responses_also_carry_cors_headers(make_client):
    async with make_client() as client:
        response = await client.post(
            URL,
            json=body(fields={"email": "nope"}),
            headers={"Origin": "http://localhost:3000"},
        )
    assert response.status_code == 422
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_cors_is_per_workspace(make_client):
    async with make_client(enabled_workspaces="northwind-academy,david-moreno") as client:
        response = await client.options(
            "/api/workspaces/northwind-academy/public-config",
            headers={
                "Origin": "https://northwind-academy.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 204


# --- rate limiting --------------------------------------------------------------------------


async def test_sixth_request_per_minute_from_the_same_ip_is_429(make_client, db):
    async with make_client(trusted_proxies="127.0.0.1/32") as client:
        headers = {"X-Forwarded-For": "203.0.113.7"}
        statuses = []
        for i in range(6):
            r = await client.post(
                URL, json=body(fields={"email": f"p{i}@example.com"}), headers=headers
            )
            statuses.append(r.status_code)
        assert statuses == [202] * 5 + [429]
        limited = r
        assert int(limited.headers["retry-after"]) > 0
        assert limited.headers["content-type"].startswith("application/problem+json")
        other = await client.post(
            URL,
            json=body(fields={"email": "x@example.com"}),
            headers={"X-Forwarded-For": "203.0.113.8"},
        )
        assert other.status_code == 202
    assert await count(db, "leads") == 6


async def test_forwarded_header_is_ignored_without_a_trusted_proxy(make_client):
    async with make_client() as client:
        statuses = [
            (
                await client.post(
                    URL,
                    json=body(fields={"email": f"s{i}@example.com"}),
                    headers={"X-Forwarded-For": f"203.0.113.{i}"},
                )
            ).status_code
            for i in range(6)
        ]
    assert statuses == [202] * 5 + [429]


async def test_workspace_wide_limit(make_client):
    async with make_client(
        rate_workspace_per_hour=2, rate_ip_per_minute=100, rate_ip_per_hour=100
    ) as c:
        statuses = [
            (await c.post(URL, json=body(fields={"email": f"w{i}@example.com"}))).status_code
            for i in range(3)
        ]
    assert statuses == [202, 202, 429]


async def test_same_email_is_limited_per_day(make_client):
    async with make_client(
        duplicate_window_minutes=0, rate_ip_per_minute=100, rate_ip_per_hour=100
    ) as c:
        statuses = [(await c.post(URL, json=body())).status_code for _ in range(4)]
    assert statuses == [202, 202, 202, 429]


# --- spam ------------------------------------------------------------------------------------


async def test_honeypot_gets_a_fake_202_and_nothing_is_stored(make_client, db):
    async with make_client() as client:
        response = await client.post(URL, json=body(hp_company_website="http://spam.example"))
    assert response.status_code == 202
    assert REFERENCE_RE.match(response.json()["reference"])
    assert await count(db, "leads") == 0
    assert await count(db, "outbox_events") == 0


async def test_form_submitted_too_fast_is_treated_as_spam(make_client, db):
    just_now = datetime.now(UTC).isoformat()
    async with make_client(min_fill_seconds=2) as client:
        response = await client.post(URL, json=body(form_rendered_at=just_now))
    assert response.status_code == 202
    assert await count(db, "leads") == 0


async def test_too_many_links_in_free_text_is_a_validation_error(make_client):
    links = " ".join(f"https://x{i}.example" for i in range(4))
    async with make_client() as client:
        response = await client.post(URL, json=body(fields={"looking_for": links}))
    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"loc": ["fields", "looking_for"], "msg": "must contain at most 3 links"}
    ]


# --- payload limits and validation ------------------------------------------------------------


async def test_oversized_body_is_413(make_client, db):
    async with make_client() as client:
        response = await client.post(URL, json=body(fields={"looking_for": "x" * 20000}))
    assert response.status_code == 413
    assert await count(db, "leads") == 0


async def test_invalid_json_is_400(make_client):
    async with make_client() as client:
        response = await client.post(
            URL, content=b"{not json", headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 400


async def test_unknown_envelope_keys_are_rejected(make_client):
    async with make_client() as client:
        response = await client.post(URL, json=body(extra="x"))
    assert response.status_code == 422


async def test_field_errors_are_reported_per_field(make_client, db):
    async with make_client() as client:
        response = await client.post(
            URL, json=body(fields={"email": "nope", "budget": "free", "name": ""})
        )
    assert response.status_code == 422
    errors = {tuple(e["loc"]): e["msg"] for e in response.json()["errors"]}
    assert errors[("fields", "email")] == "must be a valid email address"
    assert errors[("fields", "budget")] == "is not one of the allowed options"
    assert errors[("fields", "name")] == "required"
    assert await count(db, "leads") == 0


async def test_unknown_and_draft_workspaces_are_404(make_client):
    async with make_client(enabled_workspaces="northwind-academy,david-moreno") as client:
        assert (await client.post("/api/leads/nope", json=body())).status_code == 404
        assert (await client.post("/api/leads/david-moreno", json=body())).status_code == 404


# --- consent ---------------------------------------------------------------------------------


async def test_consent_must_be_given(make_client, db):
    async with make_client() as client:
        response = await client.post(URL, json=body(consent=False))
    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["consent"]
    assert await count(db, "leads") == 0


async def test_outdated_notice_version_is_rejected_with_a_specific_type(make_client):
    async with make_client() as client:
        response = await client.post(URL, json=body(consent_notice_version="2020-01-01"))
    assert response.status_code == 422
    assert response.json()["type"] == "urn:lead-qualifier:consent_outdated"


async def test_consent_version_and_time_are_stored(make_client, db):
    async with make_client() as client:
        await client.post(URL, json=body())
    async with db.connect() as conn:
        row = (
            await conn.execute(text("SELECT consent_notice_version, consent_at FROM leads"))
        ).one()
    assert row.consent_notice_version == "2026-11-01"
    assert row.consent_at is not None


# --- duplicates ------------------------------------------------------------------------------


async def test_duplicate_is_deduplicated_but_never_reveals_the_stored_reference(make_client, db):
    async with make_client() as client:
        first = await client.post(URL, json=body(fields={"email": "Dup@Example.com"}))
        second = await client.post(URL, json=body(fields={"email": "dup@example.com"}))
    assert first.status_code == second.status_code == 202
    assert first.json().keys() == second.json().keys()
    assert REFERENCE_RE.match(second.json()["reference"])
    assert second.json()["reference"] != first.json()["reference"]
    async with db.connect() as conn:
        stored = (await conn.execute(text("SELECT reference FROM leads"))).scalar_one()
    assert stored == first.json()["reference"] != second.json()["reference"]
    assert await count(db, "leads") == 1
    assert await count(db, "outbox_events") == 1


async def test_duplicate_after_the_window_creates_a_new_lead(make_client, db):
    from tests.helpers import FakeClock

    clock = FakeClock()
    async with make_client(clock=clock) as client:
        first = await client.post(URL, json=body())
        clock.advance(minutes=11)
        second = await client.post(URL, json=body())
    assert first.json()["reference"] != second.json()["reference"]
    assert await count(db, "leads") == 2


# --- logging ---------------------------------------------------------------------------------


async def test_logs_do_not_contain_personal_data(make_client):
    async with make_client() as client:
        stream = io.StringIO()
        configure_logging("DEBUG", stream=stream)
        await client.post(
            URL, json=body(fields={"name": "Zelda Unique", "email": "zelda.unique@example.com"})
        )
        await client.post(URL, json=body(fields={"email": "bad-address-unique"}))
    logs = stream.getvalue()
    assert "lead_accepted" in logs and '"event": "request"' in logs
    for secret in (
        "Zelda",
        "zelda.unique",
        "bad-address-unique",
        "Move from accounting",
        "127.0.0.1",
    ):
        assert secret not in logs
    for line in logs.splitlines():
        json.loads(line)  # every line is valid JSON


async def test_an_ip_over_its_limit_does_not_consume_workspace_quota(make_client, db):
    async with make_client(trusted_proxies="127.0.0.1/32", rate_workspace_per_hour=100) as client:
        abuser = {"X-Forwarded-For": "203.0.113.50"}
        statuses = [
            (
                await client.post(
                    URL, json=body(fields={"email": f"abuse{i}@example.com"}), headers=abuser
                )
            ).status_code
            for i in range(10)
        ]
        assert statuses == [202] * 5 + [429] * 5
        async with db.connect() as conn:
            used = (
                await conn.execute(
                    text("SELECT coalesce(sum(count),0) FROM rate_limit_hits WHERE key LIKE 'ws:%'")
                )
            ).scalar_one()
        assert used == 5  # only the 5 accepted requests; the 5 rejected by IP cost nothing
