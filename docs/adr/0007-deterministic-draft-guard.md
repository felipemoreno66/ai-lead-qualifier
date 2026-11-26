# ADR 0007: A deterministic draft guard, re-run on approve and edit

Status: accepted

## Context

Replies are sent to real people under the business's name. A model may invent prices, add links or addresses,
leave placeholders, or follow instructions hidden in the lead's text; an operator may also edit a draft into
something unsafe.

## Decision

`domain/draft_guard.py` is pure code with no model. It checks the word limit, links only on
`allowed_link_domains` (parsed like a browser, compared in punycode, bare domains count), only the business's
email addresses, no placeholders, every amount present as a price fact in the workspace config, a language sanity
check, and control or bidirectional characters. `validate_draft` runs it in the graph and redrafts once with
fixed problem codes as feedback (never lead-derived text). The same checks run again on the final text when
the operator approves or edits: problems answer 422 unless the request carries `override: true`, which is
recorded in the timeline.

## Consequences

- Approved text is checked regardless of who wrote it, and every override leaves a trace.
- The guard is strict and may reject harmless text (an unlisted amount, a bare domain); the workspace config
  is where allowed links, addresses and prices are declared.
- Language detection is a heuristic over stop words, not a classifier.

## Alternatives considered

- Asking a second model to review the draft: costs money, is not deterministic and can be injected too.
- Checking only at draft time: an edit would bypass it.
