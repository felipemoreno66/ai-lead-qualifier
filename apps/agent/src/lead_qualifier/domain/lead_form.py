"""Validation of a lead submission against a workspace's form definition.

The TypeScript twin lives in ``apps/web/lib/forms/build-lead-schema.ts``; both are checked
against the shared fixtures in ``packages/contracts/fixtures/lead-submissions``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from lead_qualifier.domain.workspace import EMAIL_RE, FieldRole, FieldType, FormField

DEFAULT_MAX_LENGTH = {FieldType.TEXT: 200, FieldType.EMAIL: 254, FieldType.TEXTAREA: 2000}
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
URL_IN_TEXT_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
MAX_URLS_IN_FREE_TEXT = 3


@dataclass(frozen=True)
class FieldError:
    field: str
    message: str


def validate_answers(
    fields: list[FormField], raw: dict[str, Any]
) -> tuple[dict[str, Any], list[FieldError]]:
    """Return (clean answers, errors). Clean values are trimmed; emails are lowercased."""
    errors: list[FieldError] = []
    clean: dict[str, Any] = {}
    known = {f.id for f in fields}
    errors.extend(FieldError(k, "unknown field") for k in sorted(set(raw) - known))

    for f in fields:
        value = raw.get(f.id)
        if _is_blank(value):
            if f.required:
                errors.append(FieldError(f.id, "required"))
            continue
        cleaned, message = _clean_value(f, value)
        if message:
            errors.append(FieldError(f.id, message))
        else:
            clean[f.id] = cleaned
    return clean, errors


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _clean_value(f: FormField, value: Any) -> tuple[Any, str | None]:
    match f.type:
        case FieldType.CHECKBOX:
            if not isinstance(value, bool):
                return None, "must be true or false"
            if f.required and not value:
                return None, "required"
            return value, None
        case FieldType.NUMBER:
            if isinstance(value, bool) or not isinstance(value, int | float):
                return None, "must be a number"
            if isinstance(value, float) and not math.isfinite(value):
                return None, "must be a number"
            return value, None
    if not isinstance(value, str):
        return None, "must be text"
    text = value.strip()
    limit = f.max_length or DEFAULT_MAX_LENGTH.get(f.type, 200)
    if len(text) > limit:
        return None, f"must be at most {limit} characters"
    match f.type:
        case FieldType.EMAIL:
            text = text.lower()
            if not EMAIL_RE.match(text):
                return None, "must be a valid email address"
        case FieldType.COUNTRY:
            if not COUNTRY_RE.match(text):
                return None, "must be a two-letter country code"
        case FieldType.SELECT:
            if text not in {o.value for o in f.options}:
                return None, "is not one of the allowed options"
    if f.role is FieldRole.FREE_TEXT and len(URL_IN_TEXT_RE.findall(text)) > MAX_URLS_IN_FREE_TEXT:
        return None, f"must contain at most {MAX_URLS_IN_FREE_TEXT} links"
    return text, None
