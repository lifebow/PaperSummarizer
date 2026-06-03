# Historical Crawl Skeptic Argument

**Date:** 2026-06-03  
**Status:** Ready  
**Role:** Skeptic  

## Recommendation

Do not build a historical crawl feature right now — the project is a daily radar with 31 passing tests and no confirmed user need for 1–5 years of backfilled papers; adding crawl + enrichment infrastructure now risks turning a working tool into an unmaintained data-pipeline experiment.

## Main Argument

The current paper_radar is a focused daily workflow: fetch, filter, summarize, digest, send. It works. The spec proposes expanding it into a multi-table, multi-job, multi-enrichment-state archive that crawls millions of papers across years of CS publications. This is not a feature addition — it is a platform pivot.

The existing codebase is small and coherent. `retrieval.py` makes two API calls. `db.py` has five tables. `daemon.py` runs a single loop. The proposed archive adds seven new tables (`paper_versions`, `paper_texts`, `paper_embeddings`, `paper_scores`, `paper_summaries`, `enrichment_jobs`, `saved_filters`), a crawl scheduler, pagination logic, rate-limit management, PDF download orchestration, text extraction pipeline, introduction detection, and enrichment job retry logic. This is a 5–10x increase in surface area for a project that has never been deployed to production.

The user said "1–5 years of papers." Semantic Scholar has rate limits. arXiv has rate limits. Even with pagination, crawling 1–5 years of CS papers means processing hundreds of thousands to millions of entries. The cost of API calls, the time to crawl, the storage for extracted text, and the maintenance burden of a retry-capable enrichment queue are all non-trivial and untested. There is no evidence the user will actually run this crawl to completion, or that they need the full archive rather than, say, the last 6 months.

The spec pauses at a key decision — eager, bounded eager, or filtered lazy enrichment — which means the core design is not settled. Building infrastructure on top of an unsettled design is how projects accumulate dead code.

## Risks

**Scope creep into a data platform.** The spec's enrichment pipeline (download PDF, extract text, detect introduction, build embedding input, summarize, score) is a production data pipeline. Each step has failure modes. The current project has no job queue, no retry logic, no rate-limit backoff beyond a 3-second sleep on arXiv. Introducing all of this at once is a large integration risk.

**SQLite at scale.** The spec proposes storing hundreds of thousands of papers with extracted text, embeddings, and enrichment state in SQLite. SQLite works for this size, but only with careful schema design. The current schema has no indexes beyond the unique `arxiv_id` constraint. The proposed schema needs 10+ new indexes. Without migration tooling, upgrading an existing database will be fragile.

**API cost and rate limits.** Semantic Scholar free tier allows 1 request/second with API key, or 100 requests/5 minutes without. arXiv allows 1 request/3 seconds. Crawling 3 years of CS papers at even 100K papers requires ~28 hours of Semantic Scholar time (with pagination), or ~83 hours through arXiv alone. The user may not have a Semantic Scholar API key, and the free tier is restrictive.

**Dead code accumulation.** The spec describes features (vector embeddings, saved filters, introduction detection, score kinds) that are explicitly non-goals for the first version but are baked into the schema. Tables that exist but are never populated become schema debt. The current `papers` table already has `last_status` and `last_error` columns that appear unused in the codebase.

**No user validation.** The user asked for this feature, but there is no confirmed use case beyond "which papers relate to X?" That query can be answered with `LIKE` on title/abstract for the existing daily papers. A full historical crawl is solving a problem that may not exist yet.

**Existing daily radar breakage.** The spec says "must not break existing daily radar/digest flow," but the changes to `db.py` (new schema, new upsert logic, version tracking) will touch the core data path. The existing `upsert_paper` method and `accepted_results_for_date` query will need updating. This is high-risk refactor territory.

## Simplicity and Reuse

The current codebase is simple by design. `retrieval.py` has 297 lines. `db.py` has 267 lines. `daemon.py` orchestrates a single loop. The proposed archive doubles or triples this with new modules for crawl scheduling, enrichment workers, job queues, and query interfaces.

Reuse is minimal. The existing `HybridRetriever` works for recent papers with a `since` parameter. Historical crawl needs pagination, cursor-based iteration, and date-range batching — a different control flow entirely. The existing `PdfDownloader` works one paper at a time in a temp directory. The archive needs persistent download tracking and cleanup. These are not the same code paths.

The simplest viable path is: add `published_at` index to the existing `papers` table, write a one-off script that paginates through Semantic Scholar's bulk search API for historical dates, and store results in the same `papers` table with a source marker. No new tables. No enrichment pipeline. No job queue. This gets the user a browsable historical list in a day of work, not a week.

## What Would Change My Mind

1. **Confirmed use case with volume.** If the user can articulate a specific query they need answered that requires 100K+ papers and cannot be answered by the daily radar alone, the archive becomes justified.

2. **Successful MVP crawl.** If the user runs a small historical crawl (say, 1 month of papers) and confirms the results are useful, that de-risks the full 1–5 year crawl.

3. **Simplified schema.** If the spec drops `paper_embeddings`, `paper_scores`, `paper_summaries`, and `enrichment_jobs` from the first version and only adds `paper_versions` and `paper_texts` (metadata + extracted intro), the scope becomes manageable.

4. **Existing tests still pass after first changes.** If the first PR — even just adding the crawl script — does not break the 31 existing tests, I would be less concerned about refactor risk.

5. **User confirms they will run the crawl.** If the user says "I will run this tonight and let you know what happens," that is different from "let's build infrastructure for a crawl I might run someday."
