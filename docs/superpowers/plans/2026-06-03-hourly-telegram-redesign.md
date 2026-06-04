# Hourly Telegram Recap Redesign Feature Plan

**Date:** 2026-06-03
**Status:** Draft
**Coordinator:** opencode coordinator
**Runner Backend:** subagent

## Goal

Replace the single-daily Telegram recap (sent at 21:00) with an hourly Telegram stream
where the first run of the day (in `daemon.timezone`) sends a full list of accepted
papers for that day, and every subsequent hourly run with new accepted papers sends
only a diff (the new batch). Hours with no new accepted papers stay silent.

## Scope

In scope:

- Add a `first-of-day full list` Telegram behavior.
- Add an `hourly diff` Telegram behavior for subsequent runs in the same day.
- Persist the `last_daily_full_sent_at` date in the `state` table so daemon restarts
  do not re-send the full list.
- Keep the daily markdown digest (`digests/YYYY-MM-DD.md`) unchanged.
- Keep `send_daily_recap(digest_date)` working as a manual CLI escape hatch
  (`paper-radar --send-recap YYYY-MM-DD`) for backward compatibility and ops recovery.
- `watch()` should not auto-call `send_daily_recap` at 21:00 anymore.
- CLI: `paper-radar` (no flags) goes into `watch()`. `paper-radar --run-once` runs one
  batch and, if it accepted new papers, sends the appropriate Telegram message
  (full vs diff). `--send-recap` keeps manual recap.

Out of scope:

- Embedding / vector search (deferred).
- Multi-user Telegram (still single chat_id).
- Configurable cadence (still 60 minutes hardcoded in `daemon.interval_minutes`).

## User Approval

- Debate decision approved: yes (user chose "Approve + implement direct").
- Acceptance criteria approved: yes.
- Debate models selected by user: not needed (direct approval).
- Final judge model selected by user: not needed.

## Design summary

1. **State**: store `last_daily_full_sent_at` (ISO date, e.g. `2026-06-03`) in
   `state` table via existing `db.set_state` / `db.get_state`.

2. **Daemon method**: `service.send_hourly_telegram(accepted_batch, now_date)`
   - If `now_date != last_daily_full_sent_at` AND `accepted_batch` is non-empty:
     send **full list** (`accepted_results_for_date(now_date)`), then
     `db.set_state("last_daily_full_sent_at", now_date)`.
   - Else if `accepted_batch` is non-empty:
     send **diff** (just the new batch, no DB query).
   - Else: do nothing (silent).

3. **Render**:
   - `render_telegram_full(date, papers)`: "Paper Radar full {date}: {N} paper(s) kept."
     followed by `render_paper_short` for each, capped at first 15 to keep Telegram
     under 4096 chars (truncate with "... and N more").
   - `render_telegram_diff(date, batch_time, papers)`: "Paper Radar +{N} {batch_time}:
     ..." with the new batch only, same truncation.
   - Reuse existing `render_paper_short` (new helper) extracted from
     `render_telegram_recap` to keep one code path.

4. **Wire into `run_once`**:
   - After `append_digest_batch(...)`, if `accepted_for_digest` non-empty, call
     `service.send_hourly_telegram(accepted_for_digest, digest_date, batch_time)`.
   - Keep `send_daily_recap` untouched, but only call it from CLI `--send-recap`.

5. **`watch()` loop**:
   - Remove the auto 21:00 recap call. Just loop `run_once()` every
     `interval_minutes`. The hourly Telegram handles user notification.

6. **CLI**:
   - `paper-radar` → `service.watch()`.
   - `paper-radar --run-once` → `service.run_once()` (which itself sends Telegram).
   - `paper-radar --send-recap 2026-06-03` → `service.send_daily_recap(...)` (manual).

7. **Backward compat**:
   - `telegram_recaps` table still updated by `send_daily_recap` (manual CLI path).
   - Markdown digest file output unchanged.
   - `tests/test_telegram_daemon.py::test_send_daily_recap_marks_sent` still passes.

## Autonomous Subagent Execution Gate

```yaml
stages:
  - id: implement
    runner: subagent
    model: fast-or-standard
    owns:
      - paper_radar/daemon.py
      - paper_radar/digest.py
      - paper_radar/db.py
      - paper_radar/cli.py
      - tests/test_telegram_daemon.py

  - id: lint
    runner: subagent
    model: fast
    command: python3 -m ruff check .
    depends_on:
      - implement

  - id: format-check
    runner: subagent
    model: fast
    command: python3 -m ruff format --check .
    depends_on:
      - implement

  - id: regression-test
    runner: subagent
    model: fast
    command: python3 -m unittest discover -v
    depends_on:
      - lint
      - format-check
```

## Feature Test Matrix

See `docs/superpowers/plans/2026-06-03-hourly-telegram-redesign-test-matrix.md`.

## Lint Before Test Gate

```bash
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m unittest discover -v
```

## Regression Gate

- `python3 -m unittest discover -v` must report all old + new tests OK.
- All existing CLI/config/db/retrieval/extraction/LLM/digest/Telegram/harness tests
  must still pass.

## Refactor Cadence Gate

This is feature 1 of the next refactor window. Refactor checkpoint will be triggered
after every 5 features per `AGENTS.md`.

## Commit Before Refactor Gate

```bash
git add paper_radar/ tests/
git commit -m "feat: hourly Telegram — first-of-day full list, subsequent diffs"
```

## Docker Deploy Smoke Gate

After implement + lint + tests pass, run `podman compose run --rm paper-radar --help`
to confirm CLI still resolves.

## Completion Checklist

- [ ] User approval recorded (done).
- [ ] Test matrix written.
- [ ] Implement subagent finished.
- [ ] Lint subagent passed.
- [ ] Format-check subagent passed.
- [ ] Regression test subagent passed.
- [ ] Docker smoke passed.
- [ ] Commit checkpoint created.
