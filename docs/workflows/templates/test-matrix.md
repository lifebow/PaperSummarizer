# FEATURE_TITLE Test Matrix

**Date:** YYYY-MM-DD  
**Status:** Draft  

## Purpose

Define comprehensive tests before implementation so future refactors can preserve
behavior with confidence.

## Happy path

- Expected normal input:
- Expected normal output:
- Existing feature interactions:

## Edge cases

- Empty input:
- Minimal valid input:
- Maximum expected input:
- Duplicate input:
- Missing optional fields:

## Niche/domain cases

- Domain-specific unusual case:
- Format variant:
- Unicode or punctuation case:
- Date/time boundary:
- Source/provider mismatch:

## Invalid input

- Invalid type:
- Invalid value:
- Missing required field:
- Malformed external data:

## Failure/retry behavior

- External client failure:
- Timeout:
- Partial result:
- Retryable error:
- Non-retryable error:

## Backward compatibility

- Existing CLI behavior still works:
- Existing config behavior still works:
- Existing DB behavior still works:
- Existing digest/Telegram behavior still works:
- Full regression command:

```bash
scripts/harness.sh
```

## Refactor safety

- Public behavior assertion:
- Data shape assertion:
- Error message/status assertion:
- No real network calls in unit tests:
- Temporary files cleaned up:

## Lint and verification order

```bash
scripts/harness.sh
scripts/harness.sh --pre-push
```
