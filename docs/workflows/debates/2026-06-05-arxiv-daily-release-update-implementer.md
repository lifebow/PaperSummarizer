# arXiv Daily Release Update — Implementer Argument

## Recommendation

Use release-window scheduler/detector without new storage entities, plus minimal fixes. Add configurable release window, poll aggressively during it, use larger retrieval limit there, store `last_release_detected_at` in `state`, and keep existing pipeline/storage.

## Main argument

The current pipeline is already adequate; the problem is scheduling and `limit=100`. `papers.arxiv_id` uniqueness and `archive_status` already provide dedupe and queueing. A release-window `watch()` helper can use a shorter interval during 07:00-09:30 UTC+7 and a larger `search_recent` limit. State-based dedupe prevents duplicate large scans. New release tables or queue abstractions duplicate current schema.

## Risks

- `show=2000` may be slow or incomplete; paginate later if needed.
- LLM spike; use existing budget/cache.
- Release drift; make window configurable and optionally extend if empty.
- Concurrent runs; add simple run lock if needed.
- SQLite contention; current sequential result writes already mitigate.

## Testability

Test config parsing, scheduler inside/outside window, large-batch dedupe, state-based skip, backward compatibility, and harness.

## Simplicity and reuse

Single helper for next run/sleep, reuse `DaemonConfig`, `local_now`, and `state`. No new modules, tables, or CLI.

## Refactor impact

Small: modify `watch()`, configurable retrieval limit in `run_once()`, add config fields. Existing behavior unchanged when config absent.

## Deployment impact

No DB migration, no dependencies, existing config still works. Optional config:

```yaml
daemon:
  release_window_start: "07:00"
  release_window_end: "09:30"
  release_window_minutes: 15
```

## What would change my mind

If `show=2000` is unreliable, version tracking is required, automatic detection is mandatory, or real-time per-paper Telegram changes are required.
