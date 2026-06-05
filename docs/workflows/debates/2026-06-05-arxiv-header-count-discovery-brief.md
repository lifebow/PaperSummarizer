# arXiv Header-Count Exact Discovery Debate Brief

**Date:** 2026-06-05  
**Status:** Draft  
**Backend:** opencode/subagents

## Question

How should `paper-radar` use the arXiv `/list/cs/recent` date header count,
for example `Fri, 5 Jun 2026 (showing first 50 of 798 entries)`, to guarantee
that it fetches the full latest daily section despite arXiv only allowing
`show` values of `25, 50, 100, 250, 500, 1000, 2000`?

## Context

- User requirement: `phải lấy đủ` — must fetch all papers in the daily arXiv CS
  section, not just 100 or a guessed limit.
- New observation from user:
  - `/list/cs/recent` contains a date section header like
    `Fri, 5 Jun 2026 (showing first 50 of 798 entries)`.
  - This gives a direct expected total for the latest section.
- Additional user observation:
  - `show=798` is invalid.
  - Valid show values are exactly `25, 50, 100, 250, 500, 1000, 2000`.
- Current implementation problems:
  - It uses configured limits and release-window logic rather than parsing
    the header total.
  - If it asks for a limit lower than the section total, it can persist only a
    prefix of the day.
  - If it asks for `show=1000` when the latest section has 798 entries, the page
    may include older date sections too; parser must count only target section.
- Existing architecture:
  - Metadata-first queue in `papers.archive_status`.
  - SQLite state table is available.
  - Hydration/relevance/summary stay budgeted.
  - Unit tests must be offline.

## Important arXiv Constraints

- Valid `show` values: `25, 50, 100, 250, 500, 1000, 2000`.
- Need a helper like `choose_allowed_show(total)`:
  - total 798 -> show 1000
  - total 1200 -> show 2000
  - total > 2000 -> show 2000 with `skip` pagination.
- Header count is per date section. Completion should be based on collecting
  entries from the target/latest section only:
  - target section date = first/latest date section header from probe,
  - expected_total = total count from that header,
  - complete iff collected target-section entries >= expected_total.
- If a larger show value includes older date sections, those older entries must
  not count toward target completion.

## Candidate Design A — Header-count exact fetch

1. Probe latest recent page with `show=50` (valid and cheap).
2. Parse first/latest section header date and expected total.
3. If state says that section date is complete with the same expected total,
   skip full refetch or use normal catch-up.
4. Otherwise choose allowed show value >= expected total, or 2000 if larger.
5. Fetch one or more pages with `skip`/`show` until target section entries >=
   expected total or no progress.
6. Persist only target-section entries as metadata-only discoveries for that
   release scan.
7. Mark state complete only when collected target-section entries >= expected.

## Candidate Design B — Always show=2000 latest section

Always fetch `/list/cs/recent?skip=0&show=2000`, parse the latest section
header total and entries, and mark complete when target entries >= expected.
Avoid probe/refetch two-step, but fetch more than necessary for small days.

## Candidate Design C — Existing state-machine heuristic

Ignore header totals, run high-limit discovery once per day and use low-count
heuristics. This was the previous judge direction, but may now be inferior given
the direct header total.

## Candidate Design D — Release tables now

Add dedicated release tables with expected count, discovered count, section
date, page attempts, failures, and completion. More auditable but more schema.

## Required Debater Sections

Each debater must answer independently with:

- Recommendation:
- Main argument:
- Risks:
- Testability:
- Simplicity and reuse:
- Refactor impact:
- Deployment impact:
- What would change my mind:

## Judge Requirements

The final judge must:

- compare header-count exact fetch vs always-show=2000 vs heuristic state machine
  vs release tables,
- account for valid `show` values only,
- specify parser/section-completion rules,
- specify state keys and completion semantics,
- list required tests,
- stop at user approval gate.
