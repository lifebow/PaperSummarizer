# Guaranteed Full Daily Discovery — Product/Operator Argument

## Recommendation

Adopt Option 2 with Option 5 hardening: state keys
`full_discovery_done:<YYYY-MM-DD>` and `full_discovery_count:<YYYY-MM-DD>`.
Until done, every run uses high limit regardless of window; after done, normal
catch-up.

## Main argument

The current behavior is silent data loss. Safe defaults must work even when
release-window config is empty or missed. Count state gives operators a clear
signal that today's full scan happened and how many papers it saw.

## Risks

- Timezone/date boundary mistakes.
- Very early runs may see stale previous-day data.
- State key accumulation is small.

## Testability

Late starts, empty release window, failure-not-done, and updated normal-window
tests are all offline mockable.

## Simplicity and reuse

Uses only existing state table and existing metadata queue.

## Refactor impact

Localized to discovery decision logic.

## Deployment impact

No new infrastructure; first run after deploy safely performs high-limit scan.

## What would change my mind

If exact release auditing/history is required, add dedicated release tables later.
