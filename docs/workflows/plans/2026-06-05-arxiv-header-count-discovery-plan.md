# arXiv Header-Count Exact Discovery Plan

**Date:** 2026-06-05  
**Status:** Approved for implementation  
**Debate:** `docs/workflows/debates/2026-06-05-arxiv-header-count-discovery-final-decision.md`

## Goal

Use the arXiv `/list/cs/recent` latest date-section header count to discover all
metadata entries for the latest daily CS section, respecting arXiv's fixed valid
`show` values and paginating with `skip` when needed.

## Scope

- In scope:
  - Header parser for latest section date and expected total.
  - Valid `show` selection: `25, 50, 100, 250, 500, 1000, 2000`.
  - Section-aware parsing/counting so older sections do not count toward latest
    section completion.
  - Optional `skip` pagination for expected totals above 2000.
  - Small completion state in existing `state` table.
  - Offline unit tests and regression gates.
- Out of scope:
  - New release tables.
  - External queue infra.
  - Unbounded hydration/LLM/summary processing.
  - Real-network tests.

## User Approval

- Debate decision approved: yes (`tự động tiếp tục đi` after decision)
- Acceptance criteria: `phải lấy đủ` using arXiv header count as source of truth
- Debate models selected by user/project: yes
- Final judge selected by user/project: yes

## Implementation Steps

1. Add pure helpers in the arXiv retrieval layer:
   - `choose_allowed_show(total: int) -> int`
   - latest-section header parser returning section date and expected total
   - section-aware recent-list parser returning entries grouped or filtered by
     target section date.
2. Add/extend arXiv list discovery method:
   - probe with `show=50`,
   - parse latest section date/expected total,
   - check existing completion state,
   - choose valid show, fetch page(s), count target-section entries only,
   - paginate with `skip` if expected total > 2000,
   - fall back to configured discovery limit if header parsing fails.
3. Update daemon discovery to use the header-count method and persist entries
   through existing `upsert_paper_discovery`.
4. Use existing `state` keys for completion:
   - `arxiv_recent_latest_section_date`
   - `arxiv_recent_latest_expected_total`
   - `arxiv_recent_latest_discovered_count`
   - `arxiv_recent_latest_complete`
5. Mark complete only when section date and expected total match and discovered
   target-section entries are at least expected total.
6. Keep hydration/relevance/summary caps unchanged.

## Verification

Run:

```bash
scripts/harness.sh
scripts/harness.sh --pre-push
podman compose run --rm paper-radar --help
```
