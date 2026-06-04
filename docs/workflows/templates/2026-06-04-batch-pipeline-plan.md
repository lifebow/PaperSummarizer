# Batch Pipeline Scaling Feature Plan

**Date:** 2026-06-04  
**Status:** Approved  
**Debate:** docs/workflows/debates/2026-06-04-batch-pipeline-scaling-final-decision.md

## Goal

Scale paper-radar daemon from sequential 20 papers/batch to parallel 100-200 papers/day with cost guards and relevance caching.

## Scope

- In scope: Two-phase parallel pipeline, relevance cache, budget guards, parallel PDF download/extract
- Out of scope: Merged summary+QA, stage abstraction, concurrent DB writes, hard keyword drop

## User Approval

- Debate decision approved: yes
- Acceptance criteria approved: yes
- Debate models selected by user: yes (pre-configured in AGENTS.md)
- Final judge model selected by user: yes

## Autonomous Subagent Execution Gate

```yaml
stages:
  - id: implement-pipeline
    runner: subagent
    model: standard
    owns:
      - paper_radar/daemon.py
      - paper_radar/config.py
      - paper_radar/db.py
      - paper_radar/llm.py
      - tests/test_pipeline_parallel.py

  - id: lint
    runner: subagent
    model: fast
    command: python3 -m ruff check .

  - id: format-check
    runner: subagent
    model: fast
    command: python3 -m ruff format --check .

  - id: regression-test
    runner: subagent
    model: fast
    command: python3 -m unittest discover -v
    depends_on:
      - lint
      - format-check

  - id: docker-smoke
    runner: subagent
    model: fast
    command: podman compose run --rm paper-radar --help
    depends_on:
      - regression-test
```

## Implementation Steps

### Step 1: Config + Budget Guard + Relevance Cache

Files changed: `config.py`, `db.py`, new `daemon.py` helpers

Config additions:
```yaml
pipeline:
  llm_concurrency: 4
  download_concurrency: 3
  max_papers_per_run: 50
  max_llm_calls_per_run: 80
  max_summary_candidates_per_run: 20
  enable_relevance_cache: true
  merge_summary_qa: false
```

DB additions:
- `relevance_cache` table: `paper_hash TEXT UNIQUE, relevance_score REAL, reason TEXT, cached_at TEXT`
- Methods: `get_cached_relevance(hash)`, `save_cached_relevance(hash, score, reason)`

New helper in daemon.py:
- `RunBudget` class: tracks `llm_calls`, `estimated_tokens`, has `can_call(estimated_tokens) -> bool`

### Step 2: Two-phase parallel pipeline

Refactor `daemon.py` `run_once()`:

Phase 1 — Relevance filtering (parallel):
1. Fetch papers from S2/arXiv
2. Deduplicate (DB check)
3. Check relevance cache
4. LLM relevance scoring via ThreadPoolExecutor(llm_concurrency)
5. Filter by threshold, cache results

Phase 2 — Summarize + QA (parallel):
1. Download PDF + extract text via ThreadPoolExecutor(download_concurrency)
2. Summary LLM → QA LLM (sequential within each paper)
3. Quality gate
4. Collect results, sort deterministic, sequential DB write

### Step 3: Counters + Logging

- Log: candidates, relevance_calls, cache_hits, summary_calls, qa_calls, skipped_by_budget, accepted_count
- Store counters in `runs` table

## Lint Before Test Gate

```bash
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m unittest discover -v
```

## Regression Gate

129 existing tests must pass. Do not delete or replace old tests.

## Commit Before Refactor Gate

```bash
git add <changed-files>
git commit -m "feat: two-phase parallel pipeline with budget guards and relevance cache"
```
