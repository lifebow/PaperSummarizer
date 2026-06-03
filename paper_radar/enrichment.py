from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ._http import download_bytes
from .db import PaperRadarDb
from .extraction import extract_introduction, extract_text_from_pdf_bytes

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    paper_id: int
    arxiv_id: str
    full_text: str
    introduction_text: str
    status: str
    error: str


def download_pdf(url: str, timeout: int = 60) -> bytes:
    return download_bytes(url, timeout=timeout)


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
            full_text = extract_text_from_pdf_bytes(pdf_bytes)

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
            logger.error("Enrichment failed for %s: %s", arxiv_id, error_msg)
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
            full_text = extract_text_from_pdf_bytes(pdf_bytes)

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
            logger.error("Enrichment failed for %s: %s", arxiv_id, error_msg)
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
