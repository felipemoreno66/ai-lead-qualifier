from __future__ import annotations

import httpx
import pytest

from lead_qualifier.config import Settings
from lead_qualifier.http.app import create_app


@pytest.fixture
def unreachable_db_app():
    settings = Settings(
        app_env="test",
        database_url="postgresql+psycopg://nobody:nopass@127.0.0.1:1/none?connect_timeout=1",
    )
    return create_app(settings)


async def test_healthz_is_ok_without_database(unreachable_db_app):
    transport = httpx.ASGITransport(app=unreachable_db_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


async def test_readyz_is_503_when_database_is_down(unreachable_db_app):
    transport = httpx.ASGITransport(app=unreachable_db_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] is False


async def test_request_id_is_echoed_when_valid(unreachable_db_app):
    transport = httpx.ASGITransport(app=unreachable_db_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz", headers={"X-Request-ID": "abc-12345678"})
    assert response.headers["x-request-id"] == "abc-12345678"
