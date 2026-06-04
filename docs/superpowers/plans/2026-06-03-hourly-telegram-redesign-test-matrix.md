# Hourly Telegram Recap Redesign Test Matrix

**Date:** 2026-06-03
**Status:** Draft

## Happy path

- First hourly run in a new day with 2 accepted papers → Telegram receives
  **full list** (2 papers) and DB `state.last_daily_full_sent_at` becomes today.
- Second hourly run same day with 1 new accepted paper → Telegram receives
  **diff** (1 paper) and `last_daily_full_sent_at` unchanged.
- Third hourly run same day with 0 new papers → no Telegram message, no DB write.
- Fourth hourly run same day with 3 new papers → Telegram receives **diff**
  (3 papers only, not cumulative).
- New day starts → `last_daily_full_sent_at` becomes the new date, first hourly
  run sends **full list** again.

## Edge cases

- First hourly run with 0 new papers → no Telegram (don't send empty).
- First hourly run with 1 paper, then second hourly with 0 papers → only first
  sent, no second (silent).
- First hourly run with 1 paper, then second hourly with 1 paper → first sends
  full (1 paper), second sends diff (1 paper).
- Daemon restart mid-day after first-of-day full already sent → next hourly
  sends diff (state persists across restarts).
- Markdown digest file still appends every batch (unchanged behavior).
- Telegram credentials missing → exception propagates but DB state is NOT marked
  as "sent" (don't poison the state).

## Niche/domain cases

- Telegram full list > 4096 chars (20+ papers) → truncate with "... and N more"
  and keep first 15 papers rendered.
- `daemon.timezone` is `Asia/Ho_Chi_Minh`; date rollover at 00:00 local time,
  not UTC. Make sure date used in `now_date` is local-date, not UTC.
- `digest_date` derived from `local_now(timezone)` not `now_utc_iso()`.

## Invalid input

- `accepted_batch` is `None` → treat as empty, no Telegram.
- `accepted_batch` has entries but all are filtered downstream → still no
  Telegram (only non-empty list triggers).
- `last_daily_full_sent_at` is corrupted/empty string → treat as "never sent",
  send full on first non-empty run.

## Failure/retry behavior

- Telegram sender raises during first-of-day full → state `last_daily_full_sent_at`
  is NOT updated, so next hourly will retry full. (Idempotent: re-sends full list,
  user gets the full list twice — acceptable, since Telegram dedup by user is
  impossible without storage.)
- Telegram sender raises during diff → state is NOT updated for this run;
  the next hourly will still send a diff (which may be just the same batch again
  if no new papers) — acceptable.
- `db.set_state` raises after Telegram sends full → log error, continue. Full
  list was sent; next hourly will re-send full (acceptable duplicate).
- `db.get_state` raises → log error, fall back to "send full" (safe default).

## Backward compatibility

- `service.send_daily_recap(date)` still works, still updates `telegram_recaps`,
  still returns bool. Used by CLI `--send-recap`.
- `tests/test_telegram_daemon.py::test_send_daily_recap_marks_sent` still passes.
- `tests/test_telegram_daemon.py::test_run_once_accepts_paper_writes_digest_and_cleans_pdf`
  still passes (no Telegram dependency in this test).
- `service.watch()` no longer calls `send_daily_recap` at 21:00 — but no test
  asserts the old auto-recap behavior, so backward compat is preserved.
- Daily markdown digest output unchanged.
- `digests/YYYY-MM-DD.md` content unchanged.
- CLI flag surface: `paper-radar`, `paper-radar --run-once`, `paper-radar --send-recap`,
  `archive-crawl`, `archive-search`, `enrich` all unchanged.

## Refactor safety

- New behavior is contained in `daemon.send_hourly_telegram` + `digest.render_*`
  helpers. No public API rename.
- Old `render_telegram_recap(date, papers)` still exported from `digest.py` and
  still used by `send_daily_recap` (manual path).
- No real network calls in unit tests: Telegram sender injected via test double.
- Temporary SQLite DBs in test tmpdirs (no leftover state).
- New tests in `tests/test_telegram_daemon.py` (existing file) — no new test file
  to keep discovery simple.

## Test commands

```bash
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m unittest tests.test_telegram_daemon -v
python3 -m unittest discover -v
```

## Test list to add (all in `tests/test_telegram_daemon.py`)

1. `test_hourly_full_first_of_day_marks_state_and_sends_all`
2. `test_hourly_diff_after_full_sends_only_new_batch`
3. `test_hourly_no_new_papers_silent`
4. `test_hourly_full_again_on_new_day_after_state_rollover`
5. `test_hourly_full_truncates_when_many_papers`
6. `test_hourly_telegram_failure_does_not_mark_state_sent`
7. `test_send_daily_recap_still_works_for_manual_cli_recovery` (regression)
