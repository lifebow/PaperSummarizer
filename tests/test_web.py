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


class NormalizeIdeasTests(unittest.TestCase):
    def setUp(self):
        from paper_radar.web import normalize_ideas

        self.normalize = normalize_ideas

    def test_list_passes_through_stripped(self):
        self.assertEqual(self.normalize(["a", " b "]), ["a", "b"])

    def test_numbered_string_splits_into_items(self):
        self.assertEqual(self.normalize("1. Alpha 2. Beta 3. Gamma"), ["Alpha", "Beta", "Gamma"])

    def test_paren_numbered_string_splits(self):
        self.assertEqual(self.normalize("1) Alpha 2) Beta"), ["Alpha", "Beta"])

    def test_bullet_string_splits(self):
        self.assertEqual(self.normalize("• Alpha • Beta"), ["Alpha", "Beta"])

    def test_semicolon_list_splits_when_no_enumeration(self):
        self.assertEqual(self.normalize("apply X; automate Y; combine Z"), ["apply X", "automate Y", "combine Z"])

    def test_plain_sentence_stays_single_item(self):
        self.assertEqual(self.normalize("Just one idea here"), ["Just one idea here"])

    def test_strips_leading_dash_marker_from_items(self):
        self.assertEqual(self.normalize("- Replace policy; - Add tests"), ["Replace policy", "Add tests"])

    def test_does_not_split_on_intra_sentence_hyphen(self):
        self.assertEqual(self.normalize("Apply role-relabeling to agents"), ["Apply role-relabeling to agents"])

    def test_empty_and_none(self):
        self.assertEqual(self.normalize(""), [])
        self.assertEqual(self.normalize(None), [])

    def test_does_not_split_into_characters(self):
        # regression: a string must never become one item per character
        result = self.normalize("1. Alpha 2. Beta")
        self.assertTrue(all(len(item) > 1 for item in result))


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

    def test_string_ideas_render_as_discrete_list_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(
                db,
                "2606.00009",
                "Paper with string ideas",
                "2026-06-05",
                summary={"ideas_to_try": "1. First idea here 2. Second idea here 3. Third idea here"},
            )
            resp = _client(db, ["ai safety"]).get("/")
        self.assertEqual(resp.text.count("<li>First idea here</li>"), 1)
        self.assertEqual(resp.text.count("<li>Second idea here</li>"), 1)
        self.assertEqual(resp.text.count("<li>Third idea here</li>"), 1)

    def test_affiliations_from_summary_are_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(
                db,
                "2606.00010",
                "Paper with affiliations",
                "2026-06-05",
                summary={
                    "what_the_paper_does": "x",
                    "author_affiliations": ["KAIST AI", "KAIST AI", "EPFL"],
                },
            )
            resp = _client(db, ["ai safety"]).get("/")
        self.assertIn("KAIST AI", resp.text)
        self.assertIn("EPFL", resp.text)
        # deduplicated: "KAIST AI" rendered once
        self.assertEqual(resp.text.count(">KAIST AI<"), 1)

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
