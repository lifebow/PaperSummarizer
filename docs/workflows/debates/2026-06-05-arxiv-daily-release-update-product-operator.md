# arXiv Daily Release Update — Product/Operator Argument

## Recommendation

Adopt release-window scheduler/detector plus targeted minimal fixes. Use one large catch-up scan after release, short/cheap polls outside the window, larger scan limit, state marker for last release scan, wire accepted papers to Telegram. Do not add release tables, version tables, or job queue yet.

## Main argument

The user promise is not missing relevant papers. Current `limit=100` against `/list/cs/recent` misses most of a 1000-2000 paper release. This is operational, not storage architectural. Existing `state`, `relevance_cache`, `archive_status`, and runs are enough. The daemon should run a comprehensive scan around release time and send accepted paper cards via existing `send_hourly_telegram()`.

## Risks

- Release time drift; use tolerance and fallback short polls.
- LLM cost spike; use cache and budget.
- `RunBudget` race must be fixed.
- `show=2000` may require empirical pagination support.
- User expectation of hourly updates; retain short polls.

## Testability

Test release window scheduling, Telegram wiring, elevated scan limit URL, budget thread safety, backward compatibility, optional integration test for arXiv `show=2000`.

## Simplicity and reuse

Reuse `state`, `relevance_cache`, `archive_status`, `RunBudget`, `send_hourly_telegram()`, `ArxivClient`. Minimal new code.

## Refactor impact

Localized to `daemon.py`, `config.py`, maybe no DB changes. Current refactor cadence likely remains under threshold.

## Deployment impact

No migration, no new secrets/dependencies. Operational change: daemon sleeps/works around release window and reduces off-hours noise.

## What would change my mind

Need release-level analytics, unreliable list pagination, batches above 2000, multi-user schedules, or empirical misses after deployment.
