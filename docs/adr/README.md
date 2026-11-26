# Architecture decision records

Short records (context, decision, consequences, alternatives) of decisions that shape the code. Each one
describes what the repository does today; details live in [../architecture.md](../architecture.md).

| ADR | Decision |
|---|---|
| 0001 | [FastAPI owns the database, Next.js is a BFF](0001-fastapi-owns-the-database-nextjs-is-a-bff.md) |
| 0002 | [Save first, then orchestrate (transactional outbox), n8n optional](0002-save-first-then-orchestrate-transactional-outbox.md) |
| 0003 | [LangGraph with a Postgres checkpointer for human review](0003-langgraph-with-postgres-checkpointer.md) |
| 0004 | [The score is computed in code from per-criterion judgments](0004-score-computed-in-code.md) |
| 0005 | [Native provider SDKs behind a port, with a fake provider](0005-native-sdks-behind-a-provider-port.md) |
| 0006 | [Append-only spend ledger and a fail-closed budget](0006-append-only-spend-ledger-and-fail-closed-budget.md) |
| 0007 | [A deterministic draft guard, re-run on approve and edit](0007-deterministic-draft-guard.md) |
| 0008 | [Citations validated against retrieved chunks, threshold before the model](0008-citations-validated-and-threshold-before-the-model.md) |
| 0009 | [Local multilingual embeddings with per-model thresholds](0009-local-multilingual-embeddings.md) |
| 0010 | [Pydantic is the source of the contracts: JSON Schema to Zod](0010-pydantic-json-schema-zod.md) |

In review and not yet recorded here: the public demo deployment (M4.3) and the private instance (M4.4).
Add a new ADR with the next number when a decision changes one of the above (mark the old one as superseded).
