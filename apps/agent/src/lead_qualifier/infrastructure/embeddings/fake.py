"""Deterministic embeddings for tests and CI: hashed bag of words, no model, no network."""

from __future__ import annotations

import hashlib
import math
import re

from lead_qualifier.ports.embeddings import EMBEDDING_DIMENSION

FAKE_MODEL_ID = "fake-hash-384"
_WORD = re.compile(r"\w+")


class FakeEmbeddings:
    model_id = FAKE_MODEL_ID
    dimension = EMBEDDING_DIMENSION

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for word in _WORD.findall(text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]
