"""Internal API: called by n8n (bearer token), never exposed to browsers."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from lead_qualifier.http.auth import require_n8n
from lead_qualifier.http.deps import EngineDep
from lead_qualifier.http.schemas import AckResult, QualifyResult
from lead_qualifier.services.outbox import acknowledge

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[require_n8n])


@router.post("/events/{event_id}/ack", response_model=AckResult)
async def ack_event(event_id: uuid.UUID, request: Request, engine: EngineDep) -> AckResult:
    changed = await acknowledge(engine, event_id, request.app.state.clock.now())
    return AckResult(event_id=event_id, changed=changed)


@router.post("/leads/{lead_id}/qualify", response_model=QualifyResult)
async def qualify_lead(lead_id: uuid.UUID, request: Request) -> QualifyResult:
    """Run the qualification graph. A failed run answers 200 with ``status: error``."""
    outcome = await request.app.state.qualifier.qualify(lead_id)
    return QualifyResult(**vars(outcome))
