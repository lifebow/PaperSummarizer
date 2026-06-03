from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar


@dataclass(frozen=True)
class ExtractedText:
    text: str
    extractor_name: str


class PdfExtractor:
    def __init__(
        self,
        *,
        primary: Callable[[Path], str] | None = None,
        fallback: Callable[[Path], str] | None = None,
        min_chars: int = 500,
    ):
        self.primary = primary or _extract_with_pymupdf
        self.fallback = fallback or _extract_with_pdfplumber
        self.min_chars = min_chars

    def extract(self, pdf_path: Path) -> ExtractedText:
        try:
            text = self.primary(pdf_path)
            if len(text.strip()) >= self.min_chars:
                return ExtractedText(text=text, extractor_name="primary")
        except Exception:
            text = ""

        fallback_text = self.fallback(pdf_path)
        if len(fallback_text.strip()) < self.min_chars:
            raise ValueError(f"Extracted PDF text is too short: {len(fallback_text.strip())} chars")
        return ExtractedText(text=fallback_text, extractor_name="fallback")


T = TypeVar("T")


def process_pdf_with_cleanup(pdf_path: Path, processor: Callable[[Path], T]) -> T:
    try:
        return processor(pdf_path)
    finally:
        with suppress(FileNotFoundError):
            pdf_path.unlink()


def _extract_with_pymupdf4llm(pdf_path: Path) -> str:
    try:
        import pymupdf4llm  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pymupdf4llm is not installed") from exc
    return str(pymupdf4llm.to_markdown(str(pdf_path)))


def _extract_with_pymupdf(pdf_path: Path) -> str:
    try:
        import pymupdf  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pymupdf is not installed") from exc
    pages = []
    with pymupdf.open(str(pdf_path)) as doc:
        for page in doc:
            pages.append(page.get_text("text"))
    text = "\n\n".join(pages)
    if text.strip():
        return text
    return _extract_with_pymupdf4llm(pdf_path)


def _extract_with_pdfplumber(pdf_path: Path) -> str:
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pdfplumber is not installed") from exc
    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n\n".join(pages)
