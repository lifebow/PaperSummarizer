# Historical Crawl - Pragmatist Argument

**Date:** 2026-06-03  
**Role:** Pragmatist  
**Focus:** User value, MVP scope, what actually matters

## Recommendation

Start with Semantic Scholar bulk search by year/category, store metadata only (no PDFs, no extraction, no embeddings), and add a basic CLI text search over title+abstract. That's the smallest thing that lets the user find older papers they care about.

## Main Argument

The user wants to find papers from 1-5 years ago. Not build a data lake. Not generate embeddings. Not run an enrichment pipeline. They want to type a query and get back papers that match.

The existing spec at `docs/superpowers/specs/2026-06-03-paper-archive-query-skeleton-design.md` is well-designed but premature. It proposes 7 new tables, a full enrichment queue, version tracking, embedding infrastructure, and introduction detection. None of that is needed to answer the user's actual question: "which papers from 2023 match this topic?"

The current codebase already has `SemanticScholarClient` with `search()` that takes a query and date filter. It already has `ArxivClient` with category-based search. The existing `papers` table already stores title, abstract, categories, and URLs. The bottleneck is not schema -- it's scope control.

**What the user actually needs right now:**

1. A crawl command that iterates through year/month ranges and fetches metadata from Semantic Scholar or arXiv, paginating through results.
2. Store results in the existing `papers` table (maybe add `archive_source` column to distinguish crawled vs. radar papers).
3. A search command: `paper-radar archive search --query "jailbreak" --since 2023-01-01 --category cs.AI` that does SQLite `LIKE` or FTS on title+abstract.
4. Rate limit handling: simple exponential backoff, resume from last successful page.

That's it. The user can search their archive. They can find papers. They can click the URL and read them. Value delivered.

**What can wait:**

- PDF extraction / full text storage: nice, but the user said "metadata + links only"
- Embeddings: the spec says "no vector database in first version" -- honor that
- Enrichment jobs queue: over-engineering for a metadata archive
- Version tracking: if a paper updates, the existing upsert handles it
- Introduction detection: pointless without embeddings to consume the output
- Saved filters: SQLite queries from CLI are sufficient

## MVP Scope

Smallest useful thing:

1. **Crawl command** (`paper-radar archive crawl`): accepts `--year-range 2021-2025`, `--categories cs.AI,cs.CL`, uses Semantic Scholar bulk search with date range pagination, upserts into existing `papers` table. Adds `archive_source='crawl'` column to distinguish from daily radar papers.

2. **Search command** (`paper-radar archive search`): accepts `--query`, `--since`, `--until`, `--category`, `--limit`. Does SQLite `LIKE '%query%'` on title + abstract. Returns formatted results with title, authors, date, arxiv link.

3. **Rate limit**: simple retry with exponential backoff on 429s. Track last successful cursor/offset in `state` table so crawl can resume.

No new tables beyond one nullable column. No new infrastructure. No enrichment. Just metadata in, search out.

## User Value

The user's workflow is: "I heard about topic X, what papers exist on it from the last few years?" Today they have to use Semantic Scholar's web UI or Google Scholar. With this MVP, they can run a local command against their own archive, which they control, which has no rate limits on search, and which they can augment with their own notes later.

The archive becomes useful the moment it has 10,000+ papers and a working search. It doesn't need embeddings or summaries to deliver value. Those features optimize for a query experience the user doesn't have yet.

## What Would Change My Mind

1. **If the user says they need semantic search, not keyword search.** If LIKE on title+abstract is too noisy and they need vector similarity, embeddings become necessary. But test keyword first -- it's often good enough for CS papers where titles are descriptive.

2. **If the crawl takes so long that resumability requires a job queue.** If crawling 5 years of papers takes weeks and crashes frequently, an enrichment job table with status tracking becomes justified. But start with simple state tracking and see if it breaks.

3. **If the user wants to enrich papers at query time, not at crawl time.** If the workflow becomes "search returns 50 results, now summarize the top 5", then a per-paper summary field makes sense. But build the search first, then see what the user actually does with results.

4. **If other debaters show that Semantic Scholar bulk search cannot cover the date range needed.** If the API simply doesn't support 2021 queries and we need arXiv OAI-PMH or another source, the data source choice changes but the MVP scope stays the same.

5. **If the existing `papers` table schema genuinely cannot support deduplication across crawl and radar.** The current `arxiv_id UNIQUE` constraint handles this. If it doesn't, add a column -- don't rebuild the schema.

## Simplicity and Reuse

The existing `upsert_paper` method handles dedup. The existing `PaperMetadata` dataclass is the transfer object. The existing `HybridRetriever` pattern (S2 + arXiv merge) already works. The new crawl is just a loop over date ranges calling existing methods. The new search is just a SQL query. Total new code: maybe 150 lines in a new `archive.py` module plus CLI wiring.

## Refactor Impact

Minimal. The existing `papers` table gets one nullable column. The existing retrieval layer is reused as-is. No changes to `daemon.py`, `digest.py`, `telegram.py`, or `llm.py`. The daily radar flow is completely untouched.

## Deployment Impact

None. Same SQLite database. Same Docker image. Same CLI entrypoint with two new subcommands. No new dependencies.

## Risks

- Semantic Scholar bulk search may not support deep historical pagination (cursor-based) -- test this first
- 5 years of CS papers across multiple categories could be 500K+ entries -- SQLite handles this fine for metadata-only
- Rate limits could make a full crawl take days -- acceptable, user can run it in background
- Keyword search may be too imprecise -- but it's the starting point, not the endpoint
