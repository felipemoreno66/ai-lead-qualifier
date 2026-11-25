"""Opt-in: the chunk cap must hold for the model's real tokenizer (needs the model files)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lead_qualifier.domain.kb_chunker import chunk_markdown, document_title, embedding_context
from lead_qualifier.infrastructure.embeddings.fastembed import FastEmbeddings
from lead_qualifier.services.kb import embedding_input
from tests.helpers import WORKSPACES_DIR

pytestmark = pytest.mark.slow
MODEL_LIMIT = 128
SPECIAL_TOKENS = 2


def _tokenizer_file() -> Path | None:
    cache = os.environ.get("EMBEDDINGS_CACHE_DIR")
    if not cache or not Path(cache).is_dir():
        return None
    return next(
        (p for p in Path(cache).rglob("tokenizer.json") if "multilingual-MiniLM" in str(p)), None
    )


def test_every_northwind_chunk_fits_the_real_tokenizer():
    path = _tokenizer_file()
    if path is None:
        pytest.skip("fastembed model files not found in EMBEDDINGS_CACHE_DIR")
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(path))
    kb = WORKSPACES_DIR / "northwind-academy" / "knowledge-base"
    checked = 0
    for doc in sorted(kb.glob("[0-9]*.md")):
        text = doc.read_text(encoding="utf-8")
        title = document_title(text, doc.stem)
        chunks = chunk_markdown(
            text,
            title=title,
            max_tokens=FastEmbeddings.max_chunk_tokens,
            overlap=FastEmbeddings.chunk_overlap_tokens,
        )
        for chunk in chunks:
            pieces = len(
                tokenizer.encode(embedding_input(title, chunk.heading_path, chunk.content)).ids
            )
            assert pieces <= MODEL_LIMIT - SPECIAL_TOKENS, (
                doc.name,
                pieces,
                embedding_context(title, chunk.heading_path),
            )
            checked += 1
    assert checked > 20
