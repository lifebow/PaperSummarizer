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

## Machine-Enforced Harness

Core verification lives in the canonical `scripts/harness.sh` command, with
`make verify` as the short alias and `.githooks/pre-push` as the versioned Git
hook.

Generated workflows should use `scripts/harness.sh` or `make verify` for local
verification and `scripts/harness.sh --pre-push` for pre-push simulation. The
pre-push mode blocks when 5 or more `feat:` commits have landed since the
latest reachable `refactor:` commit.

## Required Order

Use this order for feature work:

```text
debate when needed
  -> user approves final decision
  -> generate feature plan
  -> write comprehensive test matrix
  -> implement through subagents
  -> run scripts/harness.sh through verification subagent
  -> run scripts/harness.sh --pre-push through verification subagent
  -> Docker smoke through subagent when deploy files exist
```

The canonical harness enforces lint-before-test. Full regression tests must run
before Docker smoke.

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
- Verification subagent: runs `scripts/harness.sh`,
  `scripts/harness.sh --pre-push`, or Docker smoke.
- Debate panel: user-selected large models in OpenCode.
- Final judge: user-selected model that writes the decision memo.

## Current Project Caveats

- This workspace now has a `.git` repository for refactor checkpoints.
- Machine-enforced harness hardening is implemented; install local hooks with
  `scripts/install-hooks.sh` in new clone or tab workspaces.
- Dockerfiles exist. Podman smoke and Podman Compose smoke work locally.
- Docker Compose CLI specifically is not installed in this shell; use
  `podman compose` here or re-check `docker compose` in another OpenCode shell.
- Unit tests are offline and should stay offline.
