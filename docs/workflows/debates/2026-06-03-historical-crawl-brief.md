# Historical Crawl Debate Brief

**Date:** 2026-06-03
**Status:** Ready for debate
**Backend:** opencode

## Question

How should paper_radar crawl and store historical CS papers (1-5 years old) for long-term local archive and future query support?

## Context

- Current `paper_radar` is a daily radar: fetches recent papers, filters by relevance, stores in SQLite, generates daily Markdown digests.
- User wants to backfill papers from 1-5 years ago to build a searchable archive.
- User explicitly does NOT want to store full PDFs. Just metadata + links for later reading.
- Existing spec (`docs/superpowers/specs/2026-06-03-paper-archive-query-skeleton-design.md`) already proposes expanded schema with categories, dates, extraction status, summaries, embeddings.
- Current retrieval uses Semantic Scholar API (primary) + arXiv Atom (fallback).
- Rate limits exist on both APIs. Need pagination and throttling.
- Project uses SQLite, Python, unittest, Ruff, Podman.

## Constraints

- No full PDF storage. Links only.
- Must not break existing daily radar/digest flow.
- Must handle rate limits gracefully (1-5 years of papers = millions of entries).
- Should be incrementally enrichable (summary, scoring later).
- Keep SQLite as first archive DB.
- Must support future query: "which papers relate to X?"

## Non-Goals

- No vector database or embedding generation in first version.
- No real-time sync. Batch crawl is fine.
- No external search service (Meilisearch, etc.) yet.

## Your Role

Write an independent argument recommending an architecture. Cover:

- Data source choice and crawl strategy
- Schema additions or changes
- Pagination / rate-limit approach
- Storage decisions (what to keep, what to skip)
- How to make this incrementally enrichable
- Risks and what would change your mind

Write independently. Do not see other debaters' arguments.
