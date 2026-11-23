"""Optional OpenAI embeddings (text-embedding-3-small, shortened to 384 dimensions).

Not used by default and never called by the test suite.
"""

from __future__ import annotations

import httpx

from lead_qualifier.ports.embeddings import EMBEDDING_DIMENSION

OPENAI_MODEL = "text-embedding-3-small"
OPENAI_MODEL_ID = f"openai/{OPENAI_MODEL}@{EMBEDDING_DIMENSION}"
OPENAI_URL = "https://api.openai.com/v1/embeddings"


class OpenAIEmbeddings:
    model_id = OPENAI_MODEL_ID
    dimension = EMBEDDING_DIMENSION

    def __init__(self, api_key: str, *, timeout: float = 30.0) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when EMBEDDINGS_PROVIDER=openai")
        self._api_key = api_key
        self._timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = httpx.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": OPENAI_MODEL, "input": texts, "dimensions": self.dimension},
            timeout=self._timeout,
        )
        response.raise_for_status()
        rows = sorted(response.json()["data"], key=lambda r: r["index"])
        return [[float(x) for x in r["embedding"]] for r in rows]
