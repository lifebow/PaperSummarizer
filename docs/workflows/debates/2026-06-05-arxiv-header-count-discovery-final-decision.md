# arXiv Header-Count Exact Discovery — Final Decision

**Date:** 2026-06-05  
**Status:** Pending user approval  

## Decision

Choose **Design A / A+ header-count exact fetch** with conservative fallbacks and
completion safeguards.

Implementation should:

1. Probe arXiv recent listing with `show=50`.
2. Parse the latest date section header to determine target section and expected
   paper count.
3. Choose the smallest valid `show` value that can cover the count:
   `25, 50, 100, 250, 500, 1000, 2000`.
4. If expected count is greater than `2000`, paginate with `skip`.
5. Parse and count papers from the target/latest date section only.
6. Persist a small completion state keyed by latest section date and expected
   total.
7. Mark complete only when stored date, stored expected total, discovered count,
   and complete flag are all consistent.
8. If header parsing fails, fall back to the configured discovery limit rather
   than blocking the daemon.

## Agreements

- Current discovery can miss part of a daily arXiv batch.
- New logic must be section-aware.
- Valid `show` values are constrained.
- Parser/fixture tests are required.
- Parser fragility is the main risk.
- State should prevent repeated completed-section refetches.
- New release tables are not needed yet.
- Pagination or another strategy is needed above 2000 entries.

## Conflicts

Header-count exact fetch vs bounded overfetch. Skeptic prefers `show=2000` or a
heuristic because HTML parsing is fragile. The judge accepts the risk but chooses
header-count because bounded overfetch still fails above 2000 and still needs
section-aware parsing to avoid cross-section contamination.

## Strongest points by panelist

- Architect: A+ gives exact count + pagination + cached completion.
- Implementer: pure helpers make the risky logic testable.
- Skeptic: arXiv HTML is not a stable API; fallback/logging must exist.
- Product/operator: existing state is enough; complete only when collected >= expected.
- Coordinator-architect: completion must tie to section date + expected total.

## Rejected alternatives

- Always `show=2000`: simpler but not enough above 2000 and still needs section parsing.
- Refined heuristic: cannot prove `lấy đủ` when header count exists.
- Current/minimal logic: does not satisfy requirement.
- Release tables: premature for immediate bugfix.

## Implementation constraints

- Use Design A/A+ with small state footprint.
- Do not add release tables.
- Valid show values only: `25, 50, 100, 250, 500, 1000, 2000`.
- Probe with `show=50`.
- Parse latest date section and expected total.
- Select smallest valid show >= expected total, or `2000` with pagination.
- Count target/latest section only.
- Avoid older-section contamination.
- Complete state is valid only when date + expected total + discovered count +
  complete flag are consistent.
- Header parse failure falls back to configured discovery limit.
- Guard pagination no-progress loops.
- Validate probe/fetch race before marking complete.
- Keep helpers pure where possible.

## Required tests

- Header parse success/failure.
- Show selection boundaries.
- Multiple date sections; target-only counting.
- Small batch one selected show.
- Large batch near 2000.
- Above-2000 pagination with skip.
- No-progress pagination stop.
- State skip when date/expected/discovered/complete match.
- State invalidation when date or expected total changes.
- No complete when discovered < expected.
- Header parse fallback uses configured limit.
- Probe/fetch mismatch does not incorrectly complete.
- Existing metadata queue/hydration unchanged.
- Full regression through canonical harness.

## User approval note

This is only a debate decision. It does not become an implementation plan until
the user explicitly approves it.
