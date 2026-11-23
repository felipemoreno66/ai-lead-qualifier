"""Knowledge base: ingest a workspace's Markdown documents and retrieve chunks by similarity."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from lead_qualifier.domain.kb_chunker import Chunk, chunk_markdown, document_title
from lead_qualifier.infrastructure.db.tables import kb_chunks, kb_documents
from lead_qualifier.ports.clock import Clock
from lead_qualifier.ports.embeddings import Embeddings

EMBED_BATCH = 32


@dataclass(frozen=True)
class IngestResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    chunks: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "added": self.added,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "removed": self.removed,
            "chunks": self.chunks,
        }


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_path: str
    document_title: str
    heading_path: str
    content: str
    similarity: float


def list_documents(kb_dir: Path) -> list[Path]:
    """Markdown files of a knowledge base; names starting with ``_`` are authoring notes."""
    return sorted(
        p for p in kb_dir.rglob("*.md") if p.is_file() and not p.name.startswith(("_", "."))
    )


def embedding_input(title: str, heading_path: str, content: str) -> str:
    context = " > ".join(part for part in (title, heading_path) if part)
    return f"{context}\n{content}"


class KnowledgeBaseService:
    def __init__(self, engine: AsyncEngine, embeddings: Embeddings, clock: Clock) -> None:
        self._engine = engine
        self._embeddings = embeddings
        self._clock = clock

    async def ingest(
        self, workspace_slug: str, kb_dir: Path, *, force: bool = False
    ) -> IngestResult:
        """Bring the stored chunks in line with the files. Concurrent runs are serialized."""
        files = {p.relative_to(kb_dir).as_posix(): p for p in list_documents(kb_dir)}
        model = self._embeddings.model_id
        added = updated = unchanged = 0
        async with self._engine.begin() as conn:
            await conn.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"kb:{workspace_slug}"},
            )
            existing = {
                r.path: r
                for r in (
                    await conn.execute(
                        sa.select(
                            kb_documents.c.id,
                            kb_documents.c.path,
                            kb_documents.c.content_sha256,
                            sa.select(sa.func.count())
                            .where(
                                kb_chunks.c.document_id == kb_documents.c.id,
                                kb_chunks.c.embedding_model != model,
                            )
                            .scalar_subquery()
                            .label("foreign_model_chunks"),
                        ).where(kb_documents.c.workspace_slug == workspace_slug)
                    )
                ).all()
            }
            for path, file in files.items():
                raw = file.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                row = existing.get(path)
                if (
                    row is not None
                    and row.content_sha256 == digest
                    and row.foreign_model_chunks == 0
                    and not force
                ):
                    unchanged += 1
                    continue
                await self._store(conn, workspace_slug, path, raw.decode("utf-8"), digest, row)
                if row is None:
                    added += 1
                else:
                    updated += 1
            gone = [r.id for p, r in existing.items() if p not in files]
            if gone:
                await conn.execute(sa.delete(kb_documents).where(kb_documents.c.id.in_(gone)))
            total = (
                await conn.execute(
                    sa.select(sa.func.count())
                    .select_from(kb_chunks.join(kb_documents))
                    .where(kb_documents.c.workspace_slug == workspace_slug)
                )
            ).scalar_one()
        return IngestResult(added, updated, unchanged, len(gone), total)

    async def _store(
        self,
        conn: AsyncConnection,
        workspace_slug: str,
        path: str,
        text: str,
        digest: str,
        existing: Any,
    ) -> None:
        title = document_title(text, Path(path).stem)
        chunks = chunk_markdown(text)
        vectors = await self._embed(
            [embedding_input(title, c.heading_path, c.content) for c in chunks]
        )
        now = self._clock.now()
        if existing is not None:
            doc_id = existing.id
            await conn.execute(sa.delete(kb_chunks).where(kb_chunks.c.document_id == doc_id))
            await conn.execute(
                sa.update(kb_documents)
                .where(kb_documents.c.id == doc_id)
                .values(title=title, content_sha256=digest, ingested_at=now)
            )
        else:
            doc_id = (
                await conn.execute(
                    sa.insert(kb_documents)
                    .values(
                        workspace_slug=workspace_slug,
                        path=path,
                        title=title,
                        content_sha256=digest,
                        ingested_at=now,
                    )
                    .returning(kb_documents.c.id)
                )
            ).scalar_one()
        if chunks:
            await conn.execute(
                sa.insert(kb_chunks),
                [
                    _chunk_row(doc_id, c, v, self._embeddings.model_id)
                    for c, v in zip(chunks, vectors, strict=True)
                ],
            )

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            out.extend(
                await asyncio.to_thread(self._embeddings.embed, texts[start : start + EMBED_BATCH])
            )
        return out

    async def retrieve(
        self, workspace_slug: str, question: str, *, top_k: int = 5, min_similarity: float = 0.3
    ) -> list[RetrievedChunk]:
        """Top-k chunks by cosine similarity, best first, dropping those below the threshold."""
        (vector,) = await self._embed([question])
        distance = kb_chunks.c.embedding.cosine_distance(vector)
        stmt = (
            sa.select(
                kb_chunks.c.id,
                kb_documents.c.path,
                kb_documents.c.title,
                kb_chunks.c.heading_path,
                kb_chunks.c.content,
                (1 - distance).label("similarity"),
            )
            .join(kb_documents, kb_documents.c.id == kb_chunks.c.document_id)
            .where(
                kb_documents.c.workspace_slug == workspace_slug,
                kb_chunks.c.embedding_model == self._embeddings.model_id,
            )
            .order_by(distance)
            .limit(top_k)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return [
            RetrievedChunk(r.id, r.path, r.title, r.heading_path, r.content, float(r.similarity))
            for r in rows
            if r.similarity >= min_similarity
        ]


def _chunk_row(
    doc_id: uuid.UUID, chunk: Chunk, vector: list[float], model: str
) -> dict[str, object]:
    return {
        "document_id": doc_id,
        "chunk_index": chunk.index,
        "heading_path": chunk.heading_path,
        "content": chunk.content,
        "token_count": chunk.token_count,
        "embedding": vector,
        "embedding_model": model,
    }
