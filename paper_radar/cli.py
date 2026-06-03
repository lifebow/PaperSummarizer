from __future__ import annotations

import argparse

from .config import load_config
from .daemon import DefaultPaperLlm, PaperRadarService
from .llm import LlmClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Hourly arXiv/Semantic Scholar paper radar.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--run-once", action="store_true", help="Run one batch and exit.")
    parser.add_argument("--send-recap", help="Send recap for YYYY-MM-DD and exit.")
    args = parser.parse_args()

    config = load_config(args.config, args.env)
    llm = None
    if not args.send_recap:
        require_llm_config(config)
        llm = DefaultPaperLlm(
            LlmClient(base_url=config.llm.base_url, api_key=config.llm.api_key, model=config.llm.model)
        )
    service = PaperRadarService(config=config, llm=llm)
    if args.send_recap:
        service.send_daily_recap(args.send_recap)
    elif args.run_once:
        service.run_once()
    else:
        service.watch()


def require_llm_config(config) -> None:
    missing = []
    if not config.llm.base_url:
        missing.append("OPENAI_BASE_URL")
    if not config.llm.api_key:
        missing.append("OPENAI_API_KEY")
    if not config.llm.model:
        missing.append("OPENAI_MODEL")
    if missing:
        raise SystemExit(f"Missing LLM configuration: {', '.join(missing)}")


if __name__ == "__main__":
    main()
