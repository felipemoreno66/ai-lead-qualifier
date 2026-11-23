"""Liveness and readiness probes."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from lead_qualifier.logging import get_logger
from lead_qualifier.services.workspace_sync import sync_workspaces

log = get_logger("health")

router = APIRouter(tags=["health"])


@lru_cache
def migration_head(migrations_dir: Path) -> str | None:
    if not migrations_dir.is_dir():
        return None
    return ScriptDirectory(str(migrations_dir)).get_current_head()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, Any]:
    app = request.app
    checks = {"database": False, "migrations": False, "workspaces": False}
    try:
        async with app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            checks["database"] = True
            current = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
            checks["migrations"] = current is not None and current == migration_head(
                app.state.settings.migrations_dir
            )
        if not app.state.workspaces_synced and checks["migrations"]:
            await sync_workspaces(app.state.engine, app.state.registry, app.state.clock)
            app.state.workspaces_synced = True
        checks["workspaces"] = app.state.workspaces_synced and len(app.state.registry) > 0
    except Exception as exc:
        # A missing alembic_version table (fresh database) lands here: not ready.
        log.warning("readyz_check_failed", error_type=type(exc).__name__)
    ready = all(checks.values())
    if not ready:
        response.status_code = 503
    return {"status": "ready" if ready else "unavailable", "checks": checks}
