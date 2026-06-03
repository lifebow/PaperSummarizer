from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any


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
        self.http_post = http_post or _post_form

    def send_message(self, text: str) -> None:
        if not text.strip():
            return
        response = self.http_post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            payload={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True},
            timeout=60,
        )
        if response.get("ok") is False:
            raise RuntimeError(f"Telegram send failed: {response}")


def _post_form(url: str, *, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
