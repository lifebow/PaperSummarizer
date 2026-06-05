# arXiv Header-Count Discovery — Coordinator-Architect Argument

## Recommendation

Choose Design A with small existing-state footprint. No release tables yet.

## Main argument

Header count gives the contract: target latest section has N entries. Completion
is valid only when latest section date and expected total match state and
discovered count reaches expected total. Candidate B still needs section-aware
parsing, so probe/exact fetch is preferable.

## Risks

Parser fragility, partial progress with skip pagination, stale completion state,
and duplicate persistence if re-fetching.

## Testability

Tests for header parse, allowed show, section filtering, exact completion,
overfetch handling, pagination, no-progress, state skip and invalidation.

## Simplicity and reuse

Reuse arXiv list path, paper upsert, metadata queue, and state. New helpers stay
small and pure.

## Refactor impact

Narrow: recent-list parsing and daemon discovery logic.

## Deployment impact

Low; no migrations/dependencies.

## What would change my mind

If section boundaries cannot be reliably parsed, use always-show=2000 or release
tables depending on audit needs.
