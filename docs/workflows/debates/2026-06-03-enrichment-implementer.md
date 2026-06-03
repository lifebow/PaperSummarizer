# Enrichment Pipeline - Implementer Argument

**Date:** 2026-06-03  
**Status:** Final  
**Role:** IMPLEMENTER  

## Recommendation

Ship bounded eager enrichment by reusing the existing extraction and LLM infrastructure, adding only the minimal schema tables and a thin pipeline runner — this is a 1-2 day build, not a week.

## Main argument

The enrichment pipeline is not a greenfield feature. The daily radar in `daemon.py:60-155` already runs the exact pipeline we need:

1. Download PDF → `PdfDownloader`
2. Extract text → `PdfExtractor` (PyMuPDF primary, pdfplumber fallback)
3. LLM relevance scoring → `build_relevance_prompt`
4. LLM summarization → `build_summary_prompt`
5. LLM QA gate → `build_qa_prompt` + `passes_quality_gate`
6. Record results → `db.record_result`

The archive crawler (`archive.py:48-86`) already stores papers with `archive_status="metadata_only"`. The gap is narrow: we need schema tables for enrichment outputs and a bounded runner that picks up un-enriched papers and feeds them through the existing pipeline.

The full spec's 8 new tables (`paper_versions`, `paper_texts`, `paper_embeddings`, `paper_scores`, `paper_summaries`, `enrichment_jobs`, `saved_filters`) are over-engineered for a 1-2 day delivery. The implementable scope is 3 tables:

- `paper_texts`: extracted text + introduction snippet
- `paper_summaries`: LLM summary output
- `paper_scores`: topic/quality scores

These map directly to what `daemon.py` already produces. The `enrichment_jobs` queue can be deferred — a simple `archive_status` column transition (`metadata_only` → `extracted` → `enriched`) is sufficient for bounded eager processing.

## Implementation plan (1-2 days)

### Day 1: Schema + Pipeline Runner

**Step 1 — Schema migration** (1-2 hours)

Add to `db.py._migrate_schema`:

```sql
CREATE TABLE IF NOT EXISTS paper_texts (
    paper_id INTEGER PRIMARY KEY,
    extractor_name TEXT NOT NULL DEFAULT '',
    full_text_chars INTEGER NOT NULL DEFAULT 0,
    introduction_text TEXT NOT NULL DEFAULT '',
    extraction_status TEXT NOT NULL DEFAULT 'pending',
    extraction_error TEXT NOT NULL DEFAULT '',
    extracted_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE TABLE IF NOT EXISTS paper_summaries (
    paper_id INTEGER PRIMARY KEY,
    summary_json TEXT NOT NULL DEFAULT '{}',
    model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE TABLE IF NOT EXISTS paper_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    score_kind TEXT NOT NULL,
    score_value REAL NOT NULL DEFAULT 0,
    reason_json TEXT NOT NULL DEFAULT '{}',
    model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_paper_scores_kind ON paper_scores(score_kind);
CREATE INDEX IF NOT EXISTS idx_paper_scores_paper ON paper_scores(paper_id);
```

Add `upsert_paper_text`, `upsert_paper_summary`, `insert_paper_score` methods to `PaperRadarDb`.

**Step 2 — Introduction extraction** (2-3 hours)

Add `extract_introduction(text: str) -> str` to `extraction.py`. Simple regex-based section detection:

1. Find heading matching `Introduction` or `1 Introduction`
2. Grab text until next major heading (`Related Work`, `Background`, `Method`, `Preliminaries`, `\d+\s+\w+`)
3. Fallback: first 3000 chars of body text

This is exactly what the spec recommends and it's ~30 lines of code.

**Step 3 — Enrichment pipeline runner** (3-4 hours)

New file `paper_radar/enrichment.py` with class `ArchiveEnricher`:

```python
class ArchiveEnricher:
    def __init__(self, db, config, downloader, extractor, llm):
        ...

    def run_batch(self, limit: int = 50) -> EnrichmentResult:
        """Pick un-enriched papers, download, extract, summarize, score."""
        # SELECT papers WHERE archive_status = 'metadata_only' LIMIT ?
        # For each paper:
        #   1. Download PDF
        #   2. Extract text + introduction
        #   3. Store in paper_texts
        #   4. Run LLM summary + QA scores
        #   5. Store in paper_summaries and paper_scores
        #   6. Update archive_status to 'enriched'
        # Cleanup PDF
```

Key design decisions:
- Uses `process_pdf_with_cleanup` from `extraction.py` (existing pattern)
- Reuses `build_summary_prompt`, `build_qa_prompt`, `passes_quality_gate` from `llm.py`
- Configurable via `FilterConfig` (max_papers_per_batch already exists)
- No new queue table — just `archive_status` transitions
- Bounded by `limit` parameter (default 50, configurable)

**Step 4 — CLI command** (1 hour)

Add `paper-radar enrich` subcommand to `cli.py`:

```
paper-radar enrich [--limit 50] [--dry-run]
```

This gives immediate testability without touching the daemon loop.

### Day 2: Tests + Integration

**Step 5 — Unit tests** (3-4 hours)

Test categories per the workflow template:

- Happy path: enrich a paper with mock PDF download, mock extraction, mock LLM
- Edge: paper with no PDF URL, extraction too short, LLM timeout
- Niche: introduction detection with unusual heading formats, fallback text
- Invalid: missing arxiv_id, empty abstract
- Failure: PDF download fails, extraction raises, LLM returns malformed JSON
- Backward compatibility: existing `run_once` still works, archive_search still works
- Refactor safety: public behavior of `PaperRadarDb`, `PdfExtractor`, `LlmClient` unchanged

**Step 6 — Integration wiring** (1-2 hours)

Wire `ArchiveEnricher` into daemon's `watch` loop as optional post-crawl step:

```python
if self.config.enrichment.enabled:
    enricher.run_batch(limit=self.config.enrichment.batch_limit)
```

Add `EnrichmentConfig` dataclass to `config.py`:

```python
@dataclass(frozen=True)
class EnrichmentConfig:
    enabled: bool = True
    batch_limit: int = 50
```

## Testability

The entire pipeline is testable without real APIs because:

- `PdfDownloader` accepts mock downloaders (already done in `tests/`)
- `PdfExtractor` accepts callable extractors (already parameterized)
- `LlmClient` accepts callable `http_post` (already used in tests)
- `PaperRadarDb` is pure SQLite (already tested with temp files)

The introduction extraction is pure string processing — trivially unit-testable.

New tests fit the existing `unittest` framework. No new test infrastructure needed.

Estimated test count: 15-20 new test cases covering the 7 categories above.

## What would change my mind

1. **If the existing pipeline is fundamentally incompatible with archive papers.** I checked — `daemon.py:60-155` works on any paper record with `title`, `abstract`, and `pdf_url`. Archive papers already have these fields. No incompatibility.

2. **If introduction extraction is harder than it looks.** The spec's simple heading-matching approach covers 80%+ of CS papers. The fallback to bounded-prefix keeps the remaining cases covered. This is not a blocker.

3. **If bounded eager is too expensive at scale.** The `limit` parameter and `archive_status` transitions make this trivially adjustable. If 50 papers/batch is too much, drop to 10. If too slow, increase. The cost is bounded by design.

4. **If the team wants filtered lazy instead.** I'd adjust the `WHERE` clause to filter by `primary_category` or a broad topic match before enrichment. The pipeline code is identical — only the selection query changes. This is a config change, not an architecture change.

5. **If we actually need the full `enrichment_jobs` queue now.** We don't. The bounded eager model with `archive_status` transitions is simpler, sufficient, and ship-ready. The queue becomes relevant only when we need retry with backoff, priority ordering, or distributed processing. None of those are current requirements.
