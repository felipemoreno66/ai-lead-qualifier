# ADR 0004: The score is computed in code from per-criterion judgments

Status: accepted

## Context

Asking a model for a number from 0 to 100 gives results that are hard to explain, differ between models and
cannot be unit tested. The business rules (criteria, weights, tier thresholds) belong to each workspace's
configuration.

## Decision

The `qualify` node asks the model only for a judgment per criterion (`met`, `partial` or `unmet`) and a
recommended product. `domain/scoring.py` turns judgments into a score: values 1, 0.5 and 0 times the criterion
weights, normalised to 0-100 and rounded half up; tiers come from the workspace's `hot_min` and `warm_min`.
The output must name every criterion exactly once and a real product id, otherwise the repair loop runs and,
after two repairs, the run fails with `llm_output_invalid`. Lead data is passed as escaped JSON inside tags and
the prompt says it is data, so injected instructions in free text cannot set a score.

## Consequences

- The score is explainable (the dashboard shows each judgment), deterministic given the judgments and
  covered by plain unit tests.
- Changing weights or thresholds in a workspace file changes scores without touching prompts.
- The quality of the judgments still depends on the model; the offline eval uses the fake provider and checks
  plumbing, not model quality.

## Alternatives considered

- Model-generated score: cheaper in code, worse in every property above.
- Pairwise ranking of leads by the model: expensive and unstable.
