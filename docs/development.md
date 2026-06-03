# Development

## Harness

Use the lightweight harness before and after refactors:

```bash
python3 -m unittest discover -v
python3 -m ruff check .
python3 -m ruff format --check .
```

Use Ruff to apply formatting:

```bash
python3 -m ruff format .
```

Use Ruff to apply safe lint fixes:

```bash
python3 -m ruff check . --fix
```

## Testing Pattern

No real network calls should happen in unit tests. Prefer injected callables, fake clients, temporary directories, and local SQLite databases.

The current test suite uses `unittest`:

```bash
python3 -m unittest discover -v
```

Integration tests hit real APIs and are skipped when credentials are missing:

```bash
# Run only integration tests (requires API key)
SEMANTIC_SCHOLAR_API_KEYS=your_key python3 -m unittest tests.test_archive_integration -v

# Run all tests (unit tests pass offline, integration tests skip)
python3 -m unittest discover -v
```

## Refactor Rules

- Keep behavior stable unless a spec explicitly says otherwise.
- Run the full harness before and after refactors.
- Keep API keys in `.env` or environment variables only.
- Prefer small modules with injected external clients so tests stay offline.
- Update `AGENTS.md` when a future agent needs new handoff context.

## OpenCode And Subagent Workflow

Use `docs/opencode.md` when moving this project to OpenCode or another
subagent-capable runner.

The short version:

- user chooses debate panel models and the final judge model,
- large models in OpenCode run architecture debate,
- coordinator orchestrates and reviews but does not run mechanical checks
  directly when subagents are available,
- fast subagents run lint, format-check, full regression tests, and Docker smoke,
- lint must pass before tests,
- full regression tests must pass before deploy smoke,
- feature plans must include comprehensive niche and edge testcase matrices,
- every 5 feature additions require a refactor checkpoint,
- code must be committed before refactor so it can be reverted.

Templates live in `docs/workflows/templates/`.

## Container Build

Use Podman Compose in this workspace:

```bash
podman compose build
podman compose run --rm paper-radar --help
```

The Dockerfile keeps runtime dependency installation in a separate cacheable
layer before installing the project wheel with `--no-deps`. If runtime
dependencies in `pyproject.toml` change, update the matching Dockerfile
dependency layer too.

Do not leave repeated smoke-test images around. Keep `paper-radar:latest` and
clean dangling images when needed:

```bash
podman image prune
```

If Podman Compose leaves a created pod behind after smoke tests, remove only
this project's pod:

```bash
podman pod rm pod_newpapers
```

## Fixed OpenCode Agents

Current project agents in `opencode.json`:

- `lint`: `opencode/deepseek-v4-flash-free`
- `implement`: `acbpro/glm-5.1`
- `debate-deepseek`: `opencode/deepseek-v4-flash-free`
- `debate-mimo`: `opencode/mimo-v2.5-free`
- `debate-nemotron`: `opencode/nemotron-3-super-free`
- `debate-glm`: `acbpro/glm-5.1`
- `debate-gpt55`: `acbpro/gpt-5.5`
- `debate-judge`: `acbpro/gpt-5.5`

Verify they are loaded with:

```bash
opencode agent list
```
