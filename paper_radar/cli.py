from __future__ import annotations

import argparse
import logging
import sys

from .archive import ArchiveSearcher, HistoricalCrawler, RateLimiter
from .bot import BotServer, ExpandPipeline
from .config import load_config
from .daemon import DefaultPaperLlm, PaperRadarService
from .db import PaperRadarDb
from .enrichment import ArchiveEnricher
from .llm import LlmClient
from .telegram import TelegramSender

logger = logging.getLogger(__name__)


def _get_db(args) -> PaperRadarDb:
    config = load_config(args.config, args.env)
    db = PaperRadarDb(config.paths.database)
    db.initialize()
    return db


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

    enrich = subparsers.add_parser("enrich", help="Extract text and introduction from archived papers")
    enrich.add_argument("--limit", type=int, default=50, help="Max papers to process")
    enrich.add_argument("--dry-run", action="store_true", help="Show what would be processed")

    serve_bot = subparsers.add_parser("serve-bot", help="Start bot server for expand requests")
    serve_bot.add_argument("--port", type=int, help="Override webhook port")
    serve_bot.add_argument(
        "--poll",
        action="store_true",
        help="Use long-polling instead of webhook (no public URL needed)",
    )

    serve_web = subparsers.add_parser("serve-web", help="Start the web UI for browsing accepted papers")
    serve_web.add_argument("--host", default="0.0.0.0", help="Bind host")
    serve_web.add_argument("--port", type=int, default=8080, help="Bind port")

    expand_paper = subparsers.add_parser("expand-paper", help="Expand a paper analysis and send to Telegram")
    expand_paper.add_argument("arxiv_id", help="arXiv ID to expand")
    expand_paper.add_argument("--no-send", action="store_true", help="Print result instead of sending to Telegram")

    set_webhook = subparsers.add_parser("set-webhook", help="Set Telegram webhook URL")
    set_webhook.add_argument("url", help="Webhook URL to register")

    subparsers.add_parser("delete-webhook", help="Remove Telegram webhook")

    parser.add_argument("--run-once", action="store_true", help="Run one batch and exit.")
    parser.add_argument("--send-recap", help="Send recap for YYYY-MM-DD and exit.")
    args = parser.parse_args()

    if args.command == "archive-crawl":
        _handle_archive_crawl(args)
        return
    if args.command == "archive-search":
        _handle_archive_search(args)
        return
    if args.command == "enrich":
        _handle_enrich(args)
        return
    if args.command == "serve-bot":
        _handle_serve_bot(args)
        return
    if args.command == "serve-web":
        _handle_serve_web(args)
        return
    if args.command == "expand-paper":
        _handle_expand_paper(args)
        return
    if args.command == "set-webhook":
        _handle_set_webhook(args)
        return
    if args.command == "delete-webhook":
        _handle_delete_webhook(args)
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
    config = load_config(args.config, args.env)
    api_keys = config.semantic_scholar.api_keys
    if not api_keys:
        print(
            "Warning: No SEMANTIC_SCHOLAR_API_KEYS set. Using unauthenticated requests (rate limited).",
            file=sys.stderr,
        )
        api_keys = [""]

    db = _get_db(args)

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
    db = _get_db(args)

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


def _handle_enrich(args: argparse.Namespace) -> None:
    db = _get_db(args)

    enricher = ArchiveEnricher(db)
    results = enricher.run_batch(limit=args.limit, dry_run=args.dry_run)

    if not results:
        print("No papers to enrich.")
        return

    extracted = sum(1 for r in results if r.status == "extracted")
    errors = sum(1 for r in results if r.status == "error")
    skipped = sum(1 for r in results if r.status in ("no_pdf_url", "empty_text"))

    print(f"Enrichment complete: {extracted} extracted, {errors} errors, {skipped} skipped")

    for r in results[:10]:
        status_icon = "✓" if r.status == "extracted" else "✗" if r.status == "error" else "○"
        intro_len = len(r.introduction_text)
        print(f"  {status_icon} {r.arxiv_id}: {r.status} (intro: {intro_len} chars)")

    if len(results) > 10:
        print(f"  ... and {len(results) - 10} more")


def _handle_serve_bot(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config(args.config, args.env)
    require_llm_config(config)
    db = _get_db(args)
    llm_client = LlmClient(base_url=config.llm.base_url, api_key=config.llm.api_key, model=config.llm.model)
    telegram = TelegramSender(bot_token=config.telegram.bot_token, chat_id=config.telegram.chat_id)

    # Full pipeline service for hourly crawl
    llm = DefaultPaperLlm(llm_client)
    radar_service = PaperRadarService(config=config, db=db, llm=llm, telegram=telegram)

    if args.port:
        from dataclasses import replace

        config = replace(config, bot=replace(config.bot, webhook_port=args.port))
    server = BotServer(config=config, db=db, llm=llm_client, telegram=telegram, radar_service=radar_service)
    if args.poll:
        server.start_polling()
    else:
        server.start()


def _handle_serve_web(args: argparse.Namespace) -> None:
    import uvicorn

    from .web import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config(args.config, args.env)
    db = _get_db(args)
    app = create_app(db, config.topics.filters)
    logger.info("Serving web UI on http://%s:%d", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port)


def _handle_expand_paper(args: argparse.Namespace) -> None:
    import json as json_mod

    config = load_config(args.config, args.env)
    require_llm_config(config)
    db = _get_db(args)
    llm_client = LlmClient(base_url=config.llm.base_url, api_key=config.llm.api_key, model=config.llm.model)
    telegram = TelegramSender(bot_token=config.telegram.bot_token, chat_id=config.telegram.chat_id)

    if args.no_send:
        cached = db.get_expansion(args.arxiv_id)
        if cached:
            print(json_mod.dumps(cached.get("skeleton", {}), indent=2, ensure_ascii=False))
            return
        paper = db.get_paper_by_arxiv_id(args.arxiv_id)
        if not paper:
            print(f"Paper not found: {args.arxiv_id}", file=sys.stderr)
            sys.exit(1)
        full_text = ""
        text_data = db.get_paper_text(paper["id"])
        if text_data:
            full_text = text_data.get("full_text", "")
        from .llm import build_expand_prompt

        system, user = build_expand_prompt(paper["title"], paper["abstract"], full_text)
        result = llm_client.complete_json(system, user)
        db.save_expansion(paper["id"], args.arxiv_id, result)
        print(json_mod.dumps(result, indent=2, ensure_ascii=False))
    else:
        pipeline = ExpandPipeline(db=db, llm=llm_client, telegram=telegram)
        status = pipeline.expand_and_send(args.arxiv_id, config.telegram.chat_id)
        print(f"Expand {args.arxiv_id}: {status}")


def _handle_set_webhook(args: argparse.Namespace) -> None:
    config = load_config(args.config, args.env)
    telegram = TelegramSender(bot_token=config.telegram.bot_token, chat_id=config.telegram.chat_id)
    result = telegram.set_webhook(args.url)
    print(f"Webhook set: {result}")


def _handle_delete_webhook(args: argparse.Namespace) -> None:
    config = load_config(args.config, args.env)
    telegram = TelegramSender(bot_token=config.telegram.bot_token, chat_id=config.telegram.chat_id)
    result = telegram.delete_webhook()
    print(f"Webhook deleted: {result}")


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
