"""Knowledge retrieval port used by the answer node."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_path: str
    document_title: str
    heading_path: str
    content: str
    similarity: float


class KnowledgeRetriever(Protocol):
    """Top-k chunks of one workspace's knowledge base for a question, best first."""

    async def retrieve(self, question: str) -> list[RetrievedChunk]: ...
