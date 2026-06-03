# Historical Crawl — Architect Argument

**Date:** 2026-06-03  
**Role:** ARCHITECT  
**Status:** Draft  

## Recommendation

Use the existing HybridRetriever with a new archival crawl mode that writes directly into the expanded schema tables, keeping `papers` as the single canonical identity table and adding version tracking and enrichment job queues as first-class citizens.

## Main argument

The current system already has the right bones. `HybridRetriever.search_recent` merges S2 and arXiv into `PaperMetadata` objects, and `PaperRadarDb.upsert_paper` writes them. The historical crawl does not need a different architecture — it needs a different *mode* of the same architecture.

### Data source strategy

Semantic Scholar's bulk search API (`/graph/v1/paper/search/bulk`) supports date-range filters and pagination via cursor tokens. arXiv's Atom API supports `sortBy=submittedDate` and `max_results` pagination. Both are sufficient for 1-5 year backfill.

**Primary source: Semantic Scholar bulk search**, queried by year ranges (`publicationDateOrYear=2021:2022`), paginated through cursor tokens. S2 has richer metadata (field of study, citation counts, TLDR) and avoids arXiv's strict 3-second rate limit.

**Secondary source: arXiv Atom API**, used to fill gaps where S2 lacks an arXiv ID or where we want authoritative category metadata. arXiv should be queried by category (e.g., `cat:cs.AI`) with date-sorted pagination.

The existing `HybridRetriever` already handles merge logic. For archival crawl, we bypass the `search_recent` query-based path and add a `search_by_date_range` method that takes date bounds and categories instead of free-text queries.

### Schema proposal

The expanded spec's schema is sound. Here are my architectural refinements:

**`papers` — keep as-is from the spec.** The `archive_status` column is the key addition over the current schema. Values: `pending`, `metadata_only`, `enriched`, `failed`. This replaces the current `last_status`/`last_error` columns (which are per-run artifacts, not per-paper state). The current schema conflates "last run outcome" with paper identity — the expanded schema correctly separates them.

**Add `primary_category TEXT`** as a top-level column, not just inside `categories_json`. This enables efficient category-prefix queries (`cs.AI`, `cs.LG`) without parsing JSON on every filter.

**`paper_versions` — essential, not optional.** arXiv papers get revised. The current `upsert_paper` silently overwrites title, abstract, and dates. For a historical archive this is wrong: version 2 of a paper has a different abstract than version 1, and both are historically interesting. `paper_versions` with `(paper_id, arxiv_version)` as the unique key preserves this history. The `papers` table always holds the latest version; `paper_versions` holds the timeline.

**`paper_texts` — file-backed, not inline.** Storing full text in SQLite bloats the DB and makes backups painful. Store `full_text_path` (relative to a configured `text_dir`) and keep `introduction_text` inline in SQLite since it is bounded (typically 500-2000 chars). The `extraction_status` column (`pending`, `extracting`, `done`, `failed`) ties directly into the enrichment queue.

**`paper_embeddings` — defer but plan for it now.** The spec's non-goals say no vector DB in v1, but the schema should still have the `paper_embeddings` table so that when embeddings land, they slot in without migration. The `embedding_input_hash` column is critical: when extraction logic changes, old embeddings become stale and must be recomputed. The hash detects this.

**`paper_scores` and `paper_summaries` — keep separate from `paper_results`.** The current `paper_results` table mixes per-run scoring with paper identity. The expanded schema correctly separates `paper_scores` (topic relevance, quality scores tied to the paper) from `paper_summaries` (LLM-generated summaries tied to the paper). `paper_results` remains for the daily radar's run-specific acceptance decisions.

**`enrichment_jobs` — the right abstraction for a crawl worker.** A queue table with `job_type`, `status`, `attempt_count`, `run_after`, and `last_error` is a standard SQLite work queue pattern. It supports: bounded concurrency (limit active jobs), retry with backoff (`run_after`), error tracking, and multiple job types (extract, embed, summarize, score) without separate tables per job type.

**`saved_filters` — defer implementation but define the schema.** The `filter_json` column stores a structured query definition. This is the foundation for the CLI `archive search` commands. Define the table now; implement the query executor later.

### Pagination and rate-limit approach

The architectural concern here is **checkpoint-resumability**. A 5-year backfill will take many runs. The system must survive crashes and restarts without re-fetching data it already has.

**Strategy:**

1. Store the last successfully processed cursor/date in `state` table (`key = 'archive_crawl_cursor'`).
2. On each crawl run, resume from the stored cursor.
3. Each paper upsert is idempotent (INSERT OR REPLACE on `arxiv_id`), so re-fetching a paper that was already stored is harmless — it just updates the latest version.
4. Rate limiting: S2 allows 1 req/sec with API keys, 100 req/sec with bulk token. arXiv requires 3-second gaps. Implement a `RateLimiter` class with configurable requests-per-second and per-source limits. Store rate-limit state in the `state` table so that restarts do not burst.

**Why cursor-based, not date-shard-based:** Date-sharding (crawl 2021, then 2022, ...) creates gaps if a run crashes mid-year. Cursor-based pagination through the API's own ordering means we always resume exactly where we left off.

### Storage decisions

**Keep:** metadata (all fields from S2/arXiv), `paper_versions` history, `introduction_text`, enrichment job state, scores, summaries.

**Skip:** full PDFs, raw HTML, raw API payloads (except compact `source_payload_json` in `paper_versions` for debugging).

**Why skip full text in SQLite:** A 5-year CS archive is roughly 500K-1M papers. Full text per paper is 5K-20K chars. Storing inline would be 5GB-20GB in SQLite. File-backed storage with a `text_dir` keeps SQLite lean while preserving the data.

### Incremental enrichability

The enrichment pipeline is the right abstraction. Each paper enters the system as metadata-only, then progresses through stages:

```
metadata_only -> extraction -> intro_detection -> embedding_input -> scoring -> summarized
```

Each stage writes to its own table (`paper_texts`, `paper_embeddings`, `paper_scores`, `paper_summaries`) and updates the `enrichment_jobs` queue. The daily radar can query papers at any enrichment stage. A paper does not need to be fully enriched to be useful — it just needs metadata and an abstract for basic search.

The `enrichment_jobs.run_after` column enables retry with exponential backoff without a separate retry scheduler. The worker simply queries `SELECT * FROM enrichment_jobs WHERE status='pending' AND run_after <= now ORDER BY created_at LIMIT N`.

### How existing daily radar integrates

The daily radar remains a *consumer* of the archive, not the owner of ingestion. When a new paper is fetched by the daily radar, it goes through the same `upsert_paper` path into the archive. The `paper_results` table still tracks per-run acceptance for digests. The archive and the daily radar share the `papers` table but diverge on enrichment: the radar does lightweight scoring; the archive does deep extraction and embedding.

No changes needed to `DigestRenderer` or `TelegramSender`. They read from `paper_results` + `papers`, which remain stable.

## Risks

1. **SQLite write contention during concurrent crawl + daily radar.** SQLite handles this fine with WAL mode, but the code must set `PRAGMA journal_mode=WAL` on connection. The current `_connect()` does not do this. Fix it before starting archival work.

2. **S2 bulk API cursor tokens may expire.** If a crawl run is interrupted for days, the cursor may become invalid. Mitigation: store the cursor along with a timestamp, and if the cursor is stale ( > 7 days), fall back to date-range queries from the last known good date.

3. **Schema migration complexity.** The expanded schema adds 7 tables. The current `initialize()` method uses `CREATE TABLE IF NOT EXISTS`, which works for greenfield but not for adding columns to existing tables. Need a migration strategy: either a `schema_version` integer in `state` and an `ALTER TABLE` path, or a clean `CREATE TABLE IF NOT EXISTS` for each new table (which works since these tables do not exist yet). For the `papers` table itself, the new `primary_category` and `archive_status` columns require `ALTER TABLE ... ADD COLUMN`. Plan this.

4. **arXiv rate limits during bulk backfill.** 3 seconds per request × 500K papers = 17 days of pure arXiv crawling. S2 bulk is much faster. Recommendation: use S2 as primary for bulk backfill, arXiv only for gap-filling and category enrichment.

5. **Data model drift.** If the daily radar schema (`paper_results`) and the archive schema (`paper_scores`, `paper_summaries`) diverge too much, maintaining both becomes painful. The long-term path is to route daily radar scoring through `paper_scores` and retire the per-run score columns in `paper_results`. This is a refactor, not a blocker.

## What would change my mind

- **If the user decides full text storage is needed in SQLite** (not file-backed), I would accept it with a size warning and a WAL-mode pragma, but I would argue for an optional `full_text_inline INTEGER` flag per paper to keep the option open.

- **If S2 bulk search does not support cursor pagination for historical ranges** (only for recent papers), I would switch to date-sharded crawling with idempotent upserts. The schema stays the same; only the crawl loop changes.

- **If the user decides embeddings are needed now** (not deferred), I would add the `paper_embeddings` table in the first migration and implement a simple cosine-similarity search in Python. It works for <100K papers. Beyond that, we need a vector index, which means DuckDB or an external service.

- **If another debater convincingly argues that the enrichment queue adds too much complexity for v1**, I would accept a simpler approach: crawl metadata in one pass, then a separate `enrich` command that processes all pending papers. No queue table, just a status column on `papers`. This is less flexible but simpler, and may be right for a v1 that only does metadata + abstract search.
