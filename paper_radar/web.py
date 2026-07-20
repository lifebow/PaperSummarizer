"""FastAPI web UI for browsing accepted papers by day and topic.

Read-only over the existing SQLite database. Topics are tagged on the fly from
the configured ``topics.queries`` (see :mod:`paper_radar.topics`).
"""

from __future__ import annotations

import re
from datetime import date as _date
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .config import union_queries
from .db import PaperRadarDb
from .topics import OTHER_TOPIC, paper_filter_sets, tag_paper, topic_slug

TEMPLATES_DIR = Path(__file__).parent / "templates"


_ENUM_MARKER = re.compile(r"\s*(?:\d+[.)]|[•‣])\s+")
_LEADING_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-•‣*])\s*")


def _clean_idea(item: str) -> str:
    return _LEADING_MARKER.sub("", item).strip()


def normalize_ideas(value: Any) -> list[str]:
    """Render ``ideas_to_try`` as a list of items, whether it is a list or a
    string with numbered / bulleted / semicolon-separated content."""
    if isinstance(value, list):
        return [cleaned for item in value if (cleaned := _clean_idea(str(item)))]
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    parts = [_clean_idea(p) for p in _ENUM_MARKER.split(text) if p.strip()]
    if len(parts) > 1:
        return parts
    if ";" in text:
        semi = [_clean_idea(p) for p in text.split(";") if p.strip()]
        if len(semi) > 1:
            return semi
    return [_clean_idea(text)]


def masthead_date(value: str | None) -> str:
    """Format an ``YYYY-MM-DD`` day as the masthead label ``Thu · 2026-07-17``.

    Falls back to the raw value (or an empty string) when it cannot be parsed.
    """
    if not value:
        return ""
    try:
        weekday = _date.fromisoformat(value[:10]).strftime("%a")
    except ValueError:
        return value
    return f"{weekday} · {value[:10]}"


def _href(date: str | None, set_slug: str | None, kw_slugs: list[str], month: str | None = None) -> str:
    params: dict[str, str] = {}
    if date:
        params["date"] = date
    if month:
        params["month"] = month
    if set_slug:
        params["set"] = set_slug
    if kw_slugs:
        params["topics"] = ",".join(kw_slugs)
    return "/?" + urlencode(params) if params else "/"


def month_label(ym: str) -> str:
    """``2026-07`` -> ``JUL '26`` for the month-navigator tabs."""
    try:
        d = _date(int(ym[:4]), int(ym[5:7]), 1)
    except ValueError:
        return ym
    return f"{d.strftime('%b').upper()} '{ym[2:4]}"


def create_app(db: PaperRadarDb, filter_sets: list[Any]) -> FastAPI:
    app = FastAPI(title="PaperSummarizer")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # union of all sets' queries (dedup, order preserved) — used for keyword tags
    queries = union_queries(filter_sets)
    known_kw_slugs = {topic_slug(q) for q in queries}

    set_by_slug = {topic_slug(fset.name): fset for fset in filter_sets}

    @app.get("/", response_class=HTMLResponse)
    def home(
        request: Request,
        date: str | None = None,
        month: str | None = None,
        set_filter: str | None = Query(None, alias="set"),
        topics: str | None = None,
        q: str | None = None,
    ) -> Any:
        query = (q or "").strip()
        dates = db.dates_with_accepted_results()
        available = [d for d, _ in dates]
        # A search spans all dates, so no single day is selected.
        selected_date = None if query else (date or (available[0] if available else None))

        # Per-day counts split by filter-set membership: how many papers match a
        # configured set (e.g. AI Safety) vs the combined total (sets + Other).
        set_counts_by_date: dict[str, int] = {}
        for row in db.all_accepted_results():
            if paper_filter_sets(row, filter_sets):
                d = row["digest_date"]
                set_counts_by_date[d] = set_counts_by_date.get(d, 0) + 1

        # tier 1: one concrete set, or "other", or None (= All)
        selected_set = set_filter if (set_filter in set_by_slug or set_filter == "other") else None
        # tier 2: keyword slugs (only meaningful inside a concrete set, but filter applies if present)
        selected_kw = [s for s in (topics.split(",") if topics else []) if s in known_kw_slugs]

        if query:
            papers = db.search_accepted(query)
        else:
            papers = db.accepted_results_for_date(selected_date) if selected_date else []
        for paper in papers:
            summary = paper.get("summary") or {}
            paper["topics"] = [(label, topic_slug(label)) for label in tag_paper(paper, queries)]
            paper["ideas"] = normalize_ideas(summary.get("ideas_to_try"))
            affs = paper.get("author_affiliations") or summary.get("author_affiliations") or []
            paper["affiliations"] = list(dict.fromkeys(a for a in affs if a))
            paper["_set_slugs"] = {topic_slug(name) for name in paper_filter_sets(paper, filter_sets)}
            pdf_url = paper.get("pdf_url") or f"https://arxiv.org/pdf/{paper.get('arxiv_id', '')}.pdf"
            paper["reader_url"] = "https://pdf.lifebow.net/?url=" + quote(pdf_url, safe="")

        if selected_set == "other":
            papers = [p for p in papers if not p["_set_slugs"]]
        elif selected_set:
            papers = [p for p in papers if selected_set in p["_set_slugs"]]
        if selected_kw:
            chosen = set(selected_kw)
            papers = [p for p in papers if any(slug in chosen for _, slug in p["topics"])]

        set_links = [{"label": "All", "active": selected_set is None, "href": _href(selected_date, None, [])}]
        for fset in filter_sets:
            slug = topic_slug(fset.name)
            set_links.append(
                {
                    "label": fset.name,
                    "active": selected_set == slug,
                    "href": _href(selected_date, None if selected_set == slug else slug, []),
                }
            )
        set_links.append(
            {
                "label": OTHER_TOPIC,
                "active": selected_set == "other",
                "href": _href(selected_date, None if selected_set == "other" else "other", []),
            }
        )

        keyword_links = []
        if selected_set and selected_set in set_by_slug:
            for query in set_by_slug[selected_set].queries:
                slug = topic_slug(query)
                keyword_links.append(
                    {
                        "label": query,
                        "slug": slug,
                        "active": slug in selected_kw,
                        "href": _href(
                            selected_date,
                            selected_set,
                            [s for s in selected_kw if s != slug] if slug in selected_kw else [*selected_kw, slug],
                        ),
                    }
                )

        # Month navigator: group accepted days into months (newest first), so a
        # long day rail never overflows. A `month` picks which month's day grid
        # shows; a `date` (day chip) drives the actual fetch.
        months: dict[str, dict[str, int]] = {}
        for d, n in dates:
            ym = d[:7]
            entry = months.setdefault(ym, {"total": 0, "days": 0})
            entry["total"] += n
            entry["days"] += 1
        month_keys = sorted(months, reverse=True)

        if month in months:
            selected_month = month
        elif selected_date and selected_date[:7] in months:
            selected_month = selected_date[:7]
        elif month_keys:
            selected_month = month_keys[0]
        else:
            selected_month = None

        month_tabs = [
            {
                "key": ym,
                "label": month_label(ym),
                "count": months[ym]["total"],
                "active": ym == selected_month,
                # keep the loaded day; only switch which month's grid is shown
                "href": _href(selected_date, selected_set, selected_kw, month=ym),
            }
            for ym in month_keys
        ]

        month_days = [
            {
                "dd": d[8:10],  # day of month, e.g. "17"
                "count": n,
                "set_count": set_counts_by_date.get(d, 0),
                "active": d == selected_date,
                "href": _href(d, selected_set, selected_kw),
            }
            for d, n in dates
            if d[:7] == selected_month
        ]

        sel = months.get(selected_month)
        month_summary = f"{sel['days']} days · {sel['total']} papers" if sel else ""

        # In-scope (set-matching) count for the day's papers, for the standfirst.
        in_scope = sum(1 for p in papers if p["_set_slugs"])

        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "month_tabs": month_tabs,
                "month_days": month_days,
                "month_summary": month_summary,
                "selected_month": selected_month,
                "selected_date": selected_date,
                "masthead_date": masthead_date(selected_date or (available[0] if available else None)),
                "in_scope": in_scope,
                "set_links": set_links,
                "keyword_links": keyword_links,
                "papers": papers,
                "search_query": query,
            },
        )

    return app
