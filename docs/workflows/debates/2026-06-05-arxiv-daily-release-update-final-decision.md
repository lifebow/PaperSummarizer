# Final Decision Memo: arXiv Daily Release Update

**Decision status:** Final judge recommendation only. This decision **still requires user approval before it becomes an implementation plan**. No implementation should begin until the user approves.

## Decision

Adopt a staged combination of **Direction 1: minimal pipeline fixes** and **Direction 2: release-window scheduler/detector without new storage entities**.

The recommended update is:

1. **Broaden discovery around the arXiv release window**
   - Add configurable release-window settings around the observed 07:00-09:00 Asia/Ho_Chi_Minh batch.
   - During the release window, use a larger recent-paper retrieval limit and/or pagination if needed.
   - Keep cheaper, lower-frequency or lower-limit scans outside the window.

2. **Keep existing storage model for now**
   - Reuse `papers.arxiv_id` uniqueness, `archive_status`, `state`, `relevance_cache`, and existing run/result tables.
   - Do **not** add `arxiv_releases`, `release_papers`, version tables, or a durable job queue in this iteration.
   - Do **not** add `papers.release_batch_id` initially; prefer state markers and run counters unless later evidence shows release grouping/audit is needed.

3. **Fix the current cost/control correctness issues**
   - Make `RunBudget` thread-safe under parallel workers.
   - Clearly enforce `max_summary_candidates_per_run`.
   - Treat `max_papers_per_run`/queue-draining limits as real caps, not accidental chunk behavior.
   - Continue using relevance cache and LLM budget guards to prevent summarizing all 1000-2000 released papers.

4. **Improve Telegram behavior**
   - Wire accepted-paper notifications or hourly/release summaries through the existing Telegram helpers, especially `send_hourly_telegram()`, while preserving Expand-on-demand.
   - Keep Telegram output concise to avoid noise.

5. **Validate retrieval coverage before adding schema**
   - The highest-risk unknown is whether arXiv `/list/<archive>/recent?show=<large>` is sufficient for 1000-2000 papers or whether pagination/cursor behavior is needed.
   - Solve that empirically with fixtures and, later, optional integration checks before building release-batch tables.

This keeps the first implementation focused on the demonstrated failure: the current daemon performs shallow hourly scans with `limit=100`, while arXiv releases a much larger public batch.

## Agreements Across the Panel

The panel broadly agreed on these points:

- The current `limit=100` is a major reason relevant papers may be missed.
- The system should not summarize all 1000-2000 released papers with the LLM.
- Existing SQLite-first architecture should remain.
- Existing `archive_status`, `state`, relevance cache, and two-phase pipeline should be reused.
- `RunBudget` has a parallel accounting race and should be fixed.
- `max_summary_candidates_per_run` should be clearly enforced.
- Telegram behavior should be improved or wired into the release/hourly flow.
- Full release tables, version tracking, and durable queue infrastructure are premature.
- Unit tests should avoid real network/API calls.

## Main Conflicts

### 1. Whether to add release-batch storage now

- **Architect** recommended one lightweight schema addition: `papers.release_batch_id`.
- **Implementer**, **Product/Operator**, **Coordinator-Architect**, and **Skeptic** leaned toward no new storage entities for now.
- The stronger consensus is to avoid schema changes until there is evidence that release-level audit/replay is needed.

**Judgment:** Defer `release_batch_id`. It is simpler than full batch tables, but still not necessary to solve the immediate miss-risk.

### 2. Scheduler/detector now vs minimal fixes only

- **Skeptic** argued for minimal fixes first: raise/configure fetch limits, enforce caps, fix budget, and only add release-window heuristics after observing failures.
- **Implementer**, **Product/Operator**, and **Coordinator-Architect** argued that release-window behavior is directly tied to the user’s operational reality and should be added now.
- **Architect** also supported release-window detection.

**Judgment:** Add release-window scheduling/config now, but keep it lightweight. The release timing is part of the problem statement, so waiting for more misses is unnecessary.

### 3. Large `show` limit vs pagination/cursor correctness

- Several panelists warned that `show=2000` may be slow, incomplete, or unreliable.
- No panel argument proved that `show=2000` works reliably.
- The debate brief says current retrieval uses `/list/<archive>/recent?skip=0&show=<limit>` and defaults to `limit=100`.

**Judgment:** Implementation should support a larger configured limit first, but tests should be designed so pagination can be added if fixtures or integration checks show the large single-page request is insufficient.

### 4. Batch detection vs fixed release window

- **Architect** proposed detecting a daily batch by a large jump in unseen IDs.
- **Implementer** and **Product/Operator** emphasized configurable release-window scans and state markers.
- **Coordinator-Architect** supported release-window scheduler/detector but did not require new batch entities.

**Judgment:** Use configurable release-window behavior as the primary mechanism. A lightweight detector using unseen-paper counts can be used for logging or adaptive behavior, but it should not require new schema.

## Strongest Point From Each Panel Argument

### Architect

Strongest point: the current system lacks batch semantics, which can cause cost explosion, partial processing, and scattered Telegram UX. The architect correctly identified the need for batch-scoped caps, budget thread safety, summary cap enforcement, and Telegram wiring.

Why not fully adopt: the proposed `papers.release_batch_id` is reasonable but not yet necessary given the stronger consensus for state/config-based handling first.

### Implementer

Strongest point: the current pipeline and storage are mostly adequate; the immediate issue is scheduling plus `limit=100`. Existing `arxiv_id` uniqueness and `archive_status` already provide dedupe and queueing.

This is central to the final decision.

### Product/Operator

Strongest point: the user promise is “not missing relevant papers,” and current `limit=100` against a 1000-2000 paper release breaks that promise. The operator framing correctly prioritizes operational coverage, release-window catch-up, and Telegram delivery.

This strongly supports release-window scanning now rather than only abstract pipeline work.

### Coordinator-Architect

Strongest point: broaden cheap discovery but bound expensive processing. This captures the key tradeoff: find many papers, but do not run PDF/summary/QA on all of them.

This is the best synthesis of correctness, cost control, and simplicity.

### Skeptic

Strongest point: new entities do not improve fetch or screening rate; the real blockers are shallow discovery, cursor/pagination gaps, summary cap enforcement, and budget races.

This is the strongest caution against overbuilding release tables, version tracking, or job queues.

## Rejected Alternatives

### Rejected: Full explicit release-batch storage now

Do not add `arxiv_releases` and `release_papers` in this iteration.

Reason: The panel did not show a present need for release-level analytics, replay, or audit that cannot be handled by existing run/state/status records. It adds migrations and backfill/rollback risk without directly solving shallow discovery.

### Rejected: Version-aware arXiv tracking now

Do not add version tracking in this iteration.

Reason: The debate focused on daily release coverage, not paper revision handling. No argument provided evidence that version changes are currently causing missed relevance or stale summaries.

### Rejected: Durable multi-stage job queue now

Do not add a new durable job queue.

Reason: Existing `archive_status` already acts as a simple queue/status field. The coordinator-architect and skeptic both argued that queue discipline can be improved without introducing a new execution model.

### Rejected: Summarize all papers in the release batch

Do not run PDF extraction, summary, and QA over all 1000-2000 release papers.

Reason: The brief explicitly says not to summarize all 1000-2000 papers with LLM, and the panel consistently prioritized cost guards.

### Rejected: Minimal fixes with no release-window behavior

Do not limit the change to only raising fetch limits and fixing caps.

Reason: The user supplied a clear release timing pattern. A configurable release-window scheduler is a low-complexity operational fit and helps avoid both missed papers and off-hours waste.

### Rejected for now: `papers.release_batch_id`

Do not add this column in the first implementation.

Reason: It is the least invasive schema option, but still a schema change. Existing `state`, `runs`, `archive_status`, and logs/counters should be tried first. Add a batch identifier later only if audit/replay, false-positive analysis, or Telegram grouping requires it.

## Follow-up Tests and Experiments

Before or during implementation planning, define tests for:

1. **Release-window scheduling**
   - Inside release window uses short/aggressive polling or elevated scan mode.
   - Outside release window preserves existing/default behavior.
   - Window boundaries around 07:00 and 09:00/09:30 Asia/Ho_Chi_Minh are handled correctly.
   - Config defaults remain backward compatible.

2. **Large discovery coverage**
   - Mock arXiv recent responses larger than 100 papers.
   - Verify the daemon requests the elevated release-window limit.
   - Verify dedupe through existing `arxiv_id` uniqueness/status handling.
   - Add fixture-based pagination/cursor tests if pagination is implemented.

3. **Cost and budget controls**
   - `RunBudget` does not overspend under parallel workers.
   - `max_summary_candidates_per_run` is enforced.
   - Queue draining respects configured caps.
   - Relevance cache hits reduce LLM relevance calls.

4. **Pipeline behavior with large batches**
   - Large discovered batch does not trigger summary/QA for every paper.
   - Accepted/rejected/suppressed or queued statuses remain consistent.
   - Backlog behavior is visible through counters or logs.

5. **Telegram UX**
   - Accepted papers are sent via existing Telegram flow.
   - Expand buttons remain present.
   - Release/hourly messages are concise and do not spam.

6. **Backward compatibility**
   - Existing CLI behavior still works.
   - Existing config files without release-window settings still load.
   - Existing SQLite DBs still work without migration.
   - Existing digest, recap, and expand behavior remain intact.

7. **Optional empirical experiment**
   - With user approval and outside unit tests, perform a real arXiv retrieval check to determine whether large `show` values reliably cover the observed release size or whether pagination is required.

## Final Recommendation Summary

Proceed, after user approval, with a lightweight release-aware update:

- configurable release-window scan mode,
- larger/paginated discovery around release,
- existing SQLite/status/state storage,
- strict LLM/PDF budget and summary caps,
- thread-safe budget accounting,
- Telegram wiring for accepted papers,
- no new release/version/job tables yet.

This best satisfies the brief’s priorities: avoid missing relevant papers, keep the implementation simple, control costs, preserve current behavior/tests, and improve Telegram UX.
