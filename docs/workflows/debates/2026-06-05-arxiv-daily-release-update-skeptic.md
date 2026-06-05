# arXiv Daily Release Update — Replacement Skeptic Argument

## Recommendation

Adopt minimal fixes only first: raise/configure fetch limits, enforce `max_summary_candidates_per_run`, fix `RunBudget` locking, and improve retriever cursor/pagination correctness if needed. Do not add release tables, version tracking, or job queue. Consider a lightweight release-window heuristic only after observing misses/deadline failures.

## Main argument

There is a 12-14 hour window between morning arXiv release and 21:00 recap. The current two-phase pipeline can process enough if it sees enough papers. The actual hard blocker is `limit=100`, not lack of release architecture. New entities add maintenance burden without improving fetch or screening rate. The real risks are cursor gaps and cost races.

## Risks

- Pagination/cursor fix may skip papers if arXiv reorders; test with fixtures.
- Higher fetch limits increase relevance LLM calls; mitigate with cache/budget.
- Too many relevance-pass candidates; enforce summary cap.
- Unfixed `RunBudget` race causes spend overrun.
- Directions 3-5 create schema staleness and maintenance overhead.

## Testability

Minimal fixes are easiest: large mock arXiv response, atomic budget test, config limit tests. Release scheduler is moderate. Release tables, version tracking, and job queue greatly expand tests.

## Simplicity and reuse

Direction 1 keeps straight-line `run_once()` and current tables. Direction 2 adds timing branch. Directions 3-5 introduce new batch/version/job concepts not justified by current need.

## Refactor impact

Direction 1: small code/config/budget changes, no schema. Direction 2: small scheduler. Direction 3+: medium to very high schema/execution-model impact.

## Deployment impact

Direction 1/2: essentially zero. Direction 3-5: migrations/backfills and higher rollback risk.

## What would change my mind

Empirical proof of missed papers after raised limits, recap deadline misses, unstable release time, version changes causing missed relevance, or SQLite queue contention proven by profiling.
