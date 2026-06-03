from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "paper-radar/0.1"


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def json_get(url: str, *, params: dict[str, str], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers=headers)
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def text_get(url: str, *, timeout: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return response.read().decode("utf-8")


def download_file(url: str, dest: str, *, timeout: int = 120) -> None:
    from pathlib import Path

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
        Path(dest).write_bytes(response.read())


def download_bytes(url: str, *, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return response.read()


def json_post(url: str, *, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def post_form(url: str, *, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))
