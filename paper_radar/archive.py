from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from ._http import USER_AGENT, json_get
from ._s2 import s2_item_to_paper
from .db import PaperRadarDb

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, min_interval: float = 1.0):
        self.min_interval = min_interval
        self._last_request_at = 0.0

    def wait(self) -> None:
        elapsed = time.time() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_at = time.time()


@dataclass
class CrawlResult:
    papers_found: int
    papers_upserted: int
    years_completed: list[str]
    next_cursor: str | None


class HistoricalCrawler:
    S2_BULK_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"

    def __init__(
        self,
        db: PaperRadarDb,
        *,
        api_keys: list[str],
        rate_limiter: RateLimiter | None = None,
    ):
        self.db = db
        self.api_keys = api_keys
        self.rate_limiter = rate_limiter or RateLimiter()
        self._next_key = 0

    def crawl(
        self,
        from_date: str,
        to_date: str,
        *,
        categories: list[str] | None = None,
        page_size: int = 1000,
    ) -> CrawlResult:
        from_year = int(from_date[:4])
        to_year = int(to_date[:4])
        total_found = 0
        total_upserted = 0
        years_completed = []

        for year in range(from_year, to_year + 1):
            cursor = self.db.get_state(f"archive_cursor_{year}")
            if self.db.get_state(f"archive_completed_{year}"):
                years_completed.append(str(year))
                continue

            year_found, year_upserted, cursor = self._crawl_year(
                year, categories=categories, page_size=page_size, start_cursor=cursor
            )
            total_found += year_found
            total_upserted += year_upserted
            years_completed.append(str(year))

            if cursor:
                self.db.set_state(f"archive_cursor_{year}", cursor)
            else:
                self.db.set_state(f"archive_completed_{year}", "true")
                self.db.set_state(f"archive_cursor_{year}", "")

        return CrawlResult(
            papers_found=total_found,
            papers_upserted=total_upserted,
            years_completed=years_completed,
            next_cursor=None,
        )

    def _crawl_year(
        self,
        year: int,
        *,
        categories: list[str] | None = None,
        page_size: int = 1000,
        start_cursor: str | None = None,
    ) -> tuple[int, int, str | None]:
        cursor = start_cursor
        year_found = 0
        year_upserted = 0

        while True:
            headers = {}
            if self.api_keys:
                headers["x-api-key"] = self.api_keys[self._next_key % len(self.api_keys)]
                self._next_key += 1
            headers["User-Agent"] = USER_AGENT

            params: dict[str, str] = {
                "query": "*",
                "limit": str(page_size),
                "fields": "title,abstract,publicationDate,externalIds,openAccessPdf,fieldsOfStudy,url",
                "publicationDateOrYear": f"{year}-01-01:{year}-12-31",
            }
            if cursor:
                params["cursor"] = cursor

            self.rate_limiter.wait()
            try:
                payload = self._fetch(params, headers)
            except Exception as exc:
                logger.warning("Crawl fetch failed for year %d: %s", year, exc)
                break

            data = payload.get("data", [])
            if not data:
                break

            for item in data:
                paper_meta = s2_item_to_paper(item, include_fields_of_study=True)
                if paper_meta and paper_meta.arxiv_id:
                    if categories and paper_meta.primary_category not in categories:
                        continue
                    record = paper_meta.to_record()
                    record["archive_status"] = "metadata_only"
                    self.db.upsert_paper(record)
                    year_upserted += 1
            year_found += len(data)

            cursor = payload.get("next")
            if not cursor:
                break

            self.db.set_state(f"archive_cursor_{year}", cursor)

        return year_found, year_upserted, None

    def _fetch(self, params: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
        return json_get(self.S2_BULK_URL, params=params, headers=headers, timeout=60)


@dataclass
class SearchResult:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published_at: str
    pdf_url: str
    semantic_scholar_url: str
    primary_category: str
    categories: list[str]


class ArchiveSearcher:
    def __init__(self, db: PaperRadarDb):
        self.db = db

    def search(
        self,
        query: str,
        *,
        since: str | None = None,
        until: str | None = None,
        category: str | None = None,
        limit: int = 50,
    ) -> list[SearchResult]:
        conditions = ["(title || ' ' || abstract) LIKE ?"]
        params: list[Any] = [f"%{query}%"]

        if since:
            conditions.append("published_at >= ?")
            params.append(since)
        if until:
            conditions.append("published_at <= ?")
            params.append(until)
        if category:
            conditions.append("primary_category = ?")
            params.append(category)

        where = " AND ".join(conditions)
        sql = f"""
            SELECT arxiv_id, title, authors_json, abstract, published_at,
                   pdf_url, semantic_scholar_url, primary_category, categories_json
            FROM papers
            WHERE {where}
            ORDER BY published_at DESC
            LIMIT ?
        """
        params.append(limit)

        with self.db._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            r = dict(row)
            results.append(
                SearchResult(
                    arxiv_id=r["arxiv_id"] or "",
                    title=r["title"] or "",
                    authors=json.loads(r["authors_json"] or "[]"),
                    abstract=r["abstract"] or "",
                    published_at=r["published_at"] or "",
                    pdf_url=r["pdf_url"] or "",
                    semantic_scholar_url=r["semantic_scholar_url"] or "",
                    primary_category=r["primary_category"] or "",
                    categories=json.loads(r["categories_json"] or "[]"),
                )
            )
        return results
