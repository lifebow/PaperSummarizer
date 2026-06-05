# Guaranteed Full Daily Discovery — Implementer Argument

## Recommendation

Use a daily discovery state machine with Option 5 fallback ideas. If today's
`full_discovery_done` state is absent/stale/corrupt, use `release_discovery_limit`.
After completion, use `normal_discovery_limit`.

## Main argument

The current branch `release window ? high : normal` is the bug. Replace it with
`today complete ? normal : high`. This is minimal, uses existing state, and keeps
hydration/LLM budgets unchanged.

## Risks

- Marking done too early on partial fetch.
- Absolute zero-missed behavior beyond 2000 papers would require pagination or a
  separate archival/backfill feature.
- Concurrent daemons can duplicate high-list fetches but DB upserts are
  idempotent.

## Testability

Test 14:00/no-state uses high limit; done state uses normal; network error does
not mark done; corrupted state fails safe to high.

## Simplicity and reuse

No new tables. Reuse `get_state`/`set_state` and existing discovery code.

## Refactor impact

Low; localized to daemon.

## Deployment impact

No migration; safer defaults on next run.

## What would change my mind

If user requires guaranteed coverage above the configured list limit, add
pagination/release tables later.
