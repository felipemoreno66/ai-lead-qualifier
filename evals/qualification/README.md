# Qualification eval

Checks that the qualification agent (extract, then qualify, then the score computed in code) agrees
with a human reading of ten fictional Northwind Academy leads.

| File | What it is |
|---|---|
| `dataset.yaml` | 10 labelled leads: 4 hot, 2 warm, 2 cold, 2 prompt-injection attempts (EN, ES, PT) |
| `run.py` | Runs the graph over the dataset and prints a results table plus summary metrics |

## Metrics

- **Tier accuracy**: the tier (hot, warm, cold) equals the label. The run fails below `--min-accuracy` (default 80%).
- **Product accuracy**: the recommended program equals the label (only where the label has one).
- **Injection accuracy**: `injection_suspected` equals the label.
- **Hot despite injection**: must be 0. A suspected injection can never produce a hot lead.

## Run it (fake provider: offline, free, deterministic)

```bash
make eval
# or, from the repository root
uv run --project apps/agent python evals/qualification/run.py
```

CI runs exactly this in the agent job. The fake provider is rule-based, so a perfect score only
proves the plumbing and the scoring code; the value of the dataset is the real-provider run below.

## Run it with a real provider (opt-in, capped, not run in CI)

```bash
ANTHROPIC_API_KEY=... uv run --project apps/agent python evals/qualification/run.py \
    --provider anthropic --budget-usd 0.20
```

- The run stops **before** any call that could take its spend over `--budget-usd` (worst-case estimate from
  the prompt size and `max_tokens`, priced with `pricing.yaml`) and exits with code 3.
- The graph also drafts a reply per lead, so expect about 3 calls per lead on the default model
  (`claude-haiku-5-5`, override with `--model`). The model must be in `pricing.yaml`.
- `--output results.json` stores the per-case results for comparison between prompt versions.

No real run has been made yet. Record the first one here (date, model, prompt versions, accuracy, cost).
