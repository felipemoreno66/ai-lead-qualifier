from __future__ import annotations

from typing import Any, Protocol


class PublishError(Exception):
    """The event could not be delivered; the dispatcher will retry with backoff."""


class PermanentPublishError(PublishError):
    """Delivery was rejected and retrying cannot succeed; the event is marked dead at once."""


class EventPublisher(Protocol):
    async def publish(self, event: dict[str, Any]) -> None: ...


class AuthRejectedError(PublishError):
    """n8n answered 401: clock skew or a secret rotation in flight may clear up, so retry."""
