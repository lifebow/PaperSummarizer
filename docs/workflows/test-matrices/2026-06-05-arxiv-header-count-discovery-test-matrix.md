# arXiv Header-Count Exact Discovery Test Matrix

**Date:** 2026-06-05  
**Status:** Approved for implementation

## Happy path

- Probe header `Fri, 5 Jun 2026 (showing first 50 of 798 entries)`.
- Choose `show=1000`.
- Fetch full page and persist 798 latest-section entries.
- Mark completion state with expected=798 and discovered=798.

## Edge cases

- Boundary show values: 25, 26, 50, 51, 100, 101, 250, 251, 500, 501, 1000,
  1001, 2000, 2001.
- `show=1000` includes older section entries; only target section counts.
- Completion state skips full refetch only when date + expected + discovered +
  complete are consistent.
- Expected total changes for same date; state invalidates and refetches.

## Niche/domain cases

- Latest date section differs from daemon local date; section header remains
  source of truth.
- Target section above 2000 uses `skip` pagination.
- Pagination page includes older sections; they do not count toward target.

## Invalid input

- Malformed header falls back to configured discovery limit.
- Empty/malformed listing does not crash daemon.
- Invalid/corrupt state does not falsely skip discovery.

## Failure/retry behavior

- No-progress pagination stops safely and does not mark complete.
- Probe/fetch mismatch does not incorrectly mark complete.
- Network/list exception falls back or leaves completion unset.

## Backward compatibility

- Existing metadata-only queue behavior remains.
- Hydration, relevance, summary, digest, Telegram, and recap behavior unchanged.
- No new schema migration.

## Refactor safety

- Pure helper tests cover parser/selector boundaries.
- No real network calls in unit tests.
- Full regression command:

```bash
scripts/harness.sh
scripts/harness.sh --pre-push
```
