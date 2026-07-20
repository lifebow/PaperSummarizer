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
    """Single-set client (backward-compatible helper for keyword-level tests)."""
    from paper_radar.config import FilterSet

    return _client_sets(db, [FilterSet("AI Safety", queries)])


def _client_sets(db, filter_sets):
    from fastapi.testclient import TestClient
    from paper_radar.web import create_app

    return TestClient(create_app(db, filter_sets))


def _two_sets():
    from paper_radar.config import FilterSet

    return [
        FilterSet("AI Safety", ["jailbreak", "prompt injection"]),
        FilterSet("Computer Vision", ["object detection", "segmentation"]),
    ]


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


class MastheadDateTests(unittest.TestCase):
    def setUp(self):
        from paper_radar.web import masthead_date

        self.fmt = masthead_date

    def test_formats_weekday_and_date(self):
        # 2026-06-06 is a Saturday.
        self.assertEqual(self.fmt("2026-06-06"), "Sat · 2026-06-06")

    def test_truncates_datetime_to_day(self):
        self.assertEqual(self.fmt("2026-06-06T12:30:00Z"), "Sat · 2026-06-06")

    def test_none_and_empty_yield_empty_string(self):
        self.assertEqual(self.fmt(None), "")
        self.assertEqual(self.fmt(""), "")

    def test_unparseable_falls_back_to_raw(self):
        self.assertEqual(self.fmt("not-a-date"), "not-a-date")


class MonthLabelTests(unittest.TestCase):
    def setUp(self):
        from paper_radar.web import month_label

        self.label = month_label

    def test_formats_month_and_short_year(self):
        self.assertEqual(self.label("2026-07"), "JUL '26")
        self.assertEqual(self.label("2025-12"), "DEC '25")

    def test_unparseable_falls_back_to_raw(self):
        self.assertEqual(self.label("nope"), "nope")


class MonthNavigatorTests(unittest.TestCase):
    def _seed_two_months(self, db):
        _seed_accepted(db, "2606.00001", "June Paper", "2026-06-04")
        _seed_accepted(db, "2605.00002", "May Paper", "2026-05-29")

    def test_groups_days_into_month_tabs_with_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            self._seed_two_months(db)
            resp = _client(db, ["ai safety"]).get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Browse by month", resp.text)
        # apostrophe in "JUN '26" is HTML-escaped by Jinja -> "JUN &#39;26"
        self.assertIn("JUN", resp.text)
        self.assertIn("MAY", resp.text)
        # default month = newest day's month (June); summary reflects that month.
        self.assertIn("1 days · 1 papers", resp.text)

    def test_default_month_grid_shows_only_newest_months_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            self._seed_two_months(db)
            resp = _client(db, ["ai safety"]).get("/")
        # June is default: its day chip (04) renders; May's day (29) does not.
        self.assertIn(">04</div>", resp.text)
        self.assertNotIn(">29</div>", resp.text)

    def test_month_param_switches_day_grid_without_changing_loaded_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            self._seed_two_months(db)
            resp = _client(db, ["ai safety"]).get("/", params={"month": "2026-05"})
        # grid now shows May's day (29); loaded papers stay on the newest day (June).
        self.assertIn(">29</div>", resp.text)
        self.assertIn("June Paper", resp.text)
        self.assertNotIn("May Paper", resp.text)


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

    def test_search_matches_title_across_all_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            # older day, matches; newer day, does not
            _seed_accepted(db, "2606.00001", "A jailbreak attack study", "2026-06-04")
            _seed_accepted(db, "2606.00002", "Unrelated topic", "2026-06-05")
            resp = _client(db, ["ai safety"]).get("/", params={"q": "jailbreak"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("A jailbreak attack study", resp.text)
        self.assertNotIn("Unrelated topic", resp.text)
        self.assertIn("matching", resp.text)

    def test_search_no_results_shows_empty_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(db, "2606.00001", "Some paper", "2026-06-04")
            resp = _client(db, ["ai safety"]).get("/", params={"q": "zzzznomatch"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("No papers match", resp.text)

    def test_date_shows_separate_set_and_total_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(db, "2606.00001", "A jailbreak study", "2026-06-05")
            _seed_accepted(db, "2606.00002", "Unrelated paper", "2026-06-05")
            resp = _client(db, ["jailbreak"]).get("/")
        self.assertEqual(resp.status_code, 200)
        # Day chip shows "in-scope / total" = "1/2"; standfirst echoes the split.
        self.assertIn(">1/2</div>", resp.text)
        self.assertIn("1 in scope for AI safety", resp.text)

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
            resp = _client(db, ["jailbreak"]).get("/", params={"set": "other"})
        self.assertIn("Quantum error correction", resp.text)
        self.assertNotIn("A jailbreak study", resp.text)

    def test_empty_state_for_day_with_no_papers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(db, "2606.00002", "Newest Paper", "2026-06-05")
            resp = _client(db, ["ai safety"]).get("/", params={"date": "2099-01-01"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("No papers", resp.text)

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
        self.assertEqual(resp.text.count(">First idea here</li>"), 1)
        self.assertEqual(resp.text.count(">Second idea here</li>"), 1)
        self.assertEqual(resp.text.count(">Third idea here</li>"), 1)

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
        # Affiliations fold into the mono byline ("authors · org"), deduplicated,
        # and render in the distinct `org` color to read apart from authors.
        self.assertIn("KAIST AI", resp.text)
        self.assertIn("EPFL", resp.text)
        self.assertEqual(resp.text.count("KAIST AI"), 1)
        self.assertIn("text-org", resp.text)

    def test_unknown_topic_slug_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(db, "2606.00002", "Newest Paper", "2026-06-05")
            resp = _client(db, ["ai safety"]).get("/", params={"topics": "bogus-slug"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Newest Paper", resp.text)


class FilterSetRouteTests(unittest.TestCase):
    def _seed_two(self, db):
        _seed_accepted(db, "2606.01001", "A jailbreak prompt injection study", "2026-06-06")
        _seed_accepted(db, "2606.01002", "Real-time object detection model", "2026-06-06")
        _seed_accepted(db, "2606.01003", "Quantum error correction codes", "2026-06-06")

    def test_set_filter_keeps_only_papers_in_that_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            self._seed_two(db)
            resp = _client_sets(db, _two_sets()).get("/", params={"set": "computer-vision"})
        self.assertIn("Real-time object detection model", resp.text)
        self.assertNotIn("A jailbreak prompt injection study", resp.text)
        self.assertNotIn("Quantum error correction codes", resp.text)

    def test_other_set_keeps_papers_matching_no_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            self._seed_two(db)
            resp = _client_sets(db, _two_sets()).get("/", params={"set": "other"})
        self.assertIn("Quantum error correction codes", resp.text)
        self.assertNotIn("Real-time object detection model", resp.text)

    def test_set_plus_keyword_intersection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            _seed_accepted(db, "2606.01001", "A jailbreak study", "2026-06-06")
            _seed_accepted(db, "2606.01004", "A prompt injection attack", "2026-06-06")
            resp = _client_sets(db, _two_sets()).get("/", params={"set": "ai-safety", "topics": "jailbreak"})
        self.assertIn("A jailbreak study", resp.text)
        self.assertNotIn("A prompt injection attack", resp.text)

    def test_no_tier2_keyword_chips_in_ledger_design(self):
        # The Ledger design drops the tier-2 keyword sub-filter chips; no keyword
        # slug/href should appear in either view. (URL `topics` filtering is still
        # honored server-side — see test_set_plus_keyword_intersection.)
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            self._seed_two(db)
            client = _client_sets(db, _two_sets())
            all_view = client.get("/").text
            set_view = client.get("/", params={"set": "computer-vision"}).text
        self.assertNotIn("object-detection", all_view)
        self.assertNotIn("object-detection", set_view)
        # the matching paper's topic still shows as an accent meta tag (label form)
        self.assertIn("object detection", set_view)

    def test_unknown_set_slug_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            self._seed_two(db)
            resp = _client_sets(db, _two_sets()).get("/", params={"set": "bogus"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Real-time object detection model", resp.text)


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
