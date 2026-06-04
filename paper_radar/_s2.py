from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PaperMetadata:
    arxiv_id: str
    semantic_scholar_id: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    author_s2_ids: list[str] = field(default_factory=list)
    author_affiliations: list[str] = field(default_factory=list)
    abstract: str = ""
    semantic_scholar_tldr: str = ""
    categories: list[str] = field(default_factory=list)
    primary_category: str = ""
    published_at: str = ""
    updated_at: str = ""
    pdf_url: str = ""
    semantic_scholar_url: str = ""
    source: str = ""

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def s2_item_to_paper(item: dict[str, Any], *, include_fields_of_study: bool = False) -> PaperMetadata | None:
    external_ids = item.get("externalIds") or {}
    arxiv_id = external_ids.get("ArXiv") or external_ids.get("ARXIV")
    if not arxiv_id:
        return None

    open_access = item.get("openAccessPdf") or {}
    tldr = item.get("tldr") or {}

    primary_category = ""
    categories: list[str] = []
    if include_fields_of_study:
        fields_of_study = item.get("fieldsOfStudy") or []
        categories = [f for f in fields_of_study if isinstance(f, str)]
        primary_category = categories[0] if categories else ""

    s2_authors = item.get("authors") or []
    author_names = [a.get("name", "") for a in s2_authors if a.get("name")]
    author_s2_ids = [a.get("authorId", "") for a in s2_authors if a.get("authorId")]

    return PaperMetadata(
        arxiv_id=arxiv_id,
        semantic_scholar_id=item.get("paperId", ""),
        title=item.get("title", "") or "",
        authors=author_names,
        author_s2_ids=author_s2_ids,
        abstract=item.get("abstract", "") or "",
        semantic_scholar_tldr=tldr.get("text", "") if isinstance(tldr, dict) else "",
        categories=categories,
        primary_category=primary_category,
        published_at=item.get("publicationDate", "") or "",
        pdf_url=open_access.get("url", "") if isinstance(open_access, dict) else "",
        semantic_scholar_url=item.get("url", "") or "",
        source="semantic_scholar",
    )
