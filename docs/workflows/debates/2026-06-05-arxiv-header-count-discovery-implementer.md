# arXiv Header-Count Discovery — Implementer Argument

## Recommendation

Adopt Design A. Add pure helpers for header parsing and valid-show selection,
then implement probe → parse → choose → paginate → persist → state.

## Main argument

arXiv tells us how many entries are in the latest section. The implementation is
mechanical: translate total into valid `show`/`skip` values and fetch until
target-section count reaches expected total.

## Risks

HTML format changes, section boundary ambiguity, pagination race, and invalid
future show values.

## Testability

Test show mapping, header parse, malformed parse fallback, section filtering,
798-in-one-page, >2000 pagination, stale-state skip, no-progress termination.

## Simplicity and reuse

Reuse existing state and fake-session test patterns. No schema migration.

## Refactor impact

Low to moderate: retrieval helpers plus daemon discovery rewrite.

## Deployment impact

Pure Python behavior change; downstream pipeline unchanged.

## What would change my mind

Unreliable header format, pagination rate limits, or evidence `show=2000` alone
already covers all practical days.
