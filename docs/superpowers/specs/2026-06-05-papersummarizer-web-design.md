# PaperSummarizer Web — Design Spec

Date: 2026-06-05
Status: Approved (design), pending implementation plan

## Goal

A web UI to browse accepted papers from the paper-radar pipeline, filterable by
topic (one or more) and grouped by day. Reuses the existing SQLite data written
by the bot; runs as an additional service alongside the bot.

## Decisions (locked)

- **Filter type:** topic keyword (multi-select). Topics derive from the
  `topics.queries` list in `config.yaml`.
- **Scope:** only `accepted` papers (those that passed relevance + QA and have a
  summary), i.e. the same content sent to Telegram.
- **Deploy:** FastAPI service reading the existing SQLite read-only, running on
  the same server as the bot, added to `docker-compose`.

## Topic tagging (the new piece)

The pipeline does not store which query a paper matched (relevance LLM scores all
queries jointly). We tag papers **on the fly** at request time.

- Pure function `tag_paper(paper, queries) -> list[str]`.
- For each query in `config.yaml` `topics.queries`, do a case-insensitive phrase
  match against `title + abstract + summary` (summary/idea text from
  `summary_json`). A query that appears → that topic tag is attached.
- A paper that matches no query (LLM accepted it semantically, no literal
  keyword) is bucketed under **"Other"**.
- No schema change, no migration. Tags always reflect the current config — edit
  `config.yaml` queries and the web filters update accordingly.

**Trade-off:** literal phrase matching is cruder than semantic matching. Upgrade
path (out of scope for v1): have the QA LLM emit a `matched_topics` field, store
it, and backfill — more precise but requires pipeline changes.

## Architecture

- New module `paper_radar/web.py` — FastAPI app, server-rendered HTML (Jinja2).
  No SPA.
- SQLite opened **read-only** (URI `mode=ro`, WAL) so it never contends with the
  bot's writes.
- Styling via **Tailwind (CDN)** — dark mode default, no build step.
- CLI: new `serve-web` subcommand (uvicorn).
- `docker-compose`: new `paper-radar-web` service, mounts `./data` read-only,
  exposes port 8080, `restart: unless-stopped`.

## Routes & data flow

- `GET /?date=<YYYY-MM-DD>&topics=<slug,slug,...>`
  1. Resolve `date` (default: latest day with accepted results).
  2. `db.accepted_results_for_date(date)` (already exists).
  3. `tag_paper()` each paper against config queries.
  4. Filter to papers carrying at least one selected topic (OR semantics);
     no topics selected → show all.
  5. Render.
- `GET /paper/{arxiv_id}` — optional detail page (single paper, full summary).
- Multiple filters = multiple selected topic chips, combined with OR.
- Defaults: latest day, all topics.

## UI

- **Left sidebar:** list of days (newest → oldest) with a count badge per day,
  from `dates_with_accepted_results()`.
- **Top bar:** topic filter chips, multi-select toggle —
  `All / <each config query> / Other`. Selected state reflected in URL.
- **Main:** one card per accepted paper:
  - Title (links to arXiv `abs` and `pdf`)
  - Authors
  - Colored topic chips
  - Scores: relevance / idea / grounding
  - Summary + idea/contribution
  - Expand control for longer detail
- **Empty state:** friendly message when a day/topic combo has no papers.

## Module boundaries

- `paper_radar/db.py`: add `dates_with_accepted_results()`; reuse
  `accepted_results_for_date()`. Add a read-only connect path.
- `paper_radar/topics.py` (new): `tag_paper()` and topic-slug helpers — pure,
  unit-testable, no I/O.
- `paper_radar/web.py`: thin FastAPI routes — call db + tagger + render only.
- `templates/`: `base.html`, `index.html`, card partial; optional
  `paper_detail.html`.

## Error handling

- No data for the requested date → empty state, still render sidebar.
- Unknown topic slug in query string → ignored.
- DB busy (bot writing) → read-only connection + brief retry on `OperationalError`.
- Missing/empty `summary_json` → render title/authors/scores without summary.

## Testing

- Unit: `tag_paper()` — phrase match hits, case-insensitivity, "Other" bucket,
  multi-tag.
- `db.dates_with_accepted_results()` — ordering, counts.
- FastAPI `TestClient`: home renders, date filter, topic filter (single/multi),
  empty state, unknown-topic tolerance.

## Out of scope (YAGNI for v1)

- Authentication / access control.
- Free-text search box.
- Pagination (a day has at most a few dozen accepted papers).
- SPA / client-side framework.
- Stored LLM-derived topic tags.
