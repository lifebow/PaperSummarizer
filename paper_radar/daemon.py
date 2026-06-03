from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import AppConfig
from .db import PaperRadarDb
from .digest import append_digest_batch, render_telegram_recap
from .extraction import PdfExtractor, process_pdf_with_cleanup
from .llm import build_qa_prompt, build_relevance_prompt, build_summary_prompt, passes_quality_gate
from .retrieval import PdfDownloader, make_default_retriever
from .telegram import TelegramSender


class DefaultPaperLlm:
    def __init__(self, client):
        self.client = client

    def relevance(self, paper, topics):
        system, user = build_relevance_prompt(paper.title, paper.abstract, topics)
        return self.client.complete_json(system, user)

    def summarize(self, paper, full_text):
        system, user = build_summary_prompt(paper.title, paper.abstract, full_text)
        return self.client.complete_json(system, user)

    def qa(self, paper, summary, full_text):
        system, user = build_qa_prompt(summary, paper.abstract, full_text)
        return self.client.complete_json(system, user)


class PaperRadarService:
    def __init__(
        self,
        *,
        config: AppConfig,
        db: PaperRadarDb | None = None,
        retriever: Any | None = None,
        downloader: Any | None = None,
        extractor: Any | None = None,
        llm: Any | None = None,
        telegram: Any | None = None,
    ):
        self.config = config
        self.db = db or PaperRadarDb(config.paths.database)
        self.retriever = retriever or make_default_retriever(
            config.semantic_scholar.api_keys,
            config.semantic_scholar.fields,
        )
        self.downloader = downloader or PdfDownloader()
        self.extractor = extractor or PdfExtractor()
        self.llm = llm
        self.telegram = telegram or TelegramSender(
            bot_token=config.telegram.bot_token,
            chat_id=config.telegram.chat_id,
        )

    def run_once(self, *, now_date: str | None = None, now_time: str | None = None) -> dict[str, int]:
        self.db.initialize()
        run_id = self.db.start_run()
        since = self.db.get_state("last_successful_fetch_at") or _default_since(
            self.config.daemon.first_run_lookback_hours
        )
        now = _local_now(self.config.daemon.timezone)
        digest_date = now_date or now.strftime("%Y-%m-%d")
        batch_time = now_time or now.strftime("%H:%M")
        found_count = accepted_count = error_count = 0
        accepted_for_digest: list[dict[str, Any]] = []

        try:
            papers = self.retriever.search_recent(
                self.config.topics.queries,
                self.config.topics.categories,
                since=since,
                limit=self.config.filters.max_papers_per_batch,
            )
            found_count = len(papers)
            for paper in papers:
                if self.db.get_paper_by_arxiv_id(paper.arxiv_id):
                    continue
                try:
                    relevance = (
                        self.llm.relevance(paper, self.config.topics.queries) if self.llm else {"relevance_score": 10}
                    )
                    if float(relevance.get("relevance_score", 0)) < self.config.filters.relevance_threshold:
                        continue
                    paper_id = self.db.upsert_paper(paper.to_record())
                    pdf_path = self.downloader.download(paper, self.config.paths.tmp_pdfs)

                    def process(path, *, current_paper=paper, current_paper_id=paper_id, current_relevance=relevance):
                        extracted = self.extractor.extract(path)
                        summary = self.llm.summarize(current_paper, extracted.text) if self.llm else {}
                        qa = (
                            self.llm.qa(current_paper, summary, extracted.text)
                            if self.llm
                            else {
                                "relevance_score": 10,
                                "grounding_score": 10,
                                "idea_score": 10,
                                "qa_reason": "No LLM configured; accepted by default.",
                            }
                        )
                        accepted = passes_quality_gate(
                            qa,
                            relevance_threshold=self.config.filters.relevance_threshold,
                            grounding_threshold=self.config.filters.grounding_threshold,
                            idea_threshold=self.config.filters.idea_threshold,
                        )
                        enriched_summary = dict(summary)
                        enriched_summary["qa_scores"] = {
                            "relevance": qa.get("relevance_score", 0),
                            "grounding": qa.get("grounding_score", 0),
                            "idea": qa.get("idea_score", 0),
                        }
                        enriched_summary["qa_reason"] = qa.get("qa_reason", "")
                        self.db.record_result(
                            paper_id=current_paper_id,
                            run_id=run_id,
                            candidate_relevance_score=float(current_relevance.get("relevance_score", 0)),
                            extractor_name=extracted.extractor_name,
                            extracted_text_chars=len(extracted.text),
                            summary=enriched_summary,
                            relevance_score=float(qa.get("relevance_score", 0)),
                            grounding_score=float(qa.get("grounding_score", 0)),
                            idea_score=float(qa.get("idea_score", 0)),
                            qa_reason=str(qa.get("qa_reason", "")),
                            accepted=accepted,
                            digest_date=digest_date,
                        )
                        if accepted:
                            accepted_for_digest.append(
                                {
                                    **current_paper.to_record(),
                                    "summary": enriched_summary,
                                    "relevance_score": qa.get("relevance_score", 0),
                                    "grounding_score": qa.get("grounding_score", 0),
                                    "idea_score": qa.get("idea_score", 0),
                                }
                            )
                        return accepted

                    if process_pdf_with_cleanup(pdf_path, process):
                        accepted_count += 1
                except Exception:
                    error_count += 1
            if accepted_for_digest:
                append_digest_batch(self.config.paths.digests, digest_date, batch_time, accepted_for_digest)
            self.db.set_state("last_successful_fetch_at", datetime.now(timezone.utc).replace(microsecond=0).isoformat())
            self.db.finish_run(run_id, "ok", found_count, accepted_count, error_count)
            return {"found_count": found_count, "accepted_count": accepted_count, "error_count": error_count}
        except Exception:
            self.db.finish_run(run_id, "error", found_count, accepted_count, error_count + 1)
            raise

    def send_daily_recap(self, digest_date: str) -> bool:
        self.db.initialize()
        if self.db.was_recap_sent(digest_date):
            return False
        papers = self.db.accepted_results_for_date(digest_date)
        message = render_telegram_recap(digest_date, papers)
        if not message:
            return False
        try:
            self.telegram.send_message(message)
            self.db.mark_recap(digest_date, "sent")
            return True
        except Exception as exc:
            self.db.mark_recap(digest_date, "error", str(exc))
            raise

    def watch(self) -> None:
        while True:
            now = _local_now(self.config.daemon.timezone)
            self.run_once()
            if now.strftime("%H:%M") >= self.config.daemon.daily_recap_time:
                self.send_daily_recap(now.strftime("%Y-%m-%d"))
            time.sleep(self.config.daemon.interval_minutes * 60)


def _default_since(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0).isoformat()


def _local_now(timezone_name: str) -> datetime:
    return datetime.now(ZoneInfo(timezone_name))
