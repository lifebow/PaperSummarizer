import tempfile
import unittest
from pathlib import Path

from paper_radar.extraction import ExtractedText, PdfExtractor, process_pdf_with_cleanup


class ExtractionTests(unittest.TestCase):
    def test_uses_primary_extractor_when_text_is_long_enough(self):
        calls = []

        def primary(path):
            calls.append(("primary", path.name))
            return "A" * 100

        def fallback(path):
            calls.append(("fallback", path.name))
            return "B" * 100

        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "paper.pdf"
            pdf.write_bytes(b"%PDF")
            result = PdfExtractor(primary=primary, fallback=fallback, min_chars=20).extract(pdf)

        self.assertEqual(result, ExtractedText(text="A" * 100, extractor_name="primary"))
        self.assertEqual(calls, [("primary", "paper.pdf")])

    def test_falls_back_when_primary_text_is_too_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "paper.pdf"
            pdf.write_bytes(b"%PDF")
            result = PdfExtractor(primary=lambda path: "short", fallback=lambda path: "B" * 50, min_chars=20).extract(
                pdf
            )

        self.assertEqual(result.extractor_name, "fallback")
        self.assertEqual(len(result.text), 50)

    def test_process_pdf_with_cleanup_deletes_pdf_after_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "paper.pdf"
            pdf.write_bytes(b"%PDF")

            with self.assertRaises(RuntimeError):
                process_pdf_with_cleanup(pdf, lambda path: (_ for _ in ()).throw(RuntimeError("boom")))

            self.assertFalse(pdf.exists())


if __name__ == "__main__":
    unittest.main()
