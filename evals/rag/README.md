# RAG eval

Checks that the answer node answers a prospect's question from the Northwind Academy knowledge base,
cites the right document, and refuses what the documentation does not cover.

| File | What it is |
|---|---|
| `northwind.yaml` | 15 questions: 10 answerable in English, 2 answerable in Spanish, 3 the documentation does not cover (job guarantee, visa sponsorship, invoices or purchase orders for companies) |
| `run.py` | Indexes the knowledge base in memory, runs the answer node per question and prints a results table |

## Metrics

- **Answer accuracy**: the question was answered (not refused) and the answer matches the rubric, a list of
  keyword groups where every group must match and a group matches on any of its synonyms.
- **Expected source cited**: at least one citation points to a document the case lists in `sources`.
- **Citation precision**: citations to an expected source divided by all citations on answerable questions.
- **Refusal correctness**: unanswerable questions answered with `covered=false`.
- **Refusal correctness is two things at once**: a question with no chunk above the minimum similarity
  (`--min-similarity`, default 0.3) is refused without calling the model, so a high score can come from the
  threshold rather than from the model's judgement. The table prints the threshold used.
- **False refusals**: answerable questions that were refused (a count, lower is better).

## Run it offline (fake provider and fake embeddings, what CI runs)

```bash
make eval-rag
```

**These numbers verify the plumbing, not quality.** The fake model quotes the best retrieved passage and
never refuses on its own, and the fake embeddings are hashed bags of words (no meaning, English words
only), so some cases miss by design. CI only fails on errors.

## Run it for real (opt-in, capped, not run in CI)

```bash
ANTHROPIC_API_KEY=... uv run --project apps/agent python evals/rag/run.py \
    --provider anthropic --embeddings fastembed --budget-usd 0.10 --output results.md
```

- The first run downloads the fastembed model (about 220 MB) into `EMBEDDINGS_CACHE_DIR` (default
  `.cache/fastembed`).
- At most one model call per question that retrieved something; the spending cap stops the run before a call
  that could exceed `--budget-usd` (exit code 3).
- `--min-accuracy`, `--min-refusal` and `--min-precision` make the run fail below a threshold.
- Retrieval is in memory with the same chunker, embedding input, top-k and similarity threshold as
  production; pgvector is covered by the integration tests.

No real run has been made yet. Record the first one here (date, model, embeddings, the table above, cost).
