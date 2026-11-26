"""Resend sender (HTTP API, https://resend.com/docs/api-reference/emails/send-email)."""

from __future__ import annotations

from typing import Any

import httpx

from lead_qualifier.domain.channel import sanitize_header, strip_invisible
from lead_qualifier.ports.channel import ChannelPayload, EmailSendError

RESEND_URL = "https://api.resend.com/emails"
# Resend documents 409 as an idempotency conflict. Only the "still running" case is worth retrying:
# a different payload under the same key never succeeds.
_TRANSIENT_409 = "concurrent_idempotent_requests"


class ResendSender:
    """Delivers through Resend. The stored message id is the ``Idempotency-Key`` (valid for 24 h),
    so the retry of a send whose answer was lost cannot deliver a second copy."""

    def __init__(self, api_key: str, *, url: str = RESEND_URL, timeout: float = 15.0) -> None:
        if not api_key:
            raise ValueError("Resend needs an API key")
        self._api_key = api_key
        self.url, self.timeout = url, timeout

    def _body(self, payload: ChannelPayload) -> dict[str, Any]:
        body: dict[str, Any] = {
            "from": payload.sender,
            "to": [payload.recipient],
            "subject": sanitize_header(payload.subject),  # defence in depth
            "text": strip_invisible(payload.text),  # text only
        }
        if payload.reply_to:
            body["reply_to"] = payload.reply_to
        return body

    async def send(self, payload: ChannelPayload) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Idempotency-Key": payload.message_id.strip("<>")[:256],
            "User-Agent": "lead-qualifier",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.url, json=self._body(payload), headers=headers)
        except httpx.HTTPError as exc:  # timeouts, refused connections, drops
            # Only the class name: httpx messages can include the request URL and headers.
            raise EmailSendError(type(exc).__name__, transient=True) from exc
        if response.status_code == 200:
            provider_id = _json(response).get("id")
            if isinstance(provider_id, str) and provider_id:
                return provider_id
            raise EmailSendError("Resend answered without a message id", transient=False)
        # The answer's text can echo the recipient: keep only the status and Resend's error name.
        code = _json(response).get("name")
        label = f"Resend {response.status_code}" + (f" {code}" if isinstance(code, str) else "")
        transient = (
            response.status_code == 429
            or response.status_code >= 500
            or (response.status_code == 409 and code == _TRANSIENT_409)
        )
        raise EmailSendError(label, transient=transient)


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
