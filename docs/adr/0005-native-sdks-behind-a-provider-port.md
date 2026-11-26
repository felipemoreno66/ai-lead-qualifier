# ADR 0005: Native provider SDKs behind a port, with a fake provider

Status: accepted

## Context

Cost tracking, structured output and retry behaviour differ per provider, and LangChain's abstraction
hides token usage and provider options. CI, local development and the public demo must run without any API key.

## Decision

`ports/llm.py` defines `LLMProvider` (`generate_structured`, `generate_text`). Adapters are thin: Anthropic
(official SDK, JSON schema output), Bedrock (reusing the Anthropic SDK, not run in CI), an OpenAI skeleton and a
deterministic `FakeProvider` (a pure function of task and input; rule-based handlers give explainable
judgments; `script=[...]` injects invalid output or timeouts in tests). `RecordingProvider` wraps any adapter
with the budget guard and the `llm_calls` log, and `generate_validated` adds the parse, domain check and repair
loop. LangChain is used only for Markdown and text splitting; LangGraph only for orchestration. `LLM_PROVIDER`
defaults to `fake`.

## Consequences

- Exact token and cost accounting per call and the same recording path for every provider.
- A keyless `docker compose up` and CI that never spend money.
- Each adapter is maintained by hand; OpenAI is only a documented skeleton and Bedrock is untested in CI.
- Prompts are tuned for one provider family; moving to another needs an eval run.

## Alternatives considered

- LangChain chat models for everything: less code, but hidden token usage and provider options.
- Calling one provider's SDK directly from the graph nodes: no fake for keyless CI, no single place for the budget.
