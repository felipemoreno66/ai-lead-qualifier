# ADR 0002: Save first, then orchestrate (transactional outbox), n8n optional

Status: accepted

## Context

A lead must never be lost because an orchestrator, the model provider or the mail server is down. The author
also wants n8n as a visible integration, but a hosted demo should run without it.

## Decision

The intake request writes the lead, its `submitted` timeline event and an `outbox_events` row
(`lead.created`) in one transaction and answers 202. A dispatcher inside the agent claims due events with
`FOR UPDATE SKIP LOCKED` every 2 seconds and hands them to a publisher. Failures retry with backoff
(5 s, 30 s, 2 m, 10 m, 30 m, 1 h, 2 h, 4 h) and then become `dead`, visible and re-triggerable from the
dashboard. `ORCHESTRATOR=inline` (default) runs the qualification and sending in the agent process;
`ORCHESTRATOR=n8n` posts HMAC-signed webhooks to n8n, which calls back `/internal/*` with a separate token.
Events carry unique idempotency keys (for example `message:<id>:send`), and delivery is idempotent.

## Consequences

- An unavailable orchestrator delays work but loses nothing; tests and the keyless demo need no n8n.
- Delivery is at least once, so every consumer must be idempotent (sending checks the message status and uses
  a stable `Message-ID`).
- The dispatcher runs in the agent process, so there is a single replica; a separate worker is a later option.
- n8n workflows are committed without credentials or execution data (`scripts/sanitize_n8n.py`, checked in CI).

## Alternatives considered

- Calling n8n or the model synchronously from the intake request: slow answers, lost leads on failure.
- A message broker or Redis queue: another service to run for a single-replica app.
- n8n as the only orchestrator: the demo could not run without it.
