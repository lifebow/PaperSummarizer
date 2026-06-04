# FEATURE_TITLE Autonomous Task Graph

**Date:** YYYY-MM-DD  
**Status:** Draft  

## Graph

Harness hardening note: the approved design
`docs/superpowers/specs/2026-06-04-machine-enforced-harness-design.md` will add
`scripts/harness.sh`, `make verify`, and a pre-push refactor cadence gate. Until
that implementation exists, keep the explicit command graph below. After it
exists, prefer the canonical harness command in generated task graphs.

```yaml
feature: FEATURE_TITLE
coordinator:
  responsibilities:
    - ask user for missing decisions
    - spawn subagents
    - review results
    - stop on failed gates
  forbidden_when_subagents_exist:
    - running lint directly
    - running tests directly
    - running Docker smoke directly

stages:
  - id: debate
    runner: opencode
    backend: opencode
    models: user_selected
    judge_model: USER_CHOSEN_JUDGE_MODEL
    outputs:
      - final-decision.md

  - id: implement
    runner: subagent
    model: fast-or-standard
    depends_on:
      - debate

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

  - id: docker-smoke
    runner: subagent
    model: fast
    command: docker compose run --rm paper-radar --help
    depends_on:
      - regression-test
```

## Result Contract

Every subagent returns:

- status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
- command or files changed,
- exit code when command-based,
- summary of output,
- blocker details when blocked.
