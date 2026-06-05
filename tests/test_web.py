import tempfile
import unittest
from pathlib import Path

from paper_radar.db import PaperRadarDb
from paper_radar.retrieval import PaperMetadata


def _seed_accepted(db: PaperRadarDb, arxiv_id: str, title: str, digest_date: str, *, summary=None, idea=5):
    paper_id = db.upsert_paper(
        PaperMetadata(
            arxiv_id=arxiv_id,
            title=title,
            abstract="abstract",
            authors=["Author"],
            categories=["cs.CR"],
            primary_category="cs.CR",
            published_at=digest_date,
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            source="arxiv",
        ).to_record()
    )
    db.update_paper_archive_status(arxiv_id, "accepted")
    run_id = db.start_run()
    db.record_result(
        paper_id=paper_id,
        run_id=run_id,
        candidate_relevance_score=8,
        extractor_name="test",
        extracted_text_chars=100,
        summary=summary or {"what_the_paper_does": "does things"},
        relevance_score=8,
        grounding_score=8,
        idea_score=idea,
        qa_reason="ok",
        accepted=True,
        digest_date=digest_date,
    )


def _client(db, queries):
    from fastapi.testclient import TestClient
    from paper_radar.web import create_app

    return TestClient(create_app(db, queries))


class WebRouteTests(unittest.TestCase):
    def test_home_shows_latest_day_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(db, "2606.00001", "Older Paper", "2026-06-04")
            _seed_accepted(db, "2606.00002", "Newest Paper", "2026-06-05")
            resp = _client(db, ["ai safety"]).get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Newest Paper", resp.text)
        self.assertNotIn("Older Paper", resp.text)

    def test_date_param_selects_that_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(db, "2606.00001", "Older Paper", "2026-06-04")
            _seed_accepted(db, "2606.00002", "Newest Paper", "2026-06-05")
            resp = _client(db, ["ai safety"]).get("/", params={"date": "2026-06-04"})
        self.assertIn("Older Paper", resp.text)
        self.assertNotIn("Newest Paper", resp.text)

    def test_topic_filter_keeps_only_matching_papers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(db, "2606.00001", "A jailbreak study", "2026-06-05")
            _seed_accepted(db, "2606.00002", "Quantum error correction", "2026-06-05")
            client = _client(db, ["jailbreak"])
            resp = client.get("/", params={"topics": "jailbreak"})
        self.assertIn("A jailbreak study", resp.text)
        self.assertNotIn("Quantum error correction", resp.text)

    def test_other_bucket_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(db, "2606.00001", "A jailbreak study", "2026-06-05")
            _seed_accepted(db, "2606.00002", "Quantum error correction", "2026-06-05")
            resp = _client(db, ["jailbreak"]).get("/", params={"topics": "other"})
        self.assertIn("Quantum error correction", resp.text)
        self.assertNotIn("A jailbreak study", resp.text)

    def test_empty_state_for_day_with_no_papers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(db, "2606.00002", "Newest Paper", "2026-06-05")
            resp = _client(db, ["ai safety"]).get("/", params={"date": "2099-01-01"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Không có paper", resp.text)

    def test_unknown_topic_slug_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(db, "2606.00002", "Newest Paper", "2026-06-05")
            resp = _client(db, ["ai safety"]).get("/", params={"topics": "bogus-slug"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Newest Paper", resp.text)


class DatesWithAcceptedResultsTests(unittest.TestCase):
    def test_returns_dates_newest_first_with_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(db, "2606.00001", "P1", "2026-06-04")
            _seed_accepted(db, "2606.00002", "P2", "2026-06-05")
            _seed_accepted(db, "2606.00003", "P3", "2026-06-05")

            result = db.dates_with_accepted_results()

        self.assertEqual(result, [("2026-06-05", 2), ("2026-06-04", 1)])

    def test_empty_when_no_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            self.assertEqual(db.dates_with_accepted_results(), [])


if __name__ == "__main__":
    unittest.main()
