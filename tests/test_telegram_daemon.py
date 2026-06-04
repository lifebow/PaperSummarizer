import tempfile
import unittest
from pathlib import Path

from paper_radar.config import AppConfig, FilterConfig, PathConfig, TelegramConfig, TopicConfig
from paper_radar.daemon import PaperRadarService
from paper_radar.db import PaperRadarDb
from paper_radar.extraction import ExtractedText
from paper_radar.retrieval import PaperMetadata
from paper_radar.telegram import TelegramSender


class TelegramDaemonTests(unittest.TestCase):
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

            class FakeRetriever:
                def search_recent(self, queries, categories, *, since, limit):
                    return [paper]

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
                {"send_message": lambda self, msg: sent_messages.append(msg)},
            )()
            service = PaperRadarService(
                config=config,
                db=db,
                retriever=FakeRetriever(),
                downloader=FakeDownloader(),
                extractor=FakeExtractor(),
                llm=FakeLlm(),
                telegram=fake_telegram,
            )
            result = service.run_once(now_date="2026-05-29", now_time="15:00")

            digest = (root / "digests" / "2026-05-29.md").read_text(encoding="utf-8")

        self.assertEqual(result["accepted_count"], 1)
        self.assertIn("Agent Safety", digest)
        self.assertFalse(downloaded_pdf.exists())

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
            service = PaperRadarService(
                config=AppConfig(telegram=TelegramConfig(bot_token="bot", chat_id="chat")),
                db=db,
                telegram=type("FakeTelegram", (), {"send_message": lambda self, msg: sent_messages.append(msg)})(),
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
                    {"send_message": lambda self, msg: sent_messages.append(msg)},
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
                    {"send_message": lambda self, msg: sent_messages.append(msg)},
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
                    {"send_message": lambda self, msg: sent_messages.append(msg)},
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
                    {"send_message": lambda self, msg: sent_messages.append(msg)},
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
                    {"send_message": lambda self, msg: sent_messages.append(msg)},
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

            def raise_send(self, msg):
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


if __name__ == "__main__":
    unittest.main()
