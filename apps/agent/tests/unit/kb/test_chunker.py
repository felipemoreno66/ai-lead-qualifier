from __future__ import annotations

from lead_qualifier.domain.kb_chunker import (
    chunk_markdown,
    count_tokens,
    document_title,
    embedding_context,
)
from lead_qualifier.infrastructure.embeddings import FakeEmbeddings
from lead_qualifier.infrastructure.embeddings.fastembed import FastEmbeddings

DOC = """# Pricing

Intro line.

## Bootcamp

### Payment plan

Six payments of USD 890.

## Course

Two lines here.
"""


def chunks(markdown: str, *, max_tokens: int = 120, overlap: int = 20, title: str = "Pricing"):
    return chunk_markdown(markdown, title=title, max_tokens=max_tokens, overlap=overlap)


def test_heading_path_is_kept_per_chunk():
    result = chunks(DOC)
    paths = {c.heading_path: c.content for c in result}
    assert paths["Pricing"] == "Intro line."
    assert paths["Pricing > Bootcamp > Payment plan"] == "Six payments of USD 890."
    assert paths["Pricing > Course"] == "Two lines here."
    assert [c.index for c in result] == [0, 1, 2]


def assert_within_cap(markdown: str, cap: int, overlap: int = 20, title: str = "Some title"):
    result = chunks(markdown, max_tokens=cap, overlap=overlap, title=title)
    assert result
    for c in result:
        embedded = f"{embedding_context(title, c.heading_path)}\n{c.content}"
        assert count_tokens(embedded) <= cap, (count_tokens(embedded), c.content[:60])
    return result


def test_long_sections_are_capped_with_overlap():
    sentences = [f"Sentence number {i} talks about topic {i}." for i in range(200)]
    result = assert_within_cap("# Big\n\n## Section\n\n" + " ".join(sentences), 100, 20, "Big")
    assert len(result) > 3
    assert {c.heading_path for c in result} == {"Big > Section"}
    tail = result[0].content.split()[-2:]
    assert all(word in result[1].content for word in tail)  # overlap carries context


def test_the_cap_holds_for_text_without_separators_and_for_table_rows():
    blob = "x" * 5000  # no spaces, no newlines
    row = "| " + " | ".join(f"cell{i}" for i in range(300)) + " |"
    table = "| a | b |\n|---|---|\n" + row
    assert_within_cap(f"# T\n\n{blob}", 120)
    assert_within_cap(f"# T\n\n{table}", 120)
    assert_within_cap("# T\n\n## " + "Long heading " * 8 + f"\n\n{blob}", 120)


def test_the_cap_of_the_default_models_stays_below_what_they_read():
    assert FastEmbeddings.max_chunk_tokens <= 120  # the model reads 128 word pieces
    assert FakeEmbeddings.max_chunk_tokens <= FastEmbeddings.max_chunk_tokens


def test_token_count_is_pessimistic_and_title_is_found():
    assert count_tokens("Hello, world") == 3
    assert count_tokens("internationalization") == 4
    assert document_title(DOC, "fallback") == "Pricing"
    assert document_title("no heading", "fallback") == "fallback"


def test_empty_document_has_no_chunks():
    assert chunks("") == []
