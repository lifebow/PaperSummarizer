# Guaranteed Full Daily Discovery — Coordinator-Architect Argument

## Recommendation

Use a hybrid daily discovery state approach: one guaranteed high-limit
metadata-only discovery per local arXiv day, repeated until complete in existing
state, no release tables yet.

## Main argument

State, not wall-clock window, must drive correctness. Metadata discovery is cheap
relative to hydration/PDF/LLM work, and downstream caps already keep processing
bounded. This matches the user's intent: fetch full metadata first, then process
gradually.

## Risks

- `/list/recent` is not a perfect daily ledger.
- Wrong date key can mark the wrong day complete.
- Tiny/partial responses can falsely complete unless guarded.

## Testability

Test outside-window/no-state high limit; 11/14 late starts; success normalizes to
normal limit; failure/low count retries; duplicate high scans idempotent; date
boundary; budget separation.

## Simplicity and reuse

Reuses `papers.archive_status` queue and `state`; no new schema.

## Refactor impact

Add small helpers for discovery day key, done/count state, and limit decision.

## Deployment impact

Low; no new dependencies or Docker changes.

## What would change my mind

Historical release reconstruction or exact per-release audit requirements would
justify release tables.
