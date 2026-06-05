# Guaranteed Full Daily arXiv Discovery Test Matrix

**Date:** 2026-06-05  
**Status:** Superseded by `2026-06-05-arxiv-header-count-discovery-test-matrix.md`

This matrix was superseded after the user pointed out that arXiv's recent page
header exposes exact section totals and fixed valid `show` values. Use the
header-count matrix instead.

## Happy path

- Late daemon start at 11:00 or 14:00 with no full-discovery state uses
  `release_discovery_limit`.
- Successful high-limit discovery persists metadata-only papers and writes done
  and count state.
- Later same-day run with done state uses `normal_discovery_limit`.

## Edge cases

- Empty release-window config still uses high limit when state is absent.
- Yesterday's done state does not suppress today's high-limit discovery.
- Repeated high-limit scans are idempotent and do not duplicate papers.
- Release window is not the correctness gate.

## Niche/domain cases

- arXiv release shifts late; 11:00/14:00 starts still high-scan.
- Local date boundary uses daemon timezone consistently with digest date.
- Recent list may contain prior-day overlap; upsert remains idempotent.

## Invalid input

- Corrupt state value fails safe to high-limit discovery.
- Missing state fails safe to high-limit discovery.

## Failure/retry behavior

- arXiv/list exception does not write done/count state.
- Zero response does not write done state.
- Suspiciously low response does not write done state and next run retries high
  limit.

## Backward compatibility

- Existing config loads unchanged.
- Existing DB schema unchanged.
- Existing digest/Telegram/recap behavior unchanged.
- Processing caps still bound hydration/relevance/summary work.

## Refactor safety

- Public `run_once()` return remains compatible.
- No real network calls in unit tests.
- Full regression command:

```bash
scripts/harness.sh
scripts/harness.sh --pre-push
```
