# Guaranteed Full Daily Discovery — Skeptic Argument

## Recommendation

Reject state-machine complexity for now; raise `normal_discovery_limit` to
500-750 and rely on rolling `/list/recent` convergence. If monitoring proves
misses matter, revisit stateful discovery.

## Main argument

Paper-radar is a relevance digest, not a bibliographic index. Full discovery may
be overprecision under stochastic LLM filtering. State machines can add false
completion and corruption failure modes.

## Risks

- The rolling window assumption may fail.
- This does not satisfy a strict completeness requirement.
- Monitoring burden increases.

## Testability

Convergence is easy to test with repeated mocked list fetches and dedupe.

## Simplicity and reuse

Very small change: bump normal limit and remove/reduce release-window gating.

## Refactor impact

Minimal.

## Deployment impact

Higher normal metadata traffic; downstream budgets unchanged.

## What would change my mind

Explicit user priority for completeness over simplicity, or evidence rolling
window is too narrow.
