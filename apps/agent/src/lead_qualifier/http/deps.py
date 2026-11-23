"""FastAPI dependencies shared by the routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.config import Settings
from lead_qualifier.services.kb import KnowledgeBaseService
from lead_qualifier.workspaces.loader import WorkspaceRegistry


def settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def registry_dep(request: Request) -> WorkspaceRegistry:
    registry: WorkspaceRegistry = request.app.state.registry
    return registry


def engine_dep(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


def kb_dep(request: Request) -> KnowledgeBaseService:
    kb: KnowledgeBaseService = request.app.state.kb
    return kb


SettingsDep = Annotated[Settings, Depends(settings_dep)]
RegistryDep = Annotated[WorkspaceRegistry, Depends(registry_dep)]
EngineDep = Annotated[AsyncEngine, Depends(engine_dep)]
KbDep = Annotated[KnowledgeBaseService, Depends(kb_dep)]
