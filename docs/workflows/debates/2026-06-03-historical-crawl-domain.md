# Historical Crawl - Domain Expert Argument

**Date:** 2026-06-03  
**Role:** Domain Expert  
**Focus:** arXiv/Semantic Scholar API capabilities, rate limits, data quality, CS paper metadata best practices

## Recommendation

Use Semantic Scholar bulk search as the primary historical harvester with arXiv category-based pagination as fallback, respecting hard rate limits and producing ~200-400 papers per crawl run for a bounded eager strategy.

## Main Argument

The historical crawl faces two fundamentally different API surfaces, and a competent crawl strategy must treat them differently rather than forcing one into the other's model.

**Semantic Scholar** is the right primary source for historical bulk crawling. Its bulk search endpoint (`/graph/v1/paper/search/bulk`) is designed for exactly this: paginated traversal of the entire corpus by year, category, and keyword. It supports date-range filtering, fields-of-study filtering, and returns structured metadata with arXiv IDs pre-linked. The `publicationDateOrYear` parameter lets you walk year-by-year. The API key rotation already in `retrieval.py` is necessary - S2 rate limits unauthenticated requests to ~1 req/sec and authenticated requests to ~10 req/sec with 100-page-per-key-per-minute burst. For a 1-5 year crawl this means:

- ~2.5M CS papers across 5 years (cs.* categories)
- At 10 req/sec with 100 results/page, ~7 hours of wall time with one key
- With N rotated keys, wall time drops proportionally, but S2 enforces a per-key daily cap that must be tracked

**arXiv Atom API** is wrong for historical bulk crawl. It has no date-range filtering, no category-based pagination, and returns at most 30,000 results per query regardless of `max_results`. The current `search_recent` method works only because it fetches the latest ~20 entries. For historical work, arXiv is useful only as a metadata enrichment source for papers discovered via S2. Its strength is structured author lists, version history, and categories - data S2 sometimes misses or denormalizes.

The crawl strategy should be:

1. **S2 bulk search** by year (2021-2026) and field `Computer Science`, paginating through all results
2. For each paper discovered, **upsert into SQLite** with dedup by `arxiv_id`
3. Run **enrichment jobs** (abstract quality check, category normalization, optional TLDR extraction) in bounded batches
4. Use arXiv Atom only to **enrich author lists and category taxonomies** for papers where S2 returns sparse metadata

## API Strategy

### Semantic Scholar

| Parameter | Value | Rationale |
|---|---|---|
| Endpoint | `/graph/v1/paper/search/bulk` | Designed for bulk traversal |
| Fields | `paperId,title,abstract,externalIds,publicationDate,fieldsOfStudy,openAccessPdf,tldr,url` | Sufficient for archive; avoid expensive fields like `citations` |
| Filter | `fieldsOfStudy=Computer Science` | CS-only as specified |
| Date filter | `publicationDateOrYear=YYYY-01-01:YYYY-12-31` | Year-by-year crawl to stay within burst limits |
| Sort | `publicationDate:asc` | Deterministic ordering for resumability |
| Pagination | Use `cursor` from response | S2 bulk returns cursor tokens, not offset-based |
| Rate limit | 10 req/sec with key, ~1000 papers/sec burst | Respect per-key limits; rotate keys |

**Critical S2 caveat**: The bulk endpoint does NOT guarantee all papers in a single year will be returned if the year has >1M results. CS is well under this threshold (~500K/year), so year-by-year pagination is safe. But the cursor must be persisted after each batch so the crawl is resumable on interruption.

### arXiv

| Parameter | Value | Rationale |
|---|---|---|
| Endpoint | `https://export.arxiv.org/api/query` | Only available API |
| Max results | 30,000 hard cap | Atom API limitation |
| Filter | `cat:cs.AI` etc. | Category-based, not date-based |
| Rate limit | 3 seconds between requests | Already coded in `ArxivClient._last_request_at` |

arXiv should NOT be the crawl source. Use it only for: (a) enriching author metadata for papers found via S2 where S2 returned incomplete authors, (b) validating category taxonomies, (c) verifying version history (`paper_versions` table).

### Resumability

The `state` table already supports arbitrary key-value pairs. Use it to persist:

- `s2_crawl_cursor_{year}`: last S2 bulk cursor for each year
- `s2_crawl_completed_{year}`: boolean flag when a year is fully crawled
- `enrichment_batch_offset`: offset into the enrichment queue

This means a 1-5 year crawl can be interrupted and resumed without re-fetching.

## Data Quality Considerations

### arXiv ID Normalization

arXiv IDs are not canonical strings. They have forms like `2301.12345`, `2301.12345v2`, `hep-ph/0501001`. The current `PaperMetadata.arxiv_id` field is used as a unique key. For historical crawl:

- Strip version suffixes (`v1`, `v2`, etc.) before upsert
- Normalize old-style IDs (`hep-ph/0501001`) to new-style where possible
- Store the raw ID in `paper_versions.arxiv_version` for version tracking

S2 returns clean arXiv IDs in `externalIds.ArXiv`, but these occasionally have version suffixes that the current code does not strip.

### Duplicate Papers

A single paper may appear in S2 results from multiple query paths. The unique index on `arxiv_id` handles dedup, but the code must handle the case where S2 returns the same paper with slightly different metadata across years. The upsert strategy should prefer the record with the most complete metadata (longer abstract, more authors, non-empty PDF URL).

### Category Taxonomy

S2 `fieldsOfStudy` values do not map 1:1 to arXiv categories. S2 might return "Computer Science" for a paper that is `cs.AI` or `cs.CL` on arXiv. The archive must store the **arXiv primary category** as the canonical category, using S2's `fieldsOfStudy` only as a broad filter. When both S2 and arXiv metadata are available, arXiv categories take precedence.

### Abstract Quality

Not all papers on S2 have complete abstracts. The historical crawl should flag papers with empty or truncated abstracts (S2 occasionally truncates long abstracts at ~500 chars) and mark them for later enrichment via arXiv Atom.

### PDF URL Reliability

S2's `openAccessPdf.url` field is sometimes stale or points to a non-existent file. The archive should store this URL but not rely on it being valid at extraction time. The existing `PdfDownloader` pattern of trying multiple sources (S2 URL -> paperscraper -> arxiv.org) is the correct approach for the enrichment phase.

## What Would Change My Mind

1. **If S2's bulk endpoint proves unreliable for year-by-year crawl** (returns partial results, cursor tokens expire, or rate limits are tighter than documented), I would switch to using arXiv OAI-PMH (Open Archives Initiative Protocol for Metadata Harvesting) as the primary source. OAI-PMH is specifically designed for bulk metadata harvesting with date-range support and resumable tokens, though it requires XML parsing and is slower.

2. **If the user's machine cannot sustain the network time** for a full 5-year crawl (estimated 7+ hours with one key), I would reduce scope to targeted crawl by subcategory (e.g., `cs.AI` only is ~50K papers/year) rather than all CS.

3. **If the user later wants real-time bidirectional sync** (not just batch crawl), the S2 bulk endpoint is wrong and we would need S2's paper updates feed or arXiv RSS. This is explicitly out of scope per the brief but would invalidate the batch strategy.

4. **If SQLite proves too slow for the expected archive size** (~2.5M rows), I would accept DuckDB as a migration path, but NOT before proving the bottleneck with real data. Premature migration to Postgres or Meilisearch is a risk to guard against.
