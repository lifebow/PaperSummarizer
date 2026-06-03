# Paper Archive Query Skeleton - Design

**Date:** 2026-06-03  
**Status:** Paused after brainstorming  
**Project:** `paper_radar` archive expansion in `/Users/lifebow/Documents/arxiv_clone/newpapers`

## Goal

Expand `paper_radar` from a daily radar that keeps only selected papers into a
larger local archive for CS paper metadata, extracted text, summaries, scores,
and future query filters.

The system should be able to store a large number of papers across CS categories,
then let the user query, filter, rank, export, or build daily digests from that
archive later. The near-term design should stay compatible with the current
SQLite-based project and avoid introducing a heavy external search service too
early.

## Key Decisions

- Keep SQLite as the first archive database.
- Harvest broad CS metadata instead of only a small radar subset.
- Store enough normalized fields to support later filters by category, date,
  topic score, source, extraction status, summary status, and embedding status.
- Preserve paper version history so arXiv updates do not overwrite useful state
  invisibly.
- Extract and retain full paper text or a full-text artifact path for future
  deeper processing.
- Generate embeddings only from `title + abstract + introduction`, not from the
  full paper.
- Treat full PDF/text extraction, summary generation, scoring, and embedding as
  enrichment steps that can be queued, retried, and rate-limited.
- Keep the current daily radar/digest path as a consumer of the archive, not the
  only reason papers enter the database.

## Recommended Approach

Use a SQLite archive plus an enrichment pipeline.

The metadata harvester stores every newly discovered paper from configured CS
categories. An enrichment worker then downloads PDFs, extracts full text, detects
the introduction section, creates an embedding input from title, abstract, and
introduction, and optionally runs LLM summary/scoring.

This keeps the current MVP architecture intact while opening a path toward richer
query features. The archive can later sync to DuckDB, Postgres, Meilisearch, or a
vector database if SQLite becomes too small, but that migration should not be
part of the first skeleton.

## Alternatives Considered

### Metadata-First Lazy Extraction

Only harvest metadata widely. Download PDFs and create embeddings later when a
paper passes an initial filter or appears in a query.

This is cheaper and simpler operationally, but it means the first version of
deep search will have sparse data. It is useful as a runtime mode, but less good
as the main schema direction because the database still needs fields for text and
embedding state.

### Raw Lake Plus Normalized Database

Store raw arXiv and Semantic Scholar payloads as files, then normalize into
SQLite tables.

This is the most flexible approach for schema changes and reprocessing. It adds
more moving parts than the project needs right now, so the first skeleton should
only store compact raw payloads where they are useful for version/debug history.

## Proposed Schema Skeleton

### `papers`

Canonical paper identity and latest metadata.

- `id`
- `arxiv_id`
- `semantic_scholar_id`
- `title`
- `abstract`
- `authors_json`
- `primary_category`
- `categories_json`
- `published_at`
- `updated_at`
- `pdf_url`
- `abs_url`
- `semantic_scholar_url`
- `source`
- `first_seen_at`
- `last_seen_at`
- `archive_status`

Indexes:

- unique index on `arxiv_id`
- index on `primary_category`
- index on `published_at`
- index on `updated_at`
- index on `archive_status`

### `paper_versions`

Track arXiv revisions and source payload changes.

- `id`
- `paper_id`
- `arxiv_version`
- `title`
- `abstract`
- `published_at`
- `updated_at`
- `source_payload_json`
- `seen_at`

Indexes:

- unique index on `paper_id, arxiv_version`
- index on `updated_at`

### `paper_texts`

Store extracted full text metadata and introduction text.

- `paper_id`
- `extractor_name`
- `full_text_path`
- `full_text_chars`
- `introduction_text`
- `introduction_chars`
- `extraction_status`
- `extraction_error`
- `extracted_at`

The first implementation can choose either inline full text or file-backed full
text. File-backed storage is safer for large archives; SQLite keeps the metadata
and introduction.

### `paper_embeddings`

Embedding records for semantic query.

- `id`
- `paper_id`
- `embedding_model`
- `embedding_input_kind`
- `embedding_input_hash`
- `embedding_vector`
- `dimensions`
- `created_at`

`embedding_input_kind` should be `title_abstract_intro` for the planned first
embedding type. The input must be derived from title, abstract, and introduction
only.

### `paper_scores`

Reusable scores for filters and rankings.

- `id`
- `paper_id`
- `score_kind`
- `score_value`
- `reason_json`
- `model`
- `created_at`

Examples of `score_kind`:

- `topic:llm_agent`
- `topic:ai_safety`
- `topic:ai_jailbreak`
- `idea_quality`
- `grounding_quality`

### `paper_summaries`

LLM-generated structured summaries.

- `id`
- `paper_id`
- `summary_json`
- `model`
- `input_hash`
- `created_at`

### `enrichment_jobs`

Queue state for extraction, embedding, summary, and scoring.

- `id`
- `paper_id`
- `job_type`
- `status`
- `attempt_count`
- `last_error`
- `run_after`
- `created_at`
- `updated_at`

Examples of `job_type`:

- `extract_pdf`
- `embed_title_abstract_intro`
- `summarize`
- `score_topics`

### `saved_filters`

Named query presets.

- `id`
- `name`
- `filter_json`
- `created_at`
- `updated_at`

## Data Flow

```text
harvest configured CS categories
  -> upsert papers and paper_versions
  -> enqueue enrichment jobs
  -> download PDF
  -> extract full text
  -> detect introduction section
  -> create embedding from title + abstract + introduction
  -> optionally create summary and scores
  -> query archive through filters/search
  -> feed daily radar/digest from query results
```

## Introduction Detection

The extractor should attempt simple, explainable section detection before using
an LLM:

1. Convert PDF to text or Markdown with the existing extraction layer.
2. Find a heading matching `Introduction`, `1 Introduction`, or close variants.
3. Stop at the next major heading such as `Related Work`, `Background`,
   `Method`, `Preliminaries`, or `2 ...`.
4. If no introduction is found, fall back to a bounded prefix of the body plus
   the abstract.

The fallback keeps embeddings available even for papers with unusual formatting.
The embedding input should still be labeled as `title_abstract_intro` because the
intended semantic content remains title, abstract, and introductory context.

## Query Direction

The first query layer can be CLI-oriented and SQLite-backed:

```text
paper-radar archive search --category cs.AI --since 2026-01-01 --topic ai_safety
paper-radar archive search --text "jailbreak benchmark" --limit 50
paper-radar archive export --filter safety-high --format markdown
```

Likely filter fields:

- category or category prefix
- published/updated date range
- title/abstract text search
- extraction status
- summary status
- embedding status
- score kind and minimum score
- top N by score or recency

## Error Handling

- Harvest errors should not stop the whole archive run.
- Per-paper extraction, embedding, summary, and scoring errors should update
  `enrichment_jobs` and remain retryable.
- PDF files should still be cleaned up after extraction unless the user later
  chooses a persistent PDF cache.
- Full text should be reprocessable when extraction logic changes.
- Embeddings should use an input hash so stale vectors can be detected after
  abstract/introduction changes.

## Testing Strategy

Focused tests should cover:

- Schema migration/initialization for the new archive tables.
- Paper upsert and version insert behavior.
- Enrichment job creation, retry, and status transitions.
- Introduction extraction from normal headings and fallback text.
- Embedding input construction from title, abstract, and introduction only.
- Query filters for category, date range, status, score threshold, and text.
- Existing radar/digest tests to ensure the old daily workflow still works.

## Open Pause Point

Brainstorming is paused here. The next session should continue by deciding how
eager the enrichment worker should be:

1. Eager: every harvested paper gets extraction and intro embedding.
2. Bounded eager: process every harvested paper, but only up to configured daily
   or hourly limits.
3. Filtered lazy: harvest all metadata, but extract/embed only papers matching
   configured broad filters.

Current recommendation: bounded eager, because it builds a useful archive over
time without one run consuming too much network, disk, or API budget.

## Repository Note

The brainstorming workflow normally asks for this design document to be
committed. This workspace currently has no `.git` directory, so no commit was
created.
