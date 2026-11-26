# ADR 0006: Append-only spend ledger and a fail-closed budget

Status: accepted

## Context

A public form that triggers paid model calls can burn money through abuse or bugs. The cap must survive
purging stored calls, deleting leads and crashes between a call and its bookkeeping.

## Decision

`LLM_BUDGET_USD` is a lifetime cap enforced against the `llm_spend` ledger, which has no foreign keys and blocks
`DELETE` and `TRUNCATE` with triggers. Before each non-fake call the guard takes a Postgres advisory lock,
refuses the call if `spent + worst case of this call` would pass the cap, and persists a reservation that every
process sees. The reservation is settled with the real cost in a `finally` block (retried once, falling back to
the worst case); reservations never expire, so a crash leaves a conservative charge that an operator reconciles
by hand (documented in `docs/architecture.md`). The worst case counts one token per prompt byte plus 25%, unknown
models are priced at the highest known rate, `max_tokens` is clamped to 8192 and calls per agent run are capped
(`LLM_MAX_CALLS_PER_LEAD`). The fake provider costs 0.

## Consequences

- The cap cannot be lowered by cleanup jobs or lead deletion, and concurrent processes cannot overspend.
- A crash can leave a worst-case charge until reconciled, and the worst case is an overestimate, so the cap can
  block calls slightly early.
- Stored requests and responses are redacted for emails and phone numbers and purged after
  `LLM_CALLS_RETENTION_DAYS`, independently of the ledger.

## Alternatives considered

- Summing `llm_calls` at check time: purging calls or deleting a lead would lower the spent amount.
- Provider-side spend limits only: not visible to the app and absent for the fake or other setups.
