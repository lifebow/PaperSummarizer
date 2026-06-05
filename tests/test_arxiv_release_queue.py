import tempfile
import threading
import unittest
from pathlib import Path

from paper_radar.config import AppConfig, DaemonConfig, PathConfig, PipelineConfig, TopicConfig, load_config
from paper_radar.daemon import PaperRadarService, RunBudget
from paper_radar.db import PaperRadarDb
from paper_radar.retrieval import PaperMetadata


class FakeTelegram:
    def __init__(self):
        self.messages = []

    def send_message(self, msg, **kwargs):
        self.messages.append((msg, kwargs))


class FakeArxivClient:
    def __init__(self, discoveries=None, hydrate_with_abstract=True):
        self.discoveries = discoveries or []
        self.hydrate_with_abstract = hydrate_with_abstract
        self.search_calls = []
        self.hydrate_calls = []

    def search_list_only(self, categories, *, limit, paper_exists=None):
        self.search_calls.append((list(categories), limit))
        result = []
        for paper in self.discoveries[:limit]:
            if paper_exists and paper_exists(paper.arxiv_id):
                continue
            result.append(paper)
        return result

    def hydrate_papers(self, papers):
        self.hydrate_calls.append([paper.arxiv_id for paper in papers])
        hydrated = []
        for paper in papers:
            hydrated.append(
                PaperMetadata(
                    arxiv_id=paper.arxiv_id,
                    title=paper.title or f"Hydrated {paper.arxiv_id}",
                    abstract=f"Abstract for {paper.arxiv_id}" if self.hydrate_with_abstract else "",
                    authors=["Author"],
                    categories=["cs.AI"],
                    primary_category="cs.AI",
                    published_at="2026-06-05",
                    updated_at="2026-06-05",
                    pdf_url=paper.pdf_url or f"https://arxiv.org/pdf/{paper.arxiv_id}.pdf",
                    source="arxiv",
                )
            )
        return hydrated


def _tmp_config(root: Path, **kwargs):
    return AppConfig(
        topics=kwargs.get("topics", TopicConfig(categories=["cs.AI"], queries=["agent"])),
        daemon=kwargs.get("daemon", DaemonConfig()),
        pipeline=kwargs.get("pipeline", PipelineConfig()),
        paths=PathConfig(
            database=root / "data" / "radar.sqlite3",
            tmp_pdfs=root / "data" / "tmp_pdfs",
            digests=root / "digests",
        ),
    )


class ArxivReleaseMetadataQueueTests(unittest.TestCase):
    def test_config_loads_release_window_and_metadata_queue_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "daemon:",
                        '  release_window_start: "07:00"',
                        '  release_window_end: "09:30"',
                        "pipeline:",
                        "  release_discovery_limit: 2000",
                        "  normal_discovery_limit: 25",
                        "  hydrate_metadata_per_run: 123",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(config_path, root / ".env")

        self.assertEqual(config.daemon.release_window_start, "07:00")
        self.assertEqual(config.daemon.release_window_end, "09:30")
        self.assertEqual(config.pipeline.release_discovery_limit, 2000)
        self.assertEqual(config.pipeline.normal_discovery_limit, 25)
        self.assertEqual(config.pipeline.hydrate_metadata_per_run, 123)

    def test_release_window_discovers_full_list_only_records(self):
        discoveries = [
            PaperMetadata(
                arxiv_id=f"2606.{i:05d}",
                title=f"Paper {i}",
                categories=["cs.AI"],
                primary_category="cs.AI",
                pdf_url=f"https://arxiv.org/pdf/2606.{i:05d}.pdf",
                source="arxiv",
            )
            for i in range(5)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            arxiv = FakeArxivClient(discoveries)
            config = _tmp_config(
                root,
                daemon=DaemonConfig(release_window_start="07:00", release_window_end="09:30"),
                pipeline=PipelineConfig(
                    release_discovery_limit=5,
                    normal_discovery_limit=1,
                    hydrate_metadata_per_run=0,
                    max_papers_per_run=0,
                ),
            )

            result = PaperRadarService(
                config=config,
                db=db,
                telegram=FakeTelegram(),
                arxiv_client=arxiv,
            ).run_once(now_date="2026-06-05", now_time="08:00")

            statuses = [db.get_paper_by_arxiv_id(p.arxiv_id)["archive_status"] for p in discoveries]

        self.assertEqual(result["found_count"], 5)
        self.assertEqual(arxiv.search_calls[0][1], 5)
        self.assertEqual(statuses, ["metadata_only"] * 5)
        self.assertEqual(arxiv.hydrate_calls, [])

    def test_normal_window_uses_normal_discovery_limit(self):
        discoveries = [PaperMetadata(arxiv_id=f"2606.{i:05d}", title=f"Paper {i}") for i in range(4)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            arxiv = FakeArxivClient(discoveries)
            config = _tmp_config(
                root,
                daemon=DaemonConfig(release_window_start="07:00", release_window_end="09:30"),
                pipeline=PipelineConfig(
                    release_discovery_limit=4,
                    normal_discovery_limit=2,
                    hydrate_metadata_per_run=0,
                    max_papers_per_run=0,
                ),
            )

            result = PaperRadarService(
                config=config,
                db=db,
                telegram=FakeTelegram(),
                arxiv_client=arxiv,
            ).run_once(now_date="2026-06-05", now_time="15:00")

        self.assertEqual(result["found_count"], 2)
        self.assertEqual(arxiv.search_calls[0][1], 2)

    def test_discovery_does_not_reset_existing_completed_status(self):
        paper = PaperMetadata(arxiv_id="2606.00001", title="New title")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            db.initialize()
            db.upsert_paper({"arxiv_id": "2606.00001", "title": "Old title", "archive_status": "accepted"})
            arxiv = FakeArxivClient([paper])
            config = _tmp_config(
                root,
                pipeline=PipelineConfig(normal_discovery_limit=10, hydrate_metadata_per_run=0, max_papers_per_run=0),
            )

            PaperRadarService(config=config, db=db, telegram=FakeTelegram(), arxiv_client=arxiv).run_once(
                now_date="2026-06-05", now_time="15:00"
            )
            saved = db.get_paper_by_arxiv_id("2606.00001")

        self.assertEqual(saved["archive_status"], "accepted")
        self.assertEqual(saved["title"], "Old title")

    def test_hydration_is_bounded_and_moves_only_hydrated_papers_to_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            db.initialize()
            for i in range(5):
                db.upsert_paper_discovery(
                    {
                        "arxiv_id": f"2606.{i:05d}",
                        "title": f"Paper {i}",
                        "pdf_url": f"https://arxiv.org/pdf/2606.{i:05d}.pdf",
                    }
                )
            arxiv = FakeArxivClient([])
            config = _tmp_config(
                root,
                pipeline=PipelineConfig(normal_discovery_limit=0, hydrate_metadata_per_run=2, max_papers_per_run=0),
            )
            service = PaperRadarService(config=config, db=db, telegram=FakeTelegram(), arxiv_client=arxiv)

            hydrated = service._hydrate_metadata()

            queued = db.count_papers_by_status("queued")
            metadata_only = db.count_papers_by_status("metadata_only")

        self.assertEqual(arxiv.hydrate_calls, [["2606.00000", "2606.00001"]])
        self.assertEqual(hydrated, 2)
        self.assertEqual(queued, 2)
        self.assertEqual(metadata_only, 3)

    def test_hydration_without_abstract_keeps_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            db.initialize()
            db.upsert_paper_discovery({"arxiv_id": "2606.00001", "title": "Paper"})
            arxiv = FakeArxivClient([], hydrate_with_abstract=False)
            config = _tmp_config(
                root,
                pipeline=PipelineConfig(normal_discovery_limit=0, hydrate_metadata_per_run=1, max_papers_per_run=0),
            )
            service = PaperRadarService(config=config, db=db, telegram=FakeTelegram(), arxiv_client=arxiv)

            hydrated = service._hydrate_metadata()
            saved = db.get_paper_by_arxiv_id("2606.00001")

        self.assertEqual(hydrated, 0)
        self.assertEqual(saved["archive_status"], "metadata_only")

    def test_run_budget_try_record_call_is_thread_safe_under_contention(self):
        budget = RunBudget(25)
        successes = []
        lock = threading.Lock()

        def worker():
            if budget.try_record_call():
                with lock:
                    successes.append(1)

        threads = [threading.Thread(target=worker) for _ in range(100)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(successes), 25)
        self.assertEqual(budget.describe(), "25/25")


if __name__ == "__main__":
    unittest.main()
