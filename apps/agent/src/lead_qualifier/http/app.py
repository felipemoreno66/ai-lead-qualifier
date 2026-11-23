"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.config import Settings, get_settings
from lead_qualifier.http.client_ip import parse_networks
from lead_qualifier.http.errors import install_error_handlers
from lead_qualifier.http.middleware.cors import WorkspaceCORSMiddleware
from lead_qualifier.http.middleware.request_id import RequestIdMiddleware
from lead_qualifier.http.routers import health, public
from lead_qualifier.infrastructure.db.engine import create_engine
from lead_qualifier.logging import configure_logging, get_logger
from lead_qualifier.ports.clock import Clock, SystemClock
from lead_qualifier.services.intake import IntakeService
from lead_qualifier.services.rate_limit import RateLimiter
from lead_qualifier.services.workspace_sync import sync_workspaces
from lead_qualifier.workspaces.loader import WorkspaceRegistry, load_workspaces


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    registry: WorkspaceRegistry | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    log = get_logger("app")
    owned_engine = engine is None
    clock = clock or SystemClock()
    engine = engine or create_engine(settings.database_url)
    registry = registry or load_workspaces(
        settings.workspaces_dir,
        app_env=settings.app_env,
        enabled=settings.enabled_workspace_slugs,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info(
            "startup",
            env=settings.app_env,
            orchestrator=settings.orchestrator,
            workspaces=[w.slug for w in registry.all() if w.enabled],
        )
        try:
            await sync_workspaces(engine, registry, clock)
            app.state.workspaces_synced = True
        except Exception as exc:
            log.warning("workspace_sync_failed", error_type=type(exc).__name__)
        yield
        if owned_engine:
            await engine.dispose()
        log.info("shutdown")

    app = FastAPI(title="AI Lead Qualifier", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.registry = registry
    app.state.clock = clock
    app.state.workspaces_synced = False
    app.state.trusted_networks = parse_networks(settings.trusted_proxy_list)
    app.state.limiter = RateLimiter(engine, clock)
    app.state.intake = IntakeService(engine, settings, clock, app.state.limiter)
    app.add_middleware(
        WorkspaceCORSMiddleware,
        registry=registry,
        web_origins=[o.strip() for o in settings.web_public_origin.split(",")],
        allow_draft=settings.allow_draft_workspaces,
    )
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(public.router)
    return app
