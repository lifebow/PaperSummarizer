import tempfile
import unittest
from pathlib import Path

from paper_radar.db import PaperRadarDb
from paper_radar.enrichment import ArchiveEnricher, extract_introduction, extract_text_from_pdf


class EnrichmentTests(unittest.TestCase):
    def test_extract_introduction_with_heading(self):
        text = """
Abstract
This is the abstract.

1 Introduction
This is the introduction text. It contains some background information.
The paper proposes a new method.

2 Related Work
This is related work.
"""
        intro = extract_introduction(text, "Abstract text")
        self.assertIn("introduction text", intro)
        self.assertNotIn("Related Work", intro)

    def test_extract_introduction_with_roman_numeral(self):
        text = """
I. Introduction
This is the introduction with Roman numeral.
It has multiple sentences.

II. Background
Background section.
"""
        intro = extract_introduction(text)
        self.assertIn("introduction with Roman numeral", intro)
        self.assertNotIn("Background", intro)

    def test_extract_introduction_fallback_to_prefix(self):
        text = "This is a paper without clear section headings. " * 50
        intro = extract_introduction(text)
        self.assertGreater(len(intro), 0)
        self.assertLessEqual(len(intro), 3000)

    def test_extract_introduction_prefers_abstract_when_longer(self):
        abstract = "A" * 2000
        text = "Short intro."
        intro = extract_introduction(text, abstract)
        self.assertEqual(intro, abstract[:3000])

    def test_extract_text_from_pdf_bytes(self):
        try:
            import pymupdf

            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Hello World\nTest content")
            pdf_bytes = doc.tobytes()
            doc.close()

            text = extract_text_from_pdf(pdf_bytes)
            self.assertIn("Hello World", text)
            self.assertIn("Test content", text)
        except ImportError:
            self.skipTest("pymupdf not available")

    def test_db_paper_texts_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            paper_id = db.upsert_paper({"arxiv_id": "2501.00001", "title": "Test"})
            db.upsert_paper_text(
                paper_id,
                full_text="Full text here",
                introduction_text="Introduction here",
                extraction_status="extracted",
                extractor_name="pymupdf",
            )

            paper_text = db.get_paper_text(paper_id)
            self.assertIsNotNone(paper_text)
            self.assertEqual(paper_text["full_text"], "Full text here")
            self.assertEqual(paper_text["introduction_text"], "Introduction here")
            self.assertEqual(paper_text["extraction_status"], "extracted")

    def test_db_papers_needing_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            db.upsert_paper({"arxiv_id": "2501.00001", "title": "Paper 1"})
            db.upsert_paper({"arxiv_id": "2501.00002", "title": "Paper 2"})

            needing = db.papers_needing_extraction()
            self.assertEqual(len(needing), 2)

            paper_id = db.upsert_paper({"arxiv_id": "2501.00001", "title": "Paper 1"})
            db.upsert_paper_text(paper_id, extraction_status="extracted")

            needing = db.papers_needing_extraction()
            self.assertEqual(len(needing), 1)
            self.assertEqual(needing[0]["arxiv_id"], "2501.00002")

    def test_enricher_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            db.upsert_paper({"arxiv_id": "2501.00001", "title": "Test", "pdf_url": ""})

            enricher = ArchiveEnricher(db)
            results = enricher.run_batch(limit=10, dry_run=True)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].status, "dry_run")

    def test_enricher_no_pdf_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            db.upsert_paper({"arxiv_id": "2501.00001", "title": "Test", "pdf_url": ""})

            enricher = ArchiveEnricher(db)
            results = enricher.run_batch(limit=10)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].status, "no_pdf_url")

    def test_enricher_skips_already_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            paper_id = db.upsert_paper({"arxiv_id": "2501.00001", "title": "Test", "pdf_url": ""})
            db.upsert_paper_text(paper_id, extraction_status="extracted")

            enricher = ArchiveEnricher(db)
            results = enricher.run_batch(limit=10)

            self.assertEqual(len(results), 0)


if __name__ == "__main__":
    unittest.main()
