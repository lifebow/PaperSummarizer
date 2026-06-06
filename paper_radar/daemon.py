from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ._s2 import PaperMetadata
from ._time import local_now, now_utc_iso
from .config import AppConfig
from .db import PaperRadarDb
from .digest import (
    append_digest_batch,
    render_paper_short,
)
from .extraction import PdfExtractor, extract_introduction, process_pdf_with_cleanup
from .llm import build_qa_prompt, build_relevance_prompt, build_summary_prompt, normalize_score, passes_quality_gate
from .retrieval import (
    ArxivClient,
    PdfDownloader,
    _normalize_arxiv_id,
    choose_allowed_show,
    make_default_retriever,
    parse_latest_section_header,
)
from .telegram import TelegramSender, make_expand_keyboard

logger = logging.getLogger(__name__)


class RunBudget:
    """Track LLM call count against a per-run limit. Thread-safe."""

    def __init__(self, max_calls: int):
        self.max_calls = max_calls
        self.calls_used = 0
        self._lock = threading.Lock()

    def can_call(self) -> bool:
        with self._lock:
            if self.max_calls <= 0:
                return True
            return self.calls_used < self.max_calls

    def record_call(self) -> None:
        with self._lock:
            self.calls_used += 1

    def try_record_call(self) -> bool:
        with self._lock:
            if self.max_calls > 0 and self.calls_used >= self.max_calls:
                return False
            self.calls_used += 1
            return True

    def describe(self) -> str:
        with self._lock:
            if self.max_calls <= 0:
                return f"{self.calls_used}/unlimited"
            return f"{self.calls_used}/{self.max_calls}"


def _hash_paper(title: str, abstract: str, topic_fingerprint: str = "") -> str:
    """Deterministic hash for relevance cache key."""
    return hashlib.sha256(f"{topic_fingerprint}||{title}||{abstract}".encode()).hexdigest()[:16]


def _topic_fingerprint(config: AppConfig) -> str:
    payload = {
        "categories": config.topics.categories,
        "queries": config.topics.queries,
        "relevance_threshold": config.filters.relevance_threshold,
        "grounding_threshold": config.filters.grounding_threshold,
        "idea_threshold": config.filters.idea_threshold,
    }
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


class DefaultPaperLlm:
    def __init__(self, client, *, retry_delays: tuple[float, ...] = (5, 15, 30, 60, 120)):
        self.client = client
        self.retry_delays = retry_delays

    def relevance(self, paper, topics):
        system, user = build_relevance_prompt(paper.title, paper.abstract, topics)
        return self._complete_with_retry(system, user, "relevance", paper.arxiv_id)

    def summarize(self, paper, full_text):
        system, user = build_summary_prompt(paper.title, paper.abstract, full_text)
        return self._complete_with_retry(system, user, "summary", paper.arxiv_id)

    def qa(self, paper, summary, full_text):
        system, user = build_qa_prompt(summary, paper.abstract, full_text)
        return self._complete_with_retry(system, user, "qa", paper.arxiv_id)

    def _complete_with_retry(self, system: str, user: str, stage: str, arxiv_id: str) -> dict[str, Any]:
        attempts = len(self.retry_delays) + 1
        for attempt in range(attempts):
            try:
                return self.client.complete_json(system, user)
            except Exception as exc:
                if attempt >= len(self.retry_delays) or not _is_retryable_llm_error(exc):
                    raise
                delay = self.retry_delays[attempt]
                logger.warning(
                    "LLM %s retry %d/%d for %s after %s: %s",
                    stage,
                    attempt + 1,
                    len(self.retry_delays),
                    arxiv_id,
                    _format_delay(delay),
                    exc,
                )
                time.sleep(delay)
        raise RuntimeError("unreachable retry loop")


def _is_retryable_llm_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(code in text for code in ("429", "500", "502", "503", "504", "too many requests", "timeout"))


def _format_delay(delay: float) -> str:
    return f"{delay:g}s"


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
        arxiv_client: Any | None = None,
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
        self.arxiv_client = arxiv_client or ArxivClient()
        self.topic_fingerprint = _topic_fingerprint(config)

    def run_once(self, *, now_date: str | None = None, now_time: str | None = None) -> dict[str, int]:
        self.db.initialize()
        requeued_count = self.db.requeue_interrupted_papers()
        if requeued_count:
            logger.info("Requeued %d interrupted papers", requeued_count)
        run_id = self.db.start_run()
        now = local_now(self.config.daemon.timezone)
        digest_date = now_date or now.strftime("%Y-%m-%d")
        batch_time = now_time or now.strftime("%H:%M")
        accepted_count = error_count = 0
        accepted_for_digest: list[dict[str, Any]] = []
        budget = RunBudget(self.config.pipeline.max_llm_calls_per_run)

        try:
            discovered_count = self._discover_list_only(batch_time)
            self._hydrate_metadata()
            phase2_results = self._drain_queue(run_id, digest_date, batch_time, budget)
            for result in phase2_results:
                if result.get("accepted"):
                    accepted_count += 1
                    accepted_for_digest.append(result)
                elif result.get("error"):
                    error_count += 1

            found_count = discovered_count
            accepted_for_digest.sort(key=lambda p: p.get("arxiv_id", ""))

            if accepted_for_digest:
                append_digest_batch(self.config.paths.digests, digest_date, batch_time, accepted_for_digest)
                self._send_accepted_cards(accepted_for_digest)
            self.send_scan_notification(found_count, accepted_count, error_count, digest_date, batch_time)
            self.db.set_state("last_successful_fetch_at", now_utc_iso())
            self.db.set_state("arxiv_recent_latest_topic_fingerprint", self.topic_fingerprint)
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

    def run_startup_check(
        self,
        *,
        now_date: str | None = None,
        now_time: str | None = None,
    ) -> dict[str, Any]:
        """Notify on startup, then scan or replay the already-completed recent section."""
        self.db.initialize()
        self._send_startup_message("Bot online. Đang kiểm tra arXiv recent...")

        try:
            probe_html = self.arxiv_client.fetch_page_html(self.config.topics.categories, show=50)
            header = parse_latest_section_header(probe_html)
        except Exception as exc:
            logger.warning("Startup recent probe failed: %s", exc)
            header = None

        if header and self._is_section_complete(header.section_date, header.expected_total):
            if self._topics_changed_since_latest_scan():
                digest_date = self.db.get_state("arxiv_recent_latest_digest_date") or header.section_date_iso
                reset_count = self.db.reset_results_for_digest_date(digest_date)
                requeued = self.db.requeue_papers_published_on(header.section_date_iso)
                # Title+abstract của ngày này đã lưu trong DB; relevance chỉ cần
                # title+abstract, nên không re-scan arXiv — giữ complete=true để
                # _discover_list_only skip fetch, _drain_queue chấm điểm lại từ DB.
                self._send_startup_message(
                    "Topic filter đã đổi; chấm điểm lại "
                    f"{header.section_date} từ {requeued} paper đã lưu "
                    f"({reset_count} kết quả cũ được reset, không tải lại arXiv)."
                )
                result = self.run_once(now_date=now_date, now_time=now_time)
                return {"status": "rescored_topic_change", **result}
            digest_date = self.db.get_state("arxiv_recent_latest_digest_date") or header.section_date_iso
            papers = self.db.accepted_results_for_date(digest_date)
            discovered = self.db.get_state("arxiv_recent_latest_discovered_count") or "0"
            self._send_startup_message(
                "arXiv recent đã quét: "
                f"{header.section_date} ({discovered}/{header.expected_total} entries), "
                f"{len(papers)} accepted. Gửi lại kết quả đã lưu..."
            )
            self._send_accepted_cards(papers)
            return {
                "status": "replayed",
                "found_count": 0,
                "accepted_count": len(papers),
                "error_count": 0,
            }

        if header:
            continued = " continued" if header.continued else ""
            self._send_startup_message(
                f"Đang quét arXiv recent{continued}: {header.section_date}, "
                f"expected {header.expected_total} entries. Khi xong sẽ gửi noti lần đầu."
            )
        else:
            self._send_startup_message("Không đọc được header arXiv recent; chạy fallback scan.")

        result = self.run_once(now_date=now_date, now_time=now_time)
        return {"status": "scanned", **result}

    def _send_startup_message(self, msg: str) -> None:
        try:
            self.telegram.send_message(msg)
        except Exception as exc:
            logger.warning("Startup notification failed: %s", exc)

    def _is_release_window(self, batch_time: str) -> bool:
        cfg = self.config.daemon
        if not cfg.release_window_start or not cfg.release_window_end:
            return False
        return cfg.release_window_start <= batch_time <= cfg.release_window_end

    def _discover_list_only(self, batch_time: str) -> int:
        if self._is_release_window(batch_time):
            discovery_limit = self.config.pipeline.release_discovery_limit
        else:
            discovery_limit = self.config.pipeline.normal_discovery_limit
        if discovery_limit <= 0:
            return 0

        try:
            probe_html = self.arxiv_client.fetch_page_html(
                self.config.topics.categories,
                show=50,
            )
        except Exception as exc:
            logger.warning("List-only discovery probe failed: %s", exc)
            return self._discover_fallback(discovery_limit)

        header = parse_latest_section_header(probe_html)
        if header is None:
            logger.warning("Header parse failed; falling back to configured limit")
            return self._discover_fallback(discovery_limit)

        target_section = header.section_date
        target_section_iso = header.section_date_iso
        expected_total = header.expected_total

        if self._is_section_complete(target_section, expected_total):
            logger.info(
                "Section %s already complete (expected=%d), skipping",
                target_section,
                expected_total,
            )
            return 0

        all_papers_by_id: dict[str, Any] = {}

        while True:
            show_value = choose_allowed_show(expected_total)
            all_papers_by_id = {}

            if expected_total <= 2000:
                try:
                    page_html = self.arxiv_client.fetch_page_html(
                        self.config.topics.categories,
                        show=show_value,
                    )
                except Exception as exc:
                    logger.warning("Full page fetch failed: %s", exc)
                    return self._discover_fallback(discovery_limit)
                page_header = parse_latest_section_header(page_html)
                if page_header and (
                    page_header.section_date != target_section or page_header.expected_total != expected_total
                ):
                    logger.warning(
                        "Probe/fetch mismatch: probe=(%s, %d) fetch=(%s, %d); using fetch header",
                        target_section,
                        expected_total,
                        page_header.section_date,
                        page_header.expected_total,
                    )
                    target_section = page_header.section_date
                    target_section_iso = page_header.section_date_iso
                    expected_total = page_header.expected_total
                    if self._is_section_complete(target_section, expected_total):
                        return 0
                    if expected_total > show_value:
                        continue
                all_papers = self.arxiv_client._parse_entries_from_html(
                    page_html,
                    target_section=target_section,
                )
                all_papers_by_id = {_normalize_arxiv_id(paper.arxiv_id): paper for paper in all_papers}
                break

            skip = 0
            while len(all_papers_by_id) < expected_total:
                try:
                    page_html = self.arxiv_client.fetch_page_html(
                        self.config.topics.categories,
                        show=2000,
                        skip=skip,
                    )
                except Exception as exc:
                    logger.warning("Pagination fetch skip=%d failed: %s", skip, exc)
                    break
                page_header = parse_latest_section_header(page_html)
                if page_header and page_header.section_date != target_section:
                    logger.warning(
                        "Pagination section mismatch: expected=%s got=%s",
                        target_section,
                        page_header.section_date,
                    )
                    break
                if page_header:
                    target_section_iso = page_header.section_date_iso
                batch = self.arxiv_client._parse_entries_from_html(
                    page_html,
                    target_section=target_section,
                )
                new_in_batch = 0
                for paper in batch:
                    normalized_id = _normalize_arxiv_id(paper.arxiv_id)
                    if normalized_id not in all_papers_by_id:
                        all_papers_by_id[normalized_id] = paper
                        new_in_batch += 1
                if new_in_batch == 0:
                    break
                skip += 2000
            break

        section_discovered = len(all_papers_by_id)
        new_discovered = 0
        for paper in all_papers_by_id.values():
            paper.arxiv_id = _normalize_arxiv_id(paper.arxiv_id)
            if self.db.get_paper_by_arxiv_id(paper.arxiv_id) is not None:
                continue
            record = paper.to_record()
            record.pop("archive_status", None)
            self.db.upsert_paper_discovery(record)
            new_discovered += 1

        self._update_section_state(
            target_section,
            target_section_iso,
            expected_total,
            section_discovered,
            section_discovered >= expected_total,
        )

        logger.info(
            "Header-count discovery: %d new papers, %d section entries for section %s (expected=%d)",
            new_discovered,
            section_discovered,
            target_section,
            expected_total,
        )
        return new_discovered

    def _discover_fallback(self, discovery_limit: int) -> int:
        try:
            papers = self.arxiv_client.search_list_only(
                self.config.topics.categories,
                limit=discovery_limit,
                paper_exists=lambda arxiv_id: self.db.get_paper_by_arxiv_id(_normalize_arxiv_id(arxiv_id)) is not None,
            )
        except Exception as exc:
            logger.warning("Fallback discovery failed: %s", exc)
            return 0
        discovered = 0
        for paper in papers:
            paper.arxiv_id = _normalize_arxiv_id(paper.arxiv_id)
            record = paper.to_record()
            record.pop("archive_status", None)
            self.db.upsert_paper_discovery(record)
            discovered += 1
        logger.info("Fallback discovery: %d papers", discovered)
        return discovered

    def _is_section_complete(self, section_date: str, expected_total: int) -> bool:
        stored_date = self.db.get_state("arxiv_recent_latest_section_date")
        stored_expected = self.db.get_state("arxiv_recent_latest_expected_total")
        stored_discovered = self.db.get_state("arxiv_recent_latest_discovered_count")
        stored_complete = self.db.get_state("arxiv_recent_latest_complete")
        if stored_date != section_date:
            return False
        try:
            if int(stored_expected or "0") != expected_total:
                return False
        except (ValueError, TypeError):
            return False
        try:
            discovered = int(stored_discovered or "0")
        except (ValueError, TypeError):
            return False
        return stored_complete == "true" and discovered >= expected_total

    def _topics_changed_since_latest_scan(self) -> bool:
        stored = self.db.get_state("arxiv_recent_latest_topic_fingerprint")
        if stored is None:
            digest_date = self.db.get_state("arxiv_recent_latest_digest_date")
            if digest_date and self.db.accepted_results_for_date(digest_date):
                return True
            self.db.set_state("arxiv_recent_latest_topic_fingerprint", self.topic_fingerprint)
            return False
        return stored != self.topic_fingerprint

    def _update_section_state(
        self,
        section_date: str,
        section_date_iso: str,
        expected_total: int,
        discovered: int,
        complete: bool,
    ) -> None:
        self.db.set_state("arxiv_recent_latest_section_date", section_date)
        if section_date_iso:
            self.db.set_state("arxiv_recent_latest_section_date_iso", section_date_iso)
            self.db.set_state("arxiv_recent_latest_digest_date", section_date_iso)
        self.db.set_state("arxiv_recent_latest_expected_total", str(expected_total))
        self.db.set_state("arxiv_recent_latest_discovered_count", str(discovered))
        self.db.set_state("arxiv_recent_latest_complete", "true" if complete else "false")

    def _hydrate_metadata(self) -> int:
        hydrate_limit = self.config.pipeline.hydrate_metadata_per_run
        if hydrate_limit <= 0:
            return 0
        rows = self.db.metadata_only_papers(limit=hydrate_limit)
        if not rows:
            return 0
        papers = [
            PaperMetadata(
                arxiv_id=row.get("arxiv_id", ""),
                title=row.get("title", ""),
                pdf_url=row.get("pdf_url", ""),
                source=row.get("source", ""),
            )
            for row in rows
        ]
        try:
            hydrated = self.arxiv_client.hydrate_papers(papers)
        except Exception as exc:
            logger.warning("Metadata hydration failed: %s", exc)
            return 0
        count = 0
        for paper in hydrated:
            paper.arxiv_id = _normalize_arxiv_id(paper.arxiv_id)
            if paper.abstract:
                record = paper.to_record()
                record["archive_status"] = "queued"
                self.db.upsert_paper(record)
                count += 1
            else:
                logger.debug("Hydration produced no abstract for %s, keeping metadata_only", paper.arxiv_id)
        logger.info("Hydrated %d/%d metadata_only papers", count, len(rows))
        return count

    def _send_accepted_cards(self, accepted_batch: list[dict[str, Any]]) -> None:
        for paper in accepted_batch:
            msg = render_paper_short(paper)
            if msg:
                keyboard = make_expand_keyboard(paper.get("arxiv_id", ""))
                try:
                    self.telegram.send_message(msg, reply_markup=keyboard)
                except Exception as exc:
                    logger.warning("Telegram paper card failed for %s: %s", paper.get("arxiv_id"), exc)

    def _drain_queue(
        self,
        run_id: int,
        digest_date: str,
        batch_time: str,
        budget: RunBudget,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        total_processed = 0
        total_candidates = 0
        max_per_run = self.config.pipeline.max_papers_per_run
        max_candidates = self.config.pipeline.max_summary_candidates_per_run

        while True:
            if max_per_run > 0 and total_processed >= max_per_run:
                logger.info(
                    "Stopping queue drain: per-run processing cap reached (%d/%d)",
                    total_processed,
                    max_per_run,
                )
                break

            remaining = max_per_run - total_processed if max_per_run > 0 else 50
            papers = self._queued_paper_metadata(limit=min(remaining, 50))
            if not papers:
                break
            self._enrich_author_affiliations(papers)

            batch_size = len(papers)
            total_processed += batch_size
            logger.info(
                "Processing queued batch of %d papers (total this run: %d)",
                batch_size,
                total_processed,
            )

            candidates = self._phase1_relevance(papers, budget)
            logger.info(
                "Phase 1 done: %d/%d passed relevance (LLM calls used: %s)",
                len(candidates),
                batch_size,
                budget.describe(),
            )

            candidate_budget = max_candidates - total_candidates if max_candidates > 0 else len(candidates)
            if candidate_budget <= 0:
                logger.info(
                    "Stopping queue drain: summary candidate cap reached (%d/%d)",
                    total_candidates,
                    max_candidates,
                )
                break
            capped_candidates = candidates[:candidate_budget]
            total_candidates += len(capped_candidates)

            results.extend(self._phase2_summarize_qa(capped_candidates, run_id, digest_date, batch_time, budget))
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
            paper_hash = _hash_paper(paper.title, paper.abstract, self.topic_fingerprint)
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
            if not budget.try_record_call():
                return (paper, paper_hash, None)
            try:
                score = self.llm.relevance(paper, self.config.topics.queries)
                return (paper, paper_hash, score)
            except Exception as exc:
                logger.warning("Relevance scoring failed for %s: %s", paper.arxiv_id, exc)
                if _is_retryable_llm_error(exc):
                    self.db.update_paper_archive_status(paper.arxiv_id, "retry_later", str(exc))
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
                    if self.llm and budget.try_record_call():
                        try:
                            summary = self.llm.summarize(paper, summary_text)
                        except Exception as exc:
                            logger.warning("Summary failed for %s: %s", paper.arxiv_id, exc)
                            if _is_retryable_llm_error(exc):
                                self.db.update_paper_archive_status(paper.arxiv_id, "retry_later", str(exc))
                            return False

                    if self.llm and budget.try_record_call():
                        try:
                            qa = self.llm.qa(paper, summary, paper.abstract)
                        except Exception as exc:
                            logger.warning("QA failed for %s: %s", paper.arxiv_id, exc)
                            if _is_retryable_llm_error(exc):
                                self.db.update_paper_archive_status(paper.arxiv_id, "retry_later", str(exc))
                                return False
                            qa = {
                                "relevance_score": 0,
                                "grounding_score": 0,
                                "idea_score": 0,
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
            # Store the already-normalized 0-10 scores (data["*_score"]), not the
            # raw model output in data["qa"] which may be on a 0-1 scale.
            relevance_score=float(data.get("relevance_score", 0)),
            grounding_score=float(data.get("grounding_score", 0)),
            idea_score=float(data.get("idea_score", 0)),
            qa_reason=str(data.get("qa", {}).get("qa_reason", "")),
            accepted=data["accepted"],
            digest_date=data["digest_date"],
        )
        self.db.update_paper_archive_status(
            data["arxiv_id"],
            "accepted" if data["accepted"] else "rejected_qa",
        )

    def send_scan_notification(
        self,
        found_count: int,
        accepted_count: int,
        error_count: int,
        digest_date: str,
        batch_time: str,
    ) -> None:
        """Send a short hourly scan notification to Telegram."""
        parts = [f"📊 *{batch_time}* — "]
        if found_count == 0:
            parts.append("Không có paper mới.")
        else:
            parts.append(f"{found_count} paper mới")
            if accepted_count > 0:
                parts.append(f", *{accepted_count} match* ✅")
            if error_count > 0:
                parts.append(f", {error_count} lỗi")
        msg = "".join(parts)
        try:
            self.telegram.send_message(msg)
        except Exception as exc:
            logger.warning("Scan notification failed: %s", exc)

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
            self._maybe_send_due_recaps()
            time.sleep(self.config.daemon.interval_minutes * 60)

    def _maybe_send_due_recaps(self, now=None) -> None:
        tz = self.config.daemon.timezone
        local = now or local_now(tz)
        digest_date = local.strftime("%Y-%m-%d")
        current_hhmm = local.strftime("%H:%M")
        self.db.initialize()
        for slot in self.config.daemon.daily_recap_times:
            if slot > current_hhmm:
                continue
            state_key = f"daily_recap_sent:{digest_date}:{slot}"
            if self.db.get_state(state_key) is not None:
                continue
            papers = self.db.accepted_results_for_date(digest_date)
            if papers:
                try:
                    for paper in papers:
                        msg = render_paper_short(paper)
                        if msg:
                            keyboard = make_expand_keyboard(paper.get("arxiv_id", ""))
                            self.telegram.send_message(msg, reply_markup=keyboard)
                except Exception as exc:
                    logger.warning("Recap slot %s send failed for %s: %s", slot, digest_date, exc)
                    raise
            self.db.set_state(state_key, "sent")
            logger.info("Recap slot %s checked for %s (%d papers)", slot, digest_date, len(papers))

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
