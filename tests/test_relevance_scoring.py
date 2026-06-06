import tempfile
import unittest
from pathlib import Path

from paper_radar.daemon import PaperRadarService
from paper_radar.db import PaperRadarDb
from paper_radar.retrieval import PaperMetadata

from tests.test_arxiv_release_queue import FakeTelegram, _tmp_config


def _seed_paper(db: PaperRadarDb, arxiv_id="2606.99999"):
    return db.upsert_paper(
        PaperMetadata(
            arxiv_id=arxiv_id,
            title="T",
            abstract="a",
            authors=["A"],
            categories=["cs.AI"],
            primary_category="cs.AI",
            published_at="2026-06-06",
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            source="arxiv",
        ).to_record()
    )


class RecordPaperResultTests(unittest.TestCase):
    def test_stores_normalized_scores_not_raw_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            db.initialize()
            paper_id = _seed_paper(db)
            db.update_paper_archive_status("2606.99999", "accepted")
            run_id = db.start_run()
            service = PaperRadarService(config=_tmp_config(root), db=db, telegram=FakeTelegram())

            # Model returned 0-1 scale; pipeline normalized into top-level fields,
            # while data["qa"] still holds the raw 0-1 values.
            data = {
                "arxiv_id": "2606.99999",
                "paper_id": paper_id,
                "run_id": run_id,
                "digest_date": "2026-06-06",
                "candidate_relevance": 8.0,
                "extractor_name": "t",
                "extracted_text_chars": 10,
                "summary": {"what_the_paper_does": "x"},
                "relevance_score": 9.5,
                "grounding_score": 9.0,
                "idea_score": 8.5,
                "qa": {
                    "relevance_score": 0.95,
                    "grounding_score": 0.9,
                    "idea_score": 0.85,
                    "qa_reason": "ok",
                },
                "accepted": True,
            }
            service._record_paper_result(data)
            rows = db.accepted_results_for_date("2026-06-06")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["relevance_score"], 9.5)
        self.assertEqual(rows[0]["grounding_score"], 9.0)
        self.assertEqual(rows[0]["idea_score"], 8.5)


if __name__ == "__main__":
    unittest.main()
