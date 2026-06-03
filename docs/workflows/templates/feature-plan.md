# FEATURE_TITLE Feature Plan

**Date:** YYYY-MM-DD  
**Status:** Draft  
**Coordinator:** COORDINATOR_NAME  
**Runner Backend:** subagent | opencode  

## Goal

Describe the feature in one sentence.

## Scope

- In scope:
- Out of scope:

## User Approval

- Debate decision approved: yes | no | not needed
- Acceptance criteria approved: yes | no
- Debate models selected by user: yes | no | not needed
- Final judge model selected by user: yes | no | not needed

## Autonomous Subagent Execution Gate

The coordinator must orchestrate the work. The coordinator must not run
mechanical checks directly when subagents or OpenCode runners are available.

```yaml
stages:
  - id: implement-feature
    runner: subagent
    model: fast-or-standard
    owns:
      - FILES_TO_EDIT

  - id: lint
    runner: subagent
    model: fast
    command: python3 -m ruff check .

  - id: format-check
    runner: subagent
    model: fast
    command: python3 -m ruff format --check .

  - id: regression-test
    runner: subagent
    model: fast
    command: python3 -m unittest discover -v
    depends_on:
      - lint
      - format-check

  - id: docker-smoke
    runner: subagent
    model: fast
    command: docker compose run --rm paper-radar --help
    depends_on:
      - regression-test
```

## Feature Test Matrix

Complete `docs/workflows/templates/test-matrix.md` for this feature before
implementation starts.

Required categories:

- Happy path:
- Edge cases:
- Niche/domain cases:
- Invalid input:
- Failure/retry behavior:
- Backward compatibility:
- Refactor safety:

## Lint Before Test Gate

The lint commands must pass before full tests run:

```bash
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m unittest discover -v
```

If lint fails, stop and fix lint before running tests.

## Regression Gate

Before marking the feature done:

- run the full existing test suite,
- confirm old CLI/config/db/retrieval/extraction/LLM/digest/Telegram/harness
  tests still pass,
- do not delete or replace old tests with only new-feature tests.

Command:

```bash
python3 -m unittest discover -v
```

## Refactor Cadence Gate

After every 5 feature additions, stop and run a refactor checkpoint before
starting the next feature.

Refactor checkpoint checklist:

- Remove duplication.
- Keep APIs small.
- Reuse helpers only when reuse is real.
- Keep extension easy without over-engineering.
- Verify tests cover public behavior before refactor.
- Run lint before tests after refactor.

## Commit Before Refactor Gate

Before refactor:

```bash
git status --short
git add <changed-files>
git commit -m "feat: FEATURE_TITLE checkpoint"
```

If there is no `.git` directory:

```text
BLOCKED: cannot refactor safely because workspace has no .git repository.
```

## Docker Deploy Smoke Gate

When Docker files exist, finish with:

```bash
docker compose build
docker compose run --rm paper-radar --help
```

The smoke run must not call real APIs.

## Completion Checklist

- [ ] User decision approved.
- [ ] Comprehensive tests written first.
- [ ] Lint subagent passed.
- [ ] Format-check subagent passed.
- [ ] Full regression test subagent passed.
- [ ] Docker smoke subagent passed or blocker recorded.
- [ ] Commit checkpoint exists before any refactor.
- [ ] `AGENTS.md` updated when handoff context changed.
