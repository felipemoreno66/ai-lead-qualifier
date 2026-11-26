"""Nightly reset of the public demo.

    python -m lead_qualifier.scripts.demo_reset           # run forever: reset on schedule
    python -m lead_qualifier.scripts.demo_reset --once    # reset now and exit

Everything visitors created in the demo workspace (leads, drafts, "Ask the docs" history, rate-limit
counters, stored model calls, paused graph checkpoints, Mailpit messages) is removed, then
``demo_init --reset`` restores the fictional Northwind data. Idempotent: running it twice in a row
leaves the same state. Only runs with ``PUBLIC_DEMO=true`` so it can never wipe a private instance.
The schedule is ``DEMO_RESET_AT`` (HH:MM UTC, daily) or ``DEMO_RESET_INTERVAL_HOURS``.
"""

from __future__ import annotations

import argparse
import asyncio
import urllib.request
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.config import Settings, get_settings
from lead_qualifier.infrastructure.checkpoint import PostgresCheckpointer
from lead_qualifier.infrastructure.db.engine import create_engine
from lead_qualifier.infrastructure.db.tables import (
    agent_runs,
    kb_queries,
    llm_calls,
    rate_limit_hits,
)
from lead_qualifier.infrastructure.db.tables import leads as leads_table
from lead_qualifier.logging import configure_logging, get_logger
from lead_qualifier.scripts import demo_init
from lead_qualifier.scripts.seed import DEMO_WORKSPACE, SeedRefused

log = get_logger("demo_reset")


def next_reset(now: datetime, settings: Settings) -> datetime:
    """Next reset: ``DEMO_RESET_INTERVAL_HOURS`` from now, else the next ``DEMO_RESET_AT`` (UTC)."""
    if settings.demo_reset_interval_hours is not None:
        return now + timedelta(hours=settings.demo_reset_interval_hours)
    hour, minute = (int(part) for part in settings.demo_reset_at.split(":"))
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return due if due > now else due + timedelta(days=1)


async def purge_visitor_data(engine: AsyncEngine, settings: Settings) -> None:
    async with engine.begin() as conn:
        # Leads cascade to their events, outbox rows, messages, answers and qualify runs.
        await conn.execute(
            sa.delete(leads_table).where(leads_table.c.workspace_slug == DEMO_WORKSPACE)
        )
        await conn.execute(
            sa.delete(kb_queries).where(kb_queries.c.workspace_slug == DEMO_WORKSPACE)
        )
        await conn.execute(sa.delete(agent_runs).where(agent_runs.c.kind == "kb_chat"))
        await conn.execute(sa.delete(llm_calls))
    # Paused graph checkpoints hold lead data: with the run rows gone they are orphans.
    checkpointer = PostgresCheckpointer(settings.database_url)
    try:
        await checkpointer.purge_stale_threads(engine, datetime.now(UTC), timedelta(0))
    finally:
        await checkpointer.aclose()


def clear_mailpit(base_url: str) -> None:
    """Delete every message stored by Mailpit (the demo's only outbound mail sink)."""
    if not base_url:
        return
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("DEMO_MAILPIT_URL must be an http(s) URL")
    url = base_url.rstrip("/") + "/api/v1/messages"
    request = urllib.request.Request(url, method="DELETE")  # noqa: S310 - scheme checked above
    with urllib.request.urlopen(request, timeout=10):  # noqa: S310
        pass


async def reset_once(settings: Settings) -> list[str]:
    if not settings.public_demo:
        raise SeedRefused("Refusing to reset: PUBLIC_DEMO is not true.")
    engine = create_engine(settings.database_url)
    try:
        await purge_visitor_data(engine, settings)
    finally:
        await engine.dispose()
    report = await demo_init.run(settings, reset=True)
    engine = create_engine(settings.database_url)
    try:
        # After the reload: it logs its own "Ask the docs" answers against the hourly limit.
        async with engine.begin() as conn:
            await conn.execute(sa.delete(rate_limit_hits))
    finally:
        await engine.dispose()
    try:
        await asyncio.to_thread(clear_mailpit, settings.demo_mailpit_url)
    except (OSError, ValueError) as exc:
        report.append(f"mailpit NOT cleared ({type(exc).__name__})")
    return report


async def run_forever(settings: Settings) -> None:
    log.info(
        "demo_reset_scheduler_started",
        at=settings.demo_reset_at,
        interval_hours=settings.demo_reset_interval_hours,
    )
    while True:
        due = next_reset(datetime.now(UTC), settings)
        log.info("demo_reset_scheduled", due=due.isoformat())
        await asyncio.sleep(max((due - datetime.now(UTC)).total_seconds(), 1))
        try:
            for line in await reset_once(settings):
                log.info("demo_reset", result=line)
        except Exception:  # keep the scheduler alive: a failed night is retried the next one
            log.exception("demo_reset_failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="reset now and exit")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        if args.once:
            for line in asyncio.run(reset_once(settings)):
                print(f"demo-reset: {line}")
        else:
            if not settings.public_demo:
                raise SeedRefused("Refusing to start: PUBLIC_DEMO is not true.")
            asyncio.run(run_forever(settings))
    except SeedRefused as exc:
        raise SystemExit(f"demo-reset: {exc}") from None


if __name__ == "__main__":
    main()
