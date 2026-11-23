"""Retention for stored LLM payloads (they contain lead data, plan 8.6)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncConnection

from lead_qualifier.infrastructure.db.tables import agent_runs, kb_queries, llm_calls


class LlmCallRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def purge_before(self, cutoff: datetime) -> int:
        result = await self.conn.execute(delete(llm_calls).where(llm_calls.c.created_at < cutoff))
        return result.rowcount

    async def purge_kb_chat_before(self, cutoff: datetime) -> int:
        """Questions asked in the dashboard, and the lead-less runs behind them, past retention."""
        await self.conn.execute(delete(kb_queries).where(kb_queries.c.created_at < cutoff))
        result = await self.conn.execute(
            delete(agent_runs).where(
                agent_runs.c.kind == "kb_chat", agent_runs.c.started_at < cutoff
            )
        )
        return result.rowcount
