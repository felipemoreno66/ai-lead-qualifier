"""Local multilingual embeddings with fastembed (ONNX, CPU).

The model is downloaded into ``cache_dir`` the first time it is needed (first ingest or first
query), never at image build time.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from lead_qualifier.ports.embeddings import EMBEDDING_DIMENSION

FASTEMBED_MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class FastEmbeddings:
    model_id = FASTEMBED_MODEL_ID
    dimension = EMBEDDING_DIMENSION
    # paraphrase-multilingual-MiniLM-L12-v2 reads at most 128 word pieces and silently drops the
    # rest, so chunks stay well below that (the chunker over-counts to keep a safety margin).
    max_chunk_tokens = 120
    chunk_overlap_tokens = 20
    # Swept on the Northwind eval (see evals/rag/README.md): 0.4 to 0.6 refuse every unanswerable
    # question with no false refusals, 0.3 answers them all, 0.65 starts refusing real questions.
    default_min_similarity = 0.45

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(
                    model_name=self.model_id, cache_dir=str(self._cache_dir)
                )
            return self._model

    def warm(self) -> None:
        self._load()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [[float(x) for x in vec] for vec in self._load().embed(texts)]
