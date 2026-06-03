import tempfile
import unittest
from pathlib import Path

from paper_radar.db import PaperRadarDb


class DbTests(unittest.TestCase):
    def test_upserts_paper_by_arxiv_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            first_id = db.upsert_paper(
                {
                    "arxiv_id": "2501.00001",
                    "semantic_scholar_id": "s2-1",
                    "title": "First Title",
                    "authors": ["A"],
                    "abstract": "Abstract",
                    "categories": ["cs.AI"],
                    "published_at": "2025-01-01",
                    "updated_at": "2025-01-01",
                    "pdf_url": "https://arxiv.org/pdf/2501.00001.pdf",
                    "semantic_scholar_url": "https://semanticscholar.org/paper/s2-1",
                    "source": "semantic_scholar",
                }
            )
            second_id = db.upsert_paper(
                {
                    "arxiv_id": "2501.00001",
                    "semantic_scholar_id": "s2-1",
                    "title": "Updated Title",
                    "authors": ["A", "B"],
                    "abstract": "Updated",
                    "categories": ["cs.AI"],
                    "published_at": "2025-01-01",
                    "updated_at": "2025-01-02",
                    "pdf_url": "https://arxiv.org/pdf/2501.00001.pdf",
                    "semantic_scholar_url": "https://semanticscholar.org/paper/s2-1",
                    "source": "arxiv",
                }
            )

            paper = db.get_paper_by_arxiv_id("2501.00001")

        self.assertEqual(first_id, second_id)
        self.assertEqual(paper["title"], "Updated Title")
        self.assertEqual(paper["source"], "arxiv")

    def test_records_run_and_accepted_results_for_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            run_id = db.start_run()
            paper_id = db.upsert_paper({"arxiv_id": "2501.00002", "title": "Paper"})
            db.record_result(
                paper_id=paper_id,
                run_id=run_id,
                candidate_relevance_score=8,
                extractor_name="pymupdf4llm",
                extracted_text_chars=1234,
                summary={"title": "Paper", "ideas_to_try": ["Try it"]},
                relevance_score=8,
                grounding_score=8,
                idea_score=7,
                qa_reason="good",
                accepted=True,
                digest_date="2026-05-29",
            )
            db.finish_run(run_id, "ok", found_count=3, accepted_count=1, error_count=0)

            accepted = db.accepted_results_for_date("2026-05-29")

        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["arxiv_id"], "2501.00002")
        self.assertEqual(accepted[0]["summary"]["ideas_to_try"], ["Try it"])

    def test_tracks_telegram_recap_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            self.assertFalse(db.was_recap_sent("2026-05-29"))
            db.mark_recap("2026-05-29", "sent", error="")

            self.assertTrue(db.was_recap_sent("2026-05-29"))


if __name__ == "__main__":
    unittest.main()
