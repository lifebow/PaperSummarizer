import os
import tempfile
import unittest
from pathlib import Path

from paper_radar.archive import ArchiveSearcher, HistoricalCrawler, RateLimiter
from paper_radar.db import PaperRadarDb
from paper_radar.retrieval import SemanticScholarClient


def requires_s2_api(cls):
    api_keys_str = os.environ.get("SEMANTIC_SCHOLAR_API_KEYS", "")
    if not api_keys_str or not api_keys_str.strip():
        return unittest.skip("SEMANTIC_SCHOLAR_API_KEYS not set")(cls)
    return cls


@requires_s2_api
class ArchiveIntegrationTests(unittest.TestCase):
    def setUp(self):
        api_keys_str = os.environ.get("SEMANTIC_SCHOLAR_API_KEYS", "")
        self.api_keys = [k.strip() for k in api_keys_str.split(",") if k.strip()]
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.tmp_dir) / "radar.sqlite3"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_s2_bulk_search_returns_papers(self):
        client = SemanticScholarClient(api_keys=self.api_keys)
        papers = client.search("transformer", limit=5)
        self.assertGreater(len(papers), 0)
        for paper in papers:
            self.assertTrue(paper.arxiv_id)
            self.assertTrue(paper.title)

    def test_historical_crawler_crawls_one_month(self):
        db = PaperRadarDb(self.db_path)
        db.initialize()

        crawler = HistoricalCrawler(
            db,
            api_keys=self.api_keys,
            rate_limiter=RateLimiter(min_interval=0.5),
        )
        result = crawler.crawl("2025-01-01", "2025-01-31", page_size=100)

        self.assertGreater(result.papers_upserted, 0)
        self.assertIn("2025", result.years_completed)

        paper = db.get_paper_by_arxiv_id("2501.00001")
        if paper:
            self.assertTrue(paper["title"])
            self.assertTrue(paper["abstract"])

    def test_archive_searcher_finds_crawled_papers(self):
        db = PaperRadarDb(self.db_path)
        db.initialize()

        crawler = HistoricalCrawler(
            db,
            api_keys=self.api_keys,
            rate_limiter=RateLimiter(min_interval=0.5),
        )
        crawler.crawl("2025-01-01", "2025-01-31", page_size=100)

        searcher = ArchiveSearcher(db)
        results = searcher.search("a", limit=10)

        self.assertGreater(len(results), 0)
        for r in results:
            self.assertTrue(r.arxiv_id)
            self.assertTrue(r.title)

    def test_archive_searcher_date_filter(self):
        db = PaperRadarDb(self.db_path)
        db.initialize()

        crawler = HistoricalCrawler(
            db,
            api_keys=self.api_keys,
            rate_limiter=RateLimiter(min_interval=0.5),
        )
        crawler.crawl("2025-01-01", "2025-01-31", page_size=100)

        searcher = ArchiveSearcher(db)
        results = searcher.search("paper", since="2025-01-15", until="2025-01-20")

        for r in results:
            self.assertGreaterEqual(r.published_at, "2025-01-15")
            self.assertLessEqual(r.published_at, "2025-01-20")


if __name__ == "__main__":
    unittest.main()
