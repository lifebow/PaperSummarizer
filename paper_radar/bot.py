from __future__ import annotations

import json
import logging
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from .config import AppConfig
from .db import PaperRadarDb
from .digest import render_expanded_analysis
from .enrichment import download_pdf
from .extraction import extract_introduction, extract_text_from_pdf_bytes
from .llm import LlmClient, build_expand_prompt
from .telegram import TelegramSender

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Shared helpers
# -------------------------------------------------------------------

LONG_POLL_TIMEOUT = 60  # seconds for getUpdates long-polling


class ExpandPipeline:
    """Handles the deep expansion analysis of a paper."""

    def __init__(
        self,
        *,
        db: PaperRadarDb,
        llm: LlmClient,
        telegram: TelegramSender,
    ):
        self.db = db
        self.llm = llm
        self.telegram = telegram

    def expand_and_send(self, arxiv_id: str, chat_id: str) -> str:
        """Expand a paper and send the result to Telegram. Returns status string."""
        cached = self.db.get_expansion(arxiv_id)
        if cached:
            self._send_expansion(cached, arxiv_id, chat_id)
            return "cached"

        paper = self.db.get_paper_by_arxiv_id(arxiv_id)
        if not paper:
            self.telegram.send_message(f"❌ Paper not found: {arxiv_id}", chat_id=chat_id)
            return "not_found"

        full_text = self._get_full_text(paper)
        if not full_text:
            self.telegram.send_message(
                f"❌ Could not extract text for: {arxiv_id}",
                chat_id=chat_id,
            )
            return "no_text"

        system, user = build_expand_prompt(paper["title"], paper["abstract"], full_text)
        try:
            skeleton = self.llm.complete_json(system, user)
        except Exception as e:
            logger.error("Expand LLM failed for %s: %s", arxiv_id, e)
            self.telegram.send_message(
                f"❌ Analysis failed for: {arxiv_id}",
                chat_id=chat_id,
            )
            return "llm_error"

        self.db.save_expansion(paper["id"], arxiv_id, skeleton)

        expansion = {"skeleton": skeleton, "arxiv_id": arxiv_id}
        self._send_expansion(expansion, arxiv_id, chat_id, paper=paper)
        return "expanded"

    def _get_full_text(self, paper: dict[str, Any]) -> str:
        """Get full text from DB or extract from PDF."""
        text_data = self.db.get_paper_text(paper["id"])
        if text_data and text_data.get("full_text"):
            return text_data["full_text"]

        pdf_url = paper.get("pdf_url", "")
        if not pdf_url and paper.get("arxiv_id"):
            pdf_url = f"https://arxiv.org/pdf/{paper['arxiv_id']}.pdf"
        if not pdf_url:
            return ""

        try:
            pdf_bytes = download_pdf(pdf_url)
            full_text = extract_text_from_pdf_bytes(pdf_bytes)
            if full_text.strip():
                intro = extract_introduction(full_text, paper.get("abstract", ""))
                self.db.upsert_paper_text(
                    paper["id"],
                    full_text=full_text[:100000],
                    introduction_text=intro,
                    extraction_status="extracted",
                    extractor_name="pymupdf",
                )
                return full_text
        except Exception as e:
            logger.error("PDF extraction failed for expand %s: %s", paper.get("arxiv_id"), e)
        return ""

    def _send_expansion(
        self,
        expansion: dict[str, Any],
        arxiv_id: str,
        chat_id: str,
        *,
        paper: dict[str, Any] | None = None,
    ) -> None:
        """Format and send expansion result to Telegram."""
        text = render_expanded_analysis(expansion, paper=paper)
        # Add author affiliations if available
        if paper:
            affiliations = paper.get("author_affiliations") or []
            if affiliations:
                unique_affs = list(dict.fromkeys(affiliations))
                aff_text = f"\nAffiliations: {', '.join(unique_affs[:5])}\n"
                lines = text.split("\n")
                lines.insert(2, aff_text)
                text = "\n".join(lines)
        # Strip Markdown — LLM-generated content may break Telegram Markdown.
        # Send as plain text (no parse_mode) for reliability.
        self.telegram.send_long_message(text, chat_id=chat_id, parse_mode=None)


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Telegram webhook."""

    bot_server: BotServer

    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            update = json.loads(body) if body else {}
            self.bot_server.handle_update(update)
        except Exception as e:
            logger.error("Webhook handler error: %s", e)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("Webhook request: %s", format % args)


class BotServer:
    """Webhook-based Telegram bot server for handling expand requests."""

    def __init__(
        self,
        *,
        config: AppConfig,
        db: PaperRadarDb,
        llm: LlmClient,
        telegram: TelegramSender,
    ):
        self.config = config
        self.db = db
        self.telegram = telegram
        self.pipeline = ExpandPipeline(db=db, llm=llm, telegram=telegram)

    def start(self) -> None:
        """Start the webhook server."""
        port = self.config.bot.webhook_port
        webhook_url = self.config.bot.webhook_url

        if webhook_url:
            result = self.telegram.set_webhook(webhook_url)
            logger.info("Webhook registered: %s", result)

        handler_class = type("Handler", (WebhookHandler,), {"bot_server": self})
        server = HTTPServer(("0.0.0.0", port), handler_class)
        logger.info("Bot server listening on port %d", port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("Bot server shutting down")
            server.shutdown()

    def start_polling(self) -> None:
        """Start long-polling loop — no public URL needed."""
        import requests as _requests

        # Delete any existing webhook so getUpdates works
        self.telegram.delete_webhook()
        logger.info("Webhook deleted, starting polling mode")

        base = f"https://api.telegram.org/bot{self.telegram.bot_token}"
        offset = 0

        logger.info("Polling for updates (Ctrl+C to stop)...")
        try:
            while True:
                try:
                    resp = _requests.post(
                        f"{base}/getUpdates",
                        json={
                            "offset": offset,
                            "timeout": LONG_POLL_TIMEOUT,
                            "allowed_updates": ["callback_query", "message"],
                        },
                        timeout=LONG_POLL_TIMEOUT + 10,
                    )
                    body = resp.json()
                except Exception as exc:
                    logger.warning("getUpdates error: %s — retrying in 5s", exc)
                    time.sleep(5)
                    continue

                updates = body.get("result", [])
                for update in updates:
                    offset = max(offset, update.get("update_id", 0) + 1)
                    try:
                        self.handle_update(update)
                    except Exception as exc:
                        logger.exception("Error handling update %s: %s", update.get("update_id"), exc)

        except KeyboardInterrupt:
            logger.info("Polling stopped")

    def handle_update(self, update: dict[str, Any]) -> None:
        """Process an incoming Telegram update."""
        callback_query = update.get("callback_query")
        if callback_query:
            self._handle_callback(callback_query)
            return

        message = update.get("message", {})
        text = message.get("text", "")
        if text.startswith("/expand"):
            self._handle_expand_command(message)

    def _handle_callback(self, callback_query: dict[str, Any]) -> None:
        """Handle inline keyboard callback."""
        data = callback_query.get("data", "")
        chat_id = str(callback_query.get("message", {}).get("chat", {}).get("id", ""))
        callback_id = callback_query.get("id", "")

        if data.startswith("expand:"):
            arxiv_id = data.split(":", 1)[1]
            self.telegram.answer_callback_query(callback_id, text="Đang phân tích chi tiết...")
            status = self.pipeline.expand_and_send(arxiv_id, chat_id)
            logger.info("Expand %s: %s", arxiv_id, status)

    def _handle_expand_command(self, message: dict[str, Any]) -> None:
        """Handle /expand command."""
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")
        parts = text.strip().split(maxsplit=1)
        if len(parts) < 2:
            self.telegram.send_message(
                "Usage: /expand <arxiv_id>",
                chat_id=chat_id,
            )
            return
        arxiv_id = parts[1].strip()
        self.pipeline.expand_and_send(arxiv_id, chat_id)
