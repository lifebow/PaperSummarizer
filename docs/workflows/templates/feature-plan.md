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

Use the canonical harness command for mechanical verification. It runs lint,
format-check, and full unittest regression in the required order. Use pre-push
mode to include the refactor cadence gate.

```yaml
stages:
  - id: implement-feature
    runner: subagent
    model: fast-or-standard
    owns:
      - FILES_TO_EDIT

  - id: verify
    runner: subagent
    model: fast
    command: scripts/harness.sh

  - id: pre-push-check
    runner: subagent
    model: fast
    command: scripts/harness.sh --pre-push
    depends_on:
      - verify

  - id: docker-smoke
    runner: subagent
    model: fast
    command: podman compose run --rm paper-radar --help
    depends_on:
      - pre-push-check
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

The canonical harness must pass before full tests are considered verified:

```bash
scripts/harness.sh
```

If lint or format-check fails inside the harness, stop and fix it before
claiming regression verification.

## Regression Gate

Before marking the feature done:

- run the full existing test suite,
- confirm old CLI/config/db/retrieval/extraction/LLM/digest/Telegram/harness
  tests still pass,
- do not delete or replace old tests with only new-feature tests.

Command:

```bash
scripts/harness.sh
```

## Refactor Cadence Gate

After every 5 feature additions, stop and run a refactor checkpoint before
starting the next feature.

Pre-push blocks when there are at least 5 `feat:` commits since the latest
reachable `refactor:` commit:

```bash
scripts/harness.sh --pre-push
```

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
podman compose build
podman compose run --rm paper-radar --help
```

The smoke run must not call real APIs.

## Completion Checklist

- [ ] User decision approved.
- [ ] Comprehensive tests written first.
- [ ] `scripts/harness.sh` subagent passed.
- [ ] `scripts/harness.sh --pre-push` subagent passed.
- [ ] Docker smoke subagent passed or blocker recorded.
- [ ] Commit checkpoint exists before any refactor.
- [ ] `AGENTS.md` updated when handoff context changed.
