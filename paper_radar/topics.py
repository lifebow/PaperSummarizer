"""On-the-fly topic tagging for accepted papers.

Papers are tagged by matching the configured ``topics.queries`` phrases against
the paper's title, abstract and summary text. No data is persisted; tags always
reflect the current configuration.
"""

from __future__ import annotations

import re
from typing import Any

OTHER_TOPIC = "Other"


def topic_slug(query: str) -> str:
    """URL-safe slug for a topic query (e.g. ``"Prompt Injection" -> "prompt-injection"``)."""
    return re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")


def _searchable_text(paper: dict[str, Any]) -> str:
    parts = [str(paper.get("title", "")), str(paper.get("abstract", ""))]
    summary = paper.get("summary") or {}
    if isinstance(summary, dict):
        parts.extend(_flatten(value) for value in summary.values())
    return " ".join(parts).lower()


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    return ""


def tag_paper(paper: dict[str, Any], queries: list[str]) -> list[str]:
    """Return matching topic queries (in config order), or ``[OTHER_TOPIC]`` if none match."""
    haystack = _searchable_text(paper)
    matched = [query for query in queries if query.lower() in haystack]
    return matched or [OTHER_TOPIC]
