from __future__ import annotations

from lead_qualifier.domain.kb_chunker import chunk_markdown, count_tokens, document_title

DOC = """# Pricing

Intro line.

## Bootcamp

### Payment plan

Six payments of USD 890.

## Course

Two lines here.
"""


def test_heading_path_is_kept_per_chunk():
    chunks = chunk_markdown(DOC)
    paths = {c.heading_path: c.content for c in chunks}
    assert paths["Pricing"] == "Intro line."
    assert paths["Pricing > Bootcamp > Payment plan"] == "Six payments of USD 890."
    assert paths["Pricing > Course"] == "Two lines here."
    assert [c.index for c in chunks] == [0, 1, 2]


def test_long_sections_are_capped_with_overlap():
    sentences = [f"Sentence number {i} talks about topic {i}." for i in range(200)]
    chunks = chunk_markdown(
        "# Big\n\n## Section\n\n" + " ".join(sentences), max_tokens=100, overlap=20
    )
    assert len(chunks) > 3
    assert all(c.token_count <= 100 for c in chunks)
    assert {c.heading_path for c in chunks} == {"Big > Section"}
    first_tail = chunks[0].content.split()[-3:]
    assert all(word in chunks[1].content for word in first_tail)  # overlap carries context


def test_token_count_and_title():
    assert count_tokens("Hello, world") == 3
    assert document_title(DOC, "fallback") == "Pricing"
    assert document_title("no heading", "fallback") == "fallback"


def test_empty_document_has_no_chunks():
    assert chunk_markdown("") == []
