# Batch Pipeline Scaling Debate Brief

**Date:** 2026-06-04  
**Status:** Draft  
**Backend:** opencode  

## Question

How should the paper-radar daemon pipeline scale from 10-20 papers/hour to 100-200 papers/day while controlling LLM cost and latency?

## Context

- **Project:** paper-radar — hourly arXiv/S2 paper radar with LLM summaries, daily Markdown digests, Telegram recaps
- **Current behavior:** Sequential pipeline processes 1 paper at a time. For each paper: 3 LLM calls (relevance → summary → QA), download PDF, extract text, write DB, send Telegram. ~30s/paper.
- **Constraint:** User expects 10-20 papers/hour matching topics, potentially 100-200 papers/day across all topics.
- **LLM endpoint:** OpenAI-compatible API with unknown rate limits. Payload limit ~15K chars of text per call (413 errors above that).
- **DB:** SQLite with WAL mode. Thread-safe for reads, needs serialized writes or connection-per-thread.
- **Cost:** Each LLM call costs money. 100 papers × 3 calls = 300 calls/day. At scale this could be expensive.
- **Current test suite:** 129 tests, all pass. Must stay green.
- **Non-goals:** Switching away from SQLite, changing the Telegram UX, changing the digest format.

## User Model Selection Gate

```yaml
debate:
  backend: opencode
  user_selected: true
  panel:
    - role: architect
      model: opencode/deepseek-v4-flash-free
    - role: skeptic
      model: opencode/mimo-v2.5-free
    - role: implementer
      model: opencode/nemotron-3-super-free
    - role: performance
      model: acbpro/glm-5.1
    - role: cost-analyst
      model: acbpro/gpt-5.5
  judge:
    role: final_decision
    model: acbpro/gpt-5.5
```

## Proposed Approach (for debate)

1. **Parallel processing:** Use `concurrent.futures.ThreadPoolExecutor` with configurable concurrency (default 4-8 workers)
2. **Merged summary+QA prompt:** Combine 2 LLM calls (summary + QA) into 1 call to halve cost
3. **Two-phase pipeline:** Phase 1 = parallel relevance scoring (cheap), Phase 2 = parallel summarize+QA (expensive, only for passing papers)
4. **Cost guards:** `max_papers_per_run`, `max_llm_calls_per_run` config limits
5. **SQLite thread safety:** One connection per thread (SQLite WAL supports concurrent reads, serialized writes)

## Questions for Debaters

1. Should we merge summary+QA into one LLM call (saves cost, but prompt is larger and might reduce quality)?
2. What is the right concurrency level for LLM API calls without hitting rate limits?
3. Should we add a keyword pre-filter before LLM relevance scoring (e.g., check abstract for topic keywords)?
4. How should we handle the SQLite write contention with multiple threads?
5. Should relevance scoring be cached per paper so re-runs don't re-score already-seen papers?
6. What is the right `max_llm_calls_per_run` default for cost control?
7. Should the pipeline prioritize recent papers or random/unordered?

## Independent Arguments

Each debate model must write independently. Do not show one model another model's argument until all first-pass arguments are complete.

Required sections per debater:

- Recommendation
- Main argument
- Risks
- Testability
- Simplicity and reuse
- Refactor impact
- Deployment impact
- What would change my mind

## Final Judge

The final judge uses `acbpro/gpt-5.5`.

The judge must:

- compare all panel arguments
- identify agreements and conflicts
- cite or summarize each model's strongest point
- choose a decision
- list rejected alternatives
- list follow-up tests or experiments
- avoid inventing evidence not present in the brief or arguments

## User Approval Gate

The final decision does not become a plan until the user approves it.

## Output Files

```text
docs/workflows/debates/2026-06-04-batch-pipeline-scaling-brief.md
docs/workflows/debates/2026-06-04-batch-pipeline-scaling-architect.md
docs/workflows/debates/2026-06-04-batch-pipeline-scaling-skeptic.md
docs/workflows/debates/2026-06-04-batch-pipeline-scaling-implementer.md
docs/workflows/debates/2026-06-04-batch-pipeline-scaling-performance.md
docs/workflows/debates/2026-06-04-batch-pipeline-scaling-cost-analyst.md
docs/workflows/debates/2026-06-04-batch-pipeline-scaling-final-decision.md
```
