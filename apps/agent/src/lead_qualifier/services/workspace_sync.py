"""Mirror the file-based workspaces into the ``workspaces`` table (needed for foreign keys)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.infrastructure.db.repositories import WorkspaceRepository
from lead_qualifier.ports.clock import Clock
from lead_qualifier.workspaces.loader import WorkspaceRegistry


async def sync_workspaces(engine: AsyncEngine, registry: WorkspaceRegistry, clock: Clock) -> None:
    now = clock.now()
    async with engine.begin() as conn:
        repo = WorkspaceRepository(conn)
        for ws in registry.all():
            await repo.upsert(ws.slug, ws.config.profile.name, ws.config_hash, ws.enabled, now)
