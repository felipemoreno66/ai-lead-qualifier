"""Public endpoints: callable from browsers and external sites (CORS + rate limits apply)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import ValidationError

from lead_qualifier.domain.errors import BadRequest, NotFound, PayloadTooLarge, ValidationFailed
from lead_qualifier.domain.lead_intake import LeadAccepted, LeadSubmission
from lead_qualifier.domain.workspace import PublicWorkspaceConfig, to_public
from lead_qualifier.http.client_ip import resolve_client_ip
from lead_qualifier.http.deps import RegistryDep, SettingsDep
from lead_qualifier.security import hash_value
from lead_qualifier.services.intake import IntakeService, RequestMeta
from lead_qualifier.services.rate_limit import Limit, RateLimiter

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


@router.post("/leads/{slug}", status_code=202, response_model=LeadAccepted)
async def submit_lead(
    slug: str, request: Request, registry: RegistryDep, settings: SettingsDep
) -> LeadAccepted:
    workspace = registry.public(slug, allow_draft=settings.allow_draft_workspaces)
    if workspace is None:
        raise NotFound("Unknown workspace.")

    limiter: RateLimiter = request.app.state.limiter
    intake: IntakeService = request.app.state.intake
    client = request.client.host if request.client else None
    ip = resolve_client_ip(
        client, request.headers.get("x-forwarded-for"), request.app.state.trusted_networks
    )
    ip_hash = hash_value(ip, settings.ip_hash_secret)
    await limiter.hit(
        [
            Limit(f"ip:{ip_hash}:{slug}", settings.rate_ip_per_minute, 60),
            Limit(f"ip:{ip_hash}:{slug}", settings.rate_ip_per_hour, 3600),
        ]
    )

    payload = await _read_json(request, settings.max_body_bytes)
    try:
        submission = LeadSubmission.model_validate(payload)
    except ValidationError as exc:
        raise ValidationFailed(
            "The request body is invalid.",
            errors=[
                {"loc": [str(p) for p in e["loc"]], "msg": str(e["msg"])} for e in exc.errors()
            ],
        ) from None

    meta = RequestMeta(
        ip_hash=ip_hash,
        origin=request.headers.get("origin"),
        user_agent=request.headers.get("user-agent"),
    )
    reference = await intake.submit(workspace.config, submission, meta)
    return LeadAccepted(reference=reference)


async def _read_json(request: Request, limit: int) -> Any:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise PayloadTooLarge(f"The request body must be at most {limit} bytes.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise PayloadTooLarge(f"The request body must be at most {limit} bytes.")
    try:
        return json.loads(bytes(body))
    except ValueError:
        raise BadRequest("The request body is not valid JSON.") from None
