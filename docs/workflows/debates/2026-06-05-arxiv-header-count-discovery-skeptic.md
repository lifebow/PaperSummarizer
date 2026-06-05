# arXiv Header-Count Discovery — Skeptic Argument

## Recommendation

Prefer bounded overfetch / always `show=2000` over full header parsing, or keep a
refined heuristic. Header parsing is fragile and gives false confidence.

## Main argument

The header is human-readable HTML, not a stable API. Counts can be stale,
section-boundary parsing is brittle, and offline fixtures cannot catch future
HTML changes.

## Risks

Regex breakage, stale counts, midnight ambiguity, false confidence, and state
complexity.

## Testability

Parser tests are snapshot-dependent; Design B is easier to test by asserting a
single `show=2000` fetch and DB dedupe.

## Simplicity and reuse

Design B reuses existing entry parser and dedupe with less new parser logic.

## Refactor impact

Design A touches parser, daemon, state; Design B is smaller.

## Deployment impact

Design A adds silent runtime parse-failure modes; Design B is easy to rollback.

## What would change my mind

Evidence header count is stable/contractual, parse failures are monitored, and
the user truly requires full section fetch.
