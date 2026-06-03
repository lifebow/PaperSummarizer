# arXiv Paper Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone daemon that discovers recent arXiv AI papers through Semantic Scholar plus arXiv reconciliation, summarizes accepted papers from downloaded PDFs, writes daily Markdown digests, and sends a 21:00 Telegram recap.

**Architecture:** Python package `paper_radar` with small modules for config, SQLite state, retrieval, PDF extraction, LLM calls, QA/digest rendering, Telegram, and daemon orchestration. External network clients are injectable so unit tests use fakes and do not hit APIs.

**Tech Stack:** Python 3.10 stdlib-first core, optional `requests`, `python-dotenv`, `paperscraper`, `pymupdf4llm`, `pdfplumber`, OpenAI-compatible REST, Telegram Bot API, SQLite.

---

### Task 1: Project Skeleton And Configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env`
- Create: `.env.example`
- Create: `config.yaml`
- Create: `paper_radar/__init__.py`
- Create: `paper_radar/config.py`
- Test: `tests/test_config.py`

- [ ] Write failing unittest coverage for loading YAML defaults, `.env` values, and comma-separated Semantic Scholar keys.
- [ ] Implement `load_config()` with a tiny YAML parser for the simple config file shape, `.env` loading, and env override support.
- [ ] Verify `python3 -m unittest tests.test_config -v` passes.

### Task 2: SQLite State

**Files:**
- Create: `paper_radar/db.py`
- Test: `tests/test_db.py`

- [ ] Write failing unittest coverage for schema creation, paper upsert by arXiv id, run tracking, accepting paper results, and unsent recap lookup.
- [ ] Implement SQLite tables and repository methods.
- [ ] Verify `python3 -m unittest tests.test_db -v` passes.

### Task 3: Retrieval And Key Rotation

**Files:**
- Create: `paper_radar/retrieval.py`
- Test: `tests/test_retrieval.py`

- [ ] Write failing unittest coverage for Semantic Scholar key rotation, merging by arXiv id, filtering out non-arXiv papers, and arXiv fallback PDF URL.
- [ ] Implement `SemanticScholarClient`, `ArxivClient`, `HybridRetriever`, and `PdfDownloader` with injectable HTTP callables.
- [ ] Verify `python3 -m unittest tests.test_retrieval -v` passes.

### Task 4: PDF Extraction And Cleanup

**Files:**
- Create: `paper_radar/extraction.py`
- Test: `tests/test_extraction.py`

- [ ] Write failing unittest coverage for primary extractor success, fallback extractor use, and PDF cleanup after success/error.
- [ ] Implement optional PyMuPDF4LLM primary plus pdfplumber fallback, with injectable extractors for tests.
- [ ] Verify `python3 -m unittest tests.test_extraction -v` passes.

### Task 5: LLM Filtering, Summary, QA, Digest

**Files:**
- Create: `paper_radar/llm.py`
- Create: `paper_radar/digest.py`
- Test: `tests/test_llm_digest.py`

- [ ] Write failing unittest coverage for OpenAI-compatible payload shape, JSON extraction, QA threshold acceptance, and Markdown rendering with background/math/idea sections.
- [ ] Implement LLM client helpers, QA threshold logic, and Markdown renderer.
- [ ] Verify `python3 -m unittest tests.test_llm_digest -v` passes.

### Task 6: Telegram And Daemon Orchestration

**Files:**
- Create: `paper_radar/telegram.py`
- Create: `paper_radar/daemon.py`
- Create: `paper_radar/cli.py`
- Test: `tests/test_telegram_daemon.py`

- [ ] Write failing unittest coverage for Telegram payloads, one-run orchestration with fake retriever/LLM/extractor, digest append, PDF cleanup, and daily recap marking.
- [ ] Implement Telegram sender, `run_once()`, recap sending, and `watch()` daemon loop.
- [ ] Verify `python3 -m unittest tests.test_telegram_daemon -v` passes.

### Task 7: Full Verification

**Files:**
- Modify as needed based on failures.

- [ ] Run `python3 -m unittest discover -v`.
- [ ] Run `python3 -m paper_radar.cli --help`.
- [ ] Confirm no actual API keys are committed into source files; keys only live in ignored `.env`.
