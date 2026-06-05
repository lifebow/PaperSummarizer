# arXiv Header-Count Discovery — Architect Argument

## Recommendation

Design A+: probe with `show=50`, parse latest section date and expected total,
choose the smallest valid `show` value that covers the total, paginate with
`show=2000` when needed, count target section only, and cache completion state.

## Main argument

The header total is a direct signal from arXiv. Probe-first avoids repeated
`show=2000` overfetch while preserving correctness. Completion must be based on
target latest-section entries, not all rows in the page.

## Risks

Parser fragility, stale state after section count changes, probe/fetch race,
sections above 2000 requiring pagination, and date-boundary confusion.

## Testability

Pure tests for `choose_allowed_show`, header parser, target-section counting,
state-skip decisions, pagination, parse fallback, and no-progress loops.

## Simplicity and reuse

Reuse existing state, HTML fetch, arXiv list parser concepts, paper upsert, and
metadata-first queue. No new dependency or table.

## Refactor impact

Mostly retrieval/parser helpers and daemon discovery call path.

## Deployment impact

Low. First run after deploy full-fetches; stale runs use a cheap probe.

## What would change my mind

Official structured API, unsupported/stable header changes, or environment where
probe round-trip is too costly.
