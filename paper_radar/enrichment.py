from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from typing import Any

from .db import PaperRadarDb


@dataclass
class ExtractionResult:
    paper_id: int
    arxiv_id: str
    full_text: str
    introduction_text: str
    status: str
    error: str


INTRODUCTION_PATTERNS = [
    re.compile(r"^1\.?\s+Introduction\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^Introduction\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^I\.\s+Introduction\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\d+\.?\s+Introduction\s*$", re.MULTILINE | re.IGNORECASE),
]

STOP_SECTION_PATTERNS = [
    re.compile(r"^2\s+Related Work\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^2\s+Background\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^2\s+Method(?:s|ology)?\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^2\s+Preliminaries\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^2\s+Approach\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"\bII\.?\s+.*", re.MULTILINE | re.IGNORECASE),
    re.compile(
        r"\b\d+\.?\s+(?:Related Work|Background|Method|Methods|Methodology|"
        r"Preliminaries|Approach|Problem|Formulation|Setup)\s*$",
        re.MULTILINE | re.IGNORECASE,
    ),
]


def extract_introduction(full_text: str, abstract: str = "", max_chars: int = 3000) -> str:
    for pattern in INTRODUCTION_PATTERNS:
        match = pattern.search(full_text)
        if match:
            start = match.end()
            end = len(full_text)
            for stop_pattern in STOP_SECTION_PATTERNS:
                stop_match = stop_pattern.search(full_text, start)
                if stop_match:
                    end = stop_match.start()
                    break
            intro = full_text[start:end].strip()
            if len(intro) > 20:
                return intro[:max_chars]

    sentences = re.split(r"(?<=[.!?])\s+", full_text)
    intro_sentences = []
    char_count = 0
    for sentence in sentences:
        if char_count + len(sentence) > max_chars:
            break
        intro_sentences.append(sentence)
        char_count += len(sentence) + 1
    intro = " ".join(intro_sentences)

    if abstract and len(abstract) > len(intro):
        return abstract[:max_chars]

    return intro[:max_chars] if intro else abstract[:max_chars]


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    try:
        import pymupdf

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n\n".join(text_parts)
    except Exception:
        return ""


def download_pdf(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "paper-radar/0.1"})
    import ssl

    ctx = ssl.create_default_context()
    try:
        import certifi  # type: ignore

        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    with urllib.request.urlopen(request, timeout=timeout, context=ctx) as response:
        return response.read()


class ArchiveEnricher:
    def __init__(self, db: PaperRadarDb):
        self.db = db

    def run_batch(self, limit: int = 50, *, dry_run: bool = False) -> list[ExtractionResult]:
        papers = self.db.papers_needing_extraction(limit=limit)
        results = []

        for paper in papers:
            result = self._extract_paper(paper, dry_run=dry_run)
            results.append(result)

        return results

    def _extract_paper(self, paper: dict[str, Any], *, dry_run: bool = False) -> ExtractionResult:
        paper_id = paper["id"]
        arxiv_id = paper.get("arxiv_id", "")
        pdf_url = paper.get("pdf_url", "")

        if dry_run:
            return ExtractionResult(
                paper_id=paper_id,
                arxiv_id=arxiv_id,
                full_text="",
                introduction_text="",
                status="dry_run",
                error="",
            )

        if not pdf_url:
            self.db.upsert_paper_text(
                paper_id,
                extraction_status="no_pdf_url",
                extraction_error="No PDF URL available",
                extractor_name="pymupdf",
            )
            return ExtractionResult(
                paper_id=paper_id,
                arxiv_id=arxiv_id,
                full_text="",
                introduction_text="",
                status="no_pdf_url",
                error="No PDF URL available",
            )

        try:
            pdf_bytes = download_pdf(pdf_url)
            full_text = extract_text_from_pdf(pdf_bytes)

            if not full_text.strip():
                self.db.upsert_paper_text(
                    paper_id,
                    full_text="",
                    introduction_text="",
                    extraction_status="empty_text",
                    extraction_error="Extracted text is empty",
                    extractor_name="pymupdf",
                )
                return ExtractionResult(
                    paper_id=paper_id,
                    arxiv_id=arxiv_id,
                    full_text="",
                    introduction_text="",
                    status="empty_text",
                    error="Extracted text is empty",
                )

            abstract = paper.get("abstract", "")
            intro = extract_introduction(full_text, abstract)

            self.db.upsert_paper_text(
                paper_id,
                full_text=full_text[:100000],
                introduction_text=intro,
                extraction_status="extracted",
                extractor_name="pymupdf",
            )

            self.db.upsert_paper({"arxiv_id": arxiv_id, "archive_status": "extracted"})

            return ExtractionResult(
                paper_id=paper_id,
                arxiv_id=arxiv_id,
                full_text=full_text[:100000],
                introduction_text=intro,
                status="extracted",
                error="",
            )

        except Exception as e:
            error_msg = str(e)[:500]
            self.db.upsert_paper_text(
                paper_id,
                extraction_status="error",
                extraction_error=error_msg,
                extractor_name="pymupdf",
            )
            return ExtractionResult(
                paper_id=paper_id,
                arxiv_id=arxiv_id,
                full_text="",
                introduction_text="",
                status="error",
                error=error_msg,
            )
