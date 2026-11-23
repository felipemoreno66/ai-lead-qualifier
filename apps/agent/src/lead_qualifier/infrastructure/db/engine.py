"""Async SQLAlchemy engine factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        # Keep bound parameters (emails, free text) out of exception messages and logs.
        hide_parameters=True,
    )
