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

    def embed(self, texts: list[str]) -> list[list[float]]: ...
