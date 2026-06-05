# Guaranteed Full Daily arXiv Discovery Plan

**Date:** 2026-06-05  
**Status:** Superseded by `2026-06-05-arxiv-header-count-discovery-plan.md`  
**Debate:** `docs/workflows/debates/2026-06-05-guaranteed-full-daily-discovery-final-decision.md`

## Goal

Superseded plan. The later arXiv header-count insight showed that `/list/cs/recent`
publishes a section total such as `showing first 50 of 798 entries`, and arXiv
only accepts fixed `show` values. Use the header-count plan instead.

Original goal: ensure paper-radar performs high-limit metadata-only arXiv discovery at least
once per local day, regardless of release-window timing, so late starts and
restarts do not silently fall back to discovering only 100 papers.

## Scope

- In scope:
  - State-driven daily full-discovery decision.
  - Observability state for full-discovery count.
  - Suspiciously-low/empty/failure retry behavior.
  - Offline unit tests.
- Out of scope:
  - New release tables.
  - External queue infra.
  - Pagination beyond configured `release_discovery_limit`.
  - Increasing LLM/PDF/summary budgets.

## User Approval

- Debate decision approved: yes
- Acceptance criteria approved: yes (`phải lấy đủ` / must fetch full daily metadata)
- Debate models selected by user: yes, reused project-selected debate panel
- Final judge model selected by user: yes, `acbpro/gpt-5.5`

## Implementation Steps

1. Add daemon helpers for full-discovery state:
   - daily key based on project local date / digest date,
   - `full_discovery_done:<YYYY-MM-DD>`,
   - `full_discovery_count:<YYYY-MM-DD>`.
2. Change `_discover_list_only()` limit selection:
   - if today's full discovery is not done, use `release_discovery_limit` even
     outside release window,
   - if done, use `normal_discovery_limit`,
   - keep release window only as a hint/logging concept.
3. Mark full discovery complete only after successful high-limit discovery with
   a believable count.
4. Do not mark complete on exception, zero count, or suspiciously-low count.
5. Preserve metadata-first queue and all downstream caps.
6. Update tests that assumed normal limit outside release window without state.

## Suspicious-Low Policy

For v1, suspicious-low means a high-limit discovery returns a positive count
below `min(hydrate_metadata_per_run, max_papers_per_run, 50)` when current time
is before or near expected release completion. The implementation may choose a
simpler explicit helper, but must be deterministic and tested. Failure and zero
must never complete.

## Verification

Run:

```bash
scripts/harness.sh
scripts/harness.sh --pre-push
podman compose run --rm paper-radar --help
```

Use coordinator fallback if `@lint` reports the known `ProviderModelNotFoundError`.
