# arXiv Daily Release Update — Architect Argument

## Recommendation

Combine minimal pipeline fixes with a release-window detector and one lightweight schema addition (`papers.release_batch_id`). Do not add full `arxiv_releases`/`release_papers`, version tracking, or a durable job queue yet.

Specifics:

- Detect daily batch by a large jump in unseen IDs during release window.
- Tag papers with nullable/indexed `release_batch_id` such as `2026-06-05`.
- Process batch-scoped: relevance across batch, top `max_summary_candidates_per_run` to phase 2, mark remainder `batch_suppressed`.
- Fix `RunBudget` thread safety.
- Enforce `max_summary_candidates_per_run`.
- Wire `send_hourly_telegram()` into `run_once()`.

## Main argument

The current system lacks release-batch semantics, causing cost explosion, missed or partial processing under budgets, and scattered Telegram UX. A single `release_batch_id` is enough to group papers without new tables. Batch-scoped processing caps summary/QA cost while still scoring metadata broadly. Existing relevance cache, two-phase pipeline, state store, and Telegram helpers can be reused.

## Risks

- False-positive batch detection; mitigate with threshold and cooldown.
- Post-batch papers; keep normal hourly fallback.
- Aggressive summary cap may suppress interesting papers; keep suppressions auditable.
- Existing `RunBudget` race must be fixed.
- New column must default safely for existing DBs.

## Testability

Test batch detection, `release_batch_id` persistence, summary cap enforcement, budget cap under concurrency, hourly Telegram wiring, and full regression.

## Simplicity and reuse

Reuses `archive_status`, relevance cache, state table, two-phase pipeline, `RunBudget`, and `send_hourly_telegram()`. Adds one nullable column rather than multiple tables.

## Refactor impact

Low-to-moderate: `db.py` migration for one column, `config.py` detection settings, `daemon.py` batch detection/capping/budget/Telegram changes. No CLI changes.

## Deployment impact

Automatic SQLite migration, no new dependencies, config defaults preserve current behavior. Disable detection via config if needed.

## What would change my mind

Evidence that release grouping requires richer timestamps, false positives are common, user needs version tracking, `archive_status` cannot support suppression, or cache lookups are too slow at batch scale.
