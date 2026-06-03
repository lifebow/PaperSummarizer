from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PaperRadarDb:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    arxiv_id TEXT UNIQUE,
                    semantic_scholar_id TEXT,
                    title TEXT NOT NULL DEFAULT '',
                    authors_json TEXT NOT NULL DEFAULT '[]',
                    abstract TEXT NOT NULL DEFAULT '',
                    semantic_scholar_tldr TEXT NOT NULL DEFAULT '',
                    categories_json TEXT NOT NULL DEFAULT '[]',
                    published_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    pdf_url TEXT NOT NULL DEFAULT '',
                    semantic_scholar_url TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL,
                    last_status TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    found_count INTEGER NOT NULL DEFAULT 0,
                    accepted_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS paper_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id INTEGER NOT NULL,
                    run_id INTEGER NOT NULL,
                    candidate_relevance_score REAL NOT NULL DEFAULT 0,
                    extractor_name TEXT NOT NULL DEFAULT '',
                    extracted_text_chars INTEGER NOT NULL DEFAULT 0,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    relevance_score REAL NOT NULL DEFAULT 0,
                    grounding_score REAL NOT NULL DEFAULT 0,
                    idea_score REAL NOT NULL DEFAULT 0,
                    qa_reason TEXT NOT NULL DEFAULT '',
                    accepted INTEGER NOT NULL DEFAULT 0,
                    digest_date TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(paper_id) REFERENCES papers(id),
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );

                CREATE TABLE IF NOT EXISTS telegram_recaps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    digest_date TEXT NOT NULL UNIQUE,
                    sent_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_texts (
                    paper_id INTEGER PRIMARY KEY,
                    full_text TEXT NOT NULL DEFAULT '',
                    introduction_text TEXT NOT NULL DEFAULT '',
                    extraction_status TEXT NOT NULL DEFAULT 'pending',
                    extraction_error TEXT NOT NULL DEFAULT '',
                    extractor_name TEXT NOT NULL DEFAULT '',
                    extracted_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(paper_id) REFERENCES papers(id)
                );
                """
            )
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        migrations = [
            "ALTER TABLE papers ADD COLUMN primary_category TEXT DEFAULT ''",
            "ALTER TABLE papers ADD COLUMN archive_status TEXT DEFAULT 'metadata_only'",
        ]
        for sql in migrations:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(sql)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_published_at ON papers(published_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_primary_category ON papers(primary_category)")

    def upsert_paper(self, paper: dict[str, Any]) -> int:
        now = _now()
        arxiv_id = paper.get("arxiv_id", "")
        existing = self.get_paper_by_arxiv_id(arxiv_id) if arxiv_id else None
        values = {
            "arxiv_id": arxiv_id,
            "semantic_scholar_id": paper.get("semantic_scholar_id", ""),
            "title": paper.get("title", ""),
            "authors_json": json.dumps(paper.get("authors", []), ensure_ascii=False),
            "abstract": paper.get("abstract", ""),
            "semantic_scholar_tldr": paper.get("semantic_scholar_tldr", ""),
            "categories_json": json.dumps(paper.get("categories", []), ensure_ascii=False),
            "published_at": paper.get("published_at", ""),
            "updated_at": paper.get("updated_at", ""),
            "pdf_url": paper.get("pdf_url", ""),
            "semantic_scholar_url": paper.get("semantic_scholar_url", ""),
            "source": paper.get("source", ""),
            "primary_category": paper.get("primary_category", ""),
            "archive_status": paper.get("archive_status", "metadata_only"),
        }
        with self._connect() as conn:
            if existing:
                assignments = ", ".join(f"{key}=?" for key in values)
                conn.execute(
                    f"UPDATE papers SET {assignments} WHERE id=?",
                    [*values.values(), existing["id"]],
                )
                return int(existing["id"])
            cursor = conn.execute(
                """
                INSERT INTO papers (
                    arxiv_id, semantic_scholar_id, title, authors_json, abstract,
                    semantic_scholar_tldr, categories_json, published_at, updated_at,
                    pdf_url, semantic_scholar_url, source, first_seen_at,
                    primary_category, archive_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    values["arxiv_id"],
                    values["semantic_scholar_id"],
                    values["title"],
                    values["authors_json"],
                    values["abstract"],
                    values["semantic_scholar_tldr"],
                    values["categories_json"],
                    values["published_at"],
                    values["updated_at"],
                    values["pdf_url"],
                    values["semantic_scholar_url"],
                    values["source"],
                    now,
                    values["primary_category"],
                    values["archive_status"],
                ],
            )
            return int(cursor.lastrowid)

    def get_paper_by_arxiv_id(self, arxiv_id: str) -> dict[str, Any] | None:
        if not arxiv_id:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM papers WHERE arxiv_id=?", (arxiv_id,)).fetchone()
        return dict(row) if row else None

    def start_run(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, found_count: int, accepted_count: int, error_count: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET finished_at=?, status=?, found_count=?, accepted_count=?, error_count=?
                WHERE id=?
                """,
                (_now(), status, found_count, accepted_count, error_count, run_id),
            )

    def record_result(
        self,
        *,
        paper_id: int,
        run_id: int,
        candidate_relevance_score: float,
        extractor_name: str,
        extracted_text_chars: int,
        summary: dict[str, Any],
        relevance_score: float,
        grounding_score: float,
        idea_score: float,
        qa_reason: str,
        accepted: bool,
        digest_date: str,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO paper_results (
                    paper_id, run_id, candidate_relevance_score, extractor_name,
                    extracted_text_chars, summary_json, relevance_score, grounding_score,
                    idea_score, qa_reason, accepted, digest_date, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    run_id,
                    candidate_relevance_score,
                    extractor_name,
                    extracted_text_chars,
                    json.dumps(summary, ensure_ascii=False),
                    relevance_score,
                    grounding_score,
                    idea_score,
                    qa_reason,
                    1 if accepted else 0,
                    digest_date,
                    _now(),
                ),
            )
            return int(cursor.lastrowid)

    def accepted_results_for_date(self, digest_date: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*, r.summary_json, r.relevance_score, r.grounding_score,
                       r.idea_score, r.qa_reason
                FROM paper_results r
                JOIN papers p ON p.id = r.paper_id
                WHERE r.accepted = 1 AND r.digest_date = ?
                ORDER BY r.idea_score DESC, r.relevance_score DESC, p.title ASC
                """,
                (digest_date,),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["summary"] = json.loads(item.pop("summary_json") or "{}")
            item["authors"] = json.loads(item.get("authors_json") or "[]")
            item["categories"] = json.loads(item.get("categories_json") or "[]")
            results.append(item)
        return results

    def was_recap_sent(self, digest_date: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM telegram_recaps WHERE digest_date=?",
                (digest_date,),
            ).fetchone()
        return bool(row and row["status"] == "sent")

    def mark_recap(self, digest_date: str, status: str, error: str = "") -> None:
        sent_at = _now() if status == "sent" else ""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO telegram_recaps (digest_date, sent_at, status, error)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(digest_date) DO UPDATE SET
                    sent_at=excluded.sent_at,
                    status=excluded.status,
                    error=excluded.error
                """,
                (digest_date, sent_at, status, error),
            )

    def get_state(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set_state(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def upsert_paper_text(
        self,
        paper_id: int,
        *,
        full_text: str = "",
        introduction_text: str = "",
        extraction_status: str = "pending",
        extraction_error: str = "",
        extractor_name: str = "",
    ) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_texts (paper_id, full_text, introduction_text,
                    extraction_status, extraction_error, extractor_name, extracted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    full_text=excluded.full_text,
                    introduction_text=excluded.introduction_text,
                    extraction_status=excluded.extraction_status,
                    extraction_error=excluded.extraction_error,
                    extractor_name=excluded.extractor_name,
                    extracted_at=excluded.extracted_at
                """,
                (paper_id, full_text, introduction_text, extraction_status, extraction_error, extractor_name, now),
            )

    def get_paper_text(self, paper_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM paper_texts WHERE paper_id=?", (paper_id,)).fetchone()
        return dict(row) if row else None

    def papers_needing_extraction(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.arxiv_id, p.pdf_url, p.title
                FROM papers p
                LEFT JOIN paper_texts pt ON pt.paper_id = p.id
                WHERE pt.paper_id IS NULL
                   OR pt.extraction_status = 'pending'
                ORDER BY p.published_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
