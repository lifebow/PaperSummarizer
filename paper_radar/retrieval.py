from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ._http import USER_AGENT, download_file, json_get
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

    def lookup_by_arxiv_id(self, arxiv_id: str) -> dict[str, Any] | None:
        """Lookup a single paper by arXiv ID. Returns raw S2 item or None."""
        headers: dict[str, str] = {"User-Agent": USER_AGENT}
        if self.api_keys:
            headers["x-api-key"] = self.api_keys[self._next_key % len(self.api_keys)]
            self._next_key += 1
        try:
            return self.http_get(
                f"https://api.semanticscholar.org/graph/v1/paper/ArXiv:{arxiv_id}",
                params={"fields": "title,abstract,authors,publicationDate,externalIds,openAccessPdf,url"},
                headers=headers,
                timeout=30,
            )
        except Exception as exc:
            logger.debug("S2 lookup failed for %s: %s", arxiv_id, exc)
            return None


class ArxivClient:
    """Fetch recent papers from arXiv list pages.

    The recent CS list page exposes the newest papers in one lightweight HTML
    response, for example: https://arxiv.org/list/cs/recent?skip=0&show=1000.
    We parse arXiv IDs and titles from that page, then fetch each /abs/<id>
    page directly from arXiv for abstract, authors, date, and category metadata.
    """

    def __init__(self, *, client: Any | None = None):
        import requests as _requests

        if client:
            self._client = client
        else:
            session = _requests.Session()
            session.headers["User-Agent"] = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )
            self._client = session

    def search_recent(self, categories: list[str], *, since: str, limit: int = 200) -> list[PaperMetadata]:
        """Fetch recent arXiv papers from /list/<archive>/recent HTML."""
        since_date = since[:10] if since else "2020-01-01"
        return self.search_recent_new_only(categories, since=since_date, limit=limit, paper_exists=None)

    def search_recent_new_only(
        self,
        categories: list[str],
        *,
        since: str,
        limit: int,
        paper_exists: Callable[[str], bool] | None,
        scan_limit: int | None = None,
    ) -> list[PaperMetadata]:
        since_date = since[:10] if since else "2020-01-01"
        return self._fetch_via_list_page(
            categories,
            since_date,
            limit,
            paper_exists=paper_exists,
            scan_limit=scan_limit,
        )

    def _fetch_via_list_page(
        self,
        categories: list[str],
        since_date: str,
        limit: int,
        *,
        paper_exists: Callable[[str], bool] | None = None,
        scan_limit: int | None = None,
    ) -> list[PaperMetadata]:
        """Parse arXiv /list/<archive>/recent HTML, then fetch /abs pages."""
        import re as _re
        from html import unescape

        archive = self._archive_from_categories(categories)
        show = scan_limit or max(limit, 1000)
        url = f"https://arxiv.org/list/{archive}/recent?skip=0&show={show}"

        logger.info("arXiv list request: %s", url)
        resp = self._client.get(url, timeout=30)
        resp.raise_for_status()

        papers: list[PaperMetadata] = []
        seen_ids: set[str] = set()

        # arXiv list pages are structured as <dt> links followed by <dd> metadata.
        pairs = _re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", resp.text, _re.DOTALL | _re.IGNORECASE)
        for dt_html, dd_html in pairs:
            id_match = _re.search(r'href\s*=\s*["\']/abs/([^"\']+)["\']', dt_html)
            if not id_match:
                continue
            arxiv_id = _normalize_arxiv_id(unescape(id_match.group(1)).strip())
            if not arxiv_id or arxiv_id in seen_ids:
                continue
            if paper_exists and paper_exists(arxiv_id):
                seen_ids.add(arxiv_id)
                continue

            title = self._extract_list_title(dd_html)
            categories_found = _re.findall(r"\(([a-z-]+\.[A-Z]{2})\)", dd_html)
            primary_category = categories_found[0] if categories_found else ""
            seen_ids.add(arxiv_id)
            papers.append(
                PaperMetadata(
                    arxiv_id=arxiv_id,
                    title=title,
                    categories=categories_found,
                    primary_category=primary_category,
                    pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                    source="arxiv",
                )
            )

        if not papers:
            # Older/simple markup fallback: at least preserve IDs if title parsing fails.
            for arxiv_id in _re.findall(r'href\s*=\s*["\']/abs/(\d+\.\d+(?:v\d+)?)["\']', resp.text):
                normalized = _normalize_arxiv_id(arxiv_id)
                if normalized and normalized not in seen_ids:
                    if paper_exists and paper_exists(normalized):
                        seen_ids.add(normalized)
                        continue
                    seen_ids.add(normalized)
                    papers.append(
                        PaperMetadata(
                            arxiv_id=normalized,
                            pdf_url=f"https://arxiv.org/pdf/{normalized}.pdf",
                            source="arxiv",
                        )
                    )

        list_papers = papers[:limit] if paper_exists is None else papers[: min(len(papers), limit)]
        logger.info("arXiv recent list page returned %d papers for %s", len(list_papers), archive)
        return self._fetch_abs_metadata(list_papers, since_date)

    def _fetch_abs_metadata(self, list_papers: list[PaperMetadata], since_date: str) -> list[PaperMetadata]:
        papers: list[PaperMetadata] = []
        for index, list_paper in enumerate(list_papers):
            try:
                resp = self._client.get(f"https://arxiv.org/abs/{list_paper.arxiv_id}", timeout=30)
                resp.raise_for_status()
                abs_paper = self._parse_abs_page(list_paper.arxiv_id, resp.text)
            except Exception as exc:
                logger.debug("arXiv abs page %s failed: %s", list_paper.arxiv_id, exc)
                abs_paper = None

            paper = self._merge_abs_with_list(abs_paper, list_paper)
            papers.append(paper)
            if (index + 1) % 50 == 0:
                logger.info("arXiv abs pages fetched: %d/%d", index + 1, len(list_papers))
        return papers

    @staticmethod
    def _merge_abs_with_list(abs_paper: PaperMetadata | None, list_paper: PaperMetadata) -> PaperMetadata:
        if abs_paper is None:
            return list_paper
        return PaperMetadata(
            arxiv_id=list_paper.arxiv_id,
            title=abs_paper.title or list_paper.title,
            authors=abs_paper.authors,
            abstract=abs_paper.abstract,
            categories=abs_paper.categories or list_paper.categories,
            primary_category=abs_paper.primary_category or list_paper.primary_category,
            published_at=abs_paper.published_at,
            updated_at=abs_paper.updated_at,
            pdf_url=abs_paper.pdf_url or list_paper.pdf_url,
            source="arxiv",
        )

    @staticmethod
    def _archive_from_categories(categories: list[str]) -> str:
        for category in categories:
            if category:
                return category.split(".", maxsplit=1)[0]
        return "cs"

    @staticmethod
    def _extract_list_title(dd_html: str) -> str:
        import re as _re
        from html import unescape

        match = _re.search(r'<div class=["\']list-title[^"\']*["\']>(.*?)</div>', dd_html, _re.DOTALL | _re.IGNORECASE)
        if not match:
            return ""
        title_html = _re.sub(r'<span class=["\']descriptor["\']>\s*Title:\s*</span>', "", match.group(1), flags=_re.I)
        title_text = _re.sub(r"<[^>]+>", " ", title_html)
        return " ".join(unescape(title_text).split())

    def _parse_abs_page(self, arxiv_id: str, html: str) -> PaperMetadata | None:
        """Parse an arXiv /abs/<id> HTML page into PaperMetadata."""
        import re as _re
        from html import unescape

        def _match(pattern: str) -> str:
            m = _re.search(pattern, html)
            return unescape(m.group(1)).strip() if m else ""

        title = _match(r'<meta name="citation_title" content="(.*?)"')
        abstract_raw = _match(
            r'<blockquote class="abstract[^"]*">\s*<span class="descriptor">Abstract:</span>\s*(.*?)\s*</blockquote>',
        )
        abstract = abstract_raw.replace("<br>", " ").replace("\n", " ").strip()
        published = _match(r'<meta name="citation_date" content="(.*?)"')
        # Convert date format: "2026/06/03" -> "2026-06-03"
        published = published.replace("/", "-")
        authors_raw = _re.findall(r'<meta name="citation_author" content="(.*?)"', html)
        categories_raw = _re.findall(r"subjects:\s*(.*?)</span>", html, _re.DOTALL)

        categories: list[str] = []
        if categories_raw:
            categories = [c.strip() for c in categories_raw[0].split(";") if c.strip()]
        primary_category = categories[0] if categories else ""

        if not title:
            return None

        return PaperMetadata(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors_raw,
            abstract=abstract,
            categories=categories,
            primary_category=primary_category,
            published_at=published,
            updated_at=published,
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            source="arxiv",
        )


class HybridRetriever:
    """Retrieve recent papers directly from arXiv."""

    def __init__(
        self,
        *,
        s2_client: SemanticScholarClient,
        arxiv_search: Callable[[list[str], str, int], list[PaperMetadata]],
        paper_exists: Callable[[str], bool] | None = None,
    ):
        self.s2_client = s2_client
        self.arxiv_search = arxiv_search
        self.paper_exists = paper_exists

    def search_recent(
        self,
        queries: list[str],
        categories: list[str],
        *,
        since: str,
        limit: int,
    ) -> list[PaperMetadata]:
        try:
            if self.paper_exists:
                arxiv_papers = self.arxiv_search_new_only(categories, since=since, limit=limit)
            else:
                arxiv_papers = self.arxiv_search(categories, since, limit)
        except Exception as exc:
            logger.warning("ArXiv search failed: %s", exc)
            return []

        logger.info("arXiv returned %d papers", len(arxiv_papers))
        return arxiv_papers[:limit]

    def arxiv_search_new_only(self, categories: list[str], *, since: str, limit: int) -> list[PaperMetadata]:
        if not self.paper_exists:
            return self.arxiv_search(categories, since, limit)
        # The default ArxivClient exposes a new-only path that filters by DB
        # before fetching expensive /abs pages. Test fakes may only implement
        # the older callable shape, so keep a safe fallback.
        owner = getattr(self.arxiv_search, "__self__", None)
        if owner and hasattr(owner, "search_recent_new_only"):
            return owner.search_recent_new_only(categories, since=since, limit=limit, paper_exists=self.paper_exists)
        papers = self.arxiv_search(categories, since, limit)
        return [paper for paper in papers if not self.paper_exists(_normalize_arxiv_id(paper.arxiv_id))]


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


def make_default_retriever(
    api_keys: list[str],
    fields: list[str],
    *,
    paper_exists: Callable[[str], bool] | None = None,
) -> HybridRetriever:
    s2_client = SemanticScholarClient(api_keys=api_keys, fields=fields)
    arxiv_client = ArxivClient()

    return HybridRetriever(
        s2_client=s2_client,
        arxiv_search=arxiv_client.search_recent,
        paper_exists=paper_exists,
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
