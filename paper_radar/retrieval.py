from __future__ import annotations

import json
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PaperMetadata:
    arxiv_id: str
    semantic_scholar_id: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    semantic_scholar_tldr: str = ""
    categories: list[str] = field(default_factory=list)
    published_at: str = ""
    updated_at: str = ""
    pdf_url: str = ""
    semantic_scholar_url: str = ""
    source: str = ""

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


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
        self.fields = fields or [
            "title",
            "abstract",
            "publicationDate",
            "externalIds",
            "openAccessPdf",
            "fieldsOfStudy",
            "url",
        ]
        self.http_get = http_get or _json_get
        self._next_key = 0

    def search(self, query: str, *, limit: int = 20, since: str | None = None) -> list[PaperMetadata]:
        headers = {}
        if self.api_keys:
            headers["x-api-key"] = self.api_keys[self._next_key % len(self.api_keys)]
            self._next_key += 1
        headers["User-Agent"] = "paper-radar/0.1"
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
        return [paper for paper in (_s2_to_paper(item) for item in payload.get("data", [])) if paper]


class ArxivClient:
    API_URL = "https://export.arxiv.org/api/query"
    ATOM_NS = "{http://www.w3.org/2005/Atom}"
    ARXIV_NS = "{http://arxiv.org/schemas/atom}"

    def __init__(self, *, http_get_text: Callable[..., str] | None = None):
        self.http_get_text = http_get_text or _text_get
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
                merged[paper.arxiv_id] = paper
        try:
            arxiv_papers = self.arxiv_search(categories, since, limit)
        except Exception:
            arxiv_papers = []
        for paper in arxiv_papers:
            if paper.arxiv_id:
                existing = merged.get(paper.arxiv_id)
                merged[paper.arxiv_id] = _merge_s2_with_arxiv(existing, paper) if existing else paper
        return list(merged.values())[:limit]


class PdfDownloader:
    def __init__(
        self,
        *,
        http_download: Callable[[str, Path], None] | None = None,
        paperscraper_download: Callable[[str, Path], bool] | None = None,
    ):
        self.http_download = http_download or _download_file
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


def _s2_to_paper(item: dict[str, Any]) -> PaperMetadata | None:
    external_ids = item.get("externalIds") or {}
    arxiv_id = external_ids.get("ArXiv") or external_ids.get("ARXIV")
    if not arxiv_id:
        return None
    open_access = item.get("openAccessPdf") or {}
    return PaperMetadata(
        arxiv_id=arxiv_id,
        semantic_scholar_id=item.get("paperId", ""),
        title=item.get("title", "") or "",
        abstract=item.get("abstract", "") or "",
        semantic_scholar_tldr="",
        published_at=item.get("publicationDate", "") or "",
        pdf_url=open_access.get("url", "") if isinstance(open_access, dict) else "",
        semantic_scholar_url=item.get("url", "") or "",
        source="semantic_scholar",
    )


def _merge_s2_with_arxiv(s2: PaperMetadata | None, arxiv: PaperMetadata) -> PaperMetadata:
    if s2 is None:
        return arxiv
    return PaperMetadata(
        arxiv_id=arxiv.arxiv_id,
        semantic_scholar_id=s2.semantic_scholar_id,
        title=arxiv.title or s2.title,
        authors=arxiv.authors or s2.authors,
        abstract=arxiv.abstract or s2.abstract,
        semantic_scholar_tldr=s2.semantic_scholar_tldr,
        categories=arxiv.categories or s2.categories,
        published_at=arxiv.published_at or s2.published_at,
        updated_at=arxiv.updated_at or s2.updated_at,
        pdf_url=s2.pdf_url or arxiv.pdf_url,
        semantic_scholar_url=s2.semantic_scholar_url,
        source="hybrid",
    )


def _json_get(url: str, *, params: dict[str, str], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers=headers)
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def _text_get(url: str, *, timeout: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "paper-radar/0.1"})
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        return response.read().decode("utf-8")


def _download_file(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "paper-radar/0.1"})
    with urllib.request.urlopen(request, timeout=120, context=_ssl_context()) as response:
        dest.write_bytes(response.read())


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


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()
