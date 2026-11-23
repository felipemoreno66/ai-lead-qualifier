"""Retention for stored LLM payloads (they contain lead data, plan 8.6)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncConnection

from lead_qualifier.infrastructure.db.tables import llm_calls


class LlmCallRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def purge_before(self, cutoff: datetime) -> int:
        result = await self.conn.execute(delete(llm_calls).where(llm_calls.c.created_at < cutoff))
        return result.rowcount
