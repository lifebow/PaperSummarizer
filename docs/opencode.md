# OpenCode Autonomous Harness

This document is the handoff contract for running `paper-radar` work in
OpenCode or any agent runner with subagents. It tells the coordinator what to
delegate, what to keep for itself, how users choose debate models, and which
gates must pass before code is considered ready.

## Purpose

Use this harness when adding features, refactoring, or preparing deployment work.
The goal is to keep development autonomous without losing control of quality:

- debate hard design choices with user-selected large models,
- implement small tasks through bounded worker subagents,
- run mechanical checks through fast subagents,
- require full regression coverage before moving on,
- require versioned checkpoints before refactor,
- finish with Docker/Compose smoke verification when deploy files exist.

## Coordinator Rules

The coordinator owns orchestration and judgment. It does not own mechanical
execution when subagents or OpenCode runners are available.

The coordinator must:

- read `AGENTS.md`, `README.md`, `docs/development.md`, and this file first,
- create or load a workflow task graph,
- ask the user to choose debate panel models and the final judge model,
- spawn subagents or OpenCode jobs for each autonomous task,
- enforce dependency order between tasks,
- review subagent summaries and artifacts,
- stop when a gate fails,
- ask the user for approval after debate decision and before implementation plan.

The coordinator must not run mechanical checks directly when a subagent runner is
available. In particular, the coordinator must not run mechanical checks directly
for lint, format-check, full regression tests, or Docker smoke. Delegate those to
a fast subagent and only inspect the result.

## Runner Types

Use these runner labels in generated workflow documents.

```yaml
runners:
  coordinator:
    purpose: orchestration, user questions, integration judgment
    model: current coordinator model

  subagent:
    purpose: mechanical checks, small implementation tasks, focused reviews
    model: fast/simple model when the task is mechanical

  opencode:
    purpose: multi-model debate and autonomous large-model reasoning
    model: user selected
```

The exact runner backend may be `local`, `subagent`, or `opencode`, but the
workflow must preserve the same gates and dependencies.

## User Model Selection Gate

Before any automated debate starts, the user must choose:

- the debate backend,
- the list of debate models,
- the role assigned to each model,
- the final judge model.

Use this selection block in debate configs:

```yaml
debate:
  backend: opencode
  user_selected: true
  panel:
    - role: architect
      model: USER_CHOSEN_MODEL
    - role: skeptic
      model: USER_CHOSEN_MODEL
    - role: implementer
      model: USER_CHOSEN_MODEL
  judge:
    role: final_decision
    model: USER_CHOSEN_JUDGE_MODEL
```

Do not hardcode a required vendor or model. Suggested roles are allowed, but the
model list and final judge model belong to the user.

## Debate Flow

Use debate for architecture choices, storage choices, refactor strategy, deploy
strategy, or any decision that will shape future work.

```text
coordinator creates debate brief
  -> user chooses panel models and judge model
  -> runner: opencode launches independent debaters
  -> each debater writes an argument artifact
  -> runner: opencode launches final judge
  -> judge compares arguments and writes decision artifact
  -> user reviews and approves decision
  -> only then create implementation plan
```

Debaters must write independently. The final judge must cite or summarize panel
arguments instead of inventing new evidence. If the user does not approve the
decision, revise the brief and rerun the debate.

## Autonomous Subagent Execution Gate

Implementation plans must be split into small tasks. The coordinator creates a
task graph and delegates executable steps.

```yaml
stages:
  - id: generate-or-edit
    runner: subagent
    model: fast-or-standard

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

Subagents must report:

- command run,
- exit code,
- important stdout/stderr,
- files changed if they edited files,
- blockers if the environment is missing a tool.

## Lint Before Test Gate

Lint and format-check must run before full tests:

```bash
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m unittest discover -v
```

If lint fails, stop. Do not run tests until lint issues are fixed and
format-check passes.

## Regression Gate

Every feature must prove old behavior still works. The full existing test suite
must pass before a task is marked done:

```bash
python3 -m unittest discover -v
```

Do not replace old tests with only new-feature tests. Keep CLI, config, DB,
retrieval, extraction, LLM, digest, daemon, Telegram, and harness tests running.

## Feature Test Matrix Gate

Every new feature plan must define tests before implementation:

- happy path,
- edge cases,
- niche/domain cases,
- invalid input,
- failure or retry behavior,
- backward compatibility with old behavior,
- refactor-safety assertions for public behavior.

If a feature cannot name niche cases, the coordinator must ask for clarification
or run debate before implementation.

## Refactor Cadence Gate

After every 5 feature additions, stop and run a refactor checkpoint before adding
feature 6.

The checkpoint must review:

- duplication,
- module boundaries,
- API size,
- reuse opportunities,
- extension points,
- unnecessary abstraction,
- dead code,
- test coverage for refactor safety.

Keep it simple. Extract reusable helpers only when reuse is real.

## Commit Before Refactor Gate

Before a refactor starts, the current feature work must be committed or otherwise
versioned so it can be reverted.

Required commands in a git workspace:

```bash
git status --short
git add <changed-files>
git commit -m "feat: <feature checkpoint>"
```

If the workspace has no `.git` directory, the refactor is blocked:

```text
BLOCKED: cannot refactor safely because workspace has no .git repository.
Create or initialize a git repo, or provide another versioned checkpoint first.
```

This repository path is currently known to lack `.git` in the Codex desktop
workspace. Re-check in OpenCode before refactoring.

## Docker Deploy Smoke Gate

When Docker files exist, finish with deploy smoke verification through subagents:

```bash
docker compose build
docker compose run --rm paper-radar --help
```

The smoke command must not call real APIs. It only proves the image builds,
installs the package, and exposes the CLI entrypoint. Running the daemon requires
valid `.env` secrets and is not part of the smoke gate.

If Docker Compose is missing, report a blocker instead of claiming deploy is
verified.

## Stop Conditions

Stop and return to the user when:

- user has not selected debate models,
- final judge decision is not user approved,
- lint fails,
- regression tests fail,
- Docker smoke fails,
- commit-before-refactor is blocked,
- a subagent reports `BLOCKED`,
- a worker edited outside its assigned scope,
- generated artifacts omit any required gate.

## Minimal OpenCode Handoff Checklist

Before handing this project to OpenCode, confirm:

- `docs/opencode.md` exists,
- `docs/workflows/README.md` exists,
- workflow templates exist under `docs/workflows/templates/`,
- `python3 -m ruff check .` passes,
- `python3 -m ruff format --check .` passes,
- `python3 -m unittest discover -v` passes,
- user has selected debate models and final judge model for any debate run.
