"""Seed the Northwind Academy demo workspace with fictional leads.

    python -m lead_qualifier.scripts.seed

Idempotent (leads are keyed by their seed reference). Refuses any workspace other than
``northwind-academy`` and refuses to run when ``APP_ENV=production``, so real leads of a
private workspace can never be mixed with demo data.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.config import Settings, get_settings
from lead_qualifier.infrastructure.db.engine import create_engine
from lead_qualifier.infrastructure.db.repositories import LeadRepository, OutboxRepository
from lead_qualifier.ports.clock import Clock, SystemClock
from lead_qualifier.services.workspace_sync import sync_workspaces
from lead_qualifier.workspaces.loader import WorkspaceRegistry, load_workspaces

DEMO_WORKSPACE = "northwind-academy"
DEFAULT_SEED_FILE = Path(__file__).resolve().parents[5] / "db" / "seeds" / "northwind_leads.json"

# Status path of a seeded lead, from `new`. Each step is one `status_changed` event.
PATHS: dict[str, list[str]] = {
    "new": [],
    "qualifying": ["qualifying"],
    "pending_review": ["qualifying", "pending_review"],
    "approved": ["qualifying", "pending_review", "approved"],
    "sent": ["qualifying", "pending_review", "approved", "sent"],
    "rejected": ["qualifying", "pending_review", "rejected"],
    "error": ["qualifying", "error"],
}


class SeedRefused(Exception):
    pass


@dataclass(frozen=True)
class SeedResult:
    created: int
    skipped: int


def _guard(workspace: str, app_env: str) -> None:
    if app_env == "production":
        raise SeedRefused("Refusing to seed when APP_ENV=production.")
    if workspace != DEMO_WORKSPACE:
        raise SeedRefused(
            f"Only the {DEMO_WORKSPACE!r} demo workspace can be seeded, not {workspace!r}."
        )


async def seed(
    engine: AsyncEngine,
    registry: WorkspaceRegistry,
    *,
    workspace: str,
    app_env: str,
    clock: Clock,
    ip_hash_secret: str,
    seed_file: Path = DEFAULT_SEED_FILE,
) -> SeedResult:
    _guard(workspace, app_env)
    loaded = registry.get(workspace)
    if loaded is None:
        raise SeedRefused(f"Workspace {workspace!r} is not loaded.")
    data: dict[str, Any] = json.loads(
        await asyncio.to_thread(seed_file.read_text, encoding="utf-8")
    )
    if data["workspace"] != DEMO_WORKSPACE:
        raise SeedRefused("The seed file does not belong to the demo workspace.")

    await sync_workspaces(engine, registry, clock)
    now = clock.now()
    created = skipped = 0
    for entry in data["leads"]:
        async with engine.begin() as conn:
            leads, outbox = LeadRepository(conn), OutboxRepository(conn)
            if await leads.reference_exists(entry["reference"]):
                skipped += 1
                continue
            created_at = now - timedelta(hours=entry["hours_ago"])
            steps = PATHS[entry["status"]]
            final = entry["status"]
            milestone = {s: created_at + timedelta(minutes=2 + 3 * i) for i, s in enumerate(steps)}
            lead_id = await leads.insert(
                {
                    "reference": entry["reference"],
                    "workspace_slug": workspace,
                    "status": final,
                    "name": entry["name"],
                    "email": entry["email"],
                    "country": entry["country"],
                    "locale": entry["locale"],
                    "answers": entry["answers"],
                    "free_text": entry.get("free_text"),
                    "source": "seed",
                    "ip_hash": hmac.new(
                        ip_hash_secret.encode(), entry["reference"].encode(), hashlib.sha256
                    ).hexdigest(),
                    "consent_at": created_at,
                    "consent_notice_version": loaded.config.privacy.version,
                    "score": entry.get("score"),
                    "tier": entry.get("tier"),
                    "recommended_product": entry.get("recommended_product"),
                    "qualification": entry.get("qualification"),
                    "detected_language": entry.get("detected_language"),
                    "error_reason": entry.get("error_reason"),
                    "created_at": created_at,
                    "updated_at": milestone.get(final, created_at),
                    "qualified_at": milestone.get("pending_review"),
                    "sent_at": milestone.get("sent"),
                }
            )
            await leads.add_event(
                lead_id, "submitted", payload={"reference": entry["reference"]}, at=created_at
            )
            await outbox.enqueue(
                event_type="lead.created",
                aggregate_id=lead_id,
                lead_id=lead_id,
                payload={"lead": {"id": str(lead_id), "workspace": workspace}},
                idempotency_key=f"lead:{lead_id}:created:1",
                now=created_at + timedelta(seconds=2),
                status="delivered",
            )
            await leads.add_event(lead_id, "outbox_delivered", at=created_at + timedelta(seconds=2))
            previous = "new"
            for step in steps:
                await leads.add_event(
                    lead_id,
                    "status_changed",
                    from_status=previous,
                    to_status=step,
                    at=milestone[step],
                )
                previous = step
            created += 1
    return SeedResult(created, skipped)


async def _run(settings: Settings, workspace: str) -> SeedResult:
    registry = load_workspaces(
        settings.workspaces_dir, app_env=settings.app_env, enabled=settings.enabled_workspace_slugs
    )
    engine = create_engine(settings.database_url)
    try:
        return await seed(
            engine,
            registry,
            workspace=workspace,
            app_env=settings.app_env,
            clock=SystemClock(),
            ip_hash_secret=settings.ip_hash_secret,
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=DEMO_WORKSPACE)
    args = parser.parse_args()
    try:
        result = asyncio.run(_run(get_settings(), args.workspace))
    except SeedRefused as exc:
        raise SystemExit(f"seed: {exc}") from None
    print(f"seed: created {result.created}, already present {result.skipped}")


if __name__ == "__main__":
    main()
