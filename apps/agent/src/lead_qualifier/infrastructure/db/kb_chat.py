"""Retention of the dashboard's "Ask the docs" log."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncConnection

from lead_qualifier.infrastructure.db.tables import agent_runs, kb_queries


class KbChatRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def purge_before(self, cutoff: datetime) -> int:
        """Delete questions and their lead-less runs (and model calls) older than ``cutoff``."""
        await self.conn.execute(delete(kb_queries).where(kb_queries.c.created_at < cutoff))
        result = await self.conn.execute(
            delete(agent_runs).where(
                agent_runs.c.kind == "kb_chat", agent_runs.c.started_at < cutoff
            )
        )
        return result.rowcount
