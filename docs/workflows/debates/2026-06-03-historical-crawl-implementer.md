# Historical Crawl - Implementer Argument

**Date:** 2026-06-03  
**Status:** Final  
**Role:** Implementer

## Recommendation

Build a minimal, single-module `historical.py` that reuses the existing `ArxivClient`, `SemanticScholarClient`, and `PaperRadarDb` to crawl date-ranged batches of papers, store metadata via upsert, and expose a `--crawl-history` CLI command — delivering a usable archive in 1-2 days with zero schema disruption.

## Main argument

The existing codebase is already 80% of the way there. The `ArxivClient` already accepts categories and a limit. The `SemanticScholarClient` already accepts a `since` parameter and returns `PaperMetadata`. The `PaperRadarDb.upsert_paper` already deduplicates by `arxiv_id`. None of these need to change to support historical crawl.

What's missing is: (1) a way to iterate over date ranges instead of "since now", (2) pagination support for the arXiv API, and (3) a CLI entry point. That's it. No new tables. No new retrieval backends. No new config system.

The spec's proposed schema expansion (`paper_versions`, `paper_texts`, `paper_embeddings`, `paper_scores`, `paper_summaries`, `enrichment_jobs`) is valuable — but it's not needed for the crawl itself. The crawl should just populate the existing `papers` table. Enrichment can be layered on later as separate commands. Coupling crawl to enrichment guarantees we deliver neither in a day.

Semantic Scholar's bulk search API already supports date-range filtering via `publicationDateOrYear`. For arXiv, we can paginate the Atom API by iterating `start` offset in increments of the page size (arXiv Atom supports `start` and `max_results`). The crawl loop becomes:

```
for each month in range(start_month, end_month):
    for offset in range(0, max_results, page_size):
        fetch一页 from Semantic Scholar (date range = that month)
        fetch一页 from arXiv Atom (categories, start=offset, max_results=page_size)
        merge, upsert
        sleep to respect rate limits
```

Rate limiting is straightforward: the existing `ArxivClient` already has a 3-second sleep between requests. For Semantic Scholar with API keys, we get 1 req/sec per key. Without keys, 1 req/5 sec. The crawl module should accept a `--delay` parameter and default to 1 second.

Key implementation decisions:

- **Single file**: `paper_radar/historical.py`. No new modules except possibly a small `CrawlConfig` in config.py.
- **Reuses existing clients**: no new HTTP logic, no new parsing.
- **Reuses existing DB**: upsert by `arxiv_id` means re-runs are safe and idempotent.
- **Date range via CLI**: `paper-radar --crawl-history --from 2023-01-01 --to 2023-02-01` processes one month at a time, prints progress.
- **Checkpoint state**: use the existing `state` table to record `last_crawl_month`, so interrupted crawls resume cleanly.
- **No enrichment coupling**: the crawl stores metadata. PDF extraction, summarization, and embedding are future CLI commands.
- **No schema migration needed**: the existing `papers` table already has `categories_json`, `published_at`, `source`, `pdf_url`, `abstract` — everything the spec's `papers` table calls for.

What the spec proposes that we explicitly defer:

- `paper_versions`: not needed until we want to track arXiv revisions. The upsert already updates metadata.
- `paper_texts`, `paper_embeddings`, `paper_scores`, `paper_summaries`, `enrichment_jobs`: these are enrichment features. Crawl is independent.
- `saved_filters`: a query-layer feature, not a crawl feature.

The 1-2 day plan:

**Day 1 (4-6 hours):**
1. Add `CrawlConfig` dataclass to `config.py` with `start_date`, `end_date`, `delay_seconds`, `page_size`.
2. Add `--crawl-history` CLI arg with `--from` and `--to` date parameters.
3. Implement `HistoricalCrawler` class in `historical.py`:
   - Constructor takes `db`, `s2_client`, `arxiv_client`, `config`.
   - `crawl(start_date, end_date)` iterates months, calls `crawl_month()`.
   - `crawl_month(year, month)` pages through both APIs, merges, upserts.
   - Stores progress in `state` table.
4. Wire into CLI's `main()`.

**Day 2 (2-4 hours):**
5. Add tests: mock clients, verify upsert called with correct records, verify pagination, verify resume from checkpoint.
6. Add `--crawl-history --status` to show crawl progress.
7. Verify existing tests still pass.
8. Run lint and format.

## Testability

- **Unit test with mocked HTTP**: The existing tests already mock `http_get` and `http_get_text`. Same pattern works for `HistoricalCrawler`.
- **Test pagination**: Mock a client returning `page_size` results, verify the crawler requests next page.
- **Test date iteration**: Mock clients returning empty results, verify the crawler iterates all months in range.
- **Test resume**: Insert a `last_crawl_month` state value, verify the crawler starts from that month.
- **Test idempotency**: Upsert the same paper twice, verify only one row in `papers`.
- **Test no schema change**: Run existing 31 tests unchanged after adding the crawl feature.
- **Integration smoke**: `paper-radar --crawl-history --from 2025-01-01 --to 2025-01-02` against a test DB.

## What would change my mind

- If Semantic Scholar's bulk search API does not actually support date-range pagination at the granularity needed (month-by-month), the crawl strategy needs rethinking. I'd want to see the actual API docs first.
- If the existing `papers` table is missing a column the crawl absolutely requires (e.g., a `primary_category` field distinct from `categories_json`), then a schema migration becomes necessary and scope grows.
- If the user reveals they need enrichment (summaries, embeddings) as part of the initial crawl rather than as a separate pass, the single-day plan breaks down and we need the full spec schema.
- If rate limits are so aggressive that crawling 1-5 years of papers would take weeks even with pagination, we need to discuss whether Semantic Scholar's bulk endpoint is the right tool versus arXiv's OAI-PMH or bulk export.
