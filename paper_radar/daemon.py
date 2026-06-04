from __future__ import annotations

import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ._s2 import PaperMetadata
from ._time import default_since, local_now, now_utc_iso
from .config import AppConfig
from .db import PaperRadarDb
from .digest import (
    append_digest_batch,
    render_paper_short,
)
from .extraction import PdfExtractor, extract_introduction, process_pdf_with_cleanup
from .llm import build_qa_prompt, build_relevance_prompt, build_summary_prompt, normalize_score, passes_quality_gate
from .retrieval import PdfDownloader, _normalize_arxiv_id, make_default_retriever
from .telegram import TelegramSender, make_expand_keyboard

logger = logging.getLogger(__name__)


class RunBudget:
    """Track LLM call count against a per-run limit."""

    def __init__(self, max_calls: int):
        self.max_calls = max_calls
        self.calls_used = 0

    def can_call(self) -> bool:
        return self.calls_used < self.max_calls

    def record_call(self) -> None:
        self.calls_used += 1


def _hash_paper(title: str, abstract: str) -> str:
    """Deterministic hash for relevance cache key."""
    return hashlib.sha256(f"{title}||{abstract}".encode()).hexdigest()[:16]


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
            paper_exists=lambda arxiv_id: self.db.get_paper_by_arxiv_id(_normalize_arxiv_id(arxiv_id)) is not None,
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
        since = self.db.get_state("last_successful_fetch_at") or default_since(
            self.config.daemon.first_run_lookback_hours
        )
        now = local_now(self.config.daemon.timezone)
        digest_date = now_date or now.strftime("%Y-%m-%d")
        batch_time = now_time or now.strftime("%H:%M")
        accepted_count = error_count = 0
        accepted_for_digest: list[dict[str, Any]] = []
        budget = RunBudget(self.config.pipeline.max_llm_calls_per_run)

        try:
            found_papers = self.retriever.search_recent(
                self.config.topics.queries,
                self.config.topics.categories,
                since=since,
                limit=1000,
            )
            found_count = len(found_papers)
            queued_count = self._enqueue_found_papers(found_papers)
            phase2_results = self._drain_queue(run_id, digest_date, batch_time, budget, queued_count)
            for result in phase2_results:
                if result.get("accepted"):
                    accepted_count += 1
                    accepted_for_digest.append(result)
                elif result.get("error"):
                    error_count += 1

            # Sort deterministically before writing
            accepted_for_digest.sort(key=lambda p: p.get("arxiv_id", ""))

            if accepted_for_digest:
                append_digest_batch(self.config.paths.digests, digest_date, batch_time, accepted_for_digest)
            self.send_hourly_telegram(accepted_for_digest, digest_date, batch_time)
            self.db.set_state("last_successful_fetch_at", now_utc_iso())
            self.db.finish_run(run_id, "ok", found_count, accepted_count, error_count)
            return {"found_count": found_count, "accepted_count": accepted_count, "error_count": error_count}
        except Exception as exc:
            logger.exception("Run failed: %s", exc)
            self.db.finish_run(
                run_id,
                "error",
                found_count if "found_count" in dir() else 0,
                accepted_count,
                error_count + 1,
            )
            raise

    def _enqueue_found_papers(self, found_papers: list[Any]) -> int:
        queued_count = 0
        for paper in found_papers:
            paper.arxiv_id = _normalize_arxiv_id(paper.arxiv_id)
            record = paper.to_record()
            record["archive_status"] = "queued"
            self.db.upsert_paper(record)
            queued_count += 1
        return queued_count

    def _drain_queue(
        self,
        run_id: int,
        digest_date: str,
        batch_time: str,
        budget: RunBudget,
        queued_count: int,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        processed_count = 0
        while True:
            if self.llm and not budget.can_call():
                logger.info(
                    "Stopping queue drain: LLM budget exhausted (%d/%d)",
                    budget.calls_used,
                    budget.max_calls,
                )
                break

            papers = self._queued_paper_metadata(limit=self.config.pipeline.max_papers_per_run)
            if not papers:
                break
            self._enrich_author_affiliations(papers)

            new_papers: list[Any] = []
            for paper in papers:
                paper.arxiv_id = _normalize_arxiv_id(paper.arxiv_id)
                new_papers.append(paper)

            processed_count += len(new_papers)
            logger.info(
                "Queued %d new papers; processing queued batch of %d papers (total this run: %d)",
                queued_count,
                len(new_papers),
                processed_count,
            )

            candidates = self._phase1_relevance(new_papers, budget)
            logger.info(
                "Phase 1 done: %d/%d passed relevance (budget used: %d/%d)",
                len(candidates),
                len(new_papers),
                budget.calls_used,
                budget.max_calls,
            )

            results.extend(self._phase2_summarize_qa(candidates, run_id, digest_date, batch_time, budget))
        return results

    def _queued_paper_metadata(self, *, limit: int) -> list[PaperMetadata]:
        papers: list[PaperMetadata] = []
        for row in self.db.queued_papers(limit=limit):
            papers.append(
                PaperMetadata(
                    arxiv_id=row.get("arxiv_id", ""),
                    semantic_scholar_id=row.get("semantic_scholar_id", ""),
                    title=row.get("title", ""),
                    authors=row.get("authors", []),
                    author_s2_ids=row.get("author_s2_ids", []),
                    author_affiliations=row.get("author_affiliations", []),
                    abstract=row.get("abstract", ""),
                    semantic_scholar_tldr=row.get("semantic_scholar_tldr", ""),
                    categories=row.get("categories", []),
                    primary_category=row.get("primary_category", ""),
                    published_at=row.get("published_at", ""),
                    updated_at=row.get("updated_at", ""),
                    pdf_url=row.get("pdf_url", ""),
                    semantic_scholar_url=row.get("semantic_scholar_url", ""),
                    source=row.get("source", ""),
                )
            )
        return papers

    def _phase1_relevance(
        self,
        papers: list[Any],
        budget: RunBudget,
    ) -> list[tuple[Any, dict[str, Any]]]:
        """Score relevance in parallel. Returns [(paper, relevance)] for passing papers."""
        if not papers:
            return []

        candidates: list[tuple[Any, dict[str, Any]]] = []
        need_scoring: list[tuple[Any, str]] = []  # (paper, hash)

        # Check cache first
        for paper in papers:
            if not self.llm:
                candidates.append((paper, {"relevance_score": 10}))
                continue
            paper_hash = _hash_paper(paper.title, paper.abstract)
            if self.config.pipeline.enable_relevance_cache:
                cached = self.db.get_cached_relevance(paper_hash)
                if cached is not None:
                    score = float(cached["relevance_score"])
                    if score >= self.config.filters.relevance_threshold:
                        candidates.append((paper, cached))
                    continue
            need_scoring.append((paper, paper_hash))

        if not need_scoring or not self.llm:
            return candidates

        # Parallel LLM relevance scoring
        max_workers = min(self.config.pipeline.llm_concurrency, len(need_scoring))

        def score_one(paper: Any, paper_hash: str) -> tuple[Any, str, dict[str, Any] | None]:
            if not budget.can_call():
                return (paper, paper_hash, None)
            budget.record_call()
            try:
                score = self.llm.relevance(paper, self.config.topics.queries)
                return (paper, paper_hash, score)
            except Exception as exc:
                logger.warning("Relevance scoring failed for %s: %s", paper.arxiv_id, exc)
                return (paper, paper_hash, None)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(score_one, p, h) for p, h in need_scoring]
            for future in as_completed(futures):
                paper, paper_hash, score = future.result()
                if score is not None:
                    # Cache both accepted and rejected
                    if self.config.pipeline.enable_relevance_cache:
                        self.db.save_cached_relevance(
                            paper_hash,
                            float(score.get("relevance_score", 0)),
                            str(score.get("reason", "")),
                        )
                    if float(score.get("relevance_score", 0)) >= self.config.filters.relevance_threshold:
                        candidates.append((paper, score))
                    else:
                        self.db.update_paper_archive_status(paper.arxiv_id, "rejected_relevance")

        return candidates

    def _phase2_summarize_qa(
        self,
        candidates: list[tuple[Any, dict[str, Any]]],
        run_id: int,
        digest_date: str,
        batch_time: str,
        budget: RunBudget,
    ) -> list[dict[str, Any]]:
        """Process candidates: download PDF, summarize, QA. Returns list of result dicts."""
        if not candidates:
            return []

        results: list[dict[str, Any]] = []
        max_workers = min(self.config.pipeline.download_concurrency, len(candidates))

        def process_one(paper: Any, relevance: dict[str, Any]) -> dict[str, Any] | None:
            try:
                paper_id = self.db.upsert_paper(paper.to_record())
                self.db.update_paper_archive_status(paper.arxiv_id, "processing")
                pdf_path = self.downloader.download(paper, self.config.paths.tmp_pdfs)

                result_holder: dict[str, Any] = {}

                def extract_and_analyze(path: str) -> bool:
                    extracted = self.extractor.extract(path)
                    intro = extract_introduction(extracted.text, paper.abstract)
                    header_text = extracted.text[:3000]
                    summary_text = f"{header_text}\n\n{paper.abstract}\n\n{intro}"

                    # Summary LLM
                    summary = {}
                    qa = {}
                    if self.llm and budget.can_call():
                        budget.record_call()
                        try:
                            summary = self.llm.summarize(paper, summary_text)
                        except Exception as exc:
                            logger.warning("Summary failed for %s: %s", paper.arxiv_id, exc)
                            return False

                    # QA LLM
                    if self.llm and budget.can_call():
                        budget.record_call()
                        try:
                            qa = self.llm.qa(paper, summary, paper.abstract)
                        except Exception as exc:
                            logger.warning("QA failed for %s: %s", paper.arxiv_id, exc)
                            qa = {
                                "relevance_score": 10,
                                "grounding_score": 10,
                                "idea_score": 10,
                                "qa_reason": f"QA error: {exc}",
                            }
                    elif not self.llm:
                        qa = {
                            "relevance_score": 10,
                            "grounding_score": 10,
                            "idea_score": 10,
                            "qa_reason": "No LLM configured",
                        }

                    accepted = passes_quality_gate(
                        qa,
                        relevance_threshold=self.config.filters.relevance_threshold,
                        grounding_threshold=self.config.filters.grounding_threshold,
                        idea_threshold=self.config.filters.idea_threshold,
                    )
                    enriched_summary = dict(summary)
                    enriched_summary["qa_scores"] = {
                        "relevance": normalize_score(qa.get("relevance_score", 0)),
                        "grounding": normalize_score(qa.get("grounding_score", 0)),
                        "idea": normalize_score(qa.get("idea_score", 0)),
                    }
                    enriched_summary["qa_reason"] = qa.get("qa_reason", "")

                    result_holder["data"] = {
                        **paper.to_record(),
                        "summary": enriched_summary,
                        "relevance_score": normalize_score(qa.get("relevance_score", 0)),
                        "grounding_score": normalize_score(qa.get("grounding_score", 0)),
                        "idea_score": normalize_score(qa.get("idea_score", 0)),
                        "paper_id": paper_id,
                        "run_id": run_id,
                        "digest_date": digest_date,
                        "candidate_relevance": float(relevance.get("relevance_score", 0)),
                        "extractor_name": extracted.extractor_name,
                        "extracted_text_chars": len(extracted.text),
                        "qa": qa,
                        "accepted": accepted,
                    }
                    return accepted

                process_pdf_with_cleanup(pdf_path, extract_and_analyze)
                data = result_holder.get("data")
                if data:
                    return data
                return None
            except Exception as exc:
                logger.exception("Paper processing failed for %s: %s", paper.arxiv_id, exc)
                self.db.update_paper_archive_status(paper.arxiv_id, "error", str(exc))
                return {"error": str(exc), "arxiv_id": paper.arxiv_id}

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(process_one, p, r): p for p, r in candidates}
            for future in as_completed(futures):
                paper = futures[future]
                result = future.result()
                if result and "error" in result:
                    logger.warning("Paper %s errored: %s", paper.arxiv_id, result["error"])
                    results.append(result)
                elif result:
                    # Sequential DB write
                    self._record_paper_result(result)
                    if result.get("accepted"):
                        logger.info("Paper accepted: %s", paper.arxiv_id)
                        results.append(result)
                    else:
                        logger.info(
                            "Paper rejected by QA gate: %s (rel=%.1f gnd=%.1f idea=%.1f)",
                            paper.arxiv_id,
                            result.get("relevance_score", 0),
                            result.get("grounding_score", 0),
                            result.get("idea_score", 0),
                        )

        return results

    def _record_paper_result(self, data: dict[str, Any]) -> None:
        """Write a single paper result to DB. Called sequentially from main thread."""
        self.db.record_result(
            paper_id=data["paper_id"],
            run_id=data["run_id"],
            candidate_relevance_score=data["candidate_relevance"],
            extractor_name=data["extractor_name"],
            extracted_text_chars=data["extracted_text_chars"],
            summary=data["summary"],
            relevance_score=float(data.get("qa", {}).get("relevance_score", 0)),
            grounding_score=float(data.get("qa", {}).get("grounding_score", 0)),
            idea_score=float(data.get("qa", {}).get("idea_score", 0)),
            qa_reason=str(data.get("qa", {}).get("qa_reason", "")),
            accepted=data["accepted"],
            digest_date=data["digest_date"],
        )
        self.db.update_paper_archive_status(
            data["arxiv_id"],
            "accepted" if data["accepted"] else "rejected_qa",
        )

    def send_daily_recap(self, digest_date: str) -> bool:
        self.db.initialize()
        if self.db.was_recap_sent(digest_date):
            return False
        papers = self.db.accepted_results_for_date(digest_date)
        if not papers:
            return False
        try:
            for paper in papers:
                msg = render_paper_short(paper)
                if msg:
                    keyboard = make_expand_keyboard(paper.get("arxiv_id", ""))
                    self.telegram.send_message(msg, reply_markup=keyboard)
            self.db.mark_recap(digest_date, "sent")
            return True
        except Exception as exc:
            self.db.mark_recap(digest_date, "error", str(exc))
            raise

    def send_hourly_telegram(
        self,
        accepted_batch: list[dict[str, Any]] | None,
        digest_date: str,
        batch_time: str,
    ) -> None:
        if not accepted_batch:
            return
        self.db.initialize()
        last_sent = self.db.get_state("last_daily_full_sent_at")
        if last_sent == digest_date:
            for paper in accepted_batch:
                msg = render_paper_short(paper)
                if msg:
                    keyboard = make_expand_keyboard(paper.get("arxiv_id", ""))
                    self.telegram.send_message(msg, reply_markup=keyboard)
            return
        papers = self.db.accepted_results_for_date(digest_date)
        for paper in papers:
            msg = render_paper_short(paper)
            if msg:
                keyboard = make_expand_keyboard(paper.get("arxiv_id", ""))
                self.telegram.send_message(msg, reply_markup=keyboard)
        self.db.set_state("last_daily_full_sent_at", digest_date)

    def watch(self) -> None:
        while True:
            self.run_once()
            time.sleep(self.config.daemon.interval_minutes * 60)

    def _enrich_author_affiliations(self, papers: list[Any]) -> None:
        """Fetch and cache author affiliations from S2 for all papers in batch."""
        all_author_ids: list[str] = []
        for paper in papers:
            s2_ids = getattr(paper, "author_s2_ids", []) or []
            all_author_ids.extend(s2_ids)
        unique_ids = list(dict.fromkeys(id for id in all_author_ids if id))
        if not unique_ids:
            return

        cached = self.db.get_author_affiliations_batch(unique_ids)
        uncached_ids = [aid for aid in unique_ids if aid not in cached]

        new_affiliations: dict[str, str] = {}
        if uncached_ids and hasattr(self.retriever, "fetch_author_affiliations"):
            try:
                new_affiliations = self.retriever.fetch_author_affiliations(uncached_ids[:20])
            except Exception as exc:
                logger.warning("Author affiliation fetch failed: %s", exc)

        for aid, aff in new_affiliations.items():
            self.db.save_author_affiliation(aid, "", aff)

        all_affiliations = {**cached, **new_affiliations}
        for paper in papers:
            s2_ids = getattr(paper, "author_s2_ids", []) or []
            paper_affs = [all_affiliations[aid] for aid in s2_ids if aid in all_affiliations]
            if paper_affs:
                paper.author_affiliations = list(dict.fromkeys(paper_affs))
