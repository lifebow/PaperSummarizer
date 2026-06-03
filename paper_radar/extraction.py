from __future__ import annotations

import logging
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

logger = logging.getLogger(__name__)

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


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    try:
        import pymupdf

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n\n".join(text_parts)
    except Exception:
        logger.exception("PDF text extraction failed")
        return ""


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
        except Exception as exc:
            logger.warning("Primary extraction failed: %s", exc)
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
