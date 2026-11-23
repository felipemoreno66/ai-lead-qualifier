"""Markdown-aware chunking: split on headings first, then cap each section by size."""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

MAX_TOKENS = 500
OVERLAP_TOKENS = 50
HEADING_SEPARATOR = " > "
_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]
_TOKEN = re.compile(r"\w+|[^\w\s]")


@dataclass(frozen=True)
class Chunk:
    index: int
    heading_path: str
    content: str
    token_count: int


def count_tokens(text: str) -> int:
    """Cheap, deterministic token estimate (words and punctuation); no tokenizer download."""
    return len(_TOKEN.findall(text))


def document_title(markdown: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", markdown, re.MULTILINE)
    return match.group(1) if match else fallback


def chunk_markdown(
    markdown: str, *, max_tokens: int = MAX_TOKENS, overlap: int = OVERLAP_TOKENS
) -> list[Chunk]:
    sections = MarkdownHeaderTextSplitter(_HEADERS, strip_headers=True).split_text(markdown)
    sizer = RecursiveCharacterTextSplitter(
        chunk_size=max_tokens, chunk_overlap=overlap, length_function=count_tokens
    )
    chunks: list[Chunk] = []
    for section in sections:
        path = HEADING_SEPARATOR.join(
            section.metadata[key] for _, key in _HEADERS if key in section.metadata
        )
        for piece in sizer.split_text(section.page_content):
            text = piece.strip()
            if text:
                chunks.append(Chunk(len(chunks), path, text, count_tokens(text)))
    return chunks
