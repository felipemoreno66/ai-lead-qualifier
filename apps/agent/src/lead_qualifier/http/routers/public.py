"""Public endpoints: callable from browsers and external sites (CORS + rate limits apply)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from lead_qualifier.domain.errors import NotFound
from lead_qualifier.domain.workspace import PublicWorkspaceConfig, to_public
from lead_qualifier.http.deps import RegistryDep, SettingsDep

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/workspaces/{slug}/public-config", response_model=PublicWorkspaceConfig)
async def public_config(
    slug: str, response: Response, registry: RegistryDep, settings: SettingsDep
) -> PublicWorkspaceConfig:
    workspace = registry.public(slug, allow_draft=settings.allow_draft_workspaces)
    if workspace is None:
        raise NotFound("Unknown workspace.")
    response.headers["Cache-Control"] = "public, max-age=60"
    return to_public(workspace.config)
