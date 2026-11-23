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
        """Count one request against each limit in order; raise at the first one exceeded.

        Later limits are not incremented once an earlier one rejects the request, so an
        abusive caller cannot burn shared quotas (list the most specific limit first).
        Hits are committed even when rejecting, which keeps the caller blocked for the window.
        """
        now = self.clock.now()
        retry_after = 0
        async with self.engine.begin() as conn:
            repo = RateLimitRepository(conn)
            for limit in limits:
                start = window_start(now, limit.window_seconds)
                count = await repo.hit(f"{limit.key}:{limit.window_seconds}", start)
                if count > limit.max_hits:
                    retry_after = limit.window_seconds - int((now - start).total_seconds())
                    break
        if retry_after:
            raise RateLimited(
                "Too many requests. Please try again later.",
                headers={"Retry-After": str(max(retry_after, 1))},
            )
