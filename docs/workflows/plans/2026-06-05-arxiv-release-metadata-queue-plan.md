# arXiv Release Metadata-First Queue Feature Plan

**Date:** 2026-06-05  
**Status:** Approved for implementation  
**Coordinator:** gpt-5.5  
**Runner Backend:** subagent  
**Debate:** `docs/workflows/debates/2026-06-05-arxiv-daily-release-update-final-decision.md`

## Goal

Update paper-radar for arXiv's daily release pattern by fetching the full cheap release list first, persisting minimal paper records, and processing/hydrating papers gradually under existing budget caps.

## Scope

- In scope:
  - Add release-window config and release-mode discovery limit.
  - Add list-only arXiv discovery that parses ID/title/category/link without fetching every `/abs` page immediately.
  - Persist discovered papers into existing `papers` table with `archive_status="metadata_only"` without overwriting completed statuses.
  - Add bounded metadata hydration from `metadata_only` to `queued` by fetching `/abs/<id>` for a limited number per run.
  - Keep relevance, PDF extraction, summary, QA, digest, and Expand-on-demand on the existing pipeline.
  - Enforce queue drain and summary candidate caps.
  - Make `RunBudget` thread-safe.
  - Wire accepted papers into existing Telegram paper-card flow while keeping scan/release notification concise.
  - Add comprehensive offline unit tests.
- Out of scope:
  - New `arxiv_releases` or `release_papers` tables.
  - Version-aware tracking.
  - Durable multi-stage job queue tables.
  - Summarizing all 1000-2000 papers.
  - Real API calls in unit tests.

## User Approval

- Debate decision approved: yes
- User amendment approved: yes — use metadata-first full release discovery: fetch title/link/ID/category first, then queue gradual work.
- Acceptance criteria approved: yes
- Debate models selected by user: yes
- Final judge model selected by user: yes

## Design Summary

The implementation should distinguish cheap discovery from expensive processing:

```text
Release window:
  fetch /list/<archive>/recent list-only up to release.discovery_limit
  persist all new papers as metadata_only
  hydrate metadata_only papers up to pipeline.hydrate_metadata_per_run
  process queued papers up to max_papers_per_run and budget caps

Outside release window:
  optional smaller discovery/default behavior
  continue hydrating and processing backlog under caps
```

Use existing SQLite fields:

- `papers.archive_status = metadata_only` for list-only records.
- `papers.archive_status = queued` after abstract/authors/date are hydrated.
- Existing statuses remain: `processing`, `retry_later`, `rejected_relevance`, `accepted`, `rejected_qa`, `error`.

Do not reset completed records to `metadata_only` during discovery.

## Proposed Config

Prefer minimal additive config fields with backward-compatible defaults. Names may be adjusted if existing style suggests better placement.

```yaml
daemon:
  release_window_start: "07:00"
  release_window_end: "09:30"

pipeline:
  release_discovery_limit: 2000
  normal_discovery_limit: 100
  hydrate_metadata_per_run: 300
  max_papers_per_run: 50
  max_summary_candidates_per_run: 20
```

Default behavior must remain safe for existing configs.

## Autonomous Subagent Execution Gate

```yaml
stages:
  - id: implement-feature
    runner: subagent
    model: standard
    owns:
      - paper_radar/config.py
      - paper_radar/db.py
      - paper_radar/retrieval.py
      - paper_radar/daemon.py
      - tests/test_arxiv_release_queue.py
      - existing tests as needed for compatibility

  - id: verify
    runner: subagent
    model: fast
    command: scripts/harness.sh
    depends_on:
      - implement-feature

  - id: pre-push-check
    runner: subagent
    model: fast
    command: scripts/harness.sh --pre-push
    depends_on:
      - verify

  - id: docker-smoke
    runner: subagent
    model: fast
    command: podman compose run --rm paper-radar --help
    depends_on:
      - pre-push-check
```

## Feature Test Matrix

See `docs/workflows/test-matrices/2026-06-05-arxiv-release-metadata-queue-test-matrix.md`.

## Acceptance Criteria

- A release-window run can discover and persist more than 100 arXiv list entries without fetching all `/abs` pages immediately.
- Minimal records contain at least arXiv ID, title when available, PDF/abs link info, source, category fields when parsed, and `archive_status="metadata_only"`.
- Hydration fetches only a bounded number of `metadata_only` papers per run and marks them `queued` when abstract metadata is available.
- Existing accepted/rejected/processing statuses are not accidentally reset by list-only discovery.
- Relevance/summary/QA work remains bounded by configured caps.
- `RunBudget` does not exceed max calls under concurrent workers.
- Telegram accepted-paper flow uses existing rendering/Expand buttons and avoids noisy empty scans.
- Existing CLI/config/db/digest/Telegram/Expand behavior remains backward compatible.
- Unit tests are offline.

## Lint Before Test Gate

Verification must be delegated to lint subagent:

```bash
scripts/harness.sh
```

## Regression Gate

Full existing unittest regression must pass through the canonical harness.

## Refactor Cadence Gate

Run pre-push mode through lint subagent:

```bash
scripts/harness.sh --pre-push
```

If the refactor cadence gate blocks, stop and report.

## Docker Deploy Smoke Gate

Because deploy files exist, run through lint subagent after regression:

```bash
podman compose run --rm paper-radar --help
```

Report missing Podman/Compose as a blocker, not as a pass.

## Completion Checklist

- [ ] Metadata-first discovery implemented.
- [ ] Bounded hydration implemented.
- [ ] Queue/status transitions protected.
- [ ] Budget and summary caps enforced.
- [ ] Telegram behavior intentionally wired/tested.
- [ ] New tests cover happy/edge/niche/invalid/failure/backward/refactor-safety cases.
- [ ] `scripts/harness.sh` subagent passed.
- [ ] `scripts/harness.sh --pre-push` subagent passed.
- [ ] Docker smoke subagent passed or blocker recorded.
