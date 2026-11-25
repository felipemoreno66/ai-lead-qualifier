"""First-start setup of the keyless demo (Northwind Academy, fake provider, no keys).

    python -m lead_qualifier.scripts.demo_init [--reset]

Runs once from the ``demo-init`` compose service, every step idempotent:

1. the fictional leads (``seed``),
2. their extracted profile, model-call log and reply drafts (``db/seeds/northwind_demo.json``),
3. the knowledge base (embeddings: the configured provider, ``DEMO_EMBEDDINGS=fake`` for offline),
4. a few "Ask the docs" answers produced by the fake provider.

It does nothing unless ``DEMO_SEED=true``, never runs with ``APP_ENV=production`` and only ever
touches the ``northwind-academy`` workspace, so a private instance cannot be filled with demo data.
Step 3 and 4 failures (for example no network for the model download) are reported but do not
fail the start: the leads, drafts and metrics are already usable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.agent.prompts import PROMPT_VERSIONS
from lead_qualifier.config import Settings, get_settings
from lead_qualifier.domain.errors import AppError
from lead_qualifier.infrastructure.db.engine import create_engine
from lead_qualifier.infrastructure.db.tables import (
    agent_runs,
    kb_queries,
    lead_events,
    llm_calls,
    messages,
)
from lead_qualifier.infrastructure.db.tables import leads as leads_table
from lead_qualifier.infrastructure.embeddings import build_embeddings
from lead_qualifier.infrastructure.llm.router import build_provider
from lead_qualifier.logging import get_logger
from lead_qualifier.ports.clock import SystemClock
from lead_qualifier.scripts.seed import DEMO_WORKSPACE, SeedRefused, seed
from lead_qualifier.services.kb import KnowledgeBaseService, WorkspaceRetriever
from lead_qualifier.services.kb_chat import KbChatService
from lead_qualifier.services.qualify import GRAPH_VERSION
from lead_qualifier.services.rate_limit import RateLimiter
from lead_qualifier.workspaces.loader import load_workspaces

log = get_logger("demo_init")
DEMO_CONTENT_FILE = Path(__file__).resolve().parents[5] / "db" / "seeds" / "northwind_demo.json"
DEMO_MODEL = "claude-haiku-5-5"  # recorded next to provider "fake": it is the configured default
DEMO_QUESTIONS = (
    "How much does the Data & AI Course cost, and is there a payment plan?",
    "Can I get a refund if I change my mind?",
    "Do you offer scholarships?",
)


def load_content(path: Path = DEMO_CONTENT_FILE) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if data["workspace"] != DEMO_WORKSPACE:
        raise SeedRefused("The demo content file does not belong to the demo workspace.")
    return data


async def apply_lead_content(engine: AsyncEngine, content: dict[str, Any]) -> int:
    """Add a run, its model calls, the draft and the review trail to each seeded lead (once)."""
    applied = 0
    for reference, item in content["leads"].items():
        async with engine.begin() as conn:
            lead = (
                (
                    await conn.execute(
                        sa.select(leads_table).where(leads_table.c.reference == reference)
                    )
                )
                .mappings()
                .first()
            )
            if lead is None:
                continue
            known = await conn.execute(
                sa.select(agent_runs.c.id).where(agent_runs.c.lead_id == lead["id"]).limit(1)
            )
            if known.first() is not None:
                continue
            await _add_run(conn, dict(lead), item)
            applied += 1
    return applied


async def _add_run(conn: Any, lead: dict[str, Any], item: dict[str, Any]) -> None:
    started = lead["created_at"] + timedelta(minutes=2)
    failed = item.get("failed")
    calls = list(item["calls"])
    duration_ms = sum(c["latency_ms"] for c in calls) + (failed["latency_ms"] if failed else 0)
    message = item.get("message")
    run_status = (
        "failed"
        if failed
        else ("interrupted" if message and message["status"] == "draft" else "completed")
    )
    run_id = uuid.uuid4()
    await conn.execute(
        sa.insert(agent_runs).values(
            id=run_id,
            lead_id=lead["id"],
            kind="qualify",
            thread_id=f"demo:{lead['reference']}",
            run_number=1,
            status=run_status,
            graph_version=GRAPH_VERSION,
            prompt_versions=PROMPT_VERSIONS,
            started_at=started,
            finished_at=None if run_status == "interrupted" else started + timedelta(seconds=3),
            duration_ms=duration_ms,
            total_cost_usd=0,
            error=f"{failed['error_code']}: the model did not answer in time" if failed else None,
        )
    )
    rows = [
        {
            "agent_run_id": run_id,
            "node": c["node"],
            "provider": "fake",
            "model": DEMO_MODEL,
            "attempt": 1,
            "input_tokens": c["input_tokens"],
            "output_tokens": c["output_tokens"],
            "latency_ms": c["latency_ms"],
            "cost_usd": 0,
            "success": True,
            "error_code": None,
            "created_at": started + timedelta(milliseconds=i * 250),
        }
        for i, c in enumerate(calls)
    ]
    if failed:
        rows.append(
            {
                "agent_run_id": run_id,
                "node": failed["node"],
                "provider": "fake",
                "model": DEMO_MODEL,
                "attempt": 1,
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": failed["latency_ms"],
                "cost_usd": 0,
                "success": False,
                "error_code": failed["error_code"],
                "created_at": started + timedelta(seconds=1),
            }
        )
    await conn.execute(sa.insert(llm_calls), rows)

    qualification = dict(lead["qualification"] or {})
    if item.get("profile"):
        qualification["profile"] = item["profile"]
        await conn.execute(
            sa.update(leads_table)
            .where(leads_table.c.id == lead["id"])
            .values(qualification=qualification)
        )
    if not message:
        return
    reviewed_at = lead["updated_at"] if message["status"] != "draft" else None
    sent_at = lead["sent_at"] if message["status"] == "sent" else None
    edited = bool(message.get("edited"))
    await conn.execute(
        sa.insert(messages).values(
            lead_id=lead["id"],
            agent_run_id=run_id,
            version=1,
            language=message["language"],
            channel="email",
            channel_recipient=lead["email"],
            subject=message["subject"],
            body=message["body"],
            status=message["status"],
            edited_by_operator=edited,
            original_body=message.get("original_body") if edited else None,
            review_note=message.get("review_note"),
            created_at=started + timedelta(seconds=3),
            reviewed_at=reviewed_at,
            sent_at=sent_at,
            guard_warnings=[],
        )
    )
    if message["status"] != "draft":
        action = "reject" if message["status"] == "rejected" else ("edit" if edited else "approve")
        await conn.execute(
            sa.insert(lead_events).values(
                lead_id=lead["id"],
                type="reviewed",
                actor="operator",
                payload={"action": action},
                created_at=reviewed_at,
            )
        )
    if message["status"] == "sent":
        await conn.execute(
            sa.insert(lead_events).values(
                lead_id=lead["id"],
                type="email_sent",
                actor="system",
                payload={},
                created_at=sent_at,
            )
        )


async def ingest_and_ask(engine: AsyncEngine, settings: Settings) -> str:
    """Ingest the knowledge base, then log a few answers. Returns a one-line summary."""
    registry = load_workspaces(
        settings.workspaces_dir, app_env=settings.app_env, enabled=frozenset({DEMO_WORKSPACE})
    )
    workspace = registry.get(DEMO_WORKSPACE)
    if workspace is None or not workspace.config.knowledge_base.enabled:
        return "knowledge base disabled"
    clock = SystemClock()
    kb = KnowledgeBaseService(engine, build_embeddings(settings), clock)
    kb_dir = workspace.path / workspace.config.knowledge_base.path
    result = await kb.ingest(DEMO_WORKSPACE, kb_dir)
    summary = f"knowledge base: {result.chunks} chunks"
    if settings.llm_provider != "fake":  # never spend money on demo content
        return summary + ", demo questions skipped (not the fake provider)"
    async with engine.connect() as conn:
        asked = (
            await conn.execute(
                sa.select(sa.func.count())
                .select_from(kb_queries)
                .where(kb_queries.c.workspace_slug == DEMO_WORKSPACE)
            )
        ).scalar_one()
    if asked:
        return summary + ", demo questions already present"
    chat = KbChatService(
        engine, settings, build_provider(settings, engine), clock, RateLimiter(engine, clock)
    )
    retriever = WorkspaceRetriever(
        kb, DEMO_WORKSPACE, top_k=settings.kb_top_k, min_similarity=settings.kb_min_similarity
    )
    for question in DEMO_QUESTIONS:
        await chat.ask(workspace.config, retriever, question)
    return summary + f", {len(DEMO_QUESTIONS)} demo questions answered"


async def run(settings: Settings, *, reset: bool = False) -> list[str]:
    if not settings.demo_seed:
        return ["DEMO_SEED is not true: nothing to do"]
    if settings.app_env == "production":
        raise SeedRefused("Refusing to load demo data when APP_ENV=production.")
    registry = load_workspaces(
        settings.workspaces_dir, app_env=settings.app_env, enabled=frozenset({DEMO_WORKSPACE})
    )
    engine = create_engine(settings.database_url)
    report: list[str] = []
    try:
        result = await seed(
            engine,
            registry,
            workspace=DEMO_WORKSPACE,
            app_env=settings.app_env,
            clock=SystemClock(),
            ip_hash_secret=settings.ip_hash_secret,
            reset=reset,
        )
        report.append(f"leads: created {result.created}, already present {result.skipped}")
        applied = await apply_lead_content(engine, load_content())
        report.append(f"drafts and run logs: {applied} added")
        try:
            report.append(await ingest_and_ask(engine, settings))
        except (AppError, Exception) as exc:
            report.append(
                f"knowledge base NOT loaded ({type(exc).__name__}). Retry with "
                "`docker compose run --rm agent python -m lead_qualifier.scripts.ingest_kb "
                "northwind-academy`, or set DEMO_EMBEDDINGS=fake to skip the model download."
            )
    finally:
        await engine.dispose()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="recreate the seeded leads first")
    args = parser.parse_args()
    try:
        report = asyncio.run(run(get_settings(), reset=args.reset))
    except SeedRefused as exc:
        raise SystemExit(f"demo-init: {exc}") from None
    for line in report:
        print(f"demo-init: {line}", file=sys.stderr if "NOT" in line else sys.stdout)


if __name__ == "__main__":
    main()
