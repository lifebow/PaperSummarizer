# Workflow Harness

This directory contains Markdown contracts and templates for autonomous feature
work. The files are designed for OpenCode, Codex subagents, or another agent
runner that can execute a task graph.

## Files

- `templates/feature-plan.md`: feature implementation plan skeleton with all
  required gates.
- `templates/debate-brief.md`: multi-model debate brief with user-selected model
  placeholders.
- `templates/test-matrix.md`: comprehensive feature test matrix.
- `templates/task-graph.md`: autonomous subagent task graph skeleton.

## Required Order

Use this order for feature work:

```text
debate when needed
  -> user approves final decision
  -> generate feature plan
  -> write comprehensive test matrix
  -> implement through subagents
  -> lint through subagent
  -> format-check through subagent
  -> full regression tests through subagent
  -> Docker smoke through subagent when deploy files exist
```

Lint must run before tests. Full regression tests must run before Docker smoke.

## User Inputs

The user must provide:

- feature topic,
- debate models list when debate is needed,
- final judge model,
- acceptance criteria,
- whether Docker deploy smoke is required for the current change,
- whether the workspace has a usable git checkpoint before refactor.

## Agent Roles

- Coordinator: orchestrates, reviews, and asks user questions.
- Worker subagent: edits assigned files and writes tests.
- Verification subagent: runs lint, format-check, tests, or Docker smoke.
- Debate panel: user-selected large models in OpenCode.
- Final judge: user-selected model that writes the decision memo.

## Current Project Caveats

- The Codex desktop workspace currently has no `.git` directory.
- Docker exists locally, but Docker Compose may not be installed in this
  environment. Re-check in OpenCode.
- Unit tests are offline and should stay offline.
