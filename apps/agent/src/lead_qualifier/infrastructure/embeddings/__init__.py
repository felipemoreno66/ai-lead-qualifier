"""Embedding adapters: fastembed (default), OpenAI (optional) and a deterministic fake."""

from __future__ import annotations

from lead_qualifier.config import Settings
from lead_qualifier.infrastructure.embeddings.fake import FakeEmbeddings
from lead_qualifier.infrastructure.embeddings.fastembed import FastEmbeddings
from lead_qualifier.infrastructure.embeddings.openai import OpenAIEmbeddings
from lead_qualifier.ports.embeddings import Embeddings


def build_embeddings(settings: Settings) -> Embeddings:
    if settings.embeddings_provider == "fake":
        return FakeEmbeddings()
    if settings.embeddings_provider == "openai":
        return OpenAIEmbeddings(api_key=settings.openai_api_key.get_secret_value())
    return FastEmbeddings(cache_dir=settings.embeddings_cache_dir)


__all__ = ["FakeEmbeddings", "FastEmbeddings", "OpenAIEmbeddings", "build_embeddings"]
