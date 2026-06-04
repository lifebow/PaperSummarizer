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
- `paper_radar/db.py`: SQLite schema and repository for papers, runs, results, recap state, generic state, and paper expansions.
- `paper_radar/retrieval.py`: Semantic Scholar client, arXiv Atom client, hybrid merge by arXiv id, PDF downloader.
- `paper_radar/extraction.py`: PDF extraction with PyMuPDF primary and pdfplumber fallback, plus cleanup wrapper.
- `paper_radar/llm.py`: OpenAI-compatible JSON chat client, relevance/summary/QA/expand prompts, quality gate.
- `paper_radar/digest.py`: Markdown digest, Telegram recap rendering, and expanded analysis rendering.
- `paper_radar/telegram.py`: Telegram Bot API sender with inline keyboards, callback answers, webhook management, and long message splitting.
- `paper_radar/bot.py`: Webhook-based bot server, expand pipeline (deep LLM analysis on user request).
- `paper_radar/daemon.py`: `PaperRadarService` orchestration, `run_once`, daily recap, watch loop, inline expand buttons on Telegram messages.
- `paper_radar/cli.py`: argparse CLI with `--run-once`, `--send-recap`, `archive-crawl`, `archive-search`, `enrich`, `serve-bot`, `expand-paper`, `set-webhook`, `delete-webhook`.
- `paper_radar/archive.py`: HistoricalCrawler (S2 bulk search), ArchiveSearcher (SQLite LIKE), RateLimiter.

## Existing Docs

- Design: `docs/superpowers/specs/2026-05-29-arxiv-paper-radar-design.md`
- Archive/query skeleton design: `docs/superpowers/specs/2026-06-03-paper-archive-query-skeleton-design.md`
- Development harness design: `docs/superpowers/specs/2026-06-03-dev-harness-design.md`
- Machine-enforced harness design: `docs/superpowers/specs/2026-06-04-machine-enforced-harness-design.md`
- Plan: `docs/superpowers/plans/2026-05-29-arxiv-paper-radar-implementation.md`
- The old design targets an MVP daemon that fetches recent arXiv AI papers, filters by relevance, downloads PDFs temporarily, summarizes and QA-gates with an LLM, writes `digests/YYYY-MM-DD.md`, and sends one Telegram recap at 21:00 Asia/Ho_Chi_Minh.

## Verification Status

Last checked on 2026-06-04 from this workspace after machine-enforced harness implementation:

```bash
scripts/harness.sh
scripts/harness.sh --pre-push
scripts/install-hooks.sh
git config --get core.hooksPath
```

Result: canonical harness passed, pre-push simulation passed, hook path installed,
and `git config --get core.hooksPath` returned `.githooks`. Ruff lint passed,
Ruff format-check passed, and unittest reported
`Ran 133 tests - OK (skipped=8)` during pre-push simulation.
Pre-commit refactor cadence check reported 3 `feat:` commits since the latest
reachable `refactor:` commit (threshold: 5). Use
`scripts/harness.sh --refactor-check-only` for the current count.

Warnings seen during tests:

- `RequestsDependencyWarning` about urllib3/chardet/charset_normalizer versions.
- `paperscraper.load_dumps` warnings that biorxiv/chemrxiv/medrxiv dumps are missing.
- PyMuPDF/SWIG deprecation warnings.

## Telegram Expand Feature Status

Implemented v1 of the Telegram expand-paper feature (2026-06-04):

- `paper_radar/bot.py`: `ExpandPipeline` (deep LLM analysis), `BotServer` (webhook HTTP server), `WebhookHandler`
- `paper_radar/telegram.py`: Inline keyboard (`make_expand_keyboard`), callback answer, webhook set/delete, long message splitting
- `paper_radar/llm.py`: `build_expand_prompt` with 13-field deep analysis skeleton
- `paper_radar/digest.py`: `render_expanded_analysis` for Telegram formatting
- `paper_radar/db.py`: `paper_expansions` table, `get_expansion`/`save_expansion` methods
- `paper_radar/config.py`: `BotConfig` dataclass with `webhook_url`/`webhook_port`
- `paper_radar/daemon.py`: Papers sent with `[🔍 Expand]` inline keyboard button
- `paper_radar/cli.py`: New subcommands: `serve-bot`, `expand-paper`, `set-webhook`, `delete-webhook`
- `paper_radar/enrichment.py`: Fixed duplicate code block (lines 135-211 removed)
- At implementation time, 115 tests passed (42 original + 38 expand feature
  tests + 35 other tests)
- Tests in `tests/test_bot_expand.py` cover: DB, LLM prompt, Telegram methods, digest rendering, expand pipeline, bot server callbacks, config, backward compatibility

### Usage

```bash
# Start webhook bot server (requires public HTTPS URL)
paper-radar serve-bot --port 8080

# Set webhook URL with Telegram
paper-radar set-webhook https://your-server.com/webhook

# Expand a paper via CLI (sends result to Telegram)
paper-radar expand-paper 2606.03988

# Expand without sending to Telegram (prints JSON to stdout)
paper-radar expand-paper 2606.03988 --no-send

# Remove webhook
paper-radar delete-webhook
```

### Configuration

Add to `config.yaml` or `.env`:
```yaml
bot:
  webhook_url_env: BOT_WEBHOOK_URL
  webhook_port: 8080
```

Or set environment variable: `BOT_WEBHOOK_URL=https://your-server.com/webhook`

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
- At implementation time, 42 tests passed (31 original + 10 archive unit + 1
  harness)
- Integration tests in `tests/test_archive_integration.py` (skip if no API key)
- Docker container builds and shows archive subcommands

## Enrichment Pipeline Status

Implemented enrichment pipeline v1 (commit `9f22680`):

- `paper_radar/enrichment.py`: ArchiveEnricher, extract_text_from_pdf (PyMuPDF), extract_introduction
- Schema: added `paper_texts` table for extracted text storage
- CLI command: `paper-radar enrich` with `--limit` and `--dry-run`
- At implementation time, 60 tests passed (42 original + 10 enrichment tests +
  8 integration tests)
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

Initial harness verification at implementation time: 42 tests passed, ruff
check passed, and ruff format passed. For the current baseline, use the
Verification Status section above.

### Machine-Enforced Harness Status

Design spec: `docs/superpowers/specs/2026-06-04-machine-enforced-harness-design.md`
Implementation plan: `docs/superpowers/plans/2026-06-04-machine-enforced-harness-implementation.md`

Machine-enforced harness is implemented so core gates are enforced by executable
checks instead of Markdown memory:

- `scripts/harness.sh` as the canonical lint/format/unittest entrypoint.
- `Makefile` alias `make verify` pointing to the canonical script.
- `.githooks/pre-push` calling `scripts/harness.sh --pre-push`.
- `scripts/install-hooks.sh` setting `core.hooksPath=.githooks`.
- a pre-push `refactor-due` hard gate that blocks when there are at least 5
  `feat:` commits since the latest reachable `refactor:` commit.

Install hooks in a new clone or tab workspace with:

```bash
scripts/install-hooks.sh
```

### OpenCode Config (`opencode.json`)

`opencode.json` is the source of truth for the default agent, small model,
subagent permissions, and debate model mappings. Do not duplicate those mappings
in docs.

The `coordinator` agent is the default entry point for OpenCode sessions.
It understands the full harness workflow and delegates to subagents.
See its prompt in `opencode.json` for the complete orchestration rules.

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
- Machine-enforced harness replaces memory-based verification with
  `scripts/harness.sh`, `make verify`, and a pre-push refactor cadence gate.
