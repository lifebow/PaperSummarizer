# Batch Pipeline Scaling — Implementer Argument

**Date:** 2026-06-04  
**Role:** Implementer  
**Model:** opencode/nemotron-3-super-free

## Recommendation

Implement a minimal viable scaling approach using ThreadPoolExecutor with 4 workers, merged summary+QA prompt, and per-thread SQLite connections. Start conservatively with cost guards and monitor before increasing complexity.

## Main argument

1. **ThreadPoolExecutor with 4 workers**: 4x throughput improvement without overwhelming the LLM API. Each worker handles the full pipeline for one paper.

2. **Merge summary+QA into single LLM call**: Reduces LLM calls from 3 to 2 per paper (33% cost reduction). Combined prompt stays under 15K char limit.

3. **Per-thread SQLite connections**: SQLite WAL mode supports concurrent reads and serialized writes. Each thread gets its own connection.

4. **Cost guards**: Add `max_papers_per_run` (default 50) and `max_llm_calls_per_run` (default 100) configs.

Code size impact: ~50 lines changed in daemon.py. Maintainability high — standard concurrency patterns, sequential logic preserved within each thread.

## Risks

1. **LLM rate limits**: Mitigation: start with 2 workers, monitor, increase gradually.
2. **SQLite write contention**: Mitigation: monitor write times, batch if needed.
3. **Prompt quality degradation**: Mitigation: test with sample papers.
4. **Memory**: Each thread holds PDF text. Mitigation: limit workers to 4-8.
5. **Error handling**: Standard futures.exception() handling.

## Testability

- Unit tests mock ThreadPoolExecutor to verify worker count
- Existing tests remain valid (per-paper logic unchanged)
- Cost guards tested with low limits
- SQLite threading tested with multiple connections

## Simplicity and reuse

- Built-in Python concurrency (ThreadPoolExecutor)
- Preserves all existing per-paper logic
- No new dependencies or architectural changes
- Merged prompt reuses 80% of existing text

## Refactor impact

- daemon.py: Add thread pool + worker function (~50 lines)
- llm.py: Add merged prompt builder
- config.py: Add cost guard parameters
- No changes to db.py, extraction.py, retrieval.py, telegram.py

## Deployment impact

- No DB migrations
- No changes to external APIs
- Config changes are additive
- Simple rollback (remove thread pool)

## What would change my mind

1. Merged prompt reduces quality >15%
2. LLM API rate limits <10 RPM
3. SQLite write contention >5s per write
4. Memory issues with concurrent PDF processing
