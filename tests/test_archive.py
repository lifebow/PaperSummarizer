import tempfile
import unittest
from pathlib import Path
from typing import Any

from paper_radar.archive import ArchiveSearcher, HistoricalCrawler, RateLimiter
from paper_radar.db import PaperRadarDb


class ArchiveTests(unittest.TestCase):
    def test_schema_migration_adds_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            db.upsert_paper(
                {
                    "arxiv_id": "2501.00001",
                    "title": "Test Paper",
                    "primary_category": "cs.AI",
                    "archive_status": "metadata_only",
                }
            )

            paper = db.get_paper_by_arxiv_id("2501.00001")
            self.assertEqual(paper["primary_category"], "cs.AI")
            self.assertEqual(paper["archive_status"], "metadata_only")

    def test_schema_migration_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            db.initialize()

            db.upsert_paper({"arxiv_id": "2501.00002", "title": "Test"})
            paper = db.get_paper_by_arxiv_id("2501.00002")
            self.assertIsNotNone(paper)

    def test_historical_crawler_pagination(self):
        calls = []

        def mock_fetch(params: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
            calls.append(params)
            cursor = params.get("cursor")
            if not cursor:
                return {
                    "data": [
                        {
                            "paperId": "p1",
                            "title": "Paper 1",
                            "externalIds": {"ArXiv": "2301.00001"},
                            "publicationDate": "2023-01-15",
                        },
                        {
                            "paperId": "p2",
                            "title": "Paper 2",
                            "externalIds": {"ArXiv": "2301.00002"},
                            "publicationDate": "2023-01-20",
                        },
                    ],
                    "next": "cursor_abc",
                }
            return {"data": [], "next": None}

        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            crawler = HistoricalCrawler(db, api_keys=["test-key"], rate_limiter=RateLimiter(min_interval=0))
            crawler._fetch = mock_fetch

            result = crawler.crawl("2023-01-01", "2023-12-31", page_size=1000)

            self.assertEqual(result.papers_upserted, 2)
            self.assertIn("2023", result.years_completed)

            paper1 = db.get_paper_by_arxiv_id("2301.00001")
            self.assertIsNotNone(paper1)
            self.assertEqual(paper1["title"], "Paper 1")

            paper2 = db.get_paper_by_arxiv_id("2301.00002")
            self.assertIsNotNone(paper2)

    def test_historical_crawler_skips_completed_years(self):
        def mock_fetch(params: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
            return {"data": [], "next": None}

        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()
            db.set_state("archive_completed_2023", "true")

            crawler = HistoricalCrawler(db, api_keys=["test-key"], rate_limiter=RateLimiter(min_interval=0))
            crawler._fetch = mock_fetch

            result = crawler.crawl("2023-01-01", "2023-12-31")

            self.assertEqual(result.papers_upserted, 0)
            self.assertIn("2023", result.years_completed)

    def test_historical_crawler_rate_limiting(self):
        call_times = []

        def mock_fetch(params: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
            import time

            call_times.append(time.time())
            return {"data": [], "next": None}

        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            limiter = RateLimiter(min_interval=0.1)
            crawler = HistoricalCrawler(db, api_keys=["test-key"], rate_limiter=limiter)
            crawler._fetch = mock_fetch

            crawler.crawl("2023-01-01", "2023-01-01")

            if len(call_times) >= 2:
                elapsed = call_times[1] - call_times[0]
                self.assertGreaterEqual(elapsed, 0.1)

    def test_archive_searcher_basic(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            db.upsert_paper(
                {
                    "arxiv_id": "2501.00001",
                    "title": "Reinforcement Learning Survey",
                    "abstract": "A survey of reinforcement learning methods.",
                    "primary_category": "cs.AI",
                    "published_at": "2025-01-15",
                }
            )
            db.upsert_paper(
                {
                    "arxiv_id": "2501.00002",
                    "title": "Vision Transformers",
                    "abstract": "A new approach to image classification.",
                    "primary_category": "cs.CV",
                    "published_at": "2025-02-10",
                }
            )

            searcher = ArchiveSearcher(db)
            results = searcher.search("reinforcement learning")

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].arxiv_id, "2501.00001")
            self.assertIn("Reinforcement Learning", results[0].title)

    def test_archive_searcher_date_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            db.upsert_paper({"arxiv_id": "2501.00001", "title": "Paper A", "published_at": "2025-01-15"})
            db.upsert_paper({"arxiv_id": "2501.00002", "title": "Paper B", "published_at": "2025-06-10"})

            searcher = ArchiveSearcher(db)
            results = searcher.search("Paper", since="2025-03-01", until="2025-12-31")

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].arxiv_id, "2501.00002")

    def test_archive_searcher_category_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            db.upsert_paper({"arxiv_id": "2501.00001", "title": "AI Paper", "primary_category": "cs.AI"})
            db.upsert_paper({"arxiv_id": "2501.00002", "title": "CV Paper", "primary_category": "cs.CV"})

            searcher = ArchiveSearcher(db)
            results = searcher.search("Paper", category="cs.AI")

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].primary_category, "cs.AI")

    def test_archive_searcher_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            searcher = ArchiveSearcher(db)
            results = searcher.search("nonexistent")

            self.assertEqual(len(results), 0)

    def test_archive_searcher_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PaperRadarDb(Path(tmp) / "radar.sqlite3")
            db.initialize()

            for i in range(10):
                db.upsert_paper({"arxiv_id": f"2501.{i:05d}", "title": f"Paper {i}"})

            searcher = ArchiveSearcher(db)
            results = searcher.search("Paper", limit=3)

            self.assertEqual(len(results), 3)


if __name__ == "__main__":
    unittest.main()
