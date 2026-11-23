"""LangGraph Postgres checkpointer in its own ``langgraph`` schema, opened lazily.

The schema is created and the checkpoint tables are set up on first use (idempotent), with the
connections pinned to ``search_path=langgraph`` so they never touch the application tables.
"""

from __future__ import annotations

import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

SCHEMA = "langgraph"


def psycopg_url(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


class PostgresCheckpointer:
    def __init__(self, database_url: str) -> None:
        self._url = psycopg_url(database_url)
        self._pool: AsyncConnectionPool[AsyncConnection[dict[str, object]]] | None = None
        self._saver: AsyncPostgresSaver | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> AsyncPostgresSaver:
        async with self._lock:
            if self._saver is None:
                async with await AsyncConnection.connect(self._url, autocommit=True) as conn:
                    await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
                pool: AsyncConnectionPool[AsyncConnection[dict[str, object]]] = AsyncConnectionPool(
                    self._url,
                    kwargs={
                        "autocommit": True,
                        "row_factory": dict_row,
                        "options": f"-c search_path={SCHEMA}",
                    },
                    min_size=1,
                    max_size=4,
                    open=False,
                )
                await pool.open()
                saver = AsyncPostgresSaver(pool)
                await saver.setup()
                self._pool, self._saver = pool, saver
            return self._saver

    async def aclose(self) -> None:
        async with self._lock:
            if self._pool is not None:
                await self._pool.close()
            self._pool = self._saver = None
