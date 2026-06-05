# Guaranteed Full Daily arXiv Discovery Debate Brief

**Date:** 2026-06-05  
**Status:** Draft  
**Backend:** opencode/subagents  

## Question

How should `paper-radar` guarantee that it discovers the full daily arXiv CS paper
batch, even if the daemon starts late, restarts after the release window, misses a
polling interval, or arXiv's release timing shifts?

## Context

- Project: `paper-radar`, an hourly arXiv/Semantic Scholar paper radar with LLM
  relevance filtering, summaries, daily Markdown digests, and Telegram notices.
- Current release metadata queue implementation:
  - `PaperRadarService.run_once()` calls `_discover_list_only(batch_time)`, then
    `_hydrate_metadata()`, then drains queued papers under caps.
  - `_discover_list_only()` uses `release_discovery_limit` only when
    `_is_release_window(batch_time)` is true.
  - Outside the configured release window it uses `normal_discovery_limit`.
  - Defaults currently make `release_window_start/end` empty unless configured,
    so a default deployment may discover only `normal_discovery_limit=100`.
  - Even with a configured 07:00-09:30 release window, a daemon that starts at
    11:00 or 14:00 may miss the full 1000-2000 paper list and only discover 100.
- User requirement: full daily paper discovery must be guaranteed; missing the
  release window must not cause the system to miss most papers.
- User intent from prior amendment: fetch the full paper metadata list first
  (id/title/link), then push into a queue for gradual hydration/relevance/summary.
- arXiv reality:
  - Daily public batches for CS can be large, around 1000-2000 papers.
  - Release timing may shift; daemon may be down or delayed.
  - `/list/<archive>/recent?show=<limit>` returns recent list pages, not a
    durable project-specific daily release entity.
- Current durable state/storage:
  - SQLite `papers` with `archive_status` including `metadata_only`, `queued`,
    `accepted`, `rejected_*`, etc.
  - `state` key/value table.
  - No dedicated `arxiv_releases` or `release_papers` tables yet.
- Current constraints:
  - SQLite-first; avoid new external queue infra.
  - No real network calls in unit tests.
  - Avoid summarizing all 1000-2000 papers immediately; discovery and processing
    must remain budgeted and gradual.
  - Existing Telegram expand and recap behavior must remain compatible.
  - Keep implementation simple enough for current project size.

## Decision Space

Consider at least these alternatives:

1. **Always high-limit list discovery every run**
   - Always call `/list/cs/recent?show=2000` (or configured high limit) for the
     metadata-only discovery stage, independent of release window.
   - Keep hydration/processing caps unchanged.

2. **Daily discovery state machine**
   - Track per-date full discovery attempts/completion in `state`, e.g.
     `full_discovery_done:YYYY-MM-DD`, `full_discovery_last_count:YYYY-MM-DD`.
   - Until today's full discovery is marked done, use high limit on every run.
   - After done, optionally fall back to smaller normal discovery or keep a
     lower catch-up check.

3. **Sliding catch-up window**
   - Use high-limit discovery until a late daily cutoff (e.g. 23:59), not just
     07:00-09:30.
   - Release window becomes an optimization/hint, not correctness boundary.

4. **Dedicated release tables**
   - Add `arxiv_releases` and/or `release_papers` to track release dates, list
     counts, pages fetched, completion, and failures.
   - More durable but more schema and migration work.

5. **Hybrid low-risk approach**
   - Always use high-limit discovery once per local day, keyed by state.
   - Also run high-limit if the last full discovery count seems suspiciously
     small or if daemon has never completed today's full scan.
   - Keep release window only for logging/priority, not for limiting discovery.

## Required Debater Sections

Each debater must answer independently with:

- Recommendation:
- Main argument:
- Risks:
- Testability:
- Simplicity and reuse:
- Refactor impact:
- Deployment impact:
- What would change my mind:

## Judge Requirements

The final judge must:

- compare all panel arguments,
- identify agreements and conflicts,
- choose a decision that satisfies the user's "must discover the full day" requirement,
- list rejected alternatives,
- list implementation constraints and required tests,
- avoid inventing evidence outside this brief and the panel arguments.

## User Approval Gate

After the judge decision, coordinator must present it to the user and stop. No
implementation plan or code changes until the user approves the decision.
