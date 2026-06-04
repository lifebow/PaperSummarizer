# Machine-Enforced Harness - Design

**Date:** 2026-06-04
**Status:** Approved direction, written before implementation
**Project:** `paper_radar` in `/Users/lifebow/Documents/arxiv_clone/newpapers`

## Goal

Make the project harness harder to forget by moving the core gates from prose
into executable checks. The current lint, format, and unittest commands pass,
but several harness rules are duplicated across docs and can drift. The next
harness pass should create one canonical verification entrypoint and a
versioned pre-push gate.

## Current Findings

The current baseline is healthy:

```bash
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m unittest discover -v
```

The commands pass locally, with unittest reporting 129 tests and 8 skipped
integration tests.

The weak point is not test health. It is enforceability:

- Harness commands are repeated across multiple Markdown files.
- Some docs are stale, including old test counts and old OpenCode model
  mappings.
- Workflow templates mention `docker compose` while this workspace normally
  uses `podman compose`.
- The "every 5 feature additions" refactor cadence is not backed by a durable
  counter or hook.

## Chosen Approach

Use a small, zero-dependency harness layer:

- `scripts/harness.sh`: the canonical local verification command.
- `.githooks/pre-push`: a versioned Git hook that calls the harness in pre-push
  mode.
- `scripts/install-hooks.sh`: configures `core.hooksPath=.githooks`.
- `Makefile` alias, with `make verify` calling the canonical script.
- stronger harness tests that check executable files and detect obvious doc
  drift.

This keeps the project local-first and avoids adding a new framework such as
pre-commit until the repository needs a larger cross-project hook system.

## Harness Command

The canonical script should run fail-fast in this order:

```bash
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m unittest discover -v
```

The script should print concise section headers and preserve the underlying
command output on failure. Unit tests should still skip real API integration
tests when secrets are absent.

## Pre-Push Gate

The versioned pre-push hook should call:

```bash
scripts/harness.sh --pre-push
```

Pre-push mode should run the same lint, format, and regression gates, then run
the refactor cadence gate. If any gate fails, the hook exits non-zero and blocks
the push.

Developers can still run the same checks manually before pushing:

```bash
scripts/harness.sh --pre-push
```

## Refactor Cadence Gate

Define a "feature addition" as a Git commit whose subject starts with `feat:`.
Define a "refactor checkpoint" as a Git commit whose subject starts with
`refactor:`.

The gate finds the latest reachable `refactor:` commit, then counts reachable
`feat:` commits after it:

```text
feat_count_since_latest_refactor >= 5 => block pre-push
```

If the branch contains a newer `refactor:` commit, the count resets from that
commit. The current repository state has 3 `feat:` commits after the latest
`refactor:` commit, so this gate would not block immediately.

The failure message should be explicit:

```text
REFACTOR DUE: 5 feature commits since last refactor.
Create and pass a refactor checkpoint commit before pushing more feature work.
```

This gate should run only in pre-push mode by default. Plain `scripts/harness.sh`
can report refactor status as informational, but should not block everyday local
verification unless `--pre-push` is passed.

## Documentation Cleanup

After the executable harness exists, docs should stop duplicating command lists
where possible and point to the canonical command instead. `AGENTS.md` should
remain a short handoff entrypoint, while current command behavior should live in
the script and tests.

Specific cleanup targets:

- replace stale test counts with a latest verification record only when useful,
  or remove counts that will age quickly;
- remove stale statements that the workspace lacks `.git`;
- avoid duplicating OpenCode model mappings outside `opencode.json`;
- make deploy smoke docs explicit about `podman compose` in this workspace and
  `docker compose` only where available.

## Test Plan

Extend `tests/test_project_harness.py` so it checks behavior and drift risks,
not only doc substrings:

- `scripts/harness.sh` exists and is executable.
- `.githooks/pre-push` exists and is executable.
- `scripts/install-hooks.sh` exists and mentions `.githooks`.
- the refactor cadence logic can be tested with a temporary Git repository.
- docs do not claim this workspace lacks `.git`.
- docs do not duplicate stale `lint` and `implement` model mappings that
  conflict with `opencode.json`.

The normal verification remains:

```bash
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m unittest discover -v
```

## Implementation Decisions

- Add the `Makefile` alias now because it gives humans and agents a short,
  memorable command while keeping `scripts/harness.sh` as the source of truth.
- Do not add GitHub Actions in this pass. The repository is currently operated
  as a local-first workspace, so the versioned pre-push hook is the enforcement
  layer for now.
- Count all reachable commits for refactor cadence. The current repository
  history is linear, and this is simpler than introducing first-parent semantics
  before the project needs branch-heavy release workflows.

## Non-Goals

- Do not migrate from `unittest` to pytest.
- Do not add mypy, coverage, or a larger CI stack in this pass.
- Do not require real API keys for the harness.
- Do not make every design/debate rule machine-enforced. Debate quality and
  test-matrix completeness still need coordinator judgment.
- Do not edit runtime `paper_radar` behavior except for test-safe harness
  support code if needed.
