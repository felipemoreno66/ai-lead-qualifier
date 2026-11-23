"""Redact obvious personal identifiers (emails, phone numbers) from stored LLM payloads.

Limits, on purpose: only ASCII e-mail addresses and phone-like numbers of at least nine digits are
masked. Names, addresses and free text are NOT masked, so stored payloads still contain personal
data; the retention purge (``LLM_CALLS_RETENTION_DAYS``) and cascade deletion are the real controls.
"""

from __future__ import annotations

import re
from typing import Any

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{7,}\d(?![\w.])")


def redact_text(text: str) -> str:
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text))


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    return value
