"""Structured JSON logging with PII redaction."""

from __future__ import annotations

import logging
import sys
import traceback
from collections.abc import MutableMapping
from typing import Any, TextIO

import structlog

REDACTED_KEYS = frozenset(
    {
        "email",
        "name",
        "fields",
        "answers",
        "body",
        "subject",
        "ip",
        "free_text",
        "authorization",
        "token",
        "password",
        "secret",
    }
)


def redact_pii(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Mask values of keys that may carry personal data or credentials."""
    for key in list(event_dict):
        if key.lower() in REDACTED_KEYS:
            event_dict[key] = "[redacted]"
    return event_dict


def safe_exception(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Render ``exc_info`` as the exception type plus stack frames only.

    Exception messages can embed personal data (database errors echo bound parameters), so they
    are never written to the logs.
    """
    exc_info = event_dict.pop("exc_info", None)
    if not exc_info:
        return event_dict
    if exc_info is True:
        exc_info = sys.exc_info()
    elif isinstance(exc_info, BaseException):
        exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
    exc_type, _value, tb = exc_info
    frames = "".join(traceback.format_tb(tb)) if tb else ""
    event_dict["exception"] = (
        f"{getattr(exc_type, '__name__', 'Exception')} (message withheld)\n{frames}"
    )
    return event_dict


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper(), force=True)
    # httpx logs full request URLs at INFO; uvicorn access logs are replaced by our middleware.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_pii,
            safe_exception,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
