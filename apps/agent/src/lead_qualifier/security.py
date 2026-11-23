"""Hashing helpers so raw IPs and emails never reach the database or the logs."""

from __future__ import annotations

import hashlib
import hmac


def hash_value(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
