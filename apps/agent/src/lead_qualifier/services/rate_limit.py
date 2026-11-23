"""Postgres-backed fixed-window rate limiting (no Redis)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.domain.errors import RateLimited
from lead_qualifier.infrastructure.db.repositories import RateLimitRepository
from lead_qualifier.ports.clock import Clock


@dataclass(frozen=True)
class Limit:
    key: str
    max_hits: int
    window_seconds: int


def window_start(now: datetime, window_seconds: int) -> datetime:
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % window_seconds, tz=UTC)


class RateLimiter:
    def __init__(self, engine: AsyncEngine, clock: Clock) -> None:
        self.engine = engine
        self.clock = clock

    async def hit(self, limits: list[Limit]) -> None:
        """Count one request against every limit; raise ``RateLimited`` if any is exceeded.

        Hits are committed even when the request is rejected, so a client that keeps
        hammering stays blocked for the whole window.
        """
        now = self.clock.now()
        retry_after = 0
        async with self.engine.begin() as conn:
            repo = RateLimitRepository(conn)
            for limit in limits:
                start = window_start(now, limit.window_seconds)
                count = await repo.hit(f"{limit.key}:{limit.window_seconds}", start)
                if count > limit.max_hits:
                    remaining = limit.window_seconds - int((now - start).total_seconds())
                    retry_after = max(retry_after, remaining)
        if retry_after:
            raise RateLimited(
                "Too many requests. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )
