"""Internal API: called by n8n (bearer token), never exposed to browsers."""

from __future__ import annotations

import hmac
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from lead_qualifier.domain.errors import BadRequest, Unauthorized
from lead_qualifier.http.auth import require_n8n
from lead_qualifier.http.deps import EngineDep, SettingsDep
from lead_qualifier.http.schemas import (
    AckResult,
    DeliveryOut,
    MessageContent,
    QualifyResult,
    SendFailedCallback,
    SentCallback,
)
from lead_qualifier.infrastructure.outbox.publishers import sign
from lead_qualifier.services.outbox import acknowledge

MAX_CALLBACK_AGE_SECONDS = 300


async def verify_callback_signature(
    request: Request,
    settings: SettingsDep,
    x_timestamp: Annotated[str | None, Header()] = None,
    x_signature: Annotated[str | None, Header()] = None,
) -> None:
    """Delivery callbacks are signed like the webhook in the other direction:
    ``X-Signature: sha256=HMAC(timestamp + "." + METHOD + " " + path + "." + raw body)`` and a
    timestamp at most 5 minutes old, so a captured callback can be replayed neither later nor
    against another endpoint or message."""
    timestamp = x_timestamp or ""
    fresh = (
        timestamp.isascii()
        and timestamp.isdigit()
        and abs(time.time() - int(timestamp)) <= MAX_CALLBACK_AGE_SECONDS
    )
    expected = sign(
        await request.body(),
        settings.n8n_webhook_secret,
        timestamp,
        method=request.method,
        path=request.url.path,
    )
    if not (fresh and x_signature and hmac.compare_digest(expected, x_signature)):
        raise Unauthorized("Invalid or expired callback signature.")


Signed = Depends(verify_callback_signature)


def _require_same_message(path_id: uuid.UUID, body_id: uuid.UUID) -> None:
    if path_id != body_id:
        raise BadRequest("The message id in the body does not match the one in the path.")


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


@router.post("/messages/{message_id}/claim", response_model=MessageContent)
async def claim_message(message_id: uuid.UUID, request: Request) -> MessageContent:
    """Hand an approved message to n8n for sending and mark it ``sending`` so it is sent once."""
    return MessageContent(**await request.app.state.delivery.claim(message_id))


@router.post("/messages/{message_id}/sent", response_model=DeliveryOut, dependencies=[Signed])
async def message_sent(
    message_id: uuid.UUID, payload: SentCallback, request: Request
) -> DeliveryOut:
    _require_same_message(message_id, payload.message_id)
    result = await request.app.state.delivery.mark_sent(message_id, payload.provider_message_id)
    return DeliveryOut(**vars(result))


@router.post(
    "/messages/{message_id}/send-failed", response_model=DeliveryOut, dependencies=[Signed]
)
async def message_send_failed(
    message_id: uuid.UUID, payload: SendFailedCallback, request: Request
) -> DeliveryOut:
    _require_same_message(message_id, payload.message_id)
    result = await request.app.state.delivery.mark_send_failed(message_id, "n8n_send_failed")
    return DeliveryOut(**vars(result))
