from __future__ import annotations

import logging
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ._http import USER_AGENT, download_file, json_get, text_get
from ._s2 import PaperMetadata, s2_item_to_paper  # noqa: F401 - re-exported

logger = logging.getLogger(__name__)


class SemanticScholarClient:
    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"

    def __init__(
        self,
        *,
        api_keys: list[str],
        fields: list[str] | None = None,
        http_get: Callable[..., dict[str, Any]] | None = None,
    ):
        self.api_keys = api_keys
        base_fields = [
            "title",
            "abstract",
            "authors",
            "publicationDate",
            "externalIds",
            "openAccessPdf",
            "url",
        ]
        if fields:
            merged = list(fields)
            for f in base_fields:
                if f not in merged:
                    merged.append(f)
            self.fields = merged
        else:
            self.fields = base_fields
        self.http_get = http_get or json_get
        self._next_key = 0

    def search(self, query: str, *, limit: int = 20, since: str | None = None) -> list[PaperMetadata]:
        headers = {}
        if self.api_keys:
            headers["x-api-key"] = self.api_keys[self._next_key % len(self.api_keys)]
            self._next_key += 1
        headers["User-Agent"] = USER_AGENT
        params = {
            "query": query,
            "limit": str(limit),
            "fields": ",".join(self.fields),
            "sort": "publicationDate:desc",
        }
        if since:
            params["publicationDateOrYear"] = f"{since[:10]}:"
        payload = self.http_get(
            self.BASE_URL,
            params=params,
            headers=headers,
            timeout=60,
        )
        return [paper for paper in (s2_item_to_paper(item) for item in payload.get("data", [])) if paper]

    def fetch_author_affiliations(self, author_ids: list[str]) -> dict[str, str]:
        """Fetch affiliations for a list of S2 author IDs. Returns {author_id: affiliation}."""
        result: dict[str, str] = {}
        for author_id in author_ids:
            if not author_id:
                continue
            try:
                headers: dict[str, str] = {"User-Agent": USER_AGENT}
                if self.api_keys:
                    headers["x-api-key"] = self.api_keys[self._next_key % len(self.api_keys)]
                    self._next_key += 1
                payload = self.http_get(
                    f"https://api.semanticscholar.org/graph/v1/author/{author_id}",
                    params={"fields": "name,affiliations"},
                    headers=headers,
                    timeout=30,
                )
                affiliations = payload.get("affiliations") or []
                aff_name = affiliations[0].get("name", "") if affiliations else ""
                if aff_name:
                    result[author_id] = aff_name
            except Exception as exc:
                logger.warning("Failed to fetch affiliation for author %s: %s", author_id, exc)
        return result


class ArxivClient:
    API_URL = "https://export.arxiv.org/api/query"
    ATOM_NS = "{http://www.w3.org/2005/Atom}"
    ARXIV_NS = "{http://arxiv.org/schemas/atom}"

    def __init__(self, *, http_get_text: Callable[..., str] | None = None):
        self.http_get_text = http_get_text or text_get
        self._last_request_at = 0.0

    def search_recent(self, categories: list[str], *, since: str, limit: int = 20) -> list[PaperMetadata]:
        del since
        query = " OR ".join(f"cat:{category}" for category in categories) or "cat:cs.AI"
        params = {
            "search_query": query,
            "max_results": str(limit),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        elapsed = time.time() - self._last_request_at
        if elapsed < 3:
            time.sleep(3 - elapsed)
        self._last_request_at = time.time()
        xml_text = self.http_get_text(f"{self.API_URL}?{urllib.parse.urlencode(params)}", timeout=120)
        root = ET.fromstring(xml_text)
        papers = []
        for entry in root.findall(f"{self.ATOM_NS}entry"):
            papers.append(self._entry_to_paper(entry))
        return papers

    def _entry_to_paper(self, entry: ET.Element) -> PaperMetadata:
        title = _entry_text(entry, f"{self.ATOM_NS}title").replace("\n", " ").strip()
        abstract = _entry_text(entry, f"{self.ATOM_NS}summary").replace("\n", " ").strip()
        published = _entry_text(entry, f"{self.ATOM_NS}published")[:10]
        updated = _entry_text(entry, f"{self.ATOM_NS}updated")[:10]
        arxiv_id_raw = _entry_text(entry, f"{self.ARXIV_NS}id") or _entry_text(entry, f"{self.ATOM_NS}id")
        arxiv_id = arxiv_id_raw.split("/abs/")[-1]
        authors = []
        for author_el in entry.findall(f"{self.ATOM_NS}author"):
            name = _entry_text(author_el, f"{self.ATOM_NS}name")
            if name:
                authors.append(name)
        categories = [cat.get("term", "") for cat in entry.findall(f"{self.ATOM_NS}category") if cat.get("term")]
        return PaperMetadata(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors,
            abstract=abstract,
            categories=categories,
            published_at=published,
            updated_at=updated,
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else "",
            source="arxiv",
        )


class HybridRetriever:
    def __init__(
        self,
        *,
        semantic_scholar_search: Callable[[list[str], int], list[PaperMetadata]],
        arxiv_search: Callable[[list[str], str, int], list[PaperMetadata]],
    ):
        self.semantic_scholar_search = semantic_scholar_search
        self.arxiv_search = arxiv_search

    def search_recent(
        self,
        queries: list[str],
        categories: list[str],
        *,
        since: str,
        limit: int,
    ) -> list[PaperMetadata]:
        merged: dict[str, PaperMetadata] = {}
        for paper in self.semantic_scholar_search(queries, limit, since):
            if paper.arxiv_id:
                merged[_normalize_arxiv_id(paper.arxiv_id)] = paper
        try:
            arxiv_papers = self.arxiv_search(categories, since, limit)
        except Exception as exc:
            logger.warning("ArXiv search failed: %s", exc)
            arxiv_papers = []
        for paper in arxiv_papers:
            if paper.arxiv_id:
                key = _normalize_arxiv_id(paper.arxiv_id)
                existing = merged.get(key)
                merged[key] = _merge_s2_with_arxiv(existing, paper) if existing else paper
        return list(merged.values())[:limit]


class PdfDownloader:
    def __init__(
        self,
        *,
        http_download: Callable[[str, Path], None] | None = None,
        paperscraper_download: Callable[[str, Path], bool] | None = None,
    ):
        self.http_download = http_download or _download_file_wrapper
        self.paperscraper_download = paperscraper_download or _download_with_paperscraper

    def download(self, paper: PaperMetadata, tmp_dir: Path) -> Path:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        safe_id = paper.arxiv_id.replace("/", "_") or paper.semantic_scholar_id or "paper"
        dest = tmp_dir / f"{safe_id}.pdf"
        if paper.pdf_url:
            self.http_download(paper.pdf_url, dest)
            return dest
        if paper.arxiv_id and self.paperscraper_download(paper.arxiv_id, dest):
            return dest
        url = f"https://arxiv.org/pdf/{paper.arxiv_id}.pdf"
        self.http_download(url, dest)
        return dest


def make_default_retriever(api_keys: list[str], fields: list[str]) -> HybridRetriever:
    s2_client = SemanticScholarClient(api_keys=api_keys, fields=fields)
    arxiv_client = ArxivClient()

    def s2_search(queries: list[str], limit: int, since: str | None = None) -> list[PaperMetadata]:
        papers: list[PaperMetadata] = []
        per_query_limit = max(1, limit)
        for query in queries:
            papers.extend(s2_client.search(query, limit=per_query_limit, since=since))
        return papers

    return HybridRetriever(
        semantic_scholar_search=s2_search,
        arxiv_search=lambda categories, since, limit: arxiv_client.search_recent(categories, since=since, limit=limit),
    )


def _normalize_arxiv_id(arxiv_id: str) -> str:
    """Strip version suffix (e.g. 'v1') from an arXiv ID for dedup/merge."""
    import re

    return re.sub(r"v\d+$", "", arxiv_id)


def _merge_s2_with_arxiv(s2: PaperMetadata | None, arxiv: PaperMetadata) -> PaperMetadata:
    if s2 is None:
        return arxiv
    return PaperMetadata(
        arxiv_id=arxiv.arxiv_id,
        semantic_scholar_id=s2.semantic_scholar_id,
        title=arxiv.title or s2.title,
        authors=arxiv.authors or s2.authors,
        author_s2_ids=s2.author_s2_ids,
        author_affiliations=s2.author_affiliations,
        abstract=arxiv.abstract or s2.abstract,
        semantic_scholar_tldr=s2.semantic_scholar_tldr,
        categories=arxiv.categories or s2.categories,
        published_at=arxiv.published_at or s2.published_at,
        updated_at=arxiv.updated_at or s2.updated_at,
        pdf_url=s2.pdf_url or arxiv.pdf_url,
        semantic_scholar_url=s2.semantic_scholar_url,
        source="hybrid",
    )


def _download_file_wrapper(url: str, dest: Path) -> None:
    download_file(url, str(dest))


def _download_with_paperscraper(arxiv_id: str, dest: Path) -> bool:
    try:
        from paperscraper.pdf import save_pdf  # type: ignore
    except Exception:
        return False
    try:
        result = save_pdf({"arxiv_id": arxiv_id}, filepath=str(dest))
        return dest.exists() or bool(result)
    except TypeError:
        try:
            result = save_pdf(arxiv_id, str(dest))
            return dest.exists() or bool(result)
        except Exception:
            return False
    except Exception:
        return False


def _entry_text(entry: ET.Element, path: str) -> str:
    element = entry.find(path)
    return (element.text or "").strip() if element is not None else ""
