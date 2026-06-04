from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from ._http import post_form

logger = logging.getLogger(__name__)

TELEGRAM_MSG_LIMIT = 4096


class TelegramSender:
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        http_post: Callable[..., dict[str, Any]] | None = None,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.http_post = http_post or post_form

    @property
    def _base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}"

    def send_message(
        self,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        chat_id: str | None = None,
        parse_mode: str = "Markdown",
    ) -> dict[str, Any]:
        """Send a message. Optionally include inline keyboard reply_markup."""
        if not text.strip():
            return {}
        target_chat = chat_id or self.chat_id
        payload: dict[str, Any] = {
            "chat_id": target_chat,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        response = self.http_post(
            f"{self._base_url}/sendMessage",
            payload=payload,
            timeout=60,
        )
        if response.get("ok") is False:
            raise RuntimeError(f"Telegram send failed: {response}")
        return response

    def send_long_message(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "Markdown",
    ) -> list[dict[str, Any]]:
        """Send text that may exceed Telegram's 4096 char limit, splitting into multiple messages."""
        if not text.strip():
            return []
        chunks = _split_message(text, TELEGRAM_MSG_LIMIT)
        results = []
        for i, chunk in enumerate(chunks):
            markup = reply_markup if i == len(chunks) - 1 else None
            result = self.send_message(chunk, reply_markup=markup, chat_id=chat_id, parse_mode=parse_mode)
            results.append(result)
        return results

    def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str = "",
    ) -> dict[str, Any]:
        """Acknowledge a callback query from an inline button press."""
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
        }
        if text:
            payload["text"] = text
        response = self.http_post(
            f"{self._base_url}/answerCallbackQuery",
            payload=payload,
            timeout=30,
        )
        return response

    def set_webhook(self, webhook_url: str) -> dict[str, Any]:
        """Register a webhook URL with Telegram."""
        response = self.http_post(
            f"{self._base_url}/setWebhook",
            payload={"url": webhook_url},
            timeout=30,
        )
        return response

    def delete_webhook(self) -> dict[str, Any]:
        """Remove the current webhook."""
        response = self.http_post(
            f"{self._base_url}/deleteWebhook",
            payload={},
            timeout=30,
        )
        return response

    def get_me(self) -> dict[str, Any]:
        """Get bot info."""
        response = self.http_post(
            f"{self._base_url}/getMe",
            payload={},
            timeout=30,
        )
        return response


def make_expand_keyboard(arxiv_id: str) -> dict[str, Any]:
    """Create inline keyboard with Expand button for a paper."""
    return {
        "inline_keyboard": [
            [{"text": "🔍 Expand", "callback_data": f"expand:{arxiv_id}"}],
        ],
    }


def _split_message(text: str, limit: int) -> list[str]:
    """Split text into chunks respecting line boundaries."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_pos = remaining.rfind("\n", 0, limit)
        if split_pos <= 0:
            split_pos = limit
        chunks.append(remaining[:split_pos].rstrip("\n"))
        remaining = remaining[split_pos:].lstrip("\n")
    return chunks
