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

from lead_qualifier.domain.errors import Conflict
from lead_qualifier.domain.kb_chunker import (
    CHUNKER_VERSION,
    Chunk,
    chunk_markdown,
    document_title,
    embedding_context,
)
from lead_qualifier.infrastructure.db.tables import kb_chunks, kb_documents
from lead_qualifier.logging import get_logger
from lead_qualifier.ports.clock import Clock
from lead_qualifier.ports.embeddings import Embeddings

EMBED_BATCH = 32
MAX_FILE_BYTES = 1_000_000
log = get_logger("kb")


@dataclass(frozen=True)
class IngestResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped: int = 0
    chunks: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "added": self.added,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "removed": self.removed,
            "skipped": self.skipped,
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


@dataclass(frozen=True)
class SourceFile:
    path: str
    text: str
    digest: str


@dataclass(frozen=True)
class _Prepared:
    file: SourceFile
    title: str
    chunks: list[Chunk]
    vectors: list[list[float]]


def list_documents(kb_dir: Path) -> tuple[list[Path], list[str]]:
    """Markdown files of a knowledge base and the relative paths that were skipped.

    Names starting with ``_`` are authoring notes. Symlinks, files that resolve outside the folder
    and files over ``MAX_FILE_BYTES`` are skipped, never followed or read.
    """
    root = kb_dir.resolve()
    found: list[Path] = []
    skipped: list[str] = []
    for path in sorted(kb_dir.rglob("*.md")):
        if path.name.startswith((".", "_")) or not path.is_file():
            continue
        name = path.relative_to(kb_dir).as_posix()
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            log.warning("kb_file_skipped", path=name, reason="symlink_or_outside")
            skipped.append(name)
        elif path.stat().st_size > MAX_FILE_BYTES:
            log.warning("kb_file_skipped", path=name, reason="too_large")
            skipped.append(name)
        else:
            found.append(path)
    return found, skipped


def read_sources(kb_dir: Path, *, chunking: str) -> tuple[list[SourceFile], list[str]]:
    """Decoded files with their content hash. The hash covers the chunking rules too, so changing
    the chunker or the model's chunk size re-ingests every document."""
    paths, skipped = list_documents(kb_dir)
    sources: list[SourceFile] = []
    for path in paths:
        name = path.relative_to(kb_dir).as_posix()
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            log.warning("kb_file_skipped", path=name, reason="invalid_utf8")
            skipped.append(name)
            continue
        digest = hashlib.sha256(chunking.encode() + b"\n" + raw).hexdigest()
        sources.append(SourceFile(name, text, digest))
    return sources, skipped


def embedding_input(title: str, heading_path: str, content: str) -> str:
    return f"{embedding_context(title, heading_path)}\n{content}"


class KnowledgeBaseService:
    def __init__(self, engine: AsyncEngine, embeddings: Embeddings, clock: Clock) -> None:
        self._engine = engine
        self._embeddings = embeddings
        self._clock = clock
        self._running: set[str] = set()
        self._threads: set[asyncio.Future[list[list[float]]]] = set()

    @property
    def chunking(self) -> str:
        e = self._embeddings
        return f"{CHUNKER_VERSION}:{e.max_chunk_tokens}:{e.chunk_overlap_tokens}"

    async def ingest(
        self, workspace_slug: str, kb_dir: Path, *, force: bool = False
    ) -> IngestResult:
        """Bring the stored chunks in line with the files.

        Chunking and embedding (slow, possibly a model download) happen before the transaction;
        only writes run under the advisory lock. One ingest per workspace at a time in this process.
        """
        if workspace_slug in self._running:
            raise Conflict("A reindex of this knowledge base is already running.")
        self._running.add(workspace_slug)
        try:
            return await self._ingest(workspace_slug, kb_dir, force)
        finally:
            # A timeout cancels the await but not the thread running the model: the workspace stays
            # "running" until that thread has really ended, so a retry cannot pile on a second one.
            if self._threads:
                done = asyncio.gather(*self._threads, return_exceptions=True)
                done.add_done_callback(lambda _: self._running.discard(workspace_slug))
            else:
                self._running.discard(workspace_slug)

    async def _ingest(self, workspace_slug: str, kb_dir: Path, force: bool) -> IngestResult:
        model = self._embeddings.model_id
        sources, skipped = await asyncio.to_thread(read_sources, kb_dir, chunking=self.chunking)
        async with self._engine.connect() as conn:
            existing = await self._existing(conn, workspace_slug, model)
        prepared = [
            await self._prepare(src)
            for src in sources
            if force
            or (row := existing.get(src.path)) is None
            or row.content_sha256 != src.digest
            or row.foreign_model_chunks
        ]
        on_disk = {s.path for s in sources}  # a skipped file loses its chunks too
        added = updated = 0
        async with self._engine.begin() as conn:
            await conn.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"kb:{workspace_slug}"},
            )
            current = await self._existing(conn, workspace_slug, model)
            for item in prepared:
                await self._store(conn, workspace_slug, item, current.get(item.file.path))
                if item.file.path in current:
                    updated += 1
                else:
                    added += 1
            gone = [r.id for p, r in current.items() if p not in on_disk]
            if gone:
                await conn.execute(sa.delete(kb_documents).where(kb_documents.c.id.in_(gone)))
            total = (
                await conn.execute(
                    sa.select(sa.func.count())
                    .select_from(kb_chunks.join(kb_documents))
                    .where(kb_documents.c.workspace_slug == workspace_slug)
                )
            ).scalar_one()
        unchanged = len(sources) - len(prepared)
        return IngestResult(added, updated, unchanged, len(gone), len(skipped), total)

    @staticmethod
    async def _existing(conn: AsyncConnection, workspace_slug: str, model: str) -> dict[str, Any]:
        foreign = (
            sa.select(sa.func.count())
            .where(
                kb_chunks.c.document_id == kb_documents.c.id, kb_chunks.c.embedding_model != model
            )
            .scalar_subquery()
            .label("foreign_model_chunks")
        )
        rows = await conn.execute(
            sa.select(
                kb_documents.c.id, kb_documents.c.path, kb_documents.c.content_sha256, foreign
            ).where(kb_documents.c.workspace_slug == workspace_slug)
        )
        return {r.path: r for r in rows}

    async def _prepare(self, source: SourceFile) -> _Prepared:
        title = document_title(source.text, Path(source.path).stem)
        chunks = chunk_markdown(
            source.text,
            title=title,
            max_tokens=self._embeddings.max_chunk_tokens,
            overlap=self._embeddings.chunk_overlap_tokens,
        )
        vectors = await self._embed(
            [embedding_input(title, c.heading_path, c.content) for c in chunks]
        )
        return _Prepared(source, title, chunks, vectors)

    async def _store(
        self, conn: AsyncConnection, workspace_slug: str, item: _Prepared, existing: Any
    ) -> None:
        now = self._clock.now()
        if existing is not None:
            doc_id = existing.id
            await conn.execute(sa.delete(kb_chunks).where(kb_chunks.c.document_id == doc_id))
            await conn.execute(
                sa.update(kb_documents)
                .where(kb_documents.c.id == doc_id)
                .values(title=item.title, content_sha256=item.file.digest, ingested_at=now)
            )
        else:
            doc_id = (
                await conn.execute(
                    sa.insert(kb_documents)
                    .values(
                        workspace_slug=workspace_slug,
                        path=item.file.path,
                        title=item.title,
                        content_sha256=item.file.digest,
                        ingested_at=now,
                    )
                    .returning(kb_documents.c.id)
                )
            ).scalar_one()
        if item.chunks:
            await conn.execute(
                sa.insert(kb_chunks),
                [
                    _chunk_row(doc_id, c, v, self._embeddings.model_id)
                    for c, v in zip(item.chunks, item.vectors, strict=True)
                ],
            )

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            thread: asyncio.Future[list[list[float]]] = asyncio.ensure_future(
                asyncio.to_thread(self._embeddings.embed, texts[start : start + EMBED_BATCH])
            )
            self._threads.add(thread)
            thread.add_done_callback(self._threads.discard)
            out.extend(await asyncio.shield(thread))
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
