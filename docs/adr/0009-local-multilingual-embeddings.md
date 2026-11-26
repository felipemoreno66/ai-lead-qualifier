# ADR 0009: Local multilingual embeddings with per-model thresholds

Status: accepted

## Context

The knowledge base is in English and Spanish, ingestion should work offline and for free, and the demo must
run without keys. Similarity scores are not comparable between embedding models.

## Decision

`ports/embeddings.py` has three adapters: `fastembed` with `paraphrase-multilingual-MiniLM-L12-v2`
(384 dimensions, default), an optional OpenAI adapter at 384 dimensions (untested against the real API), and a
deterministic `FakeEmbeddings` for tests and CI. Each model declares its chunk cap (`max_chunk_tokens`: 120
estimated tokens for MiniLM, which reads only 128 word pieces) and its default minimum similarity (0.45 for
fastembed, 0.3 for the fake); `KB_MIN_SIMILARITY` overrides it. Chunks live in pgvector (`vector(384)`, HNSW
cosine index, a CHECK on the model name) and retrieval compares only vectors of the active model. The model is
downloaded on first use into a cache volume, not at image build. The recorded sweep on the Northwind eval with
the fake LLM: 0.3 answered every unanswerable question, 0.4 to 0.6 refused all of them with no false refusals,
0.65 refused 3 answerable ones.

## Consequences

- No embedding cost or key; a one-time download of about 90 MB and roughly 730 MiB of agent memory with the
  model loaded.
- A small model: 128 word pieces per chunk force short chunks.
- Switching models means re-ingesting and re-running the threshold sweep.
- fastembed has no revision pin, so the exact files are whatever the cache volume holds.

## Alternatives considered

- A hosted embedding API as the default: needs a key and costs money.
- A larger local model: more RAM on an 8 GB server.
