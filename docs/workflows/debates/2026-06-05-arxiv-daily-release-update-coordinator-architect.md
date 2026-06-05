# arXiv Daily Release Update — Coordinator-Architect Argument

## Recommendation

Stage the update: release-window scheduler/detector plus a small part of durable queue discipline, deferring explicit batch tables and version tracking. Broaden discovery during release window, bound queue draining and expensive stages, fix parallel budget accounting, and improve Telegram release messaging.

## Main argument

The core failure is mismatch between arXiv burst release and hourly shallow scanning. Improve discovery coverage first, not storage architecture. Existing `papers.archive_status` is already a minimal durable queue; strengthen its semantics with bounded draining and visible backlog. Broaden cheap discovery but bound expensive processing.

## Risks

- arXiv recent pagination/`show` may be insufficient.
- Broad `cs` archive scan causes irrelevant papers; add cheap metadata/category prefilter without hard keyword drops.
- Backlog growth under strict budgets; log/notify queued, processed, skipped counts.
- Parallel budget overspend; must fix.
- Telegram noise; use concise release/found/accepted notifications.

## Testability

Test release-window boundaries, discovery >100, dedupe, category behavior, queue caps, budget caps, Telegram release notifications, no real network calls, regression.

## Simplicity and reuse

Keep current DB, service, retriever, `archive_status`, relevance cache, digest, Telegram Expand. Add small helpers: `is_release_window`, release discovery mode, stricter queue caps, synchronized budget reservation.

## Refactor impact

Moderate but not architectural: config additions, daemon phase boundaries/limits, retriever larger/paginated recent retrieval if needed, ideally no new DB entities.

## Deployment impact

Low: no external service, SQLite remains, optional config defaults, Docker smoke unchanged.

## What would change my mind

Favor release tables if broad discovery cannot identify batches or user needs audit/replay. Favor version tracking if updates cause stale/missed relevant papers. Favor full queue if `archive_status` cannot recover or multiple processes coordinate work.
