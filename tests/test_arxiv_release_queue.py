import tempfile
import threading
import unittest
from pathlib import Path

from paper_radar.config import AppConfig, DaemonConfig, PathConfig, PipelineConfig, TopicConfig, load_config
from paper_radar.daemon import PaperRadarService, RunBudget, _hash_paper, _topic_fingerprint
from paper_radar.db import PaperRadarDb
from paper_radar.extraction import ExtractedText
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


class HeaderCountArxivClient(FakeArxivClient):
    def __init__(self, pages):
        super().__init__([])
        self.pages = pages
        self.page_calls = []

    def fetch_page_html(self, categories, *, show=50, skip=0):
        self.page_calls.append((list(categories), show, skip))
        return self.pages[(show, skip)]

    def _parse_entries_from_html(self, html, *, paper_exists=None, target_section=None):
        from paper_radar.retrieval import ArxivClient

        return ArxivClient()._parse_entries_from_html(
            html,
            paper_exists=paper_exists,
            target_section=target_section,
        )


class FakeDownloader:
    def download(self, paper, tmp_dir):
        return tmp_dir / f"{paper.arxiv_id}.pdf"


class FakeExtractor:
    def extract(self, path):
        return ExtractedText(text="full text " * 50, extractor_name="primary")


def _recent_html(section_date: str, expected_total: int, ids: list[str], older_ids: list[str] | None = None) -> str:
    def _entry(arxiv_id: str) -> str:
        return (
            f'<dt><a href="/abs/{arxiv_id}">arXiv:{arxiv_id}</a></dt>'
            f'<dd><div class="list-title"><span class="descriptor">Title:</span>Paper {arxiv_id}</div></dd>'
        )

    latest_entries = "\n".join(_entry(arxiv_id) for arxiv_id in ids)
    older_entries = "\n".join(_entry(arxiv_id) for arxiv_id in (older_ids or []))
    older_section = ""
    if older_ids:
        older_section = f"""
        <h3>Thu, 4 Jun 2026 (showing first {len(older_ids)} of {len(older_ids)} entries)</h3>
        <dl>{older_entries}</dl>
        """
    return f"""
    <h3>{section_date} (showing first {min(50, expected_total)} of {expected_total} entries)</h3>
    <dl>{latest_entries}</dl>
    {older_section}
    """


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
    def test_topic_fingerprint_changes_relevance_cache_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_config = _tmp_config(root, topics=TopicConfig(categories=["cs.AI"], queries=["LLM agent"]))
            new_config = _tmp_config(root, topics=TopicConfig(categories=["cs.AI"], queries=["AI safety"]))

        old_hash = _hash_paper("Title", "Abstract", _topic_fingerprint(old_config))
        new_hash = _hash_paper("Title", "Abstract", _topic_fingerprint(new_config))

        self.assertNotEqual(old_hash, new_hash)

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

    def test_header_count_discovery_fetches_allowed_show_and_marks_complete(self):
        ids = [f"2606.{i:05d}" for i in range(5)]
        probe_html = _recent_html("Fri, 5 Jun 2026", 5, ids[:2])
        full_html = _recent_html("Fri, 5 Jun 2026", 5, ids, older_ids=["2606.99999"])
        arxiv = HeaderCountArxivClient({(50, 0): probe_html, (25, 0): full_html})

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            config = _tmp_config(
                root,
                pipeline=PipelineConfig(normal_discovery_limit=100, hydrate_metadata_per_run=0, max_papers_per_run=0),
            )

            result = PaperRadarService(
                config=config,
                db=db,
                telegram=FakeTelegram(),
                arxiv_client=arxiv,
            ).run_once(now_date="2026-06-05", now_time="15:00")

            saved_ids = [db.get_paper_by_arxiv_id(arxiv_id)["arxiv_id"] for arxiv_id in ids]
            older_saved = db.get_paper_by_arxiv_id("2606.99999")
            section_date = db.get_state("arxiv_recent_latest_section_date")
            expected_total = db.get_state("arxiv_recent_latest_expected_total")
            discovered_count = db.get_state("arxiv_recent_latest_discovered_count")
            complete = db.get_state("arxiv_recent_latest_complete")

        self.assertEqual(result["found_count"], 5)
        self.assertEqual(arxiv.page_calls, [(["cs.AI"], 50, 0), (["cs.AI"], 25, 0)])
        self.assertEqual(saved_ids, ids)
        self.assertIsNone(older_saved)
        self.assertEqual(section_date, "Fri, 5 Jun 2026")
        self.assertEqual(expected_total, "5")
        self.assertEqual(discovered_count, "5")
        self.assertEqual(complete, "true")

    def test_header_count_completion_counts_existing_papers_in_latest_section(self):
        ids = [f"2606.{i:05d}" for i in range(3)]
        probe_html = _recent_html("Fri, 5 Jun 2026", 3, ids[:1])
        full_html = _recent_html("Fri, 5 Jun 2026", 3, ids)
        arxiv = HeaderCountArxivClient({(50, 0): probe_html, (25, 0): full_html})

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            db.initialize()
            db.upsert_paper_discovery({"arxiv_id": ids[0], "title": "Already saved"})
            config = _tmp_config(
                root,
                pipeline=PipelineConfig(normal_discovery_limit=100, hydrate_metadata_per_run=0, max_papers_per_run=0),
            )

            result = PaperRadarService(
                config=config,
                db=db,
                telegram=FakeTelegram(),
                arxiv_client=arxiv,
            ).run_once(now_date="2026-06-05", now_time="15:00")
            discovered_count = db.get_state("arxiv_recent_latest_discovered_count")
            complete = db.get_state("arxiv_recent_latest_complete")

        self.assertEqual(result["found_count"], 2)
        self.assertEqual(discovered_count, "3")
        self.assertEqual(complete, "true")

    def test_header_count_refetches_when_full_page_reports_larger_total(self):
        ids = [f"2606.{i:05d}" for i in range(51)]
        probe_html = _recent_html("Fri, 5 Jun 2026", 25, ids[:10])
        stale_full_html = _recent_html("Fri, 5 Jun 2026", 51, ids[:25])
        current_full_html = _recent_html("Fri, 5 Jun 2026", 51, ids)
        arxiv = HeaderCountArxivClient(
            {
                (50, 0): probe_html,
                (25, 0): stale_full_html,
                (100, 0): current_full_html,
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            config = _tmp_config(
                root,
                pipeline=PipelineConfig(normal_discovery_limit=100, hydrate_metadata_per_run=0, max_papers_per_run=0),
            )

            result = PaperRadarService(
                config=config,
                db=db,
                telegram=FakeTelegram(),
                arxiv_client=arxiv,
            ).run_once(now_date="2026-06-05", now_time="15:00")
            discovered_count = db.get_state("arxiv_recent_latest_discovered_count")
            complete = db.get_state("arxiv_recent_latest_complete")

        self.assertEqual(result["found_count"], 51)
        self.assertEqual(arxiv.page_calls, [(["cs.AI"], 50, 0), (["cs.AI"], 25, 0), (["cs.AI"], 100, 0)])
        self.assertEqual(discovered_count, "51")
        self.assertEqual(complete, "true")

    def test_header_count_discovery_skips_consistent_completed_state(self):
        probe_html = _recent_html("Fri, 5 Jun 2026", 3, ["2606.00001"])
        arxiv = HeaderCountArxivClient({(50, 0): probe_html})

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            db.initialize()
            db.set_state("arxiv_recent_latest_section_date", "Fri, 5 Jun 2026")
            db.set_state("arxiv_recent_latest_expected_total", "3")
            db.set_state("arxiv_recent_latest_discovered_count", "3")
            db.set_state("arxiv_recent_latest_complete", "true")
            config = _tmp_config(
                root,
                pipeline=PipelineConfig(normal_discovery_limit=100, hydrate_metadata_per_run=0, max_papers_per_run=0),
            )

            result = PaperRadarService(
                config=config,
                db=db,
                telegram=FakeTelegram(),
                arxiv_client=arxiv,
            ).run_once(now_date="2026-06-05", now_time="15:00")

        self.assertEqual(result["found_count"], 0)
        self.assertEqual(arxiv.page_calls, [(["cs.AI"], 50, 0)])

    def test_startup_check_replays_summary_and_accepted_cards_when_latest_section_complete(self):
        probe_html = _recent_html("Fri, 5 Jun 2026", 3, ["2606.00001"])
        arxiv = HeaderCountArxivClient({(50, 0): probe_html})

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            db.initialize()
            paper_id = db.upsert_paper(
                PaperMetadata(
                    arxiv_id="2606.00001",
                    title="Replay Paper",
                    abstract="Abstract",
                    authors=["Author"],
                    categories=["cs.AI"],
                    primary_category="cs.AI",
                    published_at="2026-06-05",
                    pdf_url="https://arxiv.org/pdf/2606.00001.pdf",
                    source="arxiv",
                ).to_record()
            )
            run_id = db.start_run()
            db.record_result(
                paper_id=paper_id,
                run_id=run_id,
                candidate_relevance_score=8,
                extractor_name="test",
                extracted_text_chars=100,
                summary={"summary": "Short replay summary", "idea": "Useful"},
                relevance_score=8,
                grounding_score=8,
                idea_score=8,
                qa_reason="ok",
                accepted=True,
                digest_date="2026-06-05",
            )
            db.set_state("arxiv_recent_latest_section_date", "Fri, 5 Jun 2026")
            db.set_state("arxiv_recent_latest_section_date_iso", "2026-06-05")
            db.set_state("arxiv_recent_latest_digest_date", "2026-06-05")
            db.set_state("arxiv_recent_latest_expected_total", "3")
            db.set_state("arxiv_recent_latest_discovered_count", "3")
            db.set_state("arxiv_recent_latest_complete", "true")
            telegram = FakeTelegram()
            config = _tmp_config(
                root,
                pipeline=PipelineConfig(normal_discovery_limit=100, hydrate_metadata_per_run=0, max_papers_per_run=0),
            )
            db.set_state("arxiv_recent_latest_topic_fingerprint", _topic_fingerprint(config))

            result = PaperRadarService(
                config=config,
                db=db,
                telegram=telegram,
                arxiv_client=arxiv,
            ).run_startup_check(now_date="2026-06-05", now_time="15:00")

        sent_texts = [msg for msg, _ in telegram.messages]
        self.assertEqual(result["status"], "replayed")
        self.assertEqual(arxiv.page_calls, [(["cs.AI"], 50, 0)])
        self.assertIn("Bot online", sent_texts[0])
        self.assertIn("đã quét", sent_texts[1])
        self.assertIn("3/3", sent_texts[1])
        self.assertIn("1 accepted", sent_texts[1])
        self.assertTrue(any("Replay Paper" in msg for msg in sent_texts))

    def test_startup_check_rescores_from_db_when_topic_filter_changed(self):
        ids = ["2606.00001"]
        probe_html = _recent_html("Fri, 5 Jun 2026", 1, ids)
        arxiv = HeaderCountArxivClient({(50, 0): probe_html, (25, 0): probe_html})

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            db.initialize()
            paper_id = db.upsert_paper(
                PaperMetadata(
                    arxiv_id="2606.00001",
                    title="Old Topic Paper",
                    abstract="Abstract",
                    authors=["Author"],
                    categories=["cs.AI"],
                    primary_category="cs.AI",
                    published_at="2026-06-05",
                    pdf_url="https://arxiv.org/pdf/2606.00001.pdf",
                    source="arxiv",
                ).to_record()
            )
            db.update_paper_archive_status("2606.00001", "accepted")
            run_id = db.start_run()
            db.record_result(
                paper_id=paper_id,
                run_id=run_id,
                candidate_relevance_score=8,
                extractor_name="test",
                extracted_text_chars=100,
                summary={"summary": "Old replay summary", "idea": "Old topic"},
                relevance_score=8,
                grounding_score=8,
                idea_score=8,
                qa_reason="ok",
                accepted=True,
                digest_date="2026-06-05",
            )
            db.set_state("arxiv_recent_latest_section_date", "Fri, 5 Jun 2026")
            db.set_state("arxiv_recent_latest_section_date_iso", "2026-06-05")
            db.set_state("arxiv_recent_latest_digest_date", "2026-06-05")
            db.set_state("arxiv_recent_latest_expected_total", "1")
            db.set_state("arxiv_recent_latest_discovered_count", "1")
            db.set_state("arxiv_recent_latest_complete", "true")
            old_config = _tmp_config(root, topics=TopicConfig(categories=["cs.AI"], queries=["LLM agent"]))
            db.set_state("arxiv_recent_latest_topic_fingerprint", _topic_fingerprint(old_config))

            telegram = FakeTelegram()
            config = _tmp_config(
                root,
                topics=TopicConfig(categories=["cs.AI"], queries=["AI safety", "LLM jailbreak"]),
                pipeline=PipelineConfig(normal_discovery_limit=100, hydrate_metadata_per_run=0, max_papers_per_run=1),
            )

            result = PaperRadarService(
                config=config,
                db=db,
                telegram=telegram,
                arxiv_client=arxiv,
                downloader=FakeDownloader(),
                extractor=FakeExtractor(),
            ).run_startup_check(now_date="2026-06-05", now_time="15:00")

            accepted = db.accepted_results_for_date("2026-06-05")
            stored_fingerprint = db.get_state("arxiv_recent_latest_topic_fingerprint")

        sent_texts = [msg for msg, _ in telegram.messages]
        self.assertEqual(result["status"], "rescored_topic_change")
        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(stored_fingerprint, _topic_fingerprint(config))
        self.assertTrue(any("Topic filter đã đổi" in msg for msg in sent_texts))
        self.assertFalse(any("Gửi lại kết quả đã lưu" in msg for msg in sent_texts))
        # Title+abstract đã có trong DB → chỉ probe header (show=50), KHÔNG tải lại
        # full section (show=25). Re-score thuần từ DB.
        self.assertTrue(all(show == 50 for _, show, _ in arxiv.page_calls))
        self.assertNotIn((["cs.AI"], 25, 0), arxiv.page_calls)

    def test_startup_check_notifies_scan_in_progress_when_latest_section_not_complete(self):
        ids = [f"2606.{i:05d}" for i in range(3)]
        probe_html = _recent_html("Fri, 5 Jun 2026", 3, ids[:1])
        full_html = _recent_html("Fri, 5 Jun 2026", 3, ids)
        arxiv = HeaderCountArxivClient({(50, 0): probe_html, (25, 0): full_html})

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            telegram = FakeTelegram()
            config = _tmp_config(
                root,
                pipeline=PipelineConfig(normal_discovery_limit=100, hydrate_metadata_per_run=0, max_papers_per_run=0),
            )

            result = PaperRadarService(
                config=config,
                db=db,
                telegram=telegram,
                arxiv_client=arxiv,
            ).run_startup_check(now_date="2026-06-05", now_time="15:00")

            complete = db.get_state("arxiv_recent_latest_complete")
            digest_date = db.get_state("arxiv_recent_latest_digest_date")

        sent_texts = [msg for msg, _ in telegram.messages]
        self.assertEqual(result["status"], "scanned")
        self.assertEqual(complete, "true")
        self.assertEqual(digest_date, "2026-06-05")
        self.assertIn("Bot online", sent_texts[0])
        self.assertTrue(any("Đang quét" in msg and "3 entries" in msg for msg in sent_texts))
        self.assertTrue(any("3 paper mới" in msg for msg in sent_texts))

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
