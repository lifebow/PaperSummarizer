# Development Harness - Design

**Date:** 2026-06-03  
**Status:** Approved direction, written before implementation  
**Project:** `paper_radar` in `/Users/lifebow/Documents/arxiv_clone/newpapers`

## Goal

Add a lightweight development harness around the current `paper_radar` project so
future archive/query work can be refactored safely.

The harness should provide:

- a linter and formatter,
- a clear test command,
- Markdown docs for setup and development,
- a small refactor safety layer without changing runtime behavior.

## Chosen Approach

Use Ruff plus the existing `unittest` test suite.

This keeps the project small and matches the current codebase. The project
already has 26 `unittest` tests passing, so the harness should strengthen that
path instead of forcing a migration to pytest or a larger CI stack.

## Scope

### `pyproject.toml`

Add optional development dependencies and tool configuration:

- `ruff`
- a `dev` optional dependency group
- Ruff lint and format settings

Keep runtime dependencies unchanged unless verification shows an existing import
requires a missing package.

### Docs

Add Markdown docs:

- `README.md`: project purpose, setup, configuration, and common commands.
- `docs/development.md`: development workflow, test/lint commands, refactor
  rules, and notes about avoiding real network/API calls in unit tests.

### Tests

Keep the current `unittest` suite as the source of truth:

```bash
python3 -m unittest discover -v
```

The harness should not require network access for tests. Existing fake clients
and injected callables should remain the preferred testing pattern.

### Refactor

Only perform small refactors needed to satisfy linting and make future archive
work safer. Avoid behavior changes.

Possible refactor targets:

- reduce broad or unused imports,
- make module boundaries clearer where lint flags issues,
- keep CLI/service behavior stable,
- preserve all existing tests.

## Verification

The implementation should pass:

```bash
python3 -m unittest discover -v
python3 -m ruff check .
python3 -m ruff format --check .
```

If Ruff is not installed in the current environment, install via the declared dev
dependencies or report the blocker clearly.

## Non-Goals

- Do not migrate to pytest in this harness pass.
- Do not add mypy or coverage gates yet.
- Do not introduce pre-commit yet.
- Do not implement the archive/query skeleton in this pass.
- Do not change API keys or real service configuration.

## Repository Note

This workspace currently has no `.git` directory, so the spec cannot be
committed here.
