# arXiv Header-Count Discovery — Product/Operator Argument

## Recommendation

Adopt Design A using existing state keys, not release tables. Probe header,
choose allowed show, paginate if needed, count only target section, and complete
only when collected target entries reach expected total.

## Main argument

`phải lấy đủ` means exact/latest-section completion, not a guessed limit. Header
count is the runtime source of truth; state prevents repeated full refetch.

## Risks

Parser fragility, cross-section contamination, >2000 pagination no-progress,
and stale state when expected total changes.

## Testability

Fixture tests for header parse, allowed show selection, target-only counting,
state invalidation, pagination, and completion checks.

## Simplicity and reuse

Small helpers plus existing generic state and metadata-first queue. No release
tables.

## Refactor impact

Contained to recent discovery and parser helpers; downstream unchanged.

## Deployment impact

Low. Existing configs stay valid; arXiv header count takes priority.

## What would change my mind

Unstable headers, need for historical release audit tables, or acceptance of
best-effort rather than full discovery.
