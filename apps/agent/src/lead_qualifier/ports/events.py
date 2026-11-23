from __future__ import annotations

from typing import Any, Protocol


class PublishError(Exception):
    """The event could not be delivered; the dispatcher will retry with backoff."""


class EventPublisher(Protocol):
    async def publish(self, event: dict[str, Any]) -> None: ...
