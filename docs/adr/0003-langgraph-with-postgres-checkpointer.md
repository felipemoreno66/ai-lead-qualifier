# ADR 0003: LangGraph with a Postgres checkpointer for human review

Status: accepted

## Context

Every reply is approved by a person, possibly hours after the draft is written, and the agent may restart
in between. The qualification flow has branches (redraft once when the draft guard fails, regenerate with
feedback, reject).

## Decision

The flow is a LangGraph `StateGraph` (`extract`, `qualify`, `answer`, `draft`, `validate_draft`,
`human_review`, `request_send`). `human_review` contains only `interrupt()`, so it has no side effects when the
node runs again on resume. The graph uses the Postgres checkpointer in its own `langgraph` schema, with one
thread per run (`lead:<id>:run:<n>`). A review action is first claimed in the database (row lock on the lead,
new state written, an approval queues `message.approved` once) and only then is the paused graph resumed; the
database stays the source of truth if resuming fails. Checkpoints contain lead data, so deleting a lead
deletes its threads and hourly maintenance removes orphaned or old finished threads (paused runs are kept).

## Consequences

- A paused run survives agent restarts; replays of a review request are no-ops or a 409.
- LangGraph and `langgraph-checkpoint-postgres` versions are pinned in `uv.lock`, and the graph is used behind
  `QualifyService` so it can be replaced.
- Checkpoints are personal data and need their own retention and deletion code.
- `agent_runs.duration_ms` includes the time waiting for a person.

## Alternatives considered

- Storing the draft and a status flag and re-running a function on approval: simpler, but each new branch
  (regenerate, redraft) would be hand-written state handling.
- An in-memory checkpointer: loses pending reviews on restart.
