"""Markdown-aware chunking: split on headings first, then cap each section by size.

The cap is a property of the embedding model (see ``Embeddings.max_chunk_tokens``): a model that
reads 128 word pieces silently ignores the rest of a longer chunk, so the cap counts what is
embedded, which is the document title and heading path plus the chunk text.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# Bump when the splitting rules change, so stored documents are re-ingested.
CHUNKER_VERSION = "chunker@2"
HEADING_SEPARATOR = " > "
MIN_BODY_TOKENS = 20
_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]
_WORD = re.compile(r"\w+|[^\w\s]")


@dataclass(frozen=True)
class Chunk:
    index: int
    heading_path: str
    content: str
    token_count: int


def count_tokens(text: str) -> int:
    """Deterministic, deliberately pessimistic estimate of word pieces (no tokenizer download):
    every punctuation mark is one token and a word costs one token per 5 characters."""
    return sum(1 if not m[0].isalnum() else math.ceil(len(m) / 5) for m in _WORD.findall(text))


def document_title(markdown: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", markdown, re.MULTILINE)
    return match.group(1) if match else fallback


def embedding_context(title: str, heading_path: str) -> str:
    return HEADING_SEPARATOR.join(part for part in (title, heading_path) if part)


def chunk_markdown(markdown: str, *, title: str, max_tokens: int, overlap: int) -> list[Chunk]:
    """Chunks whose ``context + text`` never exceeds ``max_tokens`` estimated tokens."""
    sections = MarkdownHeaderTextSplitter(_HEADERS, strip_headers=True).split_text(markdown)
    chunks: list[Chunk] = []
    for section in sections:
        path = HEADING_SEPARATOR.join(
            section.metadata[key] for _, key in _HEADERS if key in section.metadata
        )
        # +1 for the newline between the context and the text
        room = max(MIN_BODY_TOKENS, max_tokens - count_tokens(embedding_context(title, path)) - 1)
        sizer = RecursiveCharacterTextSplitter(
            chunk_size=room,
            chunk_overlap=min(overlap, room // 4),
            length_function=count_tokens,
        )
        for piece in sizer.split_text(section.page_content):
            text = piece.strip()
            if text:
                chunks.append(Chunk(len(chunks), path, text, count_tokens(text)))
    return chunks
