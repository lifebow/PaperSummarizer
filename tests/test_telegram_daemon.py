import tempfile
import unittest
from pathlib import Path

from paper_radar.config import AppConfig, FilterConfig, PathConfig, PipelineConfig, TelegramConfig, TopicConfig
from paper_radar.daemon import DefaultPaperLlm, PaperRadarService, RunBudget
from paper_radar.db import PaperRadarDb
from paper_radar.extraction import ExtractedText
from paper_radar.retrieval import PaperMetadata
from paper_radar.telegram import TelegramSender


def _seed_queued_papers(db, papers):
    for paper in papers:
        paper.arxiv_id = paper.arxiv_id
        record = paper.to_record()
        record["archive_status"] = "queued"
        db.upsert_paper(record)


def _fake_arxiv_client(papers):
    class FakeArxivClient:
        def __init__(self, paper_list):
            self._papers = paper_list

        def search_list_only(self, categories, *, limit, paper_exists=None):
            return [p for p in self._papers if not paper_exists or not paper_exists(p.arxiv_id)]

        def hydrate_papers(self, papers):
            return [
                PaperMetadata(
                    arxiv_id=p.arxiv_id,
                    title=p.title or "Hydrated Title",
                    abstract=f"Abstract for {p.arxiv_id}",
                    authors=["Author"],
                    categories=["cs.AI"],
                    primary_category="cs.AI",
                    published_at="2026-05-29",
                    pdf_url=p.pdf_url,
                    source="arxiv",
                )
                for p in papers
            ]

    return FakeArxivClient(papers)


class TelegramDaemonTests(unittest.TestCase):
    def test_run_budget_zero_means_unlimited(self):
        budget = RunBudget(0)

        for _ in range(3):
            self.assertTrue(budget.can_call())
            budget.record_call()

        self.assertTrue(budget.can_call())
        self.assertEqual(budget.describe(), "3/unlimited")

    def test_run_budget_try_record_call_atomic(self):
        budget = RunBudget(2)

        self.assertTrue(budget.try_record_call())
        self.assertTrue(budget.try_record_call())
        self.assertFalse(budget.try_record_call())

    def test_default_paper_llm_retries_retryable_errors(self):
        class FakeClient:
            def __init__(self):
                self.calls = 0

            def complete_json(self, system, user):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("HTTP Error 429: Too Many Requests")
                return {"relevance_score": 8}

        client = FakeClient()
        llm = DefaultPaperLlm(client, retry_delays=(0,))

        result = llm.relevance(PaperMetadata(arxiv_id="2606.00001", title="T", abstract="A"), ["agent"])

        self.assertEqual(result["relevance_score"], 8)
        self.assertEqual(client.calls, 2)

    def test_telegram_sender_posts_message(self):
        captured = {}

        def fake_post(url, *, payload, timeout):
            captured["url"] = url
            captured["payload"] = payload
            return {"ok": True}

        sender = TelegramSender(bot_token="bot-token", chat_id="chat-id", http_post=fake_post)
        sender.send_message("hello")

        self.assertIn("/botbot-token/sendMessage", captured["url"])
        self.assertEqual(captured["payload"]["chat_id"], "chat-id")
        self.assertEqual(captured["payload"]["text"], "hello")

    def test_run_once_accepts_paper_writes_digest_and_cleans_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            config = AppConfig(
                topics=TopicConfig(categories=["cs.AI"], queries=["LLM agent"]),
                filters=FilterConfig(max_papers_per_batch=5),
                paths=PathConfig(
                    database=root / "data" / "radar.sqlite3",
                    tmp_pdfs=root / "data" / "tmp_pdfs",
                    digests=root / "digests",
                ),
            )
            paper = PaperMetadata(arxiv_id="2605.12345", title="Agent Safety", abstract="abstract", pdf_url="pdf")
            downloaded_pdf = root / "data" / "tmp_pdfs" / "2605.12345.pdf"

            class FakeDownloader:
                def download(self, paper, tmp_dir):
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                    downloaded_pdf.write_bytes(b"%PDF")
                    return downloaded_pdf

            class FakeExtractor:
                def extract(self, path):
                    return ExtractedText(text="full text " * 50, extractor_name="primary")

            class FakeLlm:
                def relevance(self, paper, topics):
                    return {"relevance_score": 8, "reason": "relevant"}

                def summarize(self, paper, full_text):
                    return {
                        "background_needed": "MDP basics.",
                        "what_the_paper_does": "Studies safety.",
                        "novelty": "New benchmark.",
                        "method": "Evaluation.",
                        "math_technical_core": "Expected loss.",
                        "results_claims": "Finds failures.",
                        "limitations_uncertainty": "Small sample.",
                        "ideas_to_try": ["Try stronger tools"],
                    }

                def qa(self, paper, summary, full_text):
                    return {
                        "relevance_score": 8,
                        "grounding_score": 8,
                        "idea_score": 7,
                        "qa_reason": "good",
                        "evidence_snippets": ["abstract"],
                    }

            sent_messages = []
            fake_telegram = type(
                "FakeTelegram",
                (),
                {"send_message": lambda self, msg, **kwargs: sent_messages.append(msg)},
            )()
            service = PaperRadarService(
                config=config,
                db=db,
                downloader=FakeDownloader(),
                extractor=FakeExtractor(),
                llm=FakeLlm(),
                telegram=fake_telegram,
                arxiv_client=_fake_arxiv_client([paper]),
            )
            result = service.run_once(now_date="2026-05-29", now_time="15:00")

            digest = (root / "digests" / "2026-05-29.md").read_text(encoding="utf-8")

        self.assertEqual(result["accepted_count"], 1)
        self.assertIn("Agent Safety", digest)
        self.assertFalse(downloaded_pdf.exists())
        self.assertTrue(len(sent_messages) >= 1)
        self.assertTrue(any("match" in m for m in sent_messages))

    def test_run_once_drains_multiple_queue_batches_in_same_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            config = AppConfig(
                topics=TopicConfig(categories=["cs.AI"], queries=["LLM agent"]),
                filters=FilterConfig(max_papers_per_batch=1),
                pipeline=PipelineConfig(max_papers_per_run=2),
                paths=PathConfig(
                    database=root / "data" / "radar.sqlite3",
                    tmp_pdfs=root / "data" / "tmp_pdfs",
                    digests=root / "digests",
                ),
            )
            papers = [
                PaperMetadata(
                    arxiv_id="2605.00001",
                    title="Paper 1",
                    abstract="abstract",
                    published_at="2026-05-01",
                    pdf_url="pdf1",
                ),
                PaperMetadata(
                    arxiv_id="2605.00002",
                    title="Paper 2",
                    abstract="abstract",
                    published_at="2026-05-02",
                    pdf_url="pdf2",
                ),
            ]

            class FakeDownloader:
                def __init__(self):
                    self.downloaded = []

                def download(self, paper, tmp_dir):
                    self.downloaded.append(paper.arxiv_id)
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                    path = tmp_dir / f"{paper.arxiv_id}.pdf"
                    path.write_bytes(b"%PDF")
                    return path

            class FakeExtractor:
                def extract(self, path):
                    return ExtractedText(text="full text " * 50, extractor_name="primary")

            downloader = FakeDownloader()
            fake_telegram = type(
                "FakeTelegram",
                (),
                {"send_message": lambda self, msg, **kwargs: None},
            )()
            service = PaperRadarService(
                config=config,
                db=db,
                downloader=downloader,
                extractor=FakeExtractor(),
                llm=None,
                telegram=fake_telegram,
                arxiv_client=_fake_arxiv_client(papers),
            )

            result = service.run_once(now_date="2026-05-29", now_time="15:00")

            self.assertEqual(result["accepted_count"], 2)
            self.assertEqual(set(downloader.downloaded), {"2605.00001", "2605.00002"})
            self.assertEqual(db.queued_papers(limit=10), [])

    def test_retryable_qa_failure_is_not_auto_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "data" / "radar.sqlite3")
            config = AppConfig(
                topics=TopicConfig(categories=["cs.AI"], queries=["LLM agent"]),
                pipeline=PipelineConfig(max_papers_per_run=1),
                paths=PathConfig(
                    database=root / "data" / "radar.sqlite3",
                    tmp_pdfs=root / "data" / "tmp_pdfs",
                    digests=root / "digests",
                ),
            )
            paper = PaperMetadata(arxiv_id="2605.99999", title="Retry Paper", abstract="abstract", pdf_url="pdf")

            class FakeDownloader:
                def download(self, paper, tmp_dir):
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                    path = tmp_dir / f"{paper.arxiv_id}.pdf"
                    path.write_bytes(b"%PDF")
                    return path

            class FakeExtractor:
                def extract(self, path):
                    return ExtractedText(text="full text " * 50, extractor_name="primary")

            class FakeLlm:
                def relevance(self, paper, topics):
                    return {"relevance_score": 8, "reason": "relevant"}

                def summarize(self, paper, full_text):
                    return {"what_the_paper_does": "Does work"}

                def qa(self, paper, summary, full_text):
                    raise RuntimeError("HTTP Error 429: Too Many Requests")

            fake_telegram = type("FakeTelegram", (), {"send_message": lambda self, msg, **kwargs: None})()
            service = PaperRadarService(
                config=config,
                db=db,
                downloader=FakeDownloader(),
                extractor=FakeExtractor(),
                llm=FakeLlm(),
                telegram=fake_telegram,
                arxiv_client=_fake_arxiv_client([paper]),
            )

            result = service.run_once(now_date="2026-05-29", now_time="15:00")
            saved = db.get_paper_by_arxiv_id("2605.99999")

            self.assertEqual(result["accepted_count"], 0)
            self.assertEqual(saved["archive_status"], "retry_later")

    def test_send_scan_notification_with_new_and_accepted(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            service = PaperRadarService(
                config=AppConfig(telegram=TelegramConfig(bot_token="bot", chat_id="chat")),
                db=db,
                telegram=type(
                    "FakeTelegram",
                    (),
                    {"send_message": lambda self, msg, **kwargs: sent_messages.append(msg)},
                )(),
            )
            service.send_scan_notification(15, 3, 0, "2026-06-04", "09:00")

        self.assertEqual(len(sent_messages), 1)
        self.assertIn("09:00", sent_messages[0])
        self.assertIn("15 paper mới", sent_messages[0])
        self.assertIn("3 match", sent_messages[0])

    def test_send_scan_notification_zero_papers(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            service = PaperRadarService(
                config=AppConfig(telegram=TelegramConfig(bot_token="bot", chat_id="chat")),
                db=db,
                telegram=type(
                    "FakeTelegram",
                    (),
                    {"send_message": lambda self, msg, **kwargs: sent_messages.append(msg)},
                )(),
            )
            service.send_scan_notification(0, 0, 0, "2026-06-04", "10:00")

        self.assertEqual(len(sent_messages), 1)
        self.assertIn("Không có paper mới", sent_messages[0])

    def test_send_scan_notification_with_errors(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            service = PaperRadarService(
                config=AppConfig(telegram=TelegramConfig(bot_token="bot", chat_id="chat")),
                db=db,
                telegram=type(
                    "FakeTelegram",
                    (),
                    {"send_message": lambda self, msg, **kwargs: sent_messages.append(msg)},
                )(),
            )
            service.send_scan_notification(10, 2, 1, "2026-06-04", "11:00")

        self.assertEqual(len(sent_messages), 1)
        self.assertIn("10 paper mới", sent_messages[0])
        self.assertIn("2 match", sent_messages[0])
        self.assertIn("1 lỗi", sent_messages[0])

    def test_send_scan_notification_failure_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()

            def raise_send(self, msg, **kwargs):
                raise RuntimeError("Telegram is down")

            service = PaperRadarService(
                config=AppConfig(telegram=TelegramConfig(bot_token="bot", chat_id="chat")),
                db=db,
                telegram=type("FakeTelegram", (), {"send_message": raise_send})(),
            )
            # Should not raise, just log warning
            service.send_scan_notification(5, 1, 0, "2026-06-04", "09:00")

    def test_send_daily_recap_marks_sent(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            run_id = db.start_run()
            paper_id = db.upsert_paper({"arxiv_id": "1", "title": "Paper", "pdf_url": "link"})
            db.record_result(
                paper_id=paper_id,
                run_id=run_id,
                candidate_relevance_score=8,
                extractor_name="primary",
                extracted_text_chars=100,
                summary={"what_the_paper_does": "Does work", "ideas_to_try": ["Try"]},
                relevance_score=8,
                grounding_score=8,
                idea_score=7,
                qa_reason="ok",
                accepted=True,
                digest_date="2026-05-29",
            )
            fake_tg_cls = type(
                "FakeTelegram",
                (),
                {"send_message": lambda self, msg, **kwargs: sent_messages.append(msg)},
            )
            service = PaperRadarService(
                config=AppConfig(telegram=TelegramConfig(bot_token="bot", chat_id="chat")),
                db=db,
                telegram=fake_tg_cls(),
            )

            sent = service.send_daily_recap("2026-05-29")
            was_sent = db.was_recap_sent("2026-05-29")

        self.assertTrue(sent)
        self.assertTrue(was_sent)
        self.assertEqual(len(sent_messages), 1)
        self.assertIn("Paper", sent_messages[0])

    def test_hourly_full_first_of_day_marks_state_and_sends_all(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            run_id = db.start_run()
            accepted_batch = []
            for arxiv_id, title in [("1", "Paper One"), ("2", "Paper Two")]:
                paper_id = db.upsert_paper(
                    {"arxiv_id": arxiv_id, "title": title, "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}"}
                )
                db.record_result(
                    paper_id=paper_id,
                    run_id=run_id,
                    candidate_relevance_score=8,
                    extractor_name="primary",
                    extracted_text_chars=100,
                    summary={"what_the_paper_does": f"work {arxiv_id}", "ideas_to_try": ["Try"]},
                    relevance_score=8,
                    grounding_score=8,
                    idea_score=7,
                    qa_reason="ok",
                    accepted=True,
                    digest_date="2026-06-03",
                )
                paper = db.get_paper_by_arxiv_id(arxiv_id)
                paper["summary"] = {"what_the_paper_does": f"work {arxiv_id}", "ideas_to_try": ["Try"]}
                accepted_batch.append(paper)

            service = PaperRadarService(
                config=AppConfig(telegram=TelegramConfig(bot_token="bot", chat_id="chat")),
                db=db,
                telegram=type(
                    "FakeTelegram",
                    (),
                    {"send_message": lambda self, msg, **kwargs: sent_messages.append(msg)},
                )(),
            )

            service.send_hourly_telegram(accepted_batch, "2026-06-03", "09:00")
            state = db.get_state("last_daily_full_sent_at")

        self.assertEqual(len(sent_messages), 2)
        self.assertTrue(any("Paper One" in m for m in sent_messages))
        self.assertTrue(any("Paper Two" in m for m in sent_messages))
        self.assertEqual(state, "2026-06-03")

    def test_hourly_diff_after_full_sends_only_new_batch(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            run_id = db.start_run()
            seeded = {}
            for arxiv_id, title in [("a", "Paper A"), ("b", "Paper B"), ("c", "Paper C")]:
                paper_id = db.upsert_paper(
                    {"arxiv_id": arxiv_id, "title": title, "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}"}
                )
                db.record_result(
                    paper_id=paper_id,
                    run_id=run_id,
                    candidate_relevance_score=8,
                    extractor_name="primary",
                    extracted_text_chars=100,
                    summary={"what_the_paper_does": f"work {arxiv_id}", "ideas_to_try": ["Try"]},
                    relevance_score=8,
                    grounding_score=8,
                    idea_score=7,
                    qa_reason="ok",
                    accepted=True,
                    digest_date="2026-06-03",
                )
                paper = db.get_paper_by_arxiv_id(arxiv_id)
                paper["summary"] = {"what_the_paper_does": f"work {arxiv_id}", "ideas_to_try": ["Try"]}
                seeded[arxiv_id] = paper

            service = PaperRadarService(
                config=AppConfig(telegram=TelegramConfig(bot_token="bot", chat_id="chat")),
                db=db,
                telegram=type(
                    "FakeTelegram",
                    (),
                    {"send_message": lambda self, msg, **kwargs: sent_messages.append(msg)},
                )(),
            )

            first_batch = [seeded["a"], seeded["b"]]
            service.send_hourly_telegram(first_batch, "2026-06-03", "09:00")
            service.send_hourly_telegram([seeded["c"]], "2026-06-03", "10:00")
            state = db.get_state("last_daily_full_sent_at")

        self.assertEqual(len(sent_messages), 4)
        self.assertTrue(any("Paper A" in m for m in sent_messages))
        self.assertTrue(any("Paper B" in m for m in sent_messages))
        self.assertTrue(any("Paper C" in m for m in sent_messages))
        self.assertEqual(state, "2026-06-03")

    def test_hourly_no_new_papers_silent(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            service = PaperRadarService(
                config=AppConfig(telegram=TelegramConfig(bot_token="bot", chat_id="chat")),
                db=db,
                telegram=type(
                    "FakeTelegram",
                    (),
                    {"send_message": lambda self, msg, **kwargs: sent_messages.append(msg)},
                )(),
            )

            service.send_hourly_telegram([], "2026-06-03", "09:00")
            service.send_hourly_telegram(None, "2026-06-03", "10:00")
            state = db.get_state("last_daily_full_sent_at")

        self.assertEqual(len(sent_messages), 0)
        self.assertIsNone(state)

    def test_hourly_full_again_on_new_day_after_state_rollover(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            run_id = db.start_run()
            seeded: dict[str, dict] = {}
            for arxiv_id, title, day in [("a", "Paper DayX", "2026-06-03"), ("b", "Paper DayY", "2026-06-04")]:
                paper_id = db.upsert_paper(
                    {"arxiv_id": arxiv_id, "title": title, "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}"}
                )
                db.record_result(
                    paper_id=paper_id,
                    run_id=run_id,
                    candidate_relevance_score=8,
                    extractor_name="primary",
                    extracted_text_chars=100,
                    summary={"what_the_paper_does": f"work {arxiv_id}", "ideas_to_try": ["Try"]},
                    relevance_score=8,
                    grounding_score=8,
                    idea_score=7,
                    qa_reason="ok",
                    accepted=True,
                    digest_date=day,
                )
                paper = db.get_paper_by_arxiv_id(arxiv_id)
                paper["summary"] = {"what_the_paper_does": f"work {arxiv_id}", "ideas_to_try": ["Try"]}
                seeded[arxiv_id] = paper

            service = PaperRadarService(
                config=AppConfig(telegram=TelegramConfig(bot_token="bot", chat_id="chat")),
                db=db,
                telegram=type(
                    "FakeTelegram",
                    (),
                    {"send_message": lambda self, msg, **kwargs: sent_messages.append(msg)},
                )(),
            )

            service.send_hourly_telegram([seeded["a"]], "2026-06-03", "09:00")
            service.send_hourly_telegram([seeded["b"]], "2026-06-04", "09:00")
            state = db.get_state("last_daily_full_sent_at")

        self.assertEqual(len(sent_messages), 2)
        self.assertTrue(any("Paper DayX" in m for m in sent_messages))
        self.assertTrue(any("Paper DayY" in m for m in sent_messages))
        self.assertEqual(state, "2026-06-04")

    def test_hourly_full_truncates_when_many_papers(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            run_id = db.start_run()
            accepted_batch = []
            for i in range(20):
                arxiv_id = f"a{i}"
                paper_id = db.upsert_paper(
                    {"arxiv_id": arxiv_id, "title": f"Paper {i}", "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}"}
                )
                db.record_result(
                    paper_id=paper_id,
                    run_id=run_id,
                    candidate_relevance_score=8,
                    extractor_name="primary",
                    extracted_text_chars=100,
                    summary={"what_the_paper_does": f"work {i}", "ideas_to_try": ["Try"]},
                    relevance_score=8,
                    grounding_score=8,
                    idea_score=7,
                    qa_reason="ok",
                    accepted=True,
                    digest_date="2026-06-03",
                )
                paper = db.get_paper_by_arxiv_id(arxiv_id)
                paper["summary"] = {"what_the_paper_does": f"work {i}", "ideas_to_try": ["Try"]}
                accepted_batch.append(paper)

            service = PaperRadarService(
                config=AppConfig(telegram=TelegramConfig(bot_token="bot", chat_id="chat")),
                db=db,
                telegram=type(
                    "FakeTelegram",
                    (),
                    {"send_message": lambda self, msg, **kwargs: sent_messages.append(msg)},
                )(),
            )

            service.send_hourly_telegram(accepted_batch, "2026-06-03", "09:00")

        self.assertEqual(len(sent_messages), 20)
        self.assertTrue(any("Paper 0" in m for m in sent_messages))
        self.assertTrue(any("Paper 19" in m for m in sent_messages))

    def test_hourly_telegram_failure_does_not_mark_state_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            run_id = db.start_run()
            paper_id = db.upsert_paper({"arxiv_id": "1", "title": "Paper", "pdf_url": "https://arxiv.org/pdf/1"})
            db.record_result(
                paper_id=paper_id,
                run_id=run_id,
                candidate_relevance_score=8,
                extractor_name="primary",
                extracted_text_chars=100,
                summary={"what_the_paper_does": "Does work", "ideas_to_try": ["Try"]},
                relevance_score=8,
                grounding_score=8,
                idea_score=7,
                qa_reason="ok",
                accepted=True,
                digest_date="2026-06-03",
            )
            paper = db.get_paper_by_arxiv_id("1")
            paper["summary"] = {"what_the_paper_does": "Does work", "ideas_to_try": ["Try"]}

            def raise_send(self, msg, **kwargs):
                raise RuntimeError("Telegram is down")

            service = PaperRadarService(
                config=AppConfig(telegram=TelegramConfig(bot_token="bot", chat_id="chat")),
                db=db,
                telegram=type(
                    "FakeTelegram",
                    (),
                    {"send_message": raise_send},
                )(),
            )

            with self.assertRaises(RuntimeError):
                service.send_hourly_telegram([paper], "2026-06-03", "09:00")
            state = db.get_state("last_daily_full_sent_at")

        self.assertIsNone(state)

    def _make_recap_service(self, db, recap_times=None):
        from paper_radar.config import DaemonConfig

        daemon_cfg = DaemonConfig(daily_recap_times=recap_times or ["11:00", "23:00"])
        config = AppConfig(
            telegram=TelegramConfig(bot_token="bot", chat_id="chat"),
            daemon=daemon_cfg,
        )
        sent_messages = []

        service = PaperRadarService(
            config=config,
            db=db,
            telegram=type(
                "FakeTelegram",
                (),
                {"send_message": lambda self, msg, **kwargs: sent_messages.append(msg)},
            )(),
        )
        return service, sent_messages

    def _seed_accepted_paper(self, db, digest_date="2026-06-05", arxiv_id="r1", title="Recap Paper"):
        run_id = db.start_run()
        paper_id = db.upsert_paper(
            {"arxiv_id": arxiv_id, "title": title, "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}"}
        )
        db.record_result(
            paper_id=paper_id,
            run_id=run_id,
            candidate_relevance_score=8,
            extractor_name="primary",
            extracted_text_chars=100,
            summary={"what_the_paper_does": "work", "ideas_to_try": ["Try"]},
            relevance_score=8,
            grounding_score=8,
            idea_score=7,
            qa_reason="ok",
            accepted=True,
            digest_date=digest_date,
        )

    def test_recap_not_sent_before_first_slot(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            self._seed_accepted_paper(db)
            service, sent_messages = self._make_recap_service(db)
            before_11 = datetime(2026, 6, 5, 10, 59, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
            service._maybe_send_due_recaps(now=before_11)
            self.assertEqual(len(sent_messages), 0)
            self.assertIsNone(db.get_state("daily_recap_sent:2026-06-05:11:00"))

    def test_recap_sent_at_11_after_slot_time(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            self._seed_accepted_paper(db)
            service, sent_messages = self._make_recap_service(db)
            at_1108 = datetime(2026, 6, 5, 11, 8, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
            service._maybe_send_due_recaps(now=at_1108)
            self.assertTrue(len(sent_messages) >= 1)
            self.assertEqual(db.get_state("daily_recap_sent:2026-06-05:11:00"), "sent")
            self.assertIsNone(db.get_state("daily_recap_sent:2026-06-05:23:00"))

    def test_recap_sends_both_slots_at_23(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            self._seed_accepted_paper(db)
            service, sent_messages = self._make_recap_service(db)
            at_2300 = datetime(2026, 6, 5, 23, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
            service._maybe_send_due_recaps(now=at_2300)
            self.assertEqual(db.get_state("daily_recap_sent:2026-06-05:11:00"), "sent")
            self.assertEqual(db.get_state("daily_recap_sent:2026-06-05:23:00"), "sent")
            self.assertTrue(len(sent_messages) >= 2)

    def test_recap_23_resends_even_if_11_sent(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            self._seed_accepted_paper(db)
            service, sent_messages = self._make_recap_service(db)
            at_1108 = datetime(2026, 6, 5, 11, 8, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
            service._maybe_send_due_recaps(now=at_1108)
            first_batch_count = len(sent_messages)
            at_2305 = datetime(2026, 6, 5, 23, 5, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
            service._maybe_send_due_recaps(now=at_2305)
            self.assertTrue(len(sent_messages) > first_batch_count)

    def test_recap_restart_does_not_resend_same_slot(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            self._seed_accepted_paper(db)
            service, sent_messages = self._make_recap_service(db)
            at_1115 = datetime(2026, 6, 5, 11, 15, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
            service._maybe_send_due_recaps(now=at_1115)
            first_count = len(sent_messages)
            service._maybe_send_due_recaps(now=at_1115)
            self.assertEqual(len(sent_messages), first_count)

    def test_recap_no_papers_marks_slot_checked(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            service, sent_messages = self._make_recap_service(db)
            at_1115 = datetime(2026, 6, 5, 11, 15, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
            service._maybe_send_due_recaps(now=at_1115)
            self.assertEqual(len(sent_messages), 0)
            self.assertEqual(db.get_state("daily_recap_sent:2026-06-05:11:00"), "sent")

    def test_recap_no_papers_does_not_mark_legacy_telegram_recaps(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            service, sent_messages = self._make_recap_service(db)
            at_1115 = datetime(2026, 6, 5, 11, 15, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
            service._maybe_send_due_recaps(now=at_1115)
            self.assertFalse(db.was_recap_sent("2026-06-05"))

    def test_send_daily_recap_still_works_backward_compat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PaperRadarDb(root / "radar.sqlite3")
            db.initialize()
            run_id = db.start_run()
            paper_id = db.upsert_paper({"arxiv_id": "bc1", "title": "BC Paper", "pdf_url": "link"})
            db.record_result(
                paper_id=paper_id,
                run_id=run_id,
                candidate_relevance_score=8,
                extractor_name="primary",
                extracted_text_chars=100,
                summary={"what_the_paper_does": "Does work", "ideas_to_try": ["Try"]},
                relevance_score=8,
                grounding_score=8,
                idea_score=7,
                qa_reason="ok",
                accepted=True,
                digest_date="2026-06-05",
            )
            service, _ = self._make_recap_service(db, recap_times=["21:00"])
            sent = service.send_daily_recap("2026-06-05")
        self.assertTrue(sent)


if __name__ == "__main__":
    unittest.main()
