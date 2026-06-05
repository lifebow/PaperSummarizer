# arXiv Daily Release Update Debate Brief

**Date:** 2026-06-05  
**Status:** Draft  
**Backend:** opencode/Codex subagents using user-approved model roles  

## Question

Given the current `paper-radar` workflow, how should the bot be updated for arXiv's daily release pattern, where papers are submitted throughout the day but released in a large public batch around 07:00-09:00 Asia/Ho_Chi_Minh time?

Choose among or combine these directions:

1. Minimal fixes on the current queue/pipeline.
2. Release-window scheduler/detector without new storage entities.
3. Explicit release-batch storage (`arxiv_releases`, `release_papers`).
4. Version-aware arXiv tracking.
5. Durable multi-stage job queue.

The decision should prioritize not missing relevant papers, keeping implementation simple, controlling LLM/PDF costs, preserving current tests/behavior where possible, and supporting Telegram UX.

## Context

- Project: `paper-radar`, local arXiv AI paper radar with SQLite, LLM summaries, Markdown digests, Telegram recaps, and Expand-on-demand.
- Current scheduler:
  - `PaperRadarService.watch()` loops `run_once()` then sleeps `daemon.interval_minutes`, default 60 minutes.
  - There is no release-window scheduler.
- Current retrieval:
  - `run_once()` calls `retriever.search_recent(..., limit=100)`.
  - Default retriever uses arXiv `/list/<archive>/recent?skip=0&show=<limit>`.
  - Config category like `cs.AI` selects archive prefix `cs`, not strict `cs.AI` endpoint.
  - `since` is passed around but arXiv recent path is effectively guarded by DB dedupe, not strict timestamp filtering.
- Current storage:
  - `papers.archive_status` acts as a simple queue/status field.
  - Existing statuses include `metadata_only`, `queued`, `processing`, `retry_later`, `rejected_relevance`, `accepted`, `rejected_qa`, `error`.
  - There is no release batch table and no version table.
- Current pipeline:
  - `run_once()` enqueues found papers and drains all queued papers until empty or LLM budget exhausted.
  - Phase 1: parallel LLM relevance with cache keyed by hash of `title || abstract`.
  - Phase 2: parallel PDF download/extraction, summary LLM, QA LLM, quality gate.
  - `max_papers_per_run` currently behaves like queue chunk size, not strict total per-run cap.
  - `max_summary_candidates_per_run` exists in config but is not clearly enforced in the audited flow.
  - `RunBudget` uses unsynchronized `can_call()`/`record_call()` under parallel workers.
- Current Telegram behavior:
  - `run_once()` sends a short scan notification only.
  - `send_hourly_telegram()` exists but is not wired into `run_once()`.
  - `send_daily_recap(date)` sends accepted paper cards with Expand buttons, but is manual via CLI.
- arXiv operational reality from user:
  - Papers are submitted all day.
  - Public release appears as one daily large batch around 07:00-09:00 UTC+7.
  - Batch can contain roughly 1000-2000 papers.

## Constraints

- Follow `docs/opencode.md` workflow.
- Stop after final judge decision until user approves.
- Do not implement during debate.
- Keep SQLite-first unless a strong argument justifies otherwise.
- Avoid real network/API calls in unit tests.
- Do not touch secrets.
- Prefer least-invasive changes unless they would continue missing relevant papers.
- Existing deploy files mean later implementation must pass canonical harness and Docker/Podman smoke through lint subagent.

## Non-goals

- Do not redesign the entire product into a cloud service.
- Do not require external queue infrastructure.
- Do not summarize all 1000-2000 papers with LLM.
- Do not remove Telegram Expand-on-demand.
- Do not assume arXiv release timing is perfectly fixed every day.

## User Model Selection Gate

User approved Option A on 2026-06-05.

```yaml
debate:
  backend: codex-subagents/opencode-compatible
  user_selected: true
  panel:
    - role: architect
      model: opencode/deepseek-v4-flash-free
    - role: implementer
      model: opencode/mimo-v2.5-free
    - role: skeptic
      model: opencode/nemotron-3-super-free
    - role: product-operator
      model: acbpro/glm-5.1
    - role: coordinator-architect
      model: acbpro/gpt-5.5
  judge:
    role: final_decision
    model: acbpro/gpt-5.5
```

## Required Sections Per Debater

- Recommendation:
- Main argument:
- Risks:
- Testability:
- Simplicity and reuse:
- Refactor impact:
- Deployment impact:
- What would change my mind:

## Final Judge Requirements

The judge must:

- compare all panel arguments,
- identify agreements and conflicts,
- cite or summarize each model's strongest point,
- choose a decision,
- list rejected alternatives,
- list follow-up tests or experiments,
- avoid inventing evidence not present in the brief or arguments.

## User Approval Gate

The final decision does not become an implementation plan until the user approves it.

## Expected Output Files

```text
docs/workflows/debates/2026-06-05-arxiv-daily-release-update-brief.md
docs/workflows/debates/2026-06-05-arxiv-daily-release-update-architect.md
docs/workflows/debates/2026-06-05-arxiv-daily-release-update-implementer.md
docs/workflows/debates/2026-06-05-arxiv-daily-release-update-skeptic.md
docs/workflows/debates/2026-06-05-arxiv-daily-release-update-product-operator.md
docs/workflows/debates/2026-06-05-arxiv-daily-release-update-coordinator-architect.md
docs/workflows/debates/2026-06-05-arxiv-daily-release-update-final-decision.md
```
