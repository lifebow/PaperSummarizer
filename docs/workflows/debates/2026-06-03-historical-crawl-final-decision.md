# Historical Crawl — Final Decision

**Date:** 2026-06-03  
**Role:** FINAL JUDGE  
**Models panel:** deepseek-v4-flash-free, mimo-v2.5-free, nemotron-3-super-free, glm-5.1, gpt-5.5  

---

## Summary of Agreements and Conflicts

### Agreements (unanimous or near-unanimous)

1. **Semantic Scholar bulk search is the right primary source.** All five debaters agree. The Domain Expert provides the concrete API details (year-by-year pagination, 10 req/sec with key, ~7 hours wall time for 5 years). The Implementer notes S2 already handles date-range filtering. No one defends arXiv as the primary historical source.

2. **The existing `papers` table should remain the canonical identity table.** The Architect, Implementer, and Pragmatist all say this explicitly. The Skeptic agrees by implication — their alternative is a one-off script writing into the same table. No one proposes a separate archive database.

3. **No full PDF storage.** The brief says "metadata + links only" and all debaters honor this constraint.

4. **SQLite can handle the expected scale.** The Domain Expert estimates ~2.5M rows for 5 years of CS papers; the Skeptic acknowledges this is within SQLite's range with proper indexing.

5. **Resumability is critical.** The Architect, Domain Expert, and Implementer all agree the crawl must survive interruptions. The `state` table key-value store is the agreed mechanism.

### Conflicts

| Dimension | Camp A (minimal) | Camp B (spec-faithful) | Camp C (skeptic/delay) |
|---|---|---|---|
| New tables | 0-1 (Pragmatist, Implementer) | 7 (Architect, Domain Expert) | 0 (Skeptic) |
| Enrichment pipeline | Defer entirely (Pragmatist, Implementer) | Build now with queue table (Architect) | Skip (Skeptic) |
| Version tracking | Defer (Pragmatist, Implementer) | Essential now (Architect) | Skip (Skeptic) |
| Search capability | CLI keyword search (Pragmatist) | Schema-ready but no query executor yet (Architect) | Not needed yet (Skeptic) |
| Timeline | 1-2 days (Implementer, Pragmatist) | 3-5 days (Architect) | "Don't build" (Skeptic) |

The core conflict is **scope**: Architect wants the full 7-table spec implemented now because the schema is designed correctly and retrofitting later is harder. Implementer and Pragmatist say the crawl itself needs none of those tables — it just needs a loop over existing clients and upserts. Skeptic says the whole thing is premature.

---

## Strongest Points by Model

### Architect
**Strongest point:** Schema migration planning. The Architect correctly identifies that `papers` needs `ALTER TABLE ADD COLUMN` for `primary_category` and `archive_status`, and that the current `_connect()` lacks WAL mode. These are real correctness issues that the minimal camp glosses over. Even if we defer most tables, these two schema fixes should happen in v1.

### Skeptic
**Strongest point:** Scope discipline. The warning about "5-10x increase in surface area for a project that has never been deployed to production" is the most important risk in the debate. The current codebase is small and coherent. Every new table, every new queue, every new retry path is surface area that must be tested, maintained, and debugged. The Skeptic's demand for a proven MVP crawl before building infrastructure is the right gate.

### Implementer
**Strongest point:** Concrete 1-2 day plan with specific file paths and test cases. No other debater provides this level of implementation specificity. The plan to add `HistoricalCrawler` in `paper_radar/historical.py` reusing existing clients with zero schema disruption is the most actionable argument in the debate.

### Domain Expert
**Strongest point:** API reality check. The detailed rate limit analysis (S2 bulk endpoint behavior, arXiv's 30K hard cap, cursor token persistence, per-key daily caps) is essential engineering data that no other debater provides at this granularity. The advice to use arXiv only for metadata enrichment — never as a bulk source — is a concrete, actionable constraint.

### Pragmatist
**Strongest point:** Focus on user value. The observation that "the user wants to find papers from 1-5 years ago. Not build a data lake" is the clearest articulation of scope in the debate. The proposed search command (`paper-radar archive search --query "jailbreak" --since 2023-01-01`) is the smallest increment that delivers user-facing value.

---

## Decision

**Adopt the Implementer/Pragmatist minimal path, with two Architect corrections.**

Build `paper_radar/archive.py` as a single new module containing:

1. **`HistoricalCrawler` class** — iterates year-by-year (2021-2026) using Semantic Scholar bulk search, paginates via cursor tokens, upserts into the existing `papers` table via `PaperRadarDb.upsert_paper`. Stores progress in the `state` table under keys `s2_archive_cursor_{year}` and `s2_archive_completed_{year}`. Uses a configurable `RateLimiter` (1 req/sec default). Accepts `--delay` and `--page-size` parameters.

2. **`ArchiveSearcher` class** — queries the existing `papers` table with SQLite `LIKE` on `title || ' ' || abstract`. Accepts `--query`, `--since`, `--until`, `--category`, `--limit` parameters. Returns structured results with title, authors, date, arxiv link.

3. **Two CLI subcommands** added to `cli.py`:
   - `paper-radar archive crawl --from YYYY-MM-DD --to YYYY-MM-DD [--categories cs.AI,cs.CL] [--delay 1.0]`
   - `paper-radar archive search --query "jailbreak" [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--category cs.AI] [--limit 50]`

4. **Two schema corrections** (applied before crawl runs):
   - `ALTER TABLE papers ADD COLUMN primary_category TEXT` — enables efficient category-prefix queries.
   - `ALTER TABLE papers ADD COLUMN archive_status TEXT DEFAULT 'metadata_only'` — tracks crawl enrichment state.
   - Set `PRAGMA journal_mode=WAL` in `_connect()` for concurrent access safety.
   - Add indexes on `published_at` and `primary_category` in `papers`.

5. **Tests** — mock-based unit tests for `HistoricalCrawler` (pagination, resume, idempotent upsert, rate limit sleep) and `ArchiveSearcher` (query filtering, date range, category filter, empty results). Existing 31 tests must pass unchanged.

### What this covers

- Metadata crawl of 1-5 years of CS papers from Semantic Scholar
- Resumable crawl with cursor-based pagination
- Basic keyword search over title+abstract
- arXiv as secondary enrichment source (validate categories, fill author gaps) — implemented later, not in v1
- Rate limit handling with exponential backoff on 429s

### What this explicitly defers

| Deferred item | Rationale | When to revisit |
|---|---|---|
| `paper_versions` table | No version tracking in v1. Upsert overwrites. | When user runs a second crawl and notices metadata changes on updated papers |
| `paper_texts` table | User said "metadata + links only" | When user asks for extracted text or introduction search |
| `paper_embeddings` table | Spec says "no vector DB in v1" | When keyword search proves insufficient |
| `paper_scores` table | Enrichment pipeline is over-engineering for v1 | When user wants topic ranking or quality filtering |
| `paper_summaries` table | Requires LLM calls per paper; too expensive for bulk | When user wants to summarize top-N search results |
| `enrichment_jobs` queue | No enrichment pipeline in v1 | When we add extraction/embedding/summary as separate commands |
| `saved_filters` table | CLI arguments are sufficient for now | When user wants reusable named searches |
| `primary_category` dedup from S2 vs arXiv | Minor data quality issue | When we add arXiv enrichment pass |

---

## Rejected Alternatives

### 1. Full 7-table spec implementation (Architect, Domain Expert)
**Rejected because:** The Architect's schema is well-designed but premature. The Skeptic's warning about scope applies here: 7 new tables + enrichment queue + version tracking + embedding infrastructure is a platform pivot for a project that has never been deployed. The schema can be added incrementally as each feature is actually needed. The `archive_status` column on `papers` provides the hook for future enrichment without requiring the full queue table.

**Not rejected because the schema is wrong** — it is correct. Rejected because the implementation scope is wrong for v1.

### 2. Complete inaction (Skeptic)
**Rejected because:** The user asked for this feature and the brief defines clear constraints (no PDFs, no embeddings, no real-time sync). A one-off script with no CLI integration, no tests, and no resumability is the worst of both worlds — it has the complexity of a crawl without the reliability. The Implementer's point that "the existing codebase is already 80% of the way there" is correct.

### 3. arXiv as primary historical source (rejected by Domain Expert)
**Rejected because:** The Domain Expert's API analysis is definitive. arXiv Atom has a 30K hard cap per query, no date-range filtering, and a 3-second rate limit. At 100K papers, arXiv crawling would take ~83 hours. Semantic Scholar bulk search is purpose-built for this use case. arXiv should only be used for metadata enrichment after S2 discovery.

### 4. arXiv OAI-PMH as primary source (Domain Expert's fallback)
**Rejected for v1 because:** OAI-PMH is a valid alternative if S2 bulk search fails, but it requires custom XML parsing and is slower. The S2 bulk endpoint should be tried first; OAI-PMH is a fallback, not a first choice.

---

## Follow-up Tests or Experiments

### Before implementation
1. **S2 bulk search validation** — make 3-5 test calls to `https://api.semanticscholar.org/graph/v1/paper/search/bulk` with `publicationDateOrYear=2023-01-01:2023-12-31` and `fieldsOfStudy=Computer Science`. Verify: cursor tokens are returned, pagination works across cursors, response includes `externalIds.ArXiv` for most papers. This is a blocker — if S2 bulk doesn't work as documented, the crawl strategy changes.

2. **Existing schema test** — verify that `ALTER TABLE papers ADD COLUMN primary_category TEXT` and `ALTER TABLE papers ADD COLUMN archive_status TEXT` succeed on an existing database without data loss. Run existing tests before and after.

### After v1 implementation
3. **Small crawl smoke test** — `paper-radar archive crawl --from 2025-01-01 --to 2025-01-31 --categories cs.AI`. Expect ~2000-5000 papers. Verify: papers appear in `papers` table, `archive_status` is set, progress is recorded in `state`, interrupting and re-running resumes correctly.

4. **Search validation** — `paper-radar archive search --query "reinforcement learning" --category cs.AI --limit 20`. Verify: results are reasonable, date filter works, category filter works. Compare against S2 web UI for the same query.

5. **Regression gate** — full `python3 -m unittest discover -v` after all changes. All 31 existing tests + new archive tests must pass.

---

## Implementation Scope

### Build in v1 (this cycle)

```
paper_radar/archive.py          # HistoricalCrawler + ArchiveSearcher (~200 lines)
paper_radar/cli.py              # Add archive subcommands (~40 lines)
paper_radar/db.py               # ALTER TABLE for primary_category, archive_status; WAL mode; indexes (~20 lines)
tests/test_archive.py           # Mock-based unit tests (~150 lines)
```

Total new code: ~410 lines. Existing code changes: ~20 lines (db.py, cli.py).

### Build order
1. Schema migration (ALTER TABLE + WAL + indexes) — verify existing tests still pass
2. `HistoricalCrawler` class — mock S2 client, test pagination/resume/idempotency
3. CLI `archive crawl` command — wire up, test with mock
4. `ArchiveSearcher` class — test query filtering
5. CLI `archive search` command — wire up, test
6. Full regression test + lint + format
7. Docker smoke (if Dockerfile exists)

### Commit checkpoint
After step 6, commit: `feat: historical archive crawl and search v1`

### Refactor checkpoint
After v1, count features added since last refactor. If >= 5, run refactor checkpoint before adding enrichment features.

---

## Decision Rationale

The panel unanimously agrees on data source (S2), storage (existing `papers` table), and constraints (no PDFs, SQLite-first). The disagreement is about how much to build in the first pass.

The Skeptic is right that scope is the primary risk. The Architect is right that schema design matters. The Implementer and Pragmatist are right that the crawl itself needs almost no new infrastructure.

The resolution is: **build the crawl and search with minimal schema changes, defer the enrichment pipeline to a future cycle, and prove the value of the archive before investing in the full spec.** The two Architect corrections (WAL mode, `primary_category` column) are small, correct, and necessary for the crawl to work well. Everything else can wait until the user confirms the archive is useful and enrichment features are actually needed.
