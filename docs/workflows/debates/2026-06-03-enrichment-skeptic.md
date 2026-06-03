# Enrichment Pipeline - Skeptic Argument

**Date:** 2026-06-03  
**Role:** SKEPTIC  
**Status:** Independent argument  

## Recommendation

Do not implement the enrichment pipeline as described in the spec; defer it until the archive has proven query demand, and then build only extraction and intro-text storage—skip embeddings, summaries, and the job queue entirely.

## Main argument

The spec proposes 7 new tables, a job queue, PDF downloads at scale, introduction section detection, embedding generation, and LLM scoring—all under the label "skeleton." This is not a skeleton. It is a second production system bolted onto an MVP that already works for its stated purpose.

The current `paper_radar` does one thing: hourly fetch, filter, summarize, digest, Telegram. It does that with 42 passing tests and no external dependencies beyond an LLM API key and an S2 key. The enrichment spec asks us to triple the schema surface, add PDF download plumbing, introduce an NLP sub-problem (section detection), and build a job orchestration layer in SQLite—all before proving anyone actually queries the archive.

The honest state of affairs:

1. **The archive has zero consumers.** No CLI query, no export, no digest feeds from it. We are building extraction, embedding, and scoring infrastructure for a feature that does not exist yet. YAGNI applies with extreme force here.

2. **PDF downloads at archive scale are a cost and reliability problem, not a code problem.** A 10k-paper archive means 10k PDF downloads. Each is 500KB–5MB. That is 5–50GB of disk I/O, hours of wall time, and dozens of transient network failures. The existing `process_pdf_with_cleanup` deletes PDFs after extraction, which is correct for the daily radar but wrong for an archive that might need re-extraction. This is an unsolved design tension the spec hand-waves.

3. **Introduction detection is a real NLP problem being treated as a regex.** The spec says "find a heading matching Introduction, stop at the next major heading." Papers have wildly different formatting: two-column layouts, numbered sections, no headings, embedded figures with captions that look like headings, papers where "Introduction" spans 3 pages and papers where it is one paragraph. Getting this wrong silently degrades embedding quality with no signal. The fallback ("bounded prefix of the body plus abstract") is the real behavior, and it means the introduction detection is mostly dead code.

4. **The job queue is a second system in SQLite.** `enrichment_jobs` with `status`, `attempt_count`, `last_error`, `run_after` is a job scheduler. Building a reliable job scheduler in SQLite that handles retries, rate limits, partial failures, and concurrent access is a project unto itself. The spec does not acknowledge this complexity.

5. **LLM enrichment on thousands of papers is an ongoing cost, not a one-time cost.** Summary + QA scoring per paper is two LLM calls. At 10k papers that is 20k calls. Even at $0.001/call that is $20, and at $0.01/call it is $200. The spec does not mention cost budgets, and "bounded eager" without a cost ceiling is just "eager with extra steps."

6. **The existing extraction layer is a thin wrapper, not a production pipeline.** `PdfExtractor` calls pymupdf, falls back to pdfplumber, and raises if the result is short. It has no timeout handling, no retry logic, no partial-failure tracking. For the daily radar (1–3 papers) this is fine. For an archive enrichment worker it is a liability.

## Risks

- **Scope creep via "skeleton."** The spec calls this a skeleton but includes embeddings, summaries, scoring, saved filters, version tracking, and a job queue. Each of these is a feature. Together they are a product. The risk is that "implement the skeleton" becomes a multi-week effort that displaces the actual daily radar work.

- **SQLite as a job queue breaks under concurrency.** If the enrichment worker runs as a daemon (which the spec implies), SQLite's write lock will serialize all job updates. This is fine for single-process but breaks if anyone adds a second worker or runs the daily radar concurrently.

- **Embedding staleness is an unsolved problem.** The spec proposes input hashes to detect stale vectors. But when an abstract changes (arXiv v2), do you re-embed? Do you re-score? Do you re-summarize? The cascading invalidation problem is real and the spec punts on it.

- **Introduction detection failures are silent.** There is no testable signal for "this introduction extraction was wrong." A bad extraction produces a plausible-looking embedding input. Quality degrades silently.

- **PDF download failures will dominate the job queue.** arXiv rate-limits, network timeouts, and malformed PDFs will fill `enrichment_jobs` with retrying entries. The queue becomes a source of operational noise rather than useful state.

- **Test surface explosion.** The spec asks for tests covering schema migration, upsert behavior, job lifecycle, introduction extraction, embedding construction, query filters, and backward compatibility. That is 7 new test domains. The existing 42 tests are manageable. Adding 7 domains could double or triple the test suite with no proportional value gain.

## Simplicity and reuse

The existing codebase is admirably simple: one DB module, one retrieval module, one extraction module, one LLM module, one digest module. The enrichment spec breaks this simplicity by introducing:

- A job queue that duplicates what the daemon loop already does (fetch, process, store).
- A scoring table that duplicates what `passes_quality_gate` already does in-memory.
- A summary table that duplicates what `build_summary_prompt` already produces.
- An embedding table that has no consumer yet.

The simplest path that preserves existing behavior and still adds value:

1. Add `full_text_path` and `introduction_text` columns to `papers`.
2. Extract full text during the daily radar run (already happens for 1–3 papers).
3. Store introduction text using the existing heading-detection regex (with the fallback).
4. Skip embeddings, scoring tables, and the job queue entirely.
5. Add a CLI flag `--archive-enrich` that processes N metadata-only papers per run.

This gets you extracted text and introductions for the archive without building a second system. Embeddings and scoring can follow when there is a query feature that uses them.

## What would change my mind

1. **A working query consumer exists.** If someone builds `paper-radar archive search --text "jailbreak benchmark" --limit 50` and it actually returns useful results, I would support adding extraction to improve result quality. Build the consumer first, then enrich to serve it.

2. **A cost budget is defined.** If the spec states "we will spend at most $X/month on LLM enrichment, with a hard stop at Y papers," I would support bounded eager. Without a budget, "bounded eager" is unbounded in practice.

3. **Introduction detection has proven accuracy.** If someone runs the heading regex on 1000 papers and reports "85% correct extraction, 10% partial, 5% garbage," I would support using it. Right now it is an untested claim.

4. **The job queue is replaced by a simpler mechanism.** If the enrichment worker is just "process N papers per daemon loop iteration, no persistent queue," I would support it. SQLite job queues are a well-known source of operational complexity.

5. **The schema is cut in half.** If the spec drops `paper_embeddings`, `paper_scores`, `paper_summaries`, `enrichment_jobs`, and `saved_filters` and just adds text extraction columns to `papers`, I would support it immediately. That is a real skeleton.
