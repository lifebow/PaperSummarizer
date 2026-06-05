# arXiv Release Metadata-First Queue Test Matrix

**Date:** 2026-06-05  
**Status:** Approved  

## Purpose

Ensure paper-radar can ingest arXiv's large daily release cheaply, persist all discovered paper IDs/title/link records, and process them gradually without cost spikes or regressions.

## Happy path

- Expected normal input:
  - Fake arXiv list page with 250+ papers during release window.
  - Mixed categories including configured AI categories.
- Expected normal output:
  - All discovered unique IDs are stored as minimal `metadata_only` records without `/abs` hydration for every record.
  - Up to `hydrate_metadata_per_run` papers are hydrated and marked `queued`.
  - Up to configured processing caps are relevance scored and summarized.
- Existing feature interactions:
  - Digest append still works for accepted papers.
  - Telegram paper cards still include Expand buttons.

## Edge cases

- Empty input:
  - Empty list page produces no queued records and no noisy Telegram spam if empty scans are suppressed.
- Minimal valid input:
  - One list entry with ID and no title still stores a valid minimal record with PDF URL.
- Maximum expected input:
  - Fake 2000-entry release list stores all unique entries and hydrates/processes only bounded subsets.
- Duplicate input:
  - Duplicate arXiv IDs in list page are deduped.
  - Existing `accepted`/`rejected_*` records are not reset to `metadata_only`.
- Missing optional fields:
  - Missing category/title in list HTML does not crash discovery.

## Niche/domain cases

- Domain-specific unusual case:
  - Configured category `cs.AI` fetches broad `cs` list but records parsed primary categories when present.
- Format variant:
  - arXiv IDs with version suffixes normalize consistently.
- Unicode or punctuation case:
  - Titles with Unicode/math punctuation store correctly.
- Date/time boundary:
  - Release-window start/end around 07:00 and 09:30 Asia/Ho_Chi_Minh use release discovery limit.
  - Outside window uses normal discovery behavior.
- Source/provider mismatch:
  - arXiv list-only records still work when Semantic Scholar fields are empty.

## Invalid input

- Invalid type:
  - Bad config values should fail or coerce consistently with existing config parser behavior.
- Invalid value:
  - Negative or zero limits should be handled safely; zero should disable that stage or mean no cap only if existing semantics require it.
- Missing required field:
  - List entry without arXiv ID is skipped.
- Malformed external data:
  - Malformed arXiv HTML fallback preserves IDs when possible and does not crash.

## Failure/retry behavior

- External client failure:
  - List fetch failure does not corrupt existing queue.
  - `/abs` hydration failure marks/retries appropriately without losing minimal record.
- Timeout:
  - Downloader/extractor/LLM timeouts preserve retry semantics.
- Partial result:
  - Some `/abs` hydration successes and failures in one run leave consistent statuses.
- Retryable error:
  - Existing `retry_later` requeue behavior still works.
- Non-retryable error:
  - Paper-level error does not fail entire release queue.

## Backward compatibility

- Existing CLI behavior still works:
  - `paper-radar --run-once`, `--send-recap`, `serve-bot`, `expand-paper` retain behavior.
- Existing config behavior still works:
  - Configs without new release fields load with defaults.
- Existing DB behavior still works:
  - Existing DB rows without new schema entities remain valid.
  - No new release/job/version tables are required.
- Existing digest/Telegram behavior still works:
  - Existing rendering and Expand buttons remain.
- Full regression command:

```bash
scripts/harness.sh
```

## Refactor safety

- Public behavior assertion:
  - `run_once()` still returns `found_count`, `accepted_count`, and `error_count`.
- Data shape assertion:
  - `papers` records from list-only discovery have stable fields and status.
- Error message/status assertion:
  - Failed papers have `archive_status`/`last_error` populated consistently.
- No real network calls in unit tests:
  - Use fake retrievers/clients/LLM/Telegram/downloader/extractor.
- Temporary files cleaned up:
  - Existing PDF cleanup behavior remains covered.

## Lint and verification order

```bash
scripts/harness.sh
scripts/harness.sh --pre-push
podman compose run --rm paper-radar --help
```
