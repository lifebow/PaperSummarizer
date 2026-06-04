# Agent Notes

## OpenCode Start Here

OpenCode reads this `AGENTS.md` file first for project rules. Treat this file as
the project entrypoint, then load the detailed workflow docs configured in
`opencode.json`:

- `docs/opencode.md`
- `docs/workflows/README.md`
- `docs/workflows/templates/*.md`

For autonomous OpenCode work, follow `docs/opencode.md` before planning,
debating, implementing, testing, refactoring, or deploy-smoke verification.

## Project Snapshot

- Workspace: `/Users/lifebow/Documents/arxiv_clone/newpapers`
- This directory is a git repository with an initial harness checkpoint commit.
- Python package: `paper_radar`
- CLI entrypoint: `paper-radar = paper_radar.cli:main`
- Purpose: hourly arXiv/Semantic Scholar paper radar for AI topics, with LLM summaries, daily Markdown digests, and Telegram recaps.

## Current Structure

- `paper_radar/config.py`: dataclass config loader with a small YAML parser and `.env` support.
- `paper_radar/db.py`: SQLite schema and repository for papers, runs, results, recap state, and generic state.
- `paper_radar/retrieval.py`: Semantic Scholar client, arXiv Atom client, hybrid merge by arXiv id, PDF downloader.
- `paper_radar/extraction.py`: PDF extraction with PyMuPDF primary and pdfplumber fallback, plus cleanup wrapper.
- `paper_radar/llm.py`: OpenAI-compatible JSON chat client, relevance/summary/QA prompts, quality gate.
- `paper_radar/digest.py`: Markdown digest and Telegram recap rendering.
- `paper_radar/telegram.py`: Telegram Bot API sender.
- `paper_radar/daemon.py`: `PaperRadarService` orchestration, `run_once`, daily recap, watch loop.
- `paper_radar/cli.py`: argparse CLI with `--run-once`, `--send-recap`, `archive-crawl`, and `archive-search`.
- `paper_radar/archive.py`: HistoricalCrawler (S2 bulk search), ArchiveSearcher (SQLite LIKE), RateLimiter.

## Existing Docs

- Design: `docs/superpowers/specs/2026-05-29-arxiv-paper-radar-design.md`
- Archive/query skeleton design: `docs/superpowers/specs/2026-06-03-paper-archive-query-skeleton-design.md`
- Development harness design: `docs/superpowers/specs/2026-06-03-dev-harness-design.md`
- Plan: `docs/superpowers/plans/2026-05-29-arxiv-paper-radar-implementation.md`
- The old design targets an MVP daemon that fetches recent arXiv AI papers, filters by relevance, downloads PDFs temporarily, summarizes and QA-gates with an LLM, writes `digests/YYYY-MM-DD.md`, and sends one Telegram recap at 21:00 Asia/Ho_Chi_Minh.

## Verification Status

Last checked on 2026-06-03 from this workspace after harness documentation
hardening:

```bash
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m unittest discover -v
```

Result: ruff lint passed, ruff format-check passed, and unittest reported
`Ran 61 tests in 1.650s - OK (skipped=8)`.

Warnings seen during tests:

- `RequestsDependencyWarning` about urllib3/chardet/charset_normalizer versions.
- `paperscraper.load_dumps` warnings that biorxiv/chemrxiv/medrxiv dumps are missing.
- PyMuPDF/SWIG deprecation warnings.

Harness proof levels observed on 2026-06-03:

- Docs/unit harness: pass (`tests/test_project_harness.py`).
- Codex subagent runner execution: pass; a spawned subagent ran the local
  lint, format-check, and unittest commands and returned results.
- OpenCode config resolve: pass when allowed to write OpenCode state outside
  the repo; `opencode debug config` and `opencode debug agent lint`,
  `implement`, and `debate-judge` resolved the project agents.
- Model-backed OpenCode execution: not verified in this Codex session because
  `opencode run --agent lint ...` was blocked by data-export policy for
  external model-backed execution.

OpenCode caveat: inside a filesystem sandbox, `opencode agent list` can fail
with `SQLITE_READONLY`, `PRAGMA wal_checkpoint(PASSIVE)`, or `EPERM` on
`~/.local/state/opencode` lock paths because OpenCode needs write access to
`~/.local/share/opencode` and `~/.local/state/opencode`. Treat that as an
environment blocker, not as proof that `opencode.json` is invalid.

Unit tests (mock-based): `tests/test_archive.py` — HistoricalCrawler, ArchiveSearcher, schema migration.
Unit tests (mock-based): `tests/test_enrichment.py` — extract_introduction, extract_text_from_pdf, db schema, enricher batch.
Integration tests (real API): `tests/test_archive_integration.py` — skips if `SEMANTIC_SCHOLAR_API_KEYS` not set.
Integration tests (real API): `tests/test_enrichment.py` — skips if no network/PDF access.
Run integration tests: `SEMANTIC_SCHOLAR_API_KEYS=your_key python3 -m unittest tests.test_archive_integration -v`
Run LLM integration tests: `OPENAI_BASE_URL=... OPENAI_API_KEY=... OPENAI_MODEL=... python3 -m unittest tests.test_llm_integration -v`

## Working Constraints

- Follow the superpowers workflow when brainstorming or changing behavior.
- For creative or behavior changes, use `superpowers:brainstorming` first and get design approval before implementation.
- The brainstorming skill normally asks to commit written specs; this folder now has `.git`, so create a checkpoint commit before refactor work.
- Prefer `rg` / `rg --files` for project exploration.
- Use `apply_patch` for manual file edits.
- Do not touch real API keys. Expected secrets are loaded from `.env` or environment variables:
  - `SEMANTIC_SCHOLAR_API_KEYS`
  - `OPENAI_BASE_URL`
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`

## Brainstorming Continuation

The current code appears to satisfy the original MVP plan at the unit-test level.

The latest brainstorm moved toward a larger local archive/query skeleton:

- Store a large number of CS papers, not only daily accepted radar papers.
- Keep SQLite first.
- Add schema for paper versions, extracted text, introduction text, embeddings, scores, summaries, enrichment jobs, and saved filters.
- Extract/retain full text or full-text artifact paths.
- Generate embeddings only from `title + abstract + introduction`, not from full paper text.
- Current recommendation in the spec: bounded eager enrichment.

Paused state:

- The written spec exists at `docs/superpowers/specs/2026-06-03-paper-archive-query-skeleton-design.md`.
- User asked to pause after writing the doc.
- Next useful step is user review of that spec, especially choosing enrichment mode:
  1. eager,
  2. bounded eager,
  3. filtered lazy.

## Historical Crawl Status

Implemented v1 of the historical archive feature (commit `2162aaf`):

- `paper_radar/archive.py`: HistoricalCrawler (S2 bulk search) + ArchiveSearcher (SQLite LIKE)
- CLI commands: `paper-radar archive-crawl` and `paper-radar archive-search`
- Schema: added `primary_category` + `archive_status` columns, WAL mode, indexes
- 42 tests pass (31 original + 10 archive unit + 1 harness)
- Integration tests in `tests/test_archive_integration.py` (skip if no API key)
- Docker container builds and shows archive subcommands

## Enrichment Pipeline Status

Implemented enrichment pipeline v1 (commit `9f22680`):

- `paper_radar/enrichment.py`: ArchiveEnricher, extract_text_from_pdf (PyMuPDF), extract_introduction
- Schema: added `paper_texts` table for extracted text storage
- CLI command: `paper-radar enrich` with `--limit` and `--dry-run`
- 60 tests pass (42 original + 10 enrichment tests + 8 integration tests)
- Integration tests in `tests/test_enrichment.py` (skip if no API key)
- Introduction detection: regex heading patterns + bounded-prefix fallback
- Tested with real paper: arxiv.org/pdf/2606.03988 (97K chars, 3K intro extracted)

Deferred from v1 (per judge decision):
- `paper_versions` table (version tracking)
- `paper_texts` table (full text storage)
- `paper_embeddings` table (vector search)
- `paper_scores` table (enrichment scoring)
- `paper_summaries` table (LLM summaries)
- `enrichment_jobs` queue (pipeline orchestration)
- `saved_filters` table (named searches)

## Harness Direction

User selected approach 1 for the development harness:

- Add Ruff for linting and formatting.
- Keep the existing `unittest` suite.
- Add Markdown docs for setup and development.
- Do only light refactor needed to satisfy linting and keep behavior stable.

Spec: `docs/superpowers/specs/2026-06-03-dev-harness-design.md`

## Harness Status

Implemented development harness:

- Ruff configured in `pyproject.toml`.
- Existing `unittest` suite retained.
- Harness tests added in `tests/test_project_harness.py`.
- Setup docs added in `README.md`.
- Development workflow docs added in `docs/development.md`.
- Light Ruff-driven refactor applied without intended behavior changes.

Current verification: 42 tests pass, ruff check passes, ruff format passes.

### OpenCode Config (`opencode.json`)

- `small_model`: `opencode/deepseek-v4-flash-free`
- Subagent `lint`: model `opencode/deepseek-v4-flash-free`, edit deny
- Subagent `implement`: model `acbpro/glm-5.1`, edit allow
- Debate agents with fixed model mappings:
  - `debate-deepseek`: `opencode/deepseek-v4-flash-free`
  - `debate-mimo`: `opencode/mimo-v2.5-free`
  - `debate-nemotron`: `opencode/nemotron-3-super-free`
  - `debate-glm`: `acbpro/glm-5.1`
  - `debate-gpt55`: `acbpro/gpt-5.5`
  - `debate-judge`: `acbpro/gpt-5.5`

### User-Selected Debate Models (2026-06-03)

Panel (all debate):
1. `opencode/deepseek-v4-flash-free`
2. `opencode/mimo-v2.5-free`
3. `opencode/nemotron-3-super-free`
4. `acbpro/glm-5.1`
5. `acbpro/gpt-5.5`

Judge: `acbpro/gpt-5.5`

### Deployment / Versioning Status

- `.git` repository exists and an initial checkpoint commit was created.
- Dockerfile and `docker-compose.yml` exist.
- Container smoke passed with Podman: `podman run --rm paper-radar:latest --help`.
- Compose smoke passed with Podman Compose: `podman compose run --rm paper-radar --help`.
- Docker Compose CLI specifically cannot run in this shell because neither
  `docker compose` nor `docker-compose` is installed, but `podman compose` is available.
- Dockerfile has a separate runtime dependency install layer before app wheel
  install; normal source-only edits should reuse dependency cache. Avoid
  `--no-cache` except when debugging stale builds.
- After repeated smoke builds, keep `paper-radar:latest` and clean dangling
  images with `podman image prune`; remove only this project's leftover compose
  pod with `podman pod rm pod_newpapers` if present.

## OpenCode Workflow Docs

Markdown docs now describe the autonomous OpenCode/subagent harness:

- Main handoff: `docs/opencode.md`
- Workflow README: `docs/workflows/README.md`
- Templates:
  - `docs/workflows/templates/feature-plan.md`
  - `docs/workflows/templates/debate-brief.md`
  - `docs/workflows/templates/test-matrix.md`
  - `docs/workflows/templates/task-graph.md`

Important workflow rules encoded in docs:

- User chooses debate panel models and final judge model.
- Debate runs through OpenCode or another multi-model backend.
- Coordinator orchestrates and reviews; mechanical checks go to subagents when
  available.
- Lint and format-check run before full regression tests.
- New features need comprehensive happy-path, edge, niche, invalid, failure,
  backward-compatibility, and refactor-safety tests.
- Every 5 feature additions require a simplicity/reuse refactor checkpoint.
- Commit before refactor; if there is no `.git`, refactor is blocked.
- Docker/Compose smoke is a final gate when deploy files exist.
