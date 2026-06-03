# Development Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight Ruff + unittest + Markdown documentation harness around `paper_radar`.

**Architecture:** Keep the existing runtime modules and `unittest` tests. Add harness assertions that document the expected dev tooling, configure Ruff in `pyproject.toml`, add setup/development docs, then run Ruff format/check as the behavior-neutral refactor pass.

**Tech Stack:** Python 3.10+, `unittest`, Ruff 0.15.x-compatible configuration, Markdown docs.

---

### Task 1: Add Harness Tests

**Files:**
- Create: `tests/test_project_harness.py`

- [ ] **Step 1: Create a failing test for the development harness**

Create `tests/test_project_harness.py`:

```python
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectHarnessTests(unittest.TestCase):
    def test_pyproject_declares_ruff_harness(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("[project.optional-dependencies]", text)
        self.assertIn("ruff>=0.8", text)
        self.assertIn("[tool.ruff]", text)
        self.assertIn('target-version = "py310"', text)
        self.assertIn("[tool.ruff.lint]", text)

    def test_project_docs_describe_common_commands(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        development = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")

        self.assertIn("paper-radar", readme)
        self.assertIn("python3 -m unittest discover -v", readme)
        self.assertIn("python3 -m ruff check .", development)
        self.assertIn("python3 -m ruff format --check .", development)
        self.assertIn("No real network calls", development)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_project_harness -v
```

Expected: FAIL because `README.md`, `docs/development.md`, and Ruff config do not exist yet.

### Task 2: Add Ruff Configuration

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update `pyproject.toml`**

Replace `pyproject.toml` with:

```toml
[project]
name = "paper-radar"
version = "0.1.0"
description = "Hourly arXiv paper radar with LLM summaries and Telegram daily recaps."
requires-python = ">=3.10"
dependencies = [
  "requests>=2.31",
  "paperscraper>=0.2",
  "pymupdf4llm>=0.0.17",
  "pdfplumber>=0.11",
]

[project.optional-dependencies]
dev = [
  "ruff>=0.8",
]

[project.scripts]
paper-radar = "paper_radar.cli:main"

[tool.ruff]
target-version = "py310"
line-length = 120
src = ["paper_radar", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
ignore = []

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
line-ending = "lf"
```

- [ ] **Step 2: Run harness test again**

Run:

```bash
python3 -m unittest tests.test_project_harness -v
```

Expected: still FAIL because docs are not created yet.

### Task 3: Add Markdown Docs

**Files:**
- Create: `README.md`
- Create: `docs/development.md`

- [ ] **Step 1: Create `README.md`**

Create a concise user-facing README with these sections:

```markdown
# paper-radar

`paper-radar` is a local arXiv paper radar for AI topics. It discovers recent papers, stores processing state in SQLite, extracts PDFs, asks an OpenAI-compatible LLM for summaries and QA scores, writes daily Markdown digests, and can send Telegram recaps.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
```

## Configuration

Runtime configuration is read from `config.yaml` plus environment variables or `.env`.

Expected secrets:

- `SEMANTIC_SCHOLAR_API_KEYS`
- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Do not commit real API keys.

## Common Commands

```bash
python3 -m unittest discover -v
python3 -m ruff check .
python3 -m ruff format --check .
paper-radar --run-once
paper-radar --send-recap 2026-05-29
```

## Project Notes

Current design docs and plans live under `docs/superpowers/`. See `AGENTS.md` for the latest agent handoff notes.
```

- [ ] **Step 2: Create `docs/development.md`**

Create development workflow docs:

```markdown
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

## Refactor Rules

- Keep behavior stable unless a spec explicitly says otherwise.
- Run the full harness before and after refactors.
- Keep API keys in `.env` or environment variables only.
- Prefer small modules with injected external clients so tests stay offline.
- Update `AGENTS.md` when a future agent needs new handoff context.
```

- [ ] **Step 3: Run harness test**

Run:

```bash
python3 -m unittest tests.test_project_harness -v
```

Expected: PASS.

### Task 4: Ruff-Driven Refactor

**Files:**
- Modify: `tests/test_telegram_daemon.py`
- Format: `paper_radar/*.py`, `tests/*.py`

- [ ] **Step 1: Remove the known unused import**

Change this import in `tests/test_telegram_daemon.py`:

```python
from paper_radar.config import AppConfig, DaemonConfig, FilterConfig, PathConfig, TelegramConfig, TopicConfig
```

to:

```python
from paper_radar.config import AppConfig, FilterConfig, PathConfig, TelegramConfig, TopicConfig
```

- [ ] **Step 2: Run Ruff format**

Run:

```bash
python3 -m ruff format .
```

Expected: Ruff reformats project files and exits successfully.

- [ ] **Step 3: Run Ruff check**

Run:

```bash
python3 -m ruff check .
```

Expected: PASS.

### Task 5: Final Verification And Handoff

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Run full tests**

Run:

```bash
python3 -m unittest discover -v
```

Expected: PASS.

- [ ] **Step 2: Run full harness**

Run:

```bash
python3 -m unittest discover -v
python3 -m ruff check .
python3 -m ruff format --check .
```

Expected: all commands PASS.

- [ ] **Step 3: Update `AGENTS.md` verification notes**

Add a note that the harness is implemented and record the final verification commands.

Use this content:

```markdown
## Harness Status

Implemented development harness:

- Ruff configured in `pyproject.toml`.
- Existing `unittest` suite retained.
- Harness tests added in `tests/test_project_harness.py`.
- Setup docs added in `README.md`.
- Development workflow docs added in `docs/development.md`.

Latest harness verification:

```bash
python3 -m unittest discover -v
python3 -m ruff check .
python3 -m ruff format --check .
```
```

- [ ] **Step 4: Note git limitation**

No commit can be created in this workspace because it has no `.git` directory.
