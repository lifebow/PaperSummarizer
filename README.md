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

## OpenCode Harness

For autonomous agent work, start with:

- `docs/opencode.md`
- `docs/workflows/README.md`
- `docs/workflows/templates/`

These documents define the debate, subagent, regression, refactor, and deploy
smoke gates that future feature work must follow.
