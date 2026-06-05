# Guaranteed Full Daily Discovery — Architect Argument

## Recommendation

Adopt Option 2: a daily discovery state machine in existing SQLite `state`.
Use `release_discovery_limit` on every run until today's full discovery is
complete. Release windows become hints, not correctness gates.

## Main argument

The bug is conflating an optimization hint with correctness. If the daemon
starts outside the release window, it silently uses the normal limit and misses
most of the daily batch. State should answer whether today's full discovery is
done.

Suggested completion hardening: do not mark a tiny pre-release result complete;
use count/window-end or another suspicious-low-count guard.

## Risks

- Missing release-window-end configuration can make completion heuristics vague.
- Late arXiv releases can make a premature completion dangerous.
- State keys accumulate, but this is negligible.

## Testability

Test late start uses high limit; pre-release tiny count does not complete;
post-completion uses normal; failures do not mark complete; restart preserves
state.

## Simplicity and reuse

Reuse `state`, `upsert_paper_discovery`, and existing queue statuses. No schema
migration.

## Refactor impact

Small changes in daemon discovery decision logic.

## Deployment impact

No migration or new dependency. First run after deploy performs high-limit scan
if today's state is absent.

## What would change my mind

Evidence that high-limit list fetches are too costly, or a simpler design with
