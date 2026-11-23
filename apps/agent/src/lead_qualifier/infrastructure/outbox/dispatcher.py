"""Transactional-outbox dispatcher: claims due events and delivers them with backoff."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.config import Settings
from lead_qualifier.infrastructure.checkpoint import PostgresCheckpointer
from lead_qualifier.infrastructure.db.repositories import (
    LeadRepository,
    OutboxRepository,
    RateLimitRepository,
)
from lead_qualifier.infrastructure.llm.repository import LlmCallRepository
from lead_qualifier.logging import get_logger
from lead_qualifier.ports.clock import Clock
from lead_qualifier.ports.events import EventPublisher, PermanentPublishError
from lead_qualifier.services.outbox import envelope
from lead_qualifier.services.reaper import reap_stale_runs, report_stale_sending

log = get_logger("dispatcher")
PURGE_EVERY = timedelta(hours=1)
REAP_EVERY = timedelta(minutes=1)
RATE_LIMIT_RETENTION = timedelta(days=2)


class OutboxDispatcher:
    def __init__(
        self,
        engine: AsyncEngine,
        publisher: EventPublisher,
        clock: Clock,
        settings: Settings,
        checkpointer: PostgresCheckpointer | None = None,
    ) -> None:
        self.checkpointer = checkpointer
        self.engine = engine
        self.publisher = publisher
        self.clock = clock
        self.settings = settings
        self._last_purge = clock.now()
        self._last_reap = clock.now() - REAP_EVERY

    async def run_once(self) -> int:
        """Claim and deliver one batch. Returns how many events were handled."""
        now = self.clock.now()
        async with self.engine.begin() as conn:
            claimed = await OutboxRepository(conn).claim_due(
                now, self.settings.outbox_batch_size, self.settings.outbox_lock_seconds
            )
        for row in claimed:
            await self._deliver(row)
        return len(claimed)

    async def _deliver(self, row: dict[str, Any]) -> None:
        try:
            await self.publisher.publish(envelope(row))
        except Exception as exc:  # any publisher failure is retried; never crash the loop
            await self._record_failure(
                row,
                f"{type(exc).__name__}: {exc}",
                permanent=isinstance(exc, PermanentPublishError),
            )
            return
        now = self.clock.now()
        async with self.engine.begin() as conn:
            changed = await OutboxRepository(conn).mark_delivered(row["id"], now)
            if changed and row["lead_id"]:
                await LeadRepository(conn).add_event(
                    row["lead_id"],
                    "outbox_delivered",
                    payload={"attempts": row["attempts"] + 1},
                    at=now,
                )
        log.info("outbox_delivered", event_id=str(row["id"]), event_type=row["event_type"])

    async def _record_failure(
        self, row: dict[str, Any], error: str, *, permanent: bool = False
    ) -> None:
        now = self.clock.now()
        attempt = row["attempts"] + 1
        dead = permanent or attempt >= self.settings.outbox_max_attempts
        schedule = self.settings.backoff_schedule
        delay = schedule[min(attempt - 1, len(schedule) - 1)]
        next_attempt = None if dead else now + timedelta(seconds=delay)
        async with self.engine.begin() as conn:
            updated = await OutboxRepository(conn).mark_failed(
                row["id"], error=error, next_attempt_at=next_attempt
            )
            if updated and row["lead_id"]:
                await LeadRepository(conn).add_event(
                    row["lead_id"],
                    "outbox_failed",
                    payload={
                        "attempt": attempt,
                        "error": error[:300],
                        "dead": dead,
                        "next_attempt_at": next_attempt.isoformat() if next_attempt else None,
                    },
                    at=now,
                )
        log.warning(
            "outbox_failed",
            event_id=str(row["id"]),
            attempt=attempt,
            dead=dead,
            error_type=error.split(":", 1)[0],
        )

    async def reap_stale_runs(self) -> None:
        now = self.clock.now()
        if now - self._last_reap < REAP_EVERY:
            return
        self._last_reap = now
        await reap_stale_runs(
            self.engine, self.clock, timedelta(minutes=self.settings.agent_run_timeout_minutes)
        )
        await report_stale_sending(
            self.engine, self.clock, timedelta(minutes=self.settings.send_stale_minutes)
        )

    async def purge_rate_limits(self) -> None:
        now = self.clock.now()
        if now - self._last_purge < PURGE_EVERY:
            return
        self._last_purge = now
        async with self.engine.begin() as conn:
            removed = await RateLimitRepository(conn).purge_before(now - RATE_LIMIT_RETENTION)
            purged = await LlmCallRepository(conn).purge_before(
                now - timedelta(days=self.settings.llm_calls_retention_days)
            )
        threads = 0
        if self.checkpointer is not None:
            threads = await self.checkpointer.purge_stale_threads(
                self.engine, now, timedelta(days=self.settings.llm_calls_retention_days)
            )
        log.info(
            "rate_limits_purged",
            removed=removed,
            llm_calls_purged=purged,
            checkpoint_threads=threads,
        )

    async def run_forever(self) -> None:
        log.info("dispatcher_started", poll_seconds=self.settings.outbox_poll_seconds)
        while True:
            try:
                handled = await self.run_once()
                await self.purge_rate_limits()
                await self.reap_stale_runs()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                handled = 0
                log.error("dispatcher_error", error_type=type(exc).__name__, exc_info=True)
            if not handled:
                await asyncio.sleep(self.settings.outbox_poll_seconds)
