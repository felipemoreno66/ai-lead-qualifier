"""Embeddings port: turns texts into fixed-size vectors for the knowledge base."""

from __future__ import annotations

from typing import Protocol

EMBEDDING_DIMENSION = 384


class Embeddings(Protocol):
    """Blocking embedder; call it from a worker thread inside async code."""

    @property
    def model_id(self) -> str:
        """Stable identifier stored with every chunk; vectors of different models never mix."""
        ...

    @property
    def dimension(self) -> int: ...

    @property
    def max_chunk_tokens(self) -> int:
        """Largest chunk (title and heading path included) the model embeds without truncating."""
        ...

    @property
    def default_min_similarity(self) -> float:
        """Cosine similarity under which a chunk is not a match (the scale differs by model)."""
        ...

    @property
    def chunk_overlap_tokens(self) -> int: ...

    def warm(self) -> None:
        """Load (and, if needed, download) the model ahead of the first real use."""
        ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...
