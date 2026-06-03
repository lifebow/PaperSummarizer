from __future__ import annotations

import argparse
import os
import sys

from .archive import ArchiveSearcher, HistoricalCrawler, RateLimiter
from .config import load_config
from .daemon import DefaultPaperLlm, PaperRadarService
from .db import PaperRadarDb
from .llm import LlmClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Hourly arXiv/Semantic Scholar paper radar.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")

    subparsers = parser.add_subparsers(dest="command")

    archive_crawl = subparsers.add_parser("archive-crawl", help="Crawl historical papers from Semantic Scholar")
    archive_crawl.add_argument("--from", dest="from_date", required=True, help="Start date YYYY-MM-DD")
    archive_crawl.add_argument("--to", dest="to_date", required=True, help="End date YYYY-MM-DD")
    archive_crawl.add_argument("--categories", help="Comma-separated categories (e.g. cs.AI,cs.CL)")
    archive_crawl.add_argument("--delay", type=float, default=1.0, help="Minimum seconds between API calls")
    archive_crawl.add_argument("--page-size", type=int, default=1000, help="Results per API page")

    archive_search = subparsers.add_parser("archive-search", help="Search archived papers")
    archive_search.add_argument("--query", required=True, help="Search query")
    archive_search.add_argument("--since", help="Start date YYYY-MM-DD")
    archive_search.add_argument("--until", help="End date YYYY-MM-DD")
    archive_search.add_argument("--category", help="Filter by primary category")
    archive_search.add_argument("--limit", type=int, default=50, help="Max results")

    parser.add_argument("--run-once", action="store_true", help="Run one batch and exit.")
    parser.add_argument("--send-recap", help="Send recap for YYYY-MM-DD and exit.")
    args = parser.parse_args()

    if args.command == "archive-crawl":
        _handle_archive_crawl(args)
        return
    if args.command == "archive-search":
        _handle_archive_search(args)
        return

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


def _handle_archive_crawl(args: argparse.Namespace) -> None:
    api_keys_str = os.environ.get("SEMANTIC_SCHOLAR_API_KEYS", "")
    api_keys = [k.strip() for k in api_keys_str.split(",") if k.strip()]
    if not api_keys:
        print(
            "Warning: No SEMANTIC_SCHOLAR_API_KEYS set. Using unauthenticated requests (rate limited).",
            file=sys.stderr,
        )
        api_keys = [""]

    db_path = os.environ.get("PAPER_RADAR_DB", "data/radar.sqlite3")
    db = PaperRadarDb(db_path)
    db.initialize()

    categories = None
    if args.categories:
        categories = [c.strip() for c in args.categories.split(",") if c.strip()]

    crawler = HistoricalCrawler(
        db,
        api_keys=api_keys,
        rate_limiter=RateLimiter(min_interval=args.delay),
    )
    result = crawler.crawl(
        args.from_date,
        args.to_date,
        categories=categories,
        page_size=args.page_size,
    )
    print(f"Crawl complete: {result.papers_upserted} papers upserted across {len(result.years_completed)} years")


def _handle_archive_search(args: argparse.Namespace) -> None:
    db_path = os.environ.get("PAPER_RADAR_DB", "data/radar.sqlite3")
    db = PaperRadarDb(db_path)
    db.initialize()

    searcher = ArchiveSearcher(db)
    results = searcher.search(
        args.query,
        since=args.since,
        until=args.until,
        category=args.category,
        limit=args.limit,
    )

    if not results:
        print("No results found.")
        return

    print(f"Found {len(results)} results:\n")
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r.published_at}] {r.title}")
        print(f"   arXiv: https://arxiv.org/abs/{r.arxiv_id}")
        print(f"   Category: {r.primary_category}")
        print()


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
