# Enrichment Pipeline — Final Decision

**Date:** 2026-06-03  
**Role:** Final Judge  
**Panel:** Architect, Skeptic, Implementer  

## Summary of Agreements

All three models agree on these points:

- **Bounded eager is the right starting mode** — none recommends unbounded eager or filtered lazy as the first step.
- **SQLite is the storage layer** — no model proposes moving to a different database.
- **The existing daemon pipeline is reusable** — the Architect, Implementer, and implicitly the Skeptic acknowledge that `daemon.py` already implements download → extract → score → summarize.
- **Saved filters should be deferred** — the Architect explicitly defers `saved_filters`, and no model argues for it now.
- **Paper versions tracking can wait** — the `paper_versions` table is acknowledged as useful but not needed for v1.

## Summary of Conflicts

| Topic | Architect | Skeptic | Implementer |
|---|---|---|---|
| Scope | Full schema: 6 tables + job queue | Extraction columns only, no embeddings/scores/summaries/job queue | 3 tables: `paper_texts`, `paper_summaries`, `paper_scores` |
| Job queue | First-class `enrichment_jobs` table | Replace with a simple loop counter | Defer queue; use `archive_status` transitions |
| Embeddings | Include `paper_embeddings` with content-hash uniqueness | Skip entirely | Skip entirely |
| Introduction detection | Part of extraction | Untested NLP problem, likely dead code | Simple regex, ~30 lines, 80%+ coverage on CS papers |
| Cost control | Implicit via queue rate limits | Demands explicit $/month budget | Bounded by `limit` parameter (default 50) |
| When to build | Now | After a query consumer exists | Now, as a 1-2 day build |

## Each Model's Strongest Point

**Architect** — The state-machine design for `archive_status` and the argument that the queue is a configuration overlay (not a new system) is architecturally sound. The point about `paper_texts.paper_id` being `PRIMARY KEY` (one extraction per paper) is the correct semantic.

**Skeptic** — The observation that "the archive has zero consumers" is the single most important fact in this debate. Building embedding and scoring infrastructure before a query consumer exists is speculative. The cost concern (LLM calls per paper at scale) is also valid and unaddressed by the other two models.

**Implementer** — The concrete 1-2 day plan with specific file locations, function signatures, and step ordering is the most actionable argument. The claim that bounded eager is trivially adjustable via the `limit` parameter directly addresses the Skeptic's cost concern without requiring a full budget framework.

## Decision

**Adopt the Implementer's plan with the Skeptic's scope constraint and the Architect's schema refinements.**

Build phase 1 with these boundaries:

### What to build

1. **Schema migration** — `paper_texts`, `paper_summaries`, `paper_scores` tables only. No `enrichment_jobs`, no `paper_embeddings`, no `paper_versions`, no `saved_filters`. The Architect's refinement of `paper_texts.paper_id` as `PRIMARY KEY` is correct and should be adopted.

2. **Introduction extraction** — `extract_introduction()` in `extraction.py` with heading regex + bounded-prefix fallback. This is ~30 lines. The Skeptic's concern about accuracy is valid, but the fallback ensures no silent quality loss. Measure accuracy later against real papers.

3. **Enrichment runner** — `ArchiveEnricher` in a new `enrichment.py` file. Reuses `process_pdf_with_cleanup`, `build_summary_prompt`, `build_qa_prompt`, and `passes_quality_gate` from existing modules. Bounded by a `limit` parameter. No job queue — use `archive_status` transitions (`metadata_only` → `extracted` → `enriched`).

4. **CLI command** — `paper-radar enrich [--limit N] [--dry-run]` for immediate manual testing.

5. **Config** — `EnrichmentConfig` dataclass with `enabled: bool` and `batch_limit: int`.

6. **Tests** — 15-20 unit tests covering happy path, edge cases, introduction detection, extraction failures, LLM failures, and backward compatibility with existing `run_once`.

### What to defer

| Item | Defer until |
|---|---|
| `enrichment_jobs` queue | Retry/backoff or distributed processing is needed |
| `paper_embeddings` table | A query consumer that uses vector search exists |
| `paper_versions` table | Version tracking is a stated user requirement |
| `saved_filters` table | Query CLI is implemented |
| Cost budget framework | LLM enrichment runs for more than 1 week at scale |
| Accuracy measurement of introduction detection | After 100+ real papers are enriched |

### Migration path

The Architect's concern about `paper_results` becoming stale is real. The migration should:

1. Add the 3 new tables.
2. Mark `paper_results.extracted_text_chars` as deprecated in comments.
3. Route new extraction state through `paper_texts`.
4. Keep `paper_results` for daily radar run scoring (it still serves that purpose).

### Cost guard

The Implementer's `limit` parameter is sufficient for now. Add a log line per batch that reports: papers processed, LLM calls made, PDF bytes downloaded. This gives visibility without a budget framework. If costs are concerning after a week of operation, add a configurable `max_llm_calls_per_batch` cap.

## Rejected Alternatives

**Reject: Full 6-table schema (Architect)** — Over-engineered for day 1. The job queue, embeddings, and versions tables have no consumers. Build them when consumers exist.

**Reject: Extraction columns only on `papers` table (Skeptic)** — Too minimal. Separate tables for `paper_texts` and `paper_summaries` are the correct normalization. Mixing extracted text into the `papers` table creates a wide-row problem and makes it harder to add embeddings later without a schema rewrite.

**Reject: Filtered lazy mode** — The Architect correctly notes this is a config change on top of the same queue. Defer until query demand shows which filters matter.

**Reject: LLM scoring/summaries on every paper** — The Implementer includes `paper_summaries` and `paper_scores` in the build plan, but these should be optional. The first priority is extraction (text + introduction). LLM scoring can be gated behind a `--with-llm` flag or a config toggle. This reduces cost while still building the storage layer for when scoring is enabled.

## Implementation Scope

| Priority | Deliverable | Est. time |
|---|---|---|
| P0 | Schema migration (3 tables) | 1-2 hours |
| P0 | `extract_introduction()` | 2-3 hours |
| P0 | `ArchiveEnricher.run_batch()` | 3-4 hours |
| P0 | `paper-radar enrich` CLI | 1 hour |
| P0 | Unit tests (15-20 cases) | 3-4 hours |
| P1 | Daemon integration (optional post-crawl step) | 1 hour |
| P1 | `EnrichmentConfig` dataclass | 30 min |
| P2 | LLM scoring/summaries as opt-in | 2-3 hours |

Total P0 estimate: 10-14 hours (1-2 days).  
P1 adds 1.5 hours.  
P2 defers to after extraction is validated on real papers.

---

This decision synthesizes the Implementer's actionable plan, the Skeptic's scope discipline, and the Architect's schema quality into a single buildable path. The key principle: **build extraction first, score later, embed when consumers exist**.
