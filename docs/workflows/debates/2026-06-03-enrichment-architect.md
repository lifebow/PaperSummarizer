# Enrichment Pipeline — Architect Argument

**Date:** 2026-06-03  
**Role:** Architect  
**Focus:** Long-term system design, schema evolution, data model correctness

## Recommendation

Adopt bounded eager enrichment as the operational mode, but design the schema
and pipeline around an explicit state machine with typed enrichment jobs, so the
system can evolve toward filtered lazy or hybrid modes without a rewrite.

## Main argument

The current schema is flat and single-run: `papers` holds metadata,
`paper_results` mixes run-specific scoring with extraction state, and there is
no queue concept. This works for a daily radar but collapses when enrichment
becomes a continuous, multi-step process across thousands of papers.

The right architectural unit is not a "run" but a **paper lifecycle**. Each
paper enters at `metadata_only`, transitions through `extracted`, `embedded`,
and optionally `scored`/`summarized` states, and the pipeline processes batches
within rate and budget constraints. The state machine is implicit in the
enrichment_jobs table — a paper with all jobs in `done` state is fully
enriched; a paper with jobs in `pending` or `failed` state needs attention.

Three architectural principles should guide the schema:

1. **Separate identity from enrichment state.** The `papers` table should hold
   only identity and latest metadata. All derived state (text, embeddings,
   scores, summaries) lives in dedicated tables with foreign keys. This keeps
   the hot path (metadata upserts) fast and avoids UPDATE-heavy contention on
   the main table.

2. **Enrichment artifacts are versioned by content hash, not by run.** An
   embedding record should be keyed by `(paper_id, embedding_model,
   embedding_input_hash)`. When a paper's abstract or introduction changes, the
   old embedding is stale and a new one is created. This prevents silent
   corruption and makes reprocessing safe without a global re-embed.

3. **The queue is first-class.** `enrichment_jobs` is not an afterthought — it
   is the central coordination point. Each job type (`extract_pdf`,
   `embed_title_abstract_intro`, `summarize`, `score_topics`) is a separate
   row. The worker picks the next eligible job respecting rate limits and
   `run_after` timestamps. This makes bounded eager trivial (just set
   `max_jobs_per_hour`), enables filtered lazy later (skip embed jobs unless a
   filter matches), and supports retry/backoff without special-case logic.

The bounded eager mode is the correct starting point because it builds uniform
coverage without pathological single-run costs. The schema should not enforce
the mode — the mode is a configuration overlay on the same queue.

## Schema proposal

### Changes to existing `papers` table

Keep existing columns. Add:

```sql
ALTER TABLE papers ADD COLUMN archive_status TEXT DEFAULT 'metadata_only';
```

This column already exists via migration. Its allowed values should become an
enum: `metadata_only`, `extracted`, `embedded`, `enriched`, `failed`. The
enrichment worker updates this as a denormalized summary of the paper's
deepest completed stage, for fast filtering in queries.

Remove `last_status` and `last_error` from `papers` — those belong on
`enrichment_jobs`.

### New tables (from the spec, refined)

```sql
CREATE TABLE paper_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    arxiv_version TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    abstract TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    source_payload_json TEXT NOT NULL DEFAULT '{}',
    seen_at TEXT NOT NULL,
    FOREIGN KEY(paper_id) REFERENCES papers(id),
    UNIQUE(paper_id, arxiv_version)
);

CREATE TABLE paper_texts (
    paper_id INTEGER PRIMARY KEY,
    extractor_name TEXT NOT NULL DEFAULT '',
    full_text_path TEXT NOT NULL DEFAULT '',
    full_text_chars INTEGER NOT NULL DEFAULT 0,
    introduction_text TEXT NOT NULL DEFAULT '',
    introduction_chars INTEGER NOT NULL DEFAULT 0,
    extraction_status TEXT NOT NULL DEFAULT 'pending',
    extraction_error TEXT NOT NULL DEFAULT '',
    extracted_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE TABLE paper_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_input_kind TEXT NOT NULL DEFAULT 'title_abstract_intro',
    embedding_input_hash TEXT NOT NULL,
    embedding_vector BLOB NOT NULL,
    dimensions INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(paper_id) REFERENCES papers(id),
    UNIQUE(paper_id, embedding_model, embedding_input_hash)
);

CREATE TABLE paper_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    score_kind TEXT NOT NULL,
    score_value REAL NOT NULL DEFAULT 0,
    reason_json TEXT NOT NULL DEFAULT '{}',
    model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(paper_id) REFERENCES papers(id),
    UNIQUE(paper_id, score_kind, model)
);

CREATE TABLE paper_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    model TEXT NOT NULL DEFAULT '',
    input_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(paper_id) REFERENCES papers(id),
    UNIQUE(paper_id, model, input_hash)
);

CREATE TABLE enrichment_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    run_after TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX idx_enrichment_jobs_status_type
    ON enrichment_jobs(status, job_type, run_after);
CREATE INDEX idx_enrichment_jobs_paper
    ON enrichment_jobs(paper_id, job_type);
```

Key refinements over the spec:

- `paper_texts.paper_id` is `PRIMARY KEY` (one text record per paper, updated
  in place) rather than a separate id. A paper has one extraction, not many.
- `enrichment_jobs` gets a composite index on `(status, job_type, run_after)`
  so the worker's SELECT-next-job query is fast even with millions of rows.
- `paper_scores` and `paper_summaries` have content-hash uniqueness to prevent
  duplicate generation when the same input produces the same output.

### `saved_filters` — defer

The spec includes `saved_filters` but this is a query-layer concern, not an
enrichment concern. It should be added when the query CLI is implemented, not
as part of the enrichment pipeline.

## Risks

**Schema drift between MVP and enrichment.** The current `paper_results` table
doubles as enrichment state and scoring. If the new schema lands alongside it
without removing old columns, we get two sources of truth for "has this paper
been extracted?" The migration must deprecate `paper_results.extracted_text_chars`
and route new extraction state through `paper_texts`.

**BLOB embeddings in SQLite.** Storing vectors as BLOBs works for tens of
thousands of papers but degrades at hundreds of thousands with cosine-similarity
scans. This is acceptable for the bounded eager phase because the primary
query path is score-filtered (use `paper_scores` to find candidates, then
embed for re-ranking). If vector search becomes the primary path, migrate
embeddings to a dedicated store — but that decision should be deferred.

**Job queue starvation.** Bounded eager means the worker picks the next job
regardless of category. If one category dominates the archive, it consumes the
entire budget. The schema supports per-category quotas via a view or a
`category` column on `enrichment_jobs`, but adding it now is premature. Keep
the simple rate limit and observe.

**State machine drift.** The `archive_status` denormalized column can fall out
of sync if a job completes but the status update fails. The worker must
atomically mark the job done and update `archive_status` in the same
transaction. This is straightforward but must be tested.

## What would change my mind

1. **If the user's query pattern is always recency-based.** If the only
   meaningful query is "papers from the last N days," then building a full
   enrichment pipeline is over-engineering. A simpler daily digest with a
   rolling window would suffice. I would switch to a simpler design if the user
   confirms they never want cross-archive semantic search.

2. **If the user wants filtered lazy.** If the user prefers to only enrich
   papers matching specific topic filters (e.g., only `cs.AI` + safety
   keywords), the schema stays the same but the job creation logic changes
   fundamentally — we would not enqueue embed jobs for every paper. I would
   change my recommendation if filtered lazy is chosen, though the schema itself
   does not need modification.

3. **If SQLite write contention becomes measurable.** If concurrent harvest and
   enrichment workers cause WAL contention or lock timeouts, the architecture
   shifts toward a producer-consumer model with a separate WAL or a write-ahead
   staging table. I would revisit the single-database architecture only if
   benchmarks show contention above 5% of run time.
