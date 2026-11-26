# ADR 0008: Citations validated against retrieved chunks, threshold before the model

Status: accepted

## Context

Answers about prices, refunds or scholarships must come from the business's documents. Models can cite text
that was not retrieved or answer when nothing relevant exists.

## Decision

Retrieval (`KnowledgeBaseService.retrieve`, `KB_TOP_K`, a minimum cosine similarity) runs before the model:
a question with nothing above the threshold never reaches it and gets a fixed "not covered" text (English or
Spanish). For the rest, the model returns `answer`, `covered` and `citations` of `{chunk_id, quote}`; a domain
check requires every `chunk_id` to have been retrieved for that very question and the quote (at least 15
characters or 3 words) to appear word for word in the chunk text as a reader sees it. Violations go through the
repair loop and then fail the run. Questions and chunks are escaped JSON in tagged blocks. The same
`answer_questions` function serves the lead graph and the dashboard's Ask the docs. Citations are stored with
their quote and source and without a foreign key to chunks, so re-ingesting never breaks them.

## Consequences

- The model cannot cite a source it was not given, and unanswerable questions cost no model call.
- A correct paraphrase with a quote that is not verbatim is rejected, which can cause a failed run.
- The threshold depends on the embedding model (ADR 0009) and must be re-tuned when the model or documents
  change.

## Alternatives considered

- Trusting the model's `covered` flag alone.
- Fuzzy quote matching: weaker evidence that the cited text exists.
