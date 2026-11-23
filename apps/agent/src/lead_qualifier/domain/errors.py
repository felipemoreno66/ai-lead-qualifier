"""Domain and HTTP-facing errors, rendered as RFC 9457 problem details."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status = 500
    type = "about:blank"
    title = "Internal error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.errors = errors
        self.headers = headers or {}


class NotFound(AppError):
    status = 404
    title = "Not found"


class Conflict(AppError):
    status = 409
    title = "Conflict"


class Forbidden(AppError):
    status = 403
    title = "Forbidden"


class Unauthorized(AppError):
    status = 401
    title = "Unauthorized"


class PayloadTooLarge(AppError):
    status = 413
    title = "Payload too large"


class ValidationFailed(AppError):
    status = 422
    title = "Validation failed"


class BadRequest(AppError):
    status = 400
    title = "Bad request"


class RateLimited(AppError):
    status = 429
    title = "Too many requests"


class InvalidTransition(Conflict):
    title = "Invalid state transition"


class ConsentOutdated(ValidationFailed):
    type = "urn:lead-qualifier:consent_outdated"
    title = "Privacy notice changed"
