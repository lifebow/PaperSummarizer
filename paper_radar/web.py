"""FastAPI web UI for browsing accepted papers by day and topic.

Read-only over the existing SQLite database. Topics are tagged on the fly from
the configured ``topics.queries`` (see :mod:`paper_radar.topics`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .db import PaperRadarDb
from .topics import OTHER_TOPIC, tag_paper, topic_slug

TEMPLATES_DIR = Path(__file__).parent / "templates"


_ENUM_MARKER = re.compile(r"\s*(?:\d+[.)]|[•‣])\s+")


def normalize_ideas(value: Any) -> list[str]:
    """Render ``ideas_to_try`` as a list of items, whether it is a list or a
    string with numbered / bulleted / semicolon-separated content."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    parts = [p.strip() for p in _ENUM_MARKER.split(text) if p.strip()]
    if len(parts) > 1:
        return parts
    if ";" in text:
        semi = [p.strip() for p in text.split(";") if p.strip()]
        if len(semi) > 1:
            return semi
    return [text]


def _href(date: str | None, slugs: list[str]) -> str:
    params: dict[str, str] = {}
    if date:
        params["date"] = date
    if slugs:
        params["topics"] = ",".join(slugs)
    return "/?" + urlencode(params) if params else "/"


def create_app(db: PaperRadarDb, queries: list[str]) -> FastAPI:
    app = FastAPI(title="PaperSummarizer")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    topic_catalog = [(q, topic_slug(q)) for q in queries] + [(OTHER_TOPIC, topic_slug(OTHER_TOPIC))]
    known_slugs = {slug for _, slug in topic_catalog}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, date: str | None = None, topics: str | None = None) -> Any:
        dates = db.dates_with_accepted_results()
        available = [d for d, _ in dates]
        selected_date = date or (available[0] if available else None)

        selected_slugs = [s for s in (topics.split(",") if topics else []) if s in known_slugs]

        papers = db.accepted_results_for_date(selected_date) if selected_date else []
        for paper in papers:
            paper["topics"] = [(label, topic_slug(label)) for label in tag_paper(paper, queries)]
            paper["ideas"] = normalize_ideas((paper.get("summary") or {}).get("ideas_to_try"))

        if selected_slugs:
            chosen = set(selected_slugs)
            papers = [p for p in papers if any(slug in chosen for _, slug in p["topics"])]

        topic_links = [
            {
                "label": label,
                "slug": slug,
                "active": slug in selected_slugs,
                "href": _href(
                    selected_date,
                    [s for s in selected_slugs if s != slug] if slug in selected_slugs else [*selected_slugs, slug],
                ),
            }
            for label, slug in topic_catalog
        ]
        date_links = [
            {
                "date": d,
                "count": n,
                "active": d == selected_date,
                "href": _href(d, selected_slugs),
            }
            for d, n in dates
        ]

        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "date_links": date_links,
                "selected_date": selected_date,
                "topic_links": topic_links,
                "all_active": not selected_slugs,
                "all_href": _href(selected_date, []),
                "papers": papers,
            },
        )

    return app
