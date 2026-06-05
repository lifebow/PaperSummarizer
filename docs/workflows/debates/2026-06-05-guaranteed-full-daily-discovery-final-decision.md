# Guaranteed Full Daily arXiv Discovery — Final Decision

**Date:** 2026-06-05  
**Status:** Pending user approval  

## Decision

Adopt a **hybrid daily discovery state machine**: run at least one high-limit
metadata-only discovery for each local arXiv day, repeat it until the day is
considered complete, and only then fall back to the normal discovery limit.

The key rule is:

> Correctness is driven by per-day SQLite state, not by the release window.

Recommended behavior:

1. For today's local arXiv day, check existing SQLite state.
2. If full daily discovery for that day is not complete, use
   `release_discovery_limit` regardless of current time.
3. If the high-limit fetch succeeds and returns a believable nonzero count,
   store completion state for that day.
4. Store at least:
   - `full_discovery_done:<YYYY-MM-DD>`
   - `full_discovery_count:<YYYY-MM-DD>`
   - preferably a completion timestamp/value.
5. Once the day is marked complete, use `normal_discovery_limit` for later
   catch-up runs.
6. On failure, empty response, suspiciously low response, or missing/corrupt
   state, fail safe by using high limit again later.
7. Treat `release_window_start` / `release_window_end` as logging or expected
   timing hints only, not as correctness gates.

## Agreements

- Current release-window gating can miss the daily batch.
- The fix should stay SQLite-first.
- No external queue/service/infrastructure is needed.
- Metadata-first queue remains the foundation.
- Full discovery stores metadata; hydration/LLM processing stays capped.
- Network failures must not mark discovery complete.
- Tests must be offline and mocked.
- Repeated high-limit scans must be idempotent.

## Conflicts

The main conflict is completeness-first stateful discovery vs simplicity-first
rolling discovery. The skeptic's raised-normal-limit proposal is simpler but
does not satisfy the user's explicit hard requirement: `phải lấy đủ`.

There is also a completion-heuristic conflict: marking done after any nonzero
fetch is too permissive; completion must avoid tiny/partial false positives.

## Strongest points by panelist

- Architect: release window must be hint, not correctness gate.
- Implementer: existing state table makes this small and schema-free.
- Skeptic: state machines add failure modes and should stay minimal.
- Product/operator: current bug is silent data loss; counts improve observability.
- Coordinator-architect: suspiciously low counts should retry rather than complete.

## Rejected alternatives

- Keep release-window-gated full discovery: does not meet requirement.
- Only raise `normal_discovery_limit`: lowers miss probability but lacks guarantee.
- Always high limit forever: robust but unnecessarily wasteful after daily scan.
- New release tables/external infra: premature for this bugfix.
- Mark complete after any nonzero fetch: risks silent false completion.

## Implementation constraints

- Use existing SQLite `state` storage.
- Keep metadata-first queue and budgeted processing.
- Do not expand LLM/PDF budgets.
- Discovery completeness must not depend on release window.
- Failure/empty/suspicious-low responses must not mark done.
- Missing/corrupt/stale state fails safe to high discovery limit.
- Store count state for observability.
- Handle local date boundaries explicitly.
- No real network calls in unit tests.

## Required tests

1. Late start at 11:00/14:00 with no state uses high limit.
2. Completed day uses normal limit.
3. Network failure does not mark complete.
4. Empty response does not mark complete.
5. Suspiciously low count retries.
6. Successful high-limit discovery stores done and count state.
7. Corrupt/missing state fails safe to high limit.
8. Repeated high-limit scans are idempotent.
9. Yesterday's completion does not suppress today's high scan.
10. Empty/nonmatching release-window config does not gate correctness.
11. Existing normal-window test is updated to state-driven behavior.
12. Budget separation: high metadata discovery does not uncap LLM/summary work.
13. No real network in unit tests.
14. Full regression remains green.

## User approval note

This decision is **not yet an implementation plan**. Coordinator must present it
to the user and stop. No implementation planning or code changes until user
approval.
