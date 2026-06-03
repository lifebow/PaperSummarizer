# FEATURE_TITLE Autonomous Task Graph

**Date:** YYYY-MM-DD  
**Status:** Draft  

## Graph

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
