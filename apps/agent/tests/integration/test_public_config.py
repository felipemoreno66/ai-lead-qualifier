from __future__ import annotations

import httpx
import pytest

from lead_qualifier.config import Settings
from lead_qualifier.http.app import create_app
from tests.helpers import WORKSPACES_DIR


def _client(**overrides: object) -> httpx.AsyncClient:
    settings = Settings(
        app_env="test",
        workspaces_dir=WORKSPACES_DIR,
        enabled_workspaces=str(overrides.pop("enabled", "northwind-academy")),
        **overrides,  # type: ignore[arg-type]
    )
    app = create_app(settings)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_public_config_returns_public_data_only():
    async with _client() as client:
        response = await client.get("/api/workspaces/northwind-academy/public-config")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Northwind Academy"
    assert body["default_language"] == "en"
    assert {f["id"] for f in body["form"]["fields"]} >= {"name", "email", "program"}
    text = response.text
    for hidden in ("criteria", "owner_email", "weight", "signature", "allowed_origins"):
        assert hidden not in text
    assert response.headers["cache-control"] == "public, max-age=60"


async def test_unknown_workspace_is_404_problem_details():
    async with _client() as client:
        response = await client.get("/api/workspaces/nope/public-config")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 404


@pytest.mark.parametrize("allow_draft", [False, True])
async def test_draft_workspace_is_hidden_unless_explicitly_allowed(allow_draft: bool):
    async with _client(
        enabled="northwind-academy,david-moreno", allow_draft_workspaces=allow_draft
    ) as client:
        response = await client.get("/api/workspaces/david-moreno/public-config")
    assert response.status_code == (200 if allow_draft else 404)


async def test_workspace_that_is_not_enabled_is_404():
    async with _client() as client:
        response = await client.get("/api/workspaces/david-moreno/public-config")
    assert response.status_code == 404
