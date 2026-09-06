"""SQLite persistence for local crawl inputs, evidence, and reproducible results."""

from __future__ import annotations

import json
import re
import sqlite3
from array import array
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from app.embeddings import EmbeddingProvider, HashEmbeddingProvider, cosine_similarity
from app.knowledge import KnowledgeChunk
from app.types import (
    CorruptStateError,
    CrawlRequest,
    FrontierEntry,
    IncompatibleStateError,
    IssueRecord,
    LinkRecord,
    PageRecord,
    PipelineStage,
    ResumableCrawlError,
    StageRecord,
    StageStatus,
)

CURRENT_SCHEMA_VERSION: int = 1
CURRENT_ENGINE_VERSION: str = "2.0.0"


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


_QUERY_SYNONYMS: dict[str, list[str]] = {
    "ceo": ["chief", "executive", "officer"],
    "cto": ["chief", "technology", "officer"],
    "cfo": ["chief", "financial", "officer"],
    "coo": ["chief", "operating", "officer"],
    "training": ["workshops", "curriculum", "programs"],
    "workshops": ["training", "curriculum", "seminars"],
    "educational": ["training", "workshops"],
    "schema": ["record", "fields", "structure"],
    "refund": ["return", "reimbursement"],
    "returns": ["refund"],
    "installation": ["install", "pip"],
    "install": ["installation", "pip"],
    "quickstart": ["install", "installation"],
    "authentication": ["authenticate", "bearer", "token"],
    "authenticate": ["authentication", "bearer"],
    "keys": ["token", "tokens", "bearer"],
    "key": ["token", "tokens", "bearer"],
    "integrations": ["webhooks", "webhook"],
    "integration": ["webhooks", "webhook"],
    "webhooks": ["integration", "integrations"],
    "webhook": ["integration", "integrations"],
    "quota": ["upload", "limit", "allowance"],
    "quotas": ["upload", "limit", "allowance"],
}


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS crawls (
                  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT,
                  status TEXT NOT NULL, start_url TEXT NOT NULL, settings_json TEXT NOT NULL,
                  ownership_ack INTEGER NOT NULL, error_message TEXT NOT NULL DEFAULT '',
                  robots_status TEXT NOT NULL DEFAULT 'pending', pages_crawled INTEGER NOT NULL DEFAULT 0,
                  issues_found INTEGER NOT NULL DEFAULT 0,
                  request_json TEXT NOT NULL DEFAULT '{}', attempts INTEGER NOT NULL DEFAULT 0,
                  max_attempts INTEGER NOT NULL DEFAULT 3, next_run_at TEXT, last_attempt_at TEXT,
                  pause_reason TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS pages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, crawl_id TEXT NOT NULL REFERENCES crawls(id) ON DELETE CASCADE,
                  url TEXT NOT NULL, final_url TEXT NOT NULL, status_code INTEGER, content_type TEXT NOT NULL,
                  title TEXT NOT NULL, description TEXT NOT NULL, headings_json TEXT NOT NULL, canonical TEXT NOT NULL,
                  meta_robots TEXT NOT NULL, x_robots TEXT NOT NULL, source_html TEXT NOT NULL, rendered_html TEXT NOT NULL,
                  rendered_text TEXT NOT NULL, extracted_text TEXT NOT NULL DEFAULT '', extraction_error TEXT NOT NULL DEFAULT '', extracted_fields_json TEXT NOT NULL DEFAULT '{}', extraction_notes_json TEXT NOT NULL DEFAULT '[]', images_json TEXT NOT NULL, structured_data_json TEXT NOT NULL, api_entry_points_json TEXT NOT NULL DEFAULT '[]',
                  redirects_json TEXT NOT NULL, fetch_error TEXT NOT NULL, render_error TEXT NOT NULL,
                  robots_allowed INTEGER NOT NULL, body_truncated INTEGER NOT NULL, discovered_at TEXT NOT NULL,
                  internal_inlinks INTEGER NOT NULL DEFAULT 0, content_hash TEXT NOT NULL,
                   etag TEXT NOT NULL DEFAULT '', last_modified TEXT NOT NULL DEFAULT '',
                   is_duplicate INTEGER NOT NULL DEFAULT 0, duplicate_of TEXT NOT NULL DEFAULT '',
                   source_type TEXT NOT NULL DEFAULT 'html_page', depth INTEGER NOT NULL DEFAULT 0, parent_url TEXT NOT NULL DEFAULT '',
                   normalized_url TEXT NOT NULL DEFAULT '', fetch_strategy TEXT NOT NULL DEFAULT 'static', crawler_engine TEXT NOT NULL DEFAULT 'serial',
                   response_bytes INTEGER NOT NULL DEFAULT 0, duration_ms REAL NOT NULL DEFAULT 0.0, error_category TEXT NOT NULL DEFAULT 'none',
                   headers_json TEXT NOT NULL DEFAULT '{}',
                   requested_fetch_strategy TEXT NOT NULL DEFAULT 'static', actual_fetch_strategy TEXT NOT NULL DEFAULT 'static',
                   escalated INTEGER NOT NULL DEFAULT 0, escalation_reason TEXT NOT NULL DEFAULT '',
                   fetch_duration_ms REAL NOT NULL DEFAULT 0.0, render_duration_ms REAL NOT NULL DEFAULT 0.0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_pages_crawl_url ON pages(crawl_id, url);
                CREATE INDEX IF NOT EXISTS idx_pages_crawl_final ON pages(crawl_id, final_url);
                CREATE TABLE IF NOT EXISTS links (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, crawl_id TEXT NOT NULL REFERENCES crawls(id) ON DELETE CASCADE,
                  source_url TEXT NOT NULL, target_url TEXT NOT NULL, raw_target_url TEXT NOT NULL,
                  anchor_text TEXT NOT NULL, rel TEXT NOT NULL, is_internal INTEGER NOT NULL, nofollow INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_links_crawl_target ON links(crawl_id, target_url);
                CREATE TABLE IF NOT EXISTS issues (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, crawl_id TEXT NOT NULL REFERENCES crawls(id) ON DELETE CASCADE,
                  rule_key TEXT NOT NULL, severity TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
                  evidence TEXT NOT NULL, remediation TEXT NOT NULL, fingerprint TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_issues_crawl_severity ON issues(crawl_id, severity);
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                  crawl_id TEXT NOT NULL REFERENCES crawls(id) ON DELETE CASCADE, url TEXT NOT NULL,
                  canonical_url TEXT NOT NULL DEFAULT '', title TEXT NOT NULL, section TEXT NOT NULL DEFAULT '',
                  heading_path TEXT NOT NULL, heading_path_json TEXT NOT NULL DEFAULT '[]',
                  content_type TEXT NOT NULL DEFAULT 'text/html', source_type TEXT NOT NULL DEFAULT 'html_page',
                  crawl_timestamp TEXT NOT NULL DEFAULT '', parent_url TEXT NOT NULL DEFAULT '',
                  depth INTEGER NOT NULL DEFAULT 0, content_hash TEXT NOT NULL DEFAULT '',
                  content TEXT NOT NULL, chunk_index INTEGER NOT NULL,
                  UNIQUE(crawl_id, page_id, chunk_index)
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_crawl ON knowledge_chunks(crawl_id, page_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                  chunk_id UNINDEXED, crawl_id UNINDEXED, url, title, heading_path, content
                );
                CREATE TABLE IF NOT EXISTS vector_embeddings (
                  chunk_id INTEGER PRIMARY KEY REFERENCES knowledge_chunks(id) ON DELETE CASCADE,
                  crawl_id TEXT NOT NULL REFERENCES crawls(id) ON DELETE CASCADE,
                  provider TEXT NOT NULL, dimension INTEGER NOT NULL, embedding BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_vectors_crawl ON vector_embeddings(crawl_id);
                CREATE INDEX IF NOT EXISTS idx_vectors_crawl_provider_dim ON vector_embeddings(crawl_id, provider, dimension);
                CREATE TABLE IF NOT EXISTS workflows (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, definition_json TEXT NOT NULL,
                  active INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_runs (
                  id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
                  created_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL,
                  input_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', error_message TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow ON workflow_runs(workflow_id, created_at);
                CREATE TABLE IF NOT EXISTS crawl_frontier_checkpoints (
                  crawl_id TEXT NOT NULL REFERENCES crawls(id) ON DELETE CASCADE,
                  url TEXT NOT NULL, depth INTEGER NOT NULL DEFAULT 0,
                  parent_url TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
                  discovered_at TEXT NOT NULL DEFAULT '', retry_count INTEGER NOT NULL DEFAULT 0,
                  max_retries INTEGER NOT NULL DEFAULT 3, next_eligible_time REAL NOT NULL DEFAULT 0.0,
                  error TEXT NOT NULL DEFAULT '', skip_reason TEXT NOT NULL DEFAULT '',
                  duplicate_of TEXT NOT NULL DEFAULT '', status_code INTEGER,
                  PRIMARY KEY (crawl_id, url)
                );
                CREATE INDEX IF NOT EXISTS idx_frontier_crawl_state ON crawl_frontier_checkpoints(crawl_id, state);
                """
            )
            try:
                conn.execute(
                    "DELETE FROM links WHERE id NOT IN (SELECT MIN(id) FROM links GROUP BY crawl_id, source_url, target_url)"
                )
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_links_crawl_source_target ON links(crawl_id, source_url, target_url)"
                )
            except Exception:
                pass

            self._ensure_crawl_columns(conn)
            self._ensure_page_columns(conn)
            self._ensure_knowledge_columns(conn)
            self._ensure_vector_columns(conn)
            self._ensure_pipeline_stage_tables(conn)

    @staticmethod
    def _ensure_page_columns(conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(pages)")}
        required = {
            "extracted_text": "TEXT NOT NULL DEFAULT ''",
            "extraction_error": "TEXT NOT NULL DEFAULT ''",
            "extracted_fields_json": "TEXT NOT NULL DEFAULT '{}'",
            "extraction_notes_json": "TEXT NOT NULL DEFAULT '[]'",
            "api_entry_points_json": "TEXT NOT NULL DEFAULT '[]'",
            "etag": "TEXT NOT NULL DEFAULT ''",
            "last_modified": "TEXT NOT NULL DEFAULT ''",
            "is_duplicate": "INTEGER NOT NULL DEFAULT 0",
            "duplicate_of": "TEXT NOT NULL DEFAULT ''",
            "source_type": "TEXT NOT NULL DEFAULT 'html_page'",
            "depth": "INTEGER NOT NULL DEFAULT 0",
            "parent_url": "TEXT NOT NULL DEFAULT ''",
            "normalized_url": "TEXT NOT NULL DEFAULT ''",
            "fetch_strategy": "TEXT NOT NULL DEFAULT 'static'",
            "crawler_engine": "TEXT NOT NULL DEFAULT 'serial'",
            "response_bytes": "INTEGER NOT NULL DEFAULT 0",
            "duration_ms": "REAL NOT NULL DEFAULT 0.0",
            "error_category": "TEXT NOT NULL DEFAULT 'none'",
            "headers_json": "TEXT NOT NULL DEFAULT '{}'",
            "requested_fetch_strategy": "TEXT NOT NULL DEFAULT 'static'",
            "actual_fetch_strategy": "TEXT NOT NULL DEFAULT 'static'",
            "escalated": "INTEGER NOT NULL DEFAULT 0",
            "escalation_reason": "TEXT NOT NULL DEFAULT ''",
            "fetch_duration_ms": "REAL NOT NULL DEFAULT 0.0",
            "render_duration_ms": "REAL NOT NULL DEFAULT 0.0",
        }
        for name, definition in required.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE pages ADD COLUMN {name} {definition}")

    @staticmethod
    def _ensure_knowledge_columns(conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(knowledge_chunks)")}
        required = {
            "canonical_url": "TEXT NOT NULL DEFAULT ''",
            "section": "TEXT NOT NULL DEFAULT ''",
            "heading_path_json": "TEXT NOT NULL DEFAULT '[]'",
            "content_type": "TEXT NOT NULL DEFAULT 'text/html'",
            "source_type": "TEXT NOT NULL DEFAULT 'html_page'",
            "crawl_timestamp": "TEXT NOT NULL DEFAULT ''",
            "parent_url": "TEXT NOT NULL DEFAULT ''",
            "depth": "INTEGER NOT NULL DEFAULT 0",
            "content_hash": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in required.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE knowledge_chunks ADD COLUMN {name} {definition}")

    @staticmethod
    def _ensure_crawl_columns(conn: sqlite3.Connection) -> None:
        """Upgrade earlier local databases without requiring destructive migrations."""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(crawls)")}
        required = {
            "request_json": "TEXT NOT NULL DEFAULT '{}'",
            "attempts": "INTEGER NOT NULL DEFAULT 0",
            "max_attempts": "INTEGER NOT NULL DEFAULT 3",
            "next_run_at": "TEXT",
            "last_attempt_at": "TEXT",
            "pause_reason": "TEXT NOT NULL DEFAULT ''",
            "checkpoint_json": "TEXT NOT NULL DEFAULT '{}'",
            "schema_version": "INTEGER NOT NULL DEFAULT 1",
            "engine_version": "TEXT NOT NULL DEFAULT '2.0.0'",
        }
        for name, definition in required.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE crawls ADD COLUMN {name} {definition}")

    @staticmethod
    def _ensure_vector_columns(conn: sqlite3.Connection) -> None:
        """Upgrade vector_embeddings table to support multi-model metadata without recrawling."""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(vector_embeddings)")}
        required = {
            "model": "TEXT NOT NULL DEFAULT ''",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "content_hash": "TEXT NOT NULL DEFAULT ''",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, definition in required.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE vector_embeddings ADD COLUMN {name} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vectors_crawl_provider_dim ON vector_embeddings(crawl_id, provider, dimension)")

    @staticmethod
    def _ensure_pipeline_stage_tables(conn: sqlite3.Connection) -> None:
        """Ensure pipeline stages and failed chunks tracking tables exist."""
        conn.execute(
            """CREATE TABLE IF NOT EXISTS pipeline_stage_records (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 crawl_id TEXT NOT NULL REFERENCES crawls(id) ON DELETE CASCADE,
                 stage TEXT NOT NULL,
                 status TEXT NOT NULL,
                 started_at TEXT NOT NULL DEFAULT '',
                 completed_at TEXT NOT NULL DEFAULT '',
                 provider TEXT NOT NULL DEFAULT '',
                 model TEXT NOT NULL DEFAULT '',
                 dimension INTEGER NOT NULL DEFAULT 0,
                 total_items INTEGER NOT NULL DEFAULT 0,
                 successful_items INTEGER NOT NULL DEFAULT 0,
                 failed_items INTEGER NOT NULL DEFAULT 0,
                 pending_items INTEGER NOT NULL DEFAULT 0,
                 error_message TEXT NOT NULL DEFAULT '',
                 retryable INTEGER NOT NULL DEFAULT 0,
                 metadata_json TEXT NOT NULL DEFAULT '{}',
                 UNIQUE(crawl_id, stage)
               )"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_pipeline_stages_crawl ON pipeline_stage_records(crawl_id, stage)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS failed_embedding_chunks (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 crawl_id TEXT NOT NULL REFERENCES crawls(id) ON DELETE CASCADE,
                 chunk_id INTEGER NOT NULL REFERENCES knowledge_chunks(id) ON DELETE CASCADE,
                 provider TEXT NOT NULL,
                 model TEXT NOT NULL,
                 dimension INTEGER NOT NULL DEFAULT 0,
                 attempt_count INTEGER NOT NULL DEFAULT 1,
                 last_error TEXT NOT NULL DEFAULT '',
                 retryable INTEGER NOT NULL DEFAULT 1,
                 failed_at TEXT NOT NULL DEFAULT '',
                 UNIQUE(crawl_id, chunk_id, provider, model)
               )"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_failed_chunks_crawl ON failed_embedding_chunks(crawl_id, provider, model)"""
        )

    def create_crawl(self, request: CrawlRequest) -> str:
        crawl_id = request.crawl_id or str(uuid4())
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO crawls (id, created_at, status, start_url, settings_json, request_json, ownership_ack, next_run_at, schema_version, engine_version)
                   VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                   settings_json=excluded.settings_json, request_json=excluded.request_json,
                   schema_version=excluded.schema_version, engine_version=excluded.engine_version""",
                (crawl_id, now(), request.start_url, json.dumps(request.public_settings()), json.dumps(request.storage_payload()), int(request.acknowledgment), now(), CURRENT_SCHEMA_VERSION, CURRENT_ENGINE_VERSION),
            )
        return crawl_id

    def get_crawl_request(self, crawl_id: str) -> CrawlRequest | None:
        with self.connect() as conn:
            row = conn.execute("SELECT request_json FROM crawls WHERE id = ?", (crawl_id,)).fetchone()
        if not row or not row["request_json"] or row["request_json"] == "{}":
            return None
        return CrawlRequest.from_storage_payload(json.loads(row["request_json"]))

    def recover_interrupted_jobs(self) -> int:
        """Return interrupted work to a deliberate retryable state when the local app starts."""
        with self.connect() as conn:
            cursor = conn.execute(
                """UPDATE crawls SET status = 'retryable', next_run_at = ?, error_message = ?, pause_reason = ''
                   WHERE status = 'running'""",
                (now(), "Local worker stopped before this authorized crawl completed. It is ready for a bounded retry."),
            )
        return cursor.rowcount

    def claim_next_job(self) -> dict[str, Any] | None:
        """Atomically claim one eligible job for the sole local worker."""
        claim_time = now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT * FROM crawls
                   WHERE status IN ('queued', 'retryable')
                   AND (next_run_at IS NULL OR next_run_at <= ?)
                   ORDER BY created_at, id LIMIT 1""",
                (claim_time,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """UPDATE crawls SET status = 'running', started_at = COALESCE(started_at, ?), last_attempt_at = ?,
                   attempts = attempts + 1, error_message = '', pause_reason = '', next_run_at = NULL WHERE id = ?""",
                (claim_time, claim_time, row["id"]),
            )
            claimed = conn.execute("SELECT * FROM crawls WHERE id = ?", (row["id"],)).fetchone()
        return self._crawl_row(claimed) if claimed else None

    def defer_or_pause_job(self, crawl_id: str, error_message: str) -> dict[str, Any] | None:
        """Apply bounded backoff, then open a local circuit breaker after repeated worker failures."""
        with self.connect() as conn:
            row = conn.execute("SELECT attempts, max_attempts FROM crawls WHERE id = ?", (crawl_id,)).fetchone()
            if not row:
                return None
            attempts, maximum = int(row["attempts"]), int(row["max_attempts"])
            if attempts >= maximum:
                conn.execute(
                    """UPDATE crawls SET status = 'paused', completed_at = ?, error_message = ?, pause_reason = ?, next_run_at = NULL
                       WHERE id = ?""",
                    (now(), error_message, f"Circuit breaker opened after {attempts} worker attempts. Review the error and resume explicitly.", crawl_id),
                )
            else:
                delay_seconds = min(300, 15 * (2 ** max(0, attempts - 1)))
                retry_at = (datetime.now(UTC) + timedelta(seconds=delay_seconds)).replace(microsecond=0).isoformat()
                conn.execute(
                    """UPDATE crawls SET status = 'retryable', error_message = ?, pause_reason = ?, next_run_at = ? WHERE id = ?""",
                    (error_message, f"Retry scheduled after {delay_seconds} seconds (attempt {attempts + 1} of {maximum}).", retry_at, crawl_id),
                )
        return self.get_crawl(crawl_id)

    def pause_job(self, crawl_id: str, reason: str = "Paused by the local operator.") -> dict[str, Any] | None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE crawls SET status = 'paused', pause_reason = ?, next_run_at = NULL
                   WHERE id = ? AND status IN ('queued', 'retryable')""",
                (reason, crawl_id),
            )
        return self.get_crawl(crawl_id)

    def resume_job(self, crawl_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE crawls SET status = 'queued', attempts = 0, completed_at = NULL, error_message = '', pause_reason = '', next_run_at = ?
                   WHERE id = ? AND status IN ('paused', 'retryable', 'failed')""",
                (now(), crawl_id),
            )
        return self.get_crawl(crawl_id)

    def update_crawl(self, crawl_id: str, **values: Any) -> None:
        if not values:
            return
        columns = ", ".join(f"{key} = ?" for key in values)
        with self.connect() as conn:
            conn.execute(f"UPDATE crawls SET {columns} WHERE id = ?", (*values.values(), crawl_id))

    def get_crawl(self, crawl_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            record = conn.execute("SELECT * FROM crawls WHERE id = ?", (crawl_id,)).fetchone()
        return self._crawl_row(record) if record else None

    def list_crawls(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            records = conn.execute("SELECT * FROM crawls ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._crawl_row(row) for row in records]

    def get_crawl_coverage(self, crawl_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            page_rows = conn.execute(
                "SELECT url, final_url, status_code, content_type, is_duplicate, duplicate_of, source_type, depth, rendered_text FROM pages WHERE crawl_id = ?",
                (crawl_id,),
            ).fetchall()
            link_target_rows = conn.execute(
                "SELECT DISTINCT target_url FROM links WHERE crawl_id = ?",
                (crawl_id,),
            ).fetchall()

        crawled_urls = {r["url"] for r in page_rows}
        discovered_urls = set(crawled_urls)
        for r in link_target_rows:
            target = r[0]
            if target:
                discovered_urls.add(target)
        discovered_urls_count = len(discovered_urls)

        status_dist: dict[str, int] = {}
        content_dist: dict[str, int] = {}
        duplicates_count = 0
        api_count = 0
        total_words = 0
        word_count_pages = 0

        for r in page_rows:
            code = str(r["status_code"] or "error")
            status_dist[code] = status_dist.get(code, 0) + 1

            c_type = (r["content_type"] or "unknown").split(";")[0].strip().lower()
            content_dist[c_type] = content_dist.get(c_type, 0) + 1

            if r["is_duplicate"]:
                duplicates_count += 1
            if r["source_type"] == "official_api" or "json" in c_type:
                api_count += 1

            text = r["rendered_text"] or ""
            words = len(text.split())
            if words > 0:
                total_words += words
                word_count_pages += 1

        coverage_rate = (len(crawled_urls) / discovered_urls_count) if discovered_urls_count else 1.0
        avg_words = round(total_words / word_count_pages, 1) if word_count_pages else 0.0

        return {
            "crawl_id": crawl_id,
            "total_crawled_urls": len(crawled_urls),
            "total_discovered_urls": discovered_urls_count,
            "crawl_coverage_rate": round(coverage_rate, 2),
            "status_code_distribution": status_dist,
            "content_type_distribution": content_dist,
            "duplicates_detected": duplicates_count,
            "api_endpoints_indexed": api_count,
            "average_word_count": avg_words,
        }

    def _crawl_row(self, row: sqlite3.Row) -> dict[str, Any]:
        crawl = dict(row)
        crawl["settings"] = json.loads(crawl.pop("settings_json"))
        return crawl

    def replace_pages_and_links(self, crawl_id: str, pages: Iterable[PageRecord], links: Iterable[LinkRecord]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM links WHERE crawl_id = ?", (crawl_id,))
            conn.execute("DELETE FROM pages WHERE crawl_id = ?", (crawl_id,))
            conn.executemany(
                """INSERT INTO pages (crawl_id, url, final_url, status_code, content_type, title, description, headings_json,
                   canonical, meta_robots, x_robots, source_html, rendered_html, rendered_text, extracted_text, extraction_error, extracted_fields_json, extraction_notes_json, images_json, structured_data_json, api_entry_points_json,
                   redirects_json, fetch_error, render_error, robots_allowed, body_truncated, discovered_at, internal_inlinks, content_hash,
                   etag, last_modified, is_duplicate, duplicate_of, source_type, depth, parent_url,
                   normalized_url, fetch_strategy, crawler_engine, response_bytes, duration_ms, error_category, headers_json,
                   requested_fetch_strategy, actual_fetch_strategy, escalated, escalation_reason, fetch_duration_ms, render_duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                [
                    (
                        crawl_id, page.url, page.final_url, page.status_code, page.content_type, page.title, page.description,
                        json.dumps(page.headings), page.canonical, page.meta_robots, page.x_robots, page.source_html,
                        page.rendered_html, page.rendered_text, page.extracted_text, page.extraction_error, json.dumps(page.extracted_fields), json.dumps(page.extraction_notes), json.dumps(page.images), json.dumps(page.structured_data), json.dumps(page.api_entry_points),
                        json.dumps(page.redirect_chain), page.fetch_error, page.render_error, int(page.robots_allowed),
                        int(page.body_truncated), page.discovered_at, page.internal_inlinks, page.content_hash,
                        getattr(page, "etag", ""), getattr(page, "last_modified", ""),
                        int(getattr(page, "is_duplicate", False)), getattr(page, "duplicate_of", ""),
                        getattr(page, "source_type", "html_page"), getattr(page, "depth", 0), getattr(page, "parent_url", ""),
                        getattr(page, "normalized_url", page.final_url or page.url),
                        getattr(page, "fetch_strategy", "static"),
                        getattr(page, "crawler_engine", "serial"),
                        getattr(page, "response_bytes", 0),
                        getattr(page, "duration_ms", 0.0),
                        getattr(page, "error_category", "none"),
                        json.dumps(getattr(page, "headers", {})),
                        getattr(page, "requested_fetch_strategy", getattr(page, "fetch_strategy", "static")),
                        getattr(page, "actual_fetch_strategy", getattr(page, "fetch_strategy", "static")),
                        int(getattr(page, "escalated", False)),
                        getattr(page, "escalation_reason", ""),
                        getattr(page, "fetch_duration_ms", getattr(page, "duration_ms", 0.0)),
                        getattr(page, "render_duration_ms", 0.0),
                    ) for page in pages
                ],
            )
            conn.executemany(
                """INSERT INTO links (crawl_id, source_url, target_url, raw_target_url, anchor_text, rel, is_internal, nofollow)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(crawl_id, source_url, target_url) DO UPDATE SET
                   raw_target_url=excluded.raw_target_url, anchor_text=excluded.anchor_text,
                   rel=excluded.rel, is_internal=excluded.is_internal, nofollow=excluded.nofollow""",
                [
                    (crawl_id, link.source_url, link.target_url, link.raw_target_url, link.anchor_text, link.rel,
                     int(link.is_internal), int(link.nofollow)) for link in links
                ],
            )

    def replace_issues(self, crawl_id: str, issues: Iterable[IssueRecord]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM issues WHERE crawl_id = ?", (crawl_id,))
            conn.executemany(
                """INSERT INTO issues (crawl_id, rule_key, severity, title, url, evidence, remediation, fingerprint)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [(crawl_id, issue.rule_key, issue.severity, issue.title, issue.url, issue.evidence, issue.remediation, issue.fingerprint) for issue in issues],
            )

    def update_pipeline_stage(
        self,
        crawl_id: str,
        stage: PipelineStage | str,
        status: StageStatus | str,
        *,
        started_at: str = "",
        completed_at: str = "",
        provider: str = "",
        model: str = "",
        dimension: int = 0,
        total_items: int = -1,
        successful_items: int = -1,
        failed_items: int = -1,
        pending_items: int = -1,
        error_message: str = "",
        retryable: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> StageRecord:
        """Upsert a pipeline stage record with forensic status and counters."""
        stage_name = stage.value if isinstance(stage, PipelineStage) else str(stage)
        status_name = status.value if isinstance(status, StageStatus) else str(status)
        meta_json = json.dumps(metadata or {})
        init_total = max(0, total_items)
        init_success = max(0, successful_items)
        init_failed = max(0, failed_items)
        init_pending = max(0, pending_items)

        with self.connect() as conn:
            conn.execute(
                """INSERT INTO pipeline_stage_records (
                       crawl_id, stage, status, started_at, completed_at, provider, model, dimension,
                       total_items, successful_items, failed_items, pending_items, error_message, retryable, metadata_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(crawl_id, stage) DO UPDATE SET
                       status=excluded.status,
                       started_at=CASE WHEN excluded.started_at != '' THEN excluded.started_at ELSE pipeline_stage_records.started_at END,
                       completed_at=CASE WHEN excluded.completed_at != '' THEN excluded.completed_at ELSE pipeline_stage_records.completed_at END,
                       provider=CASE WHEN excluded.provider != '' THEN excluded.provider ELSE pipeline_stage_records.provider END,
                       model=CASE WHEN excluded.model != '' THEN excluded.model ELSE pipeline_stage_records.model END,
                       dimension=CASE WHEN excluded.dimension > 0 THEN excluded.dimension ELSE pipeline_stage_records.dimension END,
                       total_items=CASE WHEN excluded.total_items >= 0 THEN excluded.total_items ELSE pipeline_stage_records.total_items END,
                       successful_items=CASE WHEN excluded.successful_items >= 0 THEN excluded.successful_items ELSE pipeline_stage_records.successful_items END,
                       failed_items=CASE WHEN excluded.failed_items >= 0 THEN excluded.failed_items ELSE pipeline_stage_records.failed_items END,
                       pending_items=CASE WHEN excluded.pending_items >= 0 THEN excluded.pending_items ELSE pipeline_stage_records.pending_items END,
                       error_message=excluded.error_message,
                       retryable=excluded.retryable,
                       metadata_json=CASE WHEN excluded.metadata_json != '{}' THEN excluded.metadata_json ELSE pipeline_stage_records.metadata_json END""",
                (
                    crawl_id, stage_name, status_name, started_at, completed_at, provider, model, dimension,
                    init_total if total_items >= 0 else -1,
                    init_success if successful_items >= 0 else -1,
                    init_failed if failed_items >= 0 else -1,
                    init_pending if pending_items >= 0 else -1,
                    error_message, int(retryable), meta_json,
                ),
            )
            row = conn.execute(
                "SELECT * FROM pipeline_stage_records WHERE crawl_id = ? AND stage = ?",
                (crawl_id, stage_name),
            ).fetchone()

        row_dict = dict(row)
        return StageRecord(
            stage=row_dict["stage"],
            status=row_dict["status"],
            started_at=row_dict["started_at"],
            completed_at=row_dict["completed_at"],
            provider=row_dict["provider"],
            model=row_dict["model"],
            dimension=int(row_dict["dimension"]),
            total_items=int(row_dict["total_items"]),
            successful_items=int(row_dict["successful_items"]),
            failed_items=int(row_dict["failed_items"]),
            pending_items=int(row_dict["pending_items"]),
            error_message=row_dict["error_message"],
            retryable=bool(row_dict["retryable"]),
            metadata=json.loads(row_dict["metadata_json"] or "{}"),
        )

    def get_pipeline_stage(self, crawl_id: str, stage: PipelineStage | str) -> dict[str, Any] | None:
        """Get the forensic status record for a single pipeline stage."""
        stage_name = stage.value if isinstance(stage, PipelineStage) else str(stage)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_stage_records WHERE crawl_id = ? AND stage = ?",
                (crawl_id, stage_name),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["retryable"] = bool(d["retryable"])
        d["metadata"] = json.loads(d.pop("metadata_json", "{}") or "{}")
        return d

    def get_pipeline_status(self, crawl_id: str) -> dict[str, Any]:
        """Get the full decoupled pipeline status across all 7 stages."""
        standard_stages = [
            PipelineStage.CRAWL.value,
            PipelineStage.STORAGE.value,
            PipelineStage.EXTRACTION.value,
            PipelineStage.CHUNKING.value,
            PipelineStage.EMBEDDING.value,
            PipelineStage.INDEXING.value,
            PipelineStage.RAG.value,
        ]
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pipeline_stage_records WHERE crawl_id = ?",
                (crawl_id,),
            ).fetchall()
            failed_row = conn.execute(
                "SELECT COUNT(*) as count FROM failed_embedding_chunks WHERE crawl_id = ?",
                (crawl_id,),
            ).fetchone()
            crawl_row = conn.execute(
                "SELECT status, error_message, pause_reason FROM crawls WHERE id = ?",
                (crawl_id,),
            ).fetchone()

        failed_chunks_count = int(failed_row["count"]) if failed_row else 0
        stages_by_name: dict[str, dict[str, Any]] = {}
        for r in rows:
            d = dict(r)
            d["retryable"] = bool(d["retryable"])
            d["metadata"] = json.loads(d.pop("metadata_json", "{}") or "{}")
            stages_by_name[d["stage"]] = d

        complete_stages: dict[str, dict[str, Any]] = {}
        for st in standard_stages:
            if st in stages_by_name:
                complete_stages[st] = stages_by_name[st]
            else:
                complete_stages[st] = StageRecord(stage=st, status=StageStatus.NOT_STARTED.value).to_dict()

        overall_status = "unknown"
        if crawl_row:
            overall_status = crawl_row["status"]

        return {
            "crawl_id": crawl_id,
            "overall_status": overall_status,
            "stages": complete_stages,
            "failed_chunks_count": failed_chunks_count,
        }

    def detect_embedding_generation_mismatch(self, crawl_id: str, embedder: EmbeddingProvider) -> dict[str, Any]:
        """Detect if the configured embedding provider/model/dimension differs from indexed vectors."""
        active_model = getattr(embedder, "model_name", embedder.name)
        active_prov = getattr(embedder, "name", "hash")
        active_dim = getattr(embedder, "dimension", 0)

        with self.connect() as conn:
            rows = conn.execute(
                """SELECT provider, model, dimension, COUNT(*) as count
                   FROM vector_embeddings WHERE crawl_id = ?
                   GROUP BY provider, model, dimension""",
                (crawl_id,),
            ).fetchall()

        if not rows:
            return {
                "mismatch": False,
                "has_existing_embeddings": False,
                "requires_reindex": False,
                "requested": {"provider": active_prov, "model": active_model, "dimension": active_dim},
                "generations": [],
            }

        generations = [dict(r) for r in rows]
        exact_match = any(
            (r["provider"] == active_prov or r["provider"] == embedder.name)
            and (r["model"] == active_model or not r["model"])
            and r["dimension"] == active_dim
            for r in rows
        )
        primary = rows[0]
        mismatch = not exact_match
        return {
            "mismatch": mismatch,
            "has_existing_embeddings": True,
            "requires_reindex": mismatch,
            "existing": {
                "provider": primary["provider"],
                "model": primary["model"],
                "dimension": primary["dimension"],
                "chunk_count": primary["count"],
            },
            "requested": {
                "provider": active_prov,
                "model": active_model,
                "dimension": active_dim,
            },
            "generations": generations,
        }

    def index_knowledge_pipeline(
        self,
        crawl_id: str,
        chunks: Iterable[KnowledgeChunk],
        embedder: EmbeddingProvider | None = None,
        force_reembed: bool = False,
    ) -> dict[str, Any]:
        """Decoupled knowledge indexing pipeline: Lexical commit first, then vector embedding with partial fault isolation."""
        materialized = list(chunks)
        total_chunks = len(materialized)
        now_ts = now()

        # Step 1: Record Extraction Stage as SUCCESS if not already recorded
        extraction_record = self.get_pipeline_stage(crawl_id, PipelineStage.EXTRACTION)
        if not extraction_record or extraction_record.get("status") != StageStatus.SUCCESS.value:
            self.update_pipeline_stage(
                crawl_id,
                PipelineStage.EXTRACTION,
                StageStatus.SUCCESS,
                total_items=total_chunks,
                successful_items=total_chunks,
                completed_at=now_ts,
            )

        # Step 2: Durable Lexical Chunking Persistence (Atomic transaction, independent of embeddings)
        self.update_pipeline_stage(
            crawl_id,
            PipelineStage.CHUNKING,
            StageStatus.RUNNING,
            started_at=now_ts,
            total_items=total_chunks,
        )

        try:
            with self.connect() as conn:
                if force_reembed or not self.get_vector_embeddings_metadata(crawl_id):
                    conn.execute("DELETE FROM vector_embeddings WHERE crawl_id = ?", (crawl_id,))
                    conn.execute("DELETE FROM failed_embedding_chunks WHERE crawl_id = ?", (crawl_id,))

                for chunk in materialized:
                    conn.execute(
                        """INSERT INTO knowledge_chunks (
                               page_id, crawl_id, url, canonical_url, title, section, heading_path,
                               heading_path_json, content_type, source_type, crawl_timestamp,
                               parent_url, depth, content_hash, content, chunk_index
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(crawl_id, page_id, chunk_index) DO UPDATE SET
                               url=excluded.url, canonical_url=excluded.canonical_url, title=excluded.title,
                               section=excluded.section, heading_path=excluded.heading_path,
                               heading_path_json=excluded.heading_path_json, content_type=excluded.content_type,
                               source_type=excluded.source_type, crawl_timestamp=excluded.crawl_timestamp,
                               parent_url=excluded.parent_url, depth=excluded.depth, content_hash=excluded.content_hash,
                               content=excluded.content""",
                        chunk.as_row(),
                    )

                active_keys = {(c.page_id, c.chunk_index) for c in materialized}
                existing_chunks = conn.execute(
                    "SELECT id, page_id, chunk_index FROM knowledge_chunks WHERE crawl_id = ?",
                    (crawl_id,),
                ).fetchall()
                stale_ids = [r["id"] for r in existing_chunks if (r["page_id"], r["chunk_index"]) not in active_keys]
                if stale_ids:
                    stale_ph = ",".join("?" for _ in stale_ids)
                    conn.execute(f"DELETE FROM knowledge_chunks WHERE id IN ({stale_ph})", stale_ids)
                    conn.execute(f"DELETE FROM vector_embeddings WHERE chunk_id IN ({stale_ph})", stale_ids)
                    conn.execute(f"DELETE FROM failed_embedding_chunks WHERE chunk_id IN ({stale_ph})", stale_ids)

                conn.execute("DELETE FROM knowledge_fts WHERE crawl_id = ?", (crawl_id,))
                conn.execute(
                    """INSERT INTO knowledge_fts (chunk_id, crawl_id, url, title, heading_path, content)
                       SELECT id, crawl_id, url, title, heading_path, content FROM knowledge_chunks WHERE crawl_id = ?""",
                    (crawl_id,),
                )

            self.update_pipeline_stage(
                crawl_id,
                PipelineStage.CHUNKING,
                StageStatus.SUCCESS,
                total_items=total_chunks,
                successful_items=total_chunks,
                completed_at=now(),
            )
        except Exception as chunk_exc:
            self.update_pipeline_stage(
                crawl_id,
                PipelineStage.CHUNKING,
                StageStatus.FAILED,
                total_items=total_chunks,
                error_message=f"{type(chunk_exc).__name__}: {chunk_exc}",
                completed_at=now(),
            )
            raise

        # Step 3: Embeddings & Vector Indexing Stage
        active_embedder = embedder or HashEmbeddingProvider()
        active_model = getattr(active_embedder, "model_name", active_embedder.name)
        active_prov = getattr(active_embedder, "name", "hash")
        active_dim = getattr(active_embedder, "dimension", 0)

        if total_chunks == 0:
            self.update_pipeline_stage(
                crawl_id, PipelineStage.EMBEDDING, StageStatus.SUCCESS,
                provider=active_prov, model=active_model, dimension=active_dim,
                total_items=0, successful_items=0, completed_at=now(),
            )
            self.update_pipeline_stage(
                crawl_id, PipelineStage.INDEXING, StageStatus.SUCCESS,
                provider=active_prov, model=active_model, dimension=active_dim,
                total_items=0, successful_items=0, completed_at=now(),
            )
            return {"chunks_embedded": 0, "status": "success", "provider": active_prov, "model": active_model}

        if active_dim <= 0:
            self.update_pipeline_stage(
                crawl_id, PipelineStage.EMBEDDING, StageStatus.SKIPPED,
                provider=active_prov, model=active_model, dimension=0,
                total_items=total_chunks, error_message="Dimension is 0; embedding skipped.",
                completed_at=now(),
            )
            self.update_pipeline_stage(
                crawl_id, PipelineStage.INDEXING, StageStatus.SUCCESS,
                provider=active_prov, model=active_model, dimension=0,
                total_items=total_chunks, successful_items=total_chunks,
                metadata={"lexical_only": True},
                completed_at=now(),
            )
            return {"chunks_embedded": 0, "status": "skipped", "provider": active_prov, "model": active_model}

        self.update_pipeline_stage(
            crawl_id, PipelineStage.EMBEDDING, StageStatus.RUNNING,
            provider=active_prov, model=active_model, dimension=active_dim,
            total_items=total_chunks, started_at=now(),
        )
        self.update_pipeline_stage(
            crawl_id, PipelineStage.INDEXING, StageStatus.RUNNING,
            provider=active_prov, model=active_model, dimension=active_dim,
            total_items=total_chunks, started_at=now(),
        )

        with self.connect() as conn:
            stored_rows = conn.execute(
                "SELECT id, content, content_hash FROM knowledge_chunks WHERE crawl_id = ? ORDER BY id",
                (crawl_id,),
            ).fetchall()
            existing_vec_rows = conn.execute(
                """SELECT chunk_id, content_hash FROM vector_embeddings
                   WHERE crawl_id = ? AND (provider = ? OR provider = ?) AND (model = ? OR ? = '' OR model = '') AND dimension = ?""",
                (crawl_id, active_prov, active_embedder.name, active_model, active_model, active_dim),
            ).fetchall()

        existing_hashes = {r["chunk_id"]: r["content_hash"] for r in existing_vec_rows}

        # Content Hashing Skip Logic:
        # If content_hash is unchanged and model/provider/dimension matches, skip embedding!
        chunks_to_embed = []
        skipped_count = 0
        for r in stored_rows:
            c_id = r["id"]
            c_hash = r["content_hash"]
            if not force_reembed and c_id in existing_hashes and existing_hashes[c_id] == c_hash:
                skipped_count += 1
            else:
                chunks_to_embed.append(r)

        successful_count = skipped_count
        failed_count = 0
        last_error = ""
        is_retryable = False

        batch_size = max(1, getattr(active_embedder, "batch_size", 100))
        for i in range(0, len(chunks_to_embed), batch_size):
            batch = chunks_to_embed[i : i + batch_size]
            texts = [item["content"] for item in batch]
            try:
                embeddings = active_embedder.embed_batch(texts, task_type="RETRIEVAL_DOCUMENT")
                vector_rows = []
                batch_now = now()
                for item, vec in zip(batch, embeddings):
                    if vec:
                        emb_arr = array("f", vec)
                        meta_dict = {
                            "provider": active_prov,
                            "model": active_model,
                            "dimension": len(emb_arr),
                            "created_at": batch_now,
                            "task_type": "RETRIEVAL_DOCUMENT",
                        }
                        vector_rows.append((
                            item["id"], crawl_id, active_prov, active_model,
                            len(emb_arr), emb_arr.tobytes(), batch_now, item["content_hash"], json.dumps(meta_dict)
                        ))

                if vector_rows:
                    with self.connect() as conn:
                        conn.executemany(
                            """INSERT OR REPLACE INTO vector_embeddings (
                                   chunk_id, crawl_id, provider, model, dimension, embedding, created_at, content_hash, metadata_json
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            vector_rows,
                        )
                        c_ids = [r[0] for r in vector_rows]
                        placeholders = ",".join("?" for _ in c_ids)
                        conn.execute(
                            f"DELETE FROM failed_embedding_chunks WHERE crawl_id = ? AND provider = ? AND model = ? AND chunk_id IN ({placeholders})",
                            (crawl_id, active_prov, active_model, *c_ids),
                        )
                    successful_count += len(vector_rows)
            except Exception as batch_exc:
                last_error = f"{type(batch_exc).__name__}: {batch_exc}"
                err_lower = str(batch_exc).lower()
                non_retryable = any(s in err_lower for s in ["400", "401", "403", "invalid api key", "invalid_api_key", "dimension mismatch", "unauthorized", "bad request"])
                is_retryable = not non_retryable if getattr(batch_exc, "retryable", None) is None else bool(getattr(batch_exc, "retryable", False))
                failed_count += len(batch)
                fail_now = now()
                with self.connect() as conn:
                    for item in batch:
                        conn.execute(
                            """INSERT INTO failed_embedding_chunks (
                                   crawl_id, chunk_id, provider, model, dimension, attempt_count, last_error, retryable, failed_at
                               ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                               ON CONFLICT(crawl_id, chunk_id, provider, model) DO UPDATE SET
                                   attempt_count = failed_embedding_chunks.attempt_count + 1,
                                   last_error = excluded.last_error,
                                   retryable = excluded.retryable,
                                   failed_at = excluded.failed_at""",
                            (crawl_id, item["id"], active_prov, active_model, active_dim, last_error, int(is_retryable), fail_now),
                        )

        # Stage Outcome Accounting
        if failed_count == 0:
            final_status = StageStatus.SUCCESS
            final_retryable = False
        elif successful_count > 0:
            final_status = StageStatus.PARTIAL
            final_retryable = is_retryable
        else:
            final_status = StageStatus.FAILED
            final_retryable = is_retryable

        finish_now = now()
        self.update_pipeline_stage(
            crawl_id, PipelineStage.EMBEDDING, final_status,
            provider=active_prov, model=active_model, dimension=active_dim,
            total_items=total_chunks, successful_items=successful_count,
            failed_items=failed_count, pending_items=failed_count,
            error_message=last_error, retryable=final_retryable,
            completed_at=finish_now,
        )
        self.update_pipeline_stage(
            crawl_id, PipelineStage.INDEXING, final_status,
            provider=active_prov, model=active_model, dimension=active_dim,
            total_items=total_chunks, successful_items=successful_count,
            failed_items=failed_count, pending_items=failed_count,
            error_message=last_error, retryable=final_retryable,
            completed_at=finish_now,
        )

        return {
            "crawl_id": crawl_id,
            "total_chunks": total_chunks,
            "successful_items": successful_count,
            "failed_items": failed_count,
            "skipped_unchanged": skipped_count,
            "status": final_status.value,
            "provider": active_prov,
            "model": active_model,
            "dimension": active_dim,
            "retryable": final_retryable,
            "error_message": last_error,
        }

    def replace_knowledge_chunks(self, crawl_id: str, chunks: Iterable[KnowledgeChunk], embedder: EmbeddingProvider | None = None) -> None:
        """Replace one crawl's local lexical and vector indexes atomically via the decoupled pipeline."""
        self.index_knowledge_pipeline(crawl_id, chunks, embedder=embedder, force_reembed=True)

    def retry_failed_embeddings(
        self,
        crawl_id: str,
        embedder: EmbeddingProvider | None = None,
    ) -> dict[str, Any]:
        """Retry embedding for failed chunks without recrawling or re-embedding successful chunks."""
        active_embedder = embedder or HashEmbeddingProvider()
        active_model = getattr(active_embedder, "model_name", active_embedder.name)
        active_prov = getattr(active_embedder, "name", "hash")
        active_dim = getattr(active_embedder, "dimension", 0)

        with self.connect() as conn:
            failed_rows = conn.execute(
                """SELECT f.chunk_id, k.content, k.content_hash, f.attempt_count
                   FROM failed_embedding_chunks f
                   JOIN knowledge_chunks k ON k.id = f.chunk_id
                   WHERE f.crawl_id = ? AND f.retryable = 1
                   ORDER BY f.chunk_id""",
                (crawl_id,),
            ).fetchall()

        if not failed_rows:
            return {
                "crawl_id": crawl_id,
                "retried": 0,
                "succeeded": 0,
                "failed": 0,
                "status": "no_failed_chunks",
            }

        self.update_pipeline_stage(
            crawl_id, PipelineStage.EMBEDDING, StageStatus.RUNNING,
            provider=active_prov, model=active_model, dimension=active_dim,
        )
        self.update_pipeline_stage(
            crawl_id, PipelineStage.INDEXING, StageStatus.RUNNING,
            provider=active_prov, model=active_model, dimension=active_dim,
        )

        succeeded_count = 0
        still_failed_count = 0
        last_error = ""
        batch_size = max(1, getattr(active_embedder, "batch_size", 100))

        for i in range(0, len(failed_rows), batch_size):
            batch = failed_rows[i : i + batch_size]
            texts = [r["content"] for r in batch]
            try:
                embeddings = active_embedder.embed_batch(texts, task_type="RETRIEVAL_DOCUMENT")
                vector_rows = []
                retry_now = now()
                for r, vec in zip(batch, embeddings):
                    if vec:
                        emb_arr = array("f", vec)
                        meta_dict = {
                            "provider": active_prov,
                            "model": active_model,
                            "dimension": len(emb_arr),
                            "created_at": retry_now,
                            "task_type": "RETRIEVAL_DOCUMENT",
                            "retried": True,
                        }
                        vector_rows.append((
                            r["chunk_id"], crawl_id, active_prov, active_model,
                            len(emb_arr), emb_arr.tobytes(), retry_now, r["content_hash"], json.dumps(meta_dict)
                        ))

                if vector_rows:
                    with self.connect() as conn:
                        conn.executemany(
                            """INSERT OR REPLACE INTO vector_embeddings (
                                   chunk_id, crawl_id, provider, model, dimension, embedding, created_at, content_hash, metadata_json
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            vector_rows,
                        )
                        c_ids = [r[0] for r in vector_rows]
                        placeholders = ",".join("?" for _ in c_ids)
                        conn.execute(
                            f"DELETE FROM failed_embedding_chunks WHERE crawl_id = ? AND chunk_id IN ({placeholders})",
                            (crawl_id, *c_ids),
                        )
                    succeeded_count += len(vector_rows)
            except Exception as retry_exc:
                last_error = f"{type(retry_exc).__name__}: {retry_exc}"
                err_lower = str(retry_exc).lower()
                non_retryable = any(s in err_lower for s in ["400", "401", "403", "invalid api key", "invalid_api_key", "dimension mismatch", "unauthorized", "bad request"])
                is_retryable = not non_retryable if getattr(retry_exc, "retryable", None) is None else bool(getattr(retry_exc, "retryable", False))
                still_failed_count += len(batch)
                retry_fail_now = now()
                with self.connect() as conn:
                    for r in batch:
                        conn.execute(
                            """UPDATE failed_embedding_chunks SET
                                   attempt_count = attempt_count + 1,
                                   last_error = ?,
                                   retryable = ?,
                                   failed_at = ?
                               WHERE crawl_id = ? AND chunk_id = ?""",
                            (last_error, int(is_retryable), retry_fail_now, crawl_id, r["chunk_id"]),
                        )

        with self.connect() as conn:
            rem_failed = conn.execute(
                "SELECT COUNT(*) as count FROM failed_embedding_chunks WHERE crawl_id = ?",
                (crawl_id,),
            ).fetchone()
            vec_count = conn.execute(
                "SELECT COUNT(*) as count FROM vector_embeddings WHERE crawl_id = ?",
                (crawl_id,),
            ).fetchone()
            total_k = conn.execute(
                "SELECT COUNT(*) as count FROM knowledge_chunks WHERE crawl_id = ?",
                (crawl_id,),
            ).fetchone()

        remaining_failed = int(rem_failed["count"]) if rem_failed else 0
        total_items = int(total_k["count"]) if total_k else 0
        successful_items = int(vec_count["count"]) if vec_count else 0

        retry_finish_now = now()
        if remaining_failed == 0:
            final_status = StageStatus.SUCCESS
            self.update_pipeline_stage(
                crawl_id, PipelineStage.EMBEDDING, final_status,
                provider=active_prov, model=active_model, dimension=active_dim,
                total_items=total_items, successful_items=successful_items,
                failed_items=0, pending_items=0, completed_at=retry_finish_now,
            )
            self.update_pipeline_stage(
                crawl_id, PipelineStage.INDEXING, final_status,
                provider=active_prov, model=active_model, dimension=active_dim,
                total_items=total_items, successful_items=successful_items,
                failed_items=0, pending_items=0, completed_at=retry_finish_now,
            )
            self.update_pipeline_stage(
                crawl_id, PipelineStage.RAG, StageStatus.SUCCESS,
                provider=active_prov, model=active_model, dimension=active_dim,
                metadata={"ready": True, "hybrid": True},
                completed_at=retry_finish_now,
            )
            self.update_crawl(crawl_id, pause_reason="")
        else:
            final_status = StageStatus.PARTIAL if successful_items > 0 else StageStatus.FAILED
            self.update_pipeline_stage(
                crawl_id, PipelineStage.EMBEDDING, final_status,
                provider=active_prov, model=active_model, dimension=active_dim,
                total_items=total_items, successful_items=successful_items,
                failed_items=remaining_failed, pending_items=remaining_failed,
                error_message=last_error, retryable=True,
                completed_at=retry_finish_now,
            )
            self.update_pipeline_stage(
                crawl_id, PipelineStage.INDEXING, final_status,
                provider=active_prov, model=active_model, dimension=active_dim,
                total_items=total_items, successful_items=successful_items,
                failed_items=remaining_failed, pending_items=remaining_failed,
                error_message=last_error, retryable=True,
                completed_at=retry_finish_now,
            )

        return {
            "crawl_id": crawl_id,
            "retried": len(failed_rows),
            "succeeded": succeeded_count,
            "failed": still_failed_count,
            "remaining_failed": remaining_failed,
            "status": final_status.value,
        }

    def reembed_knowledge(self, crawl_id: str, embedder: EmbeddingProvider) -> dict[str, Any]:
        """Re-embed an existing crawl's knowledge chunks with a new model/provider without recrawling or modifying source content."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id, content, content_hash FROM knowledge_chunks WHERE crawl_id = ? ORDER BY id""",
                (crawl_id,),
            ).fetchall()

        if not rows:
            return {
                "chunks_embedded": 0,
                "provider": embedder.name,
                "model": getattr(embedder, "model_name", embedder.name),
                "dimension": getattr(embedder, "dimension", 0),
            }

        active_model = getattr(embedder, "model_name", embedder.name)
        active_prov = getattr(embedder, "name", "hash")
        now_ts = now()
        texts = [r["content"] for r in rows]

        try:
            embeddings = embedder.embed_batch(texts, task_type="RETRIEVAL_DOCUMENT")
        except Exception:
            embeddings = [embedder.embed(t, task_type="RETRIEVAL_DOCUMENT") for t in texts]

        vector_rows = []
        for r, vec in zip(rows, embeddings):
            if vec:
                emb_arr = array("f", vec)
                meta_dict = {
                    "provider": active_prov,
                    "model": active_model,
                    "dimension": len(emb_arr),
                    "created_at": now_ts,
                    "task_type": "RETRIEVAL_DOCUMENT",
                    "reembedded": True,
                }
                vector_rows.append((
                    r["id"], crawl_id, active_prov, active_model,
                    len(emb_arr), emb_arr.tobytes(), now_ts, r["content_hash"], json.dumps(meta_dict)
                ))

        with self.connect() as conn:
            conn.execute("DELETE FROM failed_embedding_chunks WHERE crawl_id = ?", (crawl_id,))
            conn.executemany(
                """INSERT OR REPLACE INTO vector_embeddings (
                       chunk_id, crawl_id, provider, model, dimension, embedding, created_at, content_hash, metadata_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                vector_rows,
            )

        self.update_pipeline_stage(
            crawl_id, PipelineStage.EMBEDDING, StageStatus.SUCCESS,
            provider=active_prov, model=active_model, dimension=embedder.dimension,
            total_items=len(rows), successful_items=len(vector_rows),
            failed_items=0, pending_items=0, completed_at=now_ts,
        )
        self.update_pipeline_stage(
            crawl_id, PipelineStage.INDEXING, StageStatus.SUCCESS,
            provider=active_prov, model=active_model, dimension=embedder.dimension,
            total_items=len(rows), successful_items=len(vector_rows),
            failed_items=0, pending_items=0, completed_at=now_ts,
        )
        self.update_pipeline_stage(
            crawl_id, PipelineStage.RAG, StageStatus.SUCCESS,
            provider=active_prov, model=active_model, dimension=embedder.dimension,
            metadata={"ready": True, "hybrid": True},
            completed_at=now_ts,
        )
        self.update_crawl(crawl_id, pause_reason="")

        return {
            "chunks_embedded": len(vector_rows),
            "provider": embedder.name,
            "model": active_model,
            "dimension": embedder.dimension,
            "reembedded_at": now_ts,
        }

    def get_vector_embeddings_metadata(self, crawl_id: str) -> list[dict[str, Any]]:
        """Retrieve distinct vector embedding generations and their metadata for a crawl."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT provider, model, dimension, COUNT(*) as chunk_count, MAX(created_at) as latest_created_at
                   FROM vector_embeddings WHERE crawl_id = ?
                   GROUP BY provider, model, dimension""",
                (crawl_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_knowledge_chunks(self, crawl_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id, page_id, crawl_id, url, canonical_url, title, section,
                          heading_path, heading_path_json, content_type, source_type,
                          crawl_timestamp, parent_url, depth, content_hash, content, chunk_index
                   FROM knowledge_chunks WHERE crawl_id = ? ORDER BY url, chunk_index""",
                (crawl_id,),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if "heading_path_json" in item and item["heading_path_json"]:
                try:
                    item["heading_path_list"] = json.loads(item["heading_path_json"])
                except Exception:
                    item["heading_path_list"] = [item.get("heading_path", "")]
            results.append(item)
        return results


    def knowledge_count(self, crawl_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM knowledge_chunks WHERE crawl_id = ?", (crawl_id,)).fetchone()
        return int(row["count"]) if row else 0

    def save_workflow(self, workflow_id: str, name: str, definition_json: str, active: bool = False) -> None:
        timestamp = now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO workflows (id, name, definition_json, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, definition_json=excluded.definition_json,
                   active=excluded.active, updated_at=excluded.updated_at""",
                (workflow_id, name, definition_json, int(active), timestamp, timestamp),
            )

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["active"] = bool(result["active"])
        result["definition"] = json.loads(result.pop("definition_json"))
        return result

    def list_workflows(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
        return [self.get_workflow(str(row["id"])) for row in rows if row]

    def create_workflow_run(self, workflow_id: str, input_data: dict[str, Any]) -> str:
        run_id = str(uuid4())
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO workflow_runs (id, workflow_id, created_at, status, input_json) VALUES (?, ?, ?, 'running', ?)",
                (run_id, workflow_id, now(), json.dumps(input_data)),
            )
        return run_id

    def finish_workflow_run(self, run_id: str, status: str, result: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE workflow_runs SET completed_at = ?, status = ?, result_json = ?, error_message = ? WHERE id = ?",
                (now(), status, json.dumps(result), str(result.get("error", "")), run_id),
            )

    def list_workflow_runs(self, workflow_id: str, limit: int = 20) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM workflow_runs WHERE workflow_id = ? ORDER BY created_at DESC LIMIT ?", (workflow_id, bounded_limit)).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["input"] = json.loads(item.pop("input_json"))
            item["result"] = json.loads(item.pop("result_json"))
            result.append(item)
        return result

    def readonly_query(self, sql: str, params: list[Any] | tuple[Any, ...] | None = None, limit: int = 100) -> list[dict[str, Any]]:
        statement = sql.strip()
        if not re.match(r"^(SELECT|WITH)\b", statement, re.IGNORECASE) or ";" in statement or re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|ATTACH|DETACH|CREATE|REPLACE|PRAGMA|VACUUM)\b", statement, re.IGNORECASE):
            raise ValueError("Only one read-only SELECT or WITH query is allowed.")
        bounded_limit = max(1, min(int(limit), 500))
        with self.connect() as conn:
            rows = conn.execute(f"SELECT * FROM ({statement}) LIMIT ?", tuple(params or ()) + (bounded_limit,)).fetchall()
        return [dict(row) for row in rows]

    def vector_count(self, crawl_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM vector_embeddings WHERE crawl_id = ?", (crawl_id,)).fetchone()
        return int(row["count"]) if row else 0

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        stop_words = {
            "what", "which", "where", "when", "does", "this", "that", "the", "and",
            "for", "from", "with", "about", "are", "is", "how", "can", "tell",
            "please", "who", "was", "were", "will", "would", "could", "should",
            "has", "have", "had", "into", "your", "our", "their", "get", "got",
            "gets", "do", "did", "doing", "done", "i", "me", "my", "we", "us",
            "you", "yours", "they", "them", "he", "him", "his", "she", "her",
            "it", "its", "or", "so", "if", "as", "by", "at", "an", "a", "all",
            "any", "some", "be", "been", "being", "on", "to", "in", "of", "per",
            "across", "between", "over", "under", "via"
        }
        terms = [term for term in re.findall(r"[\w][\w'-]{1,}", query.lower()) if term not in stop_words]
        return list(dict.fromkeys(terms[:16]))

    @staticmethod
    def _coverage(item: dict[str, Any], terms: list[str]) -> float:
        if not terms:
            return 0.0
        haystack = " ".join(str(item.get(key, "")) for key in ("title", "heading_path", "content")).lower()
        matched = 0
        for term in terms:
            parts = [p for p in re.findall(r"[a-zA-Z0-9_]+", term) if len(p) >= 2]
            stem = term.rstrip("s") if len(term) > 3 else term
            synonyms = _QUERY_SYNONYMS.get(term, [])
            if (
                re.search(rf"(?<![\w'-]){re.escape(term)}(?![\w'-])", haystack)
                or (stem and re.search(rf"(?<![\w'-]){re.escape(stem)}", haystack))
                or (parts and all(re.search(rf"(?<![\w'-]){re.escape(p)}", haystack) for p in parts))
                or (synonyms and any(re.search(rf"(?<![\w'-]){re.escape(syn)}", haystack) for syn in synonyms))
            ):
                matched += 1
        return matched / len(terms)

    def search_hybrid_knowledge(
        self,
        crawl_id: str,
        query: str,
        limit: int = 6,
        embedder: EmbeddingProvider | None = None,
        query_type: str = "general",
        ablation_mode: str = "full",
    ) -> list[dict[str, Any]]:
        """Fuse FTS5 BM25 and dense vector retrieval with query-adaptive RRF, reranking, and ablation modes."""
        lexical = self.search_knowledge(crawl_id, query, max(limit * 4, 16))
        lexical_rank = {int(item["id"]): position for position, item in enumerate(lexical, start=1)}
        query_terms = self._query_terms(query)
        clean_query = " ".join(query.lower().split())
        active_embedder = embedder or HashEmbeddingProvider()
        query_vector = active_embedder.embed(query, task_type="RETRIEVAL_QUERY")

        # 1. Lexical-only ablation
        if ablation_mode == "lexical_only":
            selected = []
            for item in lexical[:limit]:
                enriched = dict(
                    item,
                    hybrid_score=round(float(item.get("rank", 0.0)), 4),
                    term_coverage=round(self._coverage(item, query_terms), 2),
                    retrieval_mode="lexical_only",
                    semantic_first=False,
                    semantic_score=0.0,
                    lexical_match=True,
                )
                selected.append(enriched)
            return selected

        active_model = getattr(active_embedder, "model_name", active_embedder.name)
        active_prov = getattr(active_embedder, "provider_type", active_embedder.name)
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT k.id, k.page_id, k.crawl_id, k.url, k.canonical_url, k.title, k.section,
                          k.heading_path, k.heading_path_json, k.content_type, k.source_type,
                          k.crawl_timestamp, k.parent_url, k.depth, k.content_hash, k.content, k.chunk_index,
                          v.embedding
                   FROM vector_embeddings v JOIN knowledge_chunks k ON k.id = v.chunk_id
                   WHERE v.crawl_id = ? AND (v.provider = ? OR v.provider = ?) AND (v.model = ? OR ? = '' OR v.model = '') AND v.dimension = ?""",
                (crawl_id, active_prov, active_embedder.name, active_model, active_model, len(query_vector)),
            ).fetchall()
        vector_candidates = []
        for row in rows:
            similarity = cosine_similarity(query_vector, array("f", row["embedding"]))
            if active_embedder.name == "hash":
                continue
            if similarity < 0.35:
                continue
            item = dict(row)
            item.pop("embedding", None)
            if "heading_path_json" in item and item["heading_path_json"]:
                try:
                    item["heading_path_list"] = json.loads(item["heading_path_json"])
                except Exception:
                    item["heading_path_list"] = [item.get("heading_path", "")]
            item["vector_similarity"] = similarity
            vector_candidates.append((item, similarity))
        vector_ranked = sorted(vector_candidates, key=lambda item: item[1], reverse=True)
        vector_rank = {int(item[0]["id"]): position for position, item in enumerate(vector_ranked, start=1)}

        # 2. Vector-only ablation
        if ablation_mode == "vector_only":
            selected = []
            for item, sim in vector_ranked[:limit]:
                enriched = dict(
                    item,
                    hybrid_score=round(sim, 4),
                    term_coverage=round(self._coverage(item, query_terms), 2),
                    retrieval_mode="vector_only",
                    semantic_first=True,
                    semantic_score=sim,
                    lexical_match=int(item["id"]) in lexical_rank,
                )
                selected.append(enriched)
            return selected

        # 3. Exact-only ablation
        if ablation_mode == "exact_only":
            selected = []
            for item in lexical:
                content_lower = str(item.get("content", "")).lower()
                title_lower = str(item.get("title", "")).lower()
                if clean_query and (clean_query in content_lower or clean_query in title_lower):
                    enriched = dict(
                        item,
                        hybrid_score=1.0,
                        term_coverage=1.0,
                        retrieval_mode="exact_only",
                        semantic_first=False,
                        semantic_score=0.0,
                        lexical_match=True,
                    )
                    selected.append(enriched)
                    if len(selected) >= limit:
                        break
            return selected

        candidates = {int(item["id"]): item for item in lexical}
        candidates.update({int(item[0]["id"]): item[0] for item in vector_ranked})

        # Adaptive RRF weights based on query type
        if query_type in {"exact_phrase", "identifier_lookup"}:
            w_lex, w_vec = 0.85, 0.15
        elif query_type in {"numerical_structured", "numerical_query"}:
            w_lex, w_vec = 0.55, 0.45
        else:
            w_lex, w_vec = 0.35, 0.65

        scored = []
        for chunk_id, item in candidates.items():
            coverage = self._coverage(item, query_terms)
            vector_similarity = float(item.get("vector_similarity", 0.0))
            if coverage <= 0 and vector_similarity < 0.35 and chunk_id not in lexical_rank:
                continue

            # Reciprocal Rank Fusion component
            lex_rrf = (1.0 / (60 + lexical_rank[chunk_id])) if chunk_id in lexical_rank else 0.0
            vec_rrf = (1.0 / (60 + vector_rank[chunk_id])) if chunk_id in vector_rank else 0.0
            rrf_score = (w_lex * lex_rrf) + (w_vec * vec_rrf)

            if ablation_mode == "hybrid_raw":
                total_score = rrf_score * 40.0
                scored.append((total_score, coverage, item))
                continue

            # Exact phrase match bonus and identifier boost
            content_lower = item.get("content", "").lower()
            title_lower = item.get("title", "").lower()
            phrase_bonus = 0.0
            if clean_query and (clean_query in content_lower or clean_query in title_lower):
                phrase_bonus = 0.35
            for term in query_terms:
                if len(term) >= 4 and (term in content_lower or term in title_lower):
                    if re.search(r"^[a-z0-9]+[._-][a-z0-9._-]+$", term):
                        phrase_bonus += 0.25

            if ablation_mode == "hybrid_rerank":
                total_score = (rrf_score * 40.0) + (coverage * 0.25) + (vector_similarity * 0.25) + phrase_bonus
                scored.append((total_score, coverage, item))
                continue

            # Full mode includes metadata: source quality, structured bonus, heading relevance
            src_type = item.get("source_type", "html_page")
            source_bonus = 0.0
            if src_type == "official_api":
                source_bonus = 0.12
            elif src_type == "documentation":
                source_bonus = 0.10
            elif src_type == "landing_page":
                source_bonus = 0.04

            # Structured/numerical content bonus for numerical queries
            structured_bonus = 0.0
            if query_type in {"numerical_structured", "numerical_query"} and ("field =" in content_lower or re.search(r"\b\d+\b", content_lower)):
                structured_bonus = 0.15

            # Heading path relevance
            heading_bonus = 0.0
            if any(term in item.get("heading_path", "").lower() for term in query_terms):
                heading_bonus = 0.08

            total_score = (rrf_score * 40.0) + (coverage * 0.25) + (vector_similarity * 0.25) + source_bonus + phrase_bonus + structured_bonus + heading_bonus
            scored.append((total_score, coverage, item))

        scored.sort(key=lambda x: (-x[0], -x[1], str(x[2].get("url", "")), int(x[2].get("chunk_index", 0))))

        # Source diversity: avoid more than 2 passages from same URL unless needed
        target_limit = max(1, min(limit, 20))
        selected = []
        per_url: dict[str, int] = {}
        for score, coverage, item in scored:
            u = str(item.get("url", ""))
            if ablation_mode in {"full", "hybrid_rerank_metadata"} and per_url.get(u, 0) >= 2 and len(selected) < target_limit and len(scored) > target_limit:
                continue
            per_url[u] = per_url.get(u, 0) + 1
            enriched = dict(
                item,
                hybrid_score=round(score, 4),
                term_coverage=round(coverage, 2),
                retrieval_mode="hybrid" if ablation_mode == "full" else ablation_mode,
                semantic_first=True,
                semantic_score=float(item.get("vector_similarity", 0.0)),
                lexical_match=item.get("id") in lexical_rank,
            )
            selected.append(enriched)
            if len(selected) >= target_limit:
                break
        return selected

    def search_knowledge(self, crawl_id: str, query: str, limit: int = 6) -> list[dict[str, Any]]:
        """Search only one crawl and return ranked passages with verifiable provenance."""
        terms = self._query_terms(query)
        expanded_terms = list(terms)
        for t in terms:
            stem = re.sub(r"(?:ation|tion|sion|ment|able|ible|ness|ity|ive|ize|ise|ing|ed|es|s)$", "", t)
            if len(stem) >= 3 and stem != t:
                expanded_terms.append(stem)
            if t in _QUERY_SYNONYMS:
                expanded_terms.extend(_QUERY_SYNONYMS[t])

        clean_terms: list[str] = []
        for term in expanded_terms:
            parts = [p for p in re.findall(r"[a-zA-Z0-9_]+", term) if len(p) >= 2]
            if parts:
                clean_terms.extend(parts)
            whole = re.sub(r"[^a-zA-Z0-9_]", "", term)
            if whole and whole not in clean_terms:
                clean_terms.append(whole)
        if not clean_terms:
            return []
        match_query = " OR ".join(f"{term}*" for term in list(dict.fromkeys(clean_terms))[:24])
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT k.id, k.page_id, k.crawl_id, k.url, k.canonical_url, k.title, k.section,
                          k.heading_path, k.heading_path_json, k.content_type, k.source_type,
                          k.crawl_timestamp, k.parent_url, k.depth, k.content_hash, k.content, k.chunk_index,
                          bm25(knowledge_fts) AS rank
                   FROM knowledge_fts f
                   JOIN knowledge_chunks k ON k.id = f.chunk_id
                   WHERE f.crawl_id = ? AND knowledge_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (crawl_id, match_query, max(1, min(limit, 30))),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if "heading_path_json" in item and item["heading_path_json"]:
                try:
                    item["heading_path_list"] = json.loads(item["heading_path_json"])
                except Exception:
                    item["heading_path_list"] = [item.get("heading_path", "")]
            coverage = self._coverage(item, terms)
            if coverage > 0:
                item["term_coverage"] = coverage
                results.append(item)
        results.sort(key=lambda item: (-float(item["term_coverage"]), float(item.get("rank", 0.0)), str(item.get("url", "")), int(item.get("chunk_index", 0))))
        return results

    def get_pages(self, crawl_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM pages WHERE crawl_id = ? ORDER BY url", (crawl_id,)).fetchall()
        return [self._page_row(row) for row in rows]

    def get_links(self, crawl_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM links WHERE crawl_id = ? ORDER BY source_url, target_url", (crawl_id,)).fetchall()
        return [dict(row) | {"is_internal": bool(row["is_internal"]), "nofollow": bool(row["nofollow"])} for row in rows]

    def get_issues(self, crawl_id: str) -> list[dict[str, Any]]:
        order = "CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, title, url"
        with self.connect() as conn:
            rows = conn.execute(f"SELECT * FROM issues WHERE crawl_id = ? ORDER BY {order}", (crawl_id,)).fetchall()
        return [dict(row) for row in rows]

    def _page_row(self, row: sqlite3.Row) -> dict[str, Any]:
        page = dict(row)
        for key in ("headings_json", "images_json", "structured_data_json", "api_entry_points_json", "redirects_json", "extracted_fields_json", "extraction_notes_json", "headers_json"):
            if key in page and page[key]:
                try:
                    page[key.removesuffix("_json")] = json.loads(page.pop(key))
                except Exception:
                    page[key.removesuffix("_json")] = {} if "dict" in key or "headers" in key or "fields" in key else []
            elif key in page:
                page.pop(key)
                page[key.removesuffix("_json")] = {} if "headers" in key or "fields" in key else []
        page["robots_allowed"] = bool(page["robots_allowed"])
        page["body_truncated"] = bool(page["body_truncated"])
        page["is_duplicate"] = bool(page.get("is_duplicate", 0))
        page["escalated"] = bool(page.get("escalated", 0))
        return page

    def save_page(self, crawl_id: str, page: PageRecord, links: list[LinkRecord] | None = None) -> None:
        """Atomically upsert a single page and its outgoing links incrementally."""
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO pages (crawl_id, url, final_url, status_code, content_type, title, description, headings_json,
                   canonical, meta_robots, x_robots, source_html, rendered_html, rendered_text, extracted_text, extraction_error, extracted_fields_json, extraction_notes_json, images_json, structured_data_json, api_entry_points_json,
                   redirects_json, fetch_error, render_error, robots_allowed, body_truncated, discovered_at, internal_inlinks, content_hash,
                   etag, last_modified, is_duplicate, duplicate_of, source_type, depth, parent_url,
                   normalized_url, fetch_strategy, crawler_engine, response_bytes, duration_ms, error_category, headers_json,
                   requested_fetch_strategy, actual_fetch_strategy, escalated, escalation_reason, fetch_duration_ms, render_duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(crawl_id, url) DO UPDATE SET
                   final_url=excluded.final_url, status_code=excluded.status_code, content_type=excluded.content_type,
                   title=excluded.title, description=excluded.description, headings_json=excluded.headings_json,
                   canonical=excluded.canonical, meta_robots=excluded.meta_robots, x_robots=excluded.x_robots,
                   source_html=excluded.source_html, rendered_html=excluded.rendered_html, rendered_text=excluded.rendered_text,
                   extracted_text=excluded.extracted_text, extraction_error=excluded.extraction_error,
                   extracted_fields_json=excluded.extracted_fields_json, extraction_notes_json=excluded.extraction_notes_json,
                   images_json=excluded.images_json, structured_data_json=excluded.structured_data_json,
                   api_entry_points_json=excluded.api_entry_points_json, redirects_json=excluded.redirects_json,
                   fetch_error=excluded.fetch_error, render_error=excluded.render_error, robots_allowed=excluded.robots_allowed,
                   body_truncated=excluded.body_truncated, internal_inlinks=excluded.internal_inlinks,
                   content_hash=excluded.content_hash, etag=excluded.etag, last_modified=excluded.last_modified,
                   is_duplicate=excluded.is_duplicate, duplicate_of=excluded.duplicate_of, source_type=excluded.source_type,
                   depth=excluded.depth, parent_url=excluded.parent_url, normalized_url=excluded.normalized_url,
                   fetch_strategy=excluded.fetch_strategy, crawler_engine=excluded.crawler_engine,
                   response_bytes=excluded.response_bytes, duration_ms=excluded.duration_ms,
                   error_category=excluded.error_category, headers_json=excluded.headers_json,
                   requested_fetch_strategy=excluded.requested_fetch_strategy,
                   actual_fetch_strategy=excluded.actual_fetch_strategy, escalated=excluded.escalated,
                   escalation_reason=excluded.escalation_reason, fetch_duration_ms=excluded.fetch_duration_ms,
                   render_duration_ms=excluded.render_duration_ms""",
                (
                    crawl_id, page.url, page.final_url, page.status_code, page.content_type, page.title, page.description,
                    json.dumps(page.headings), page.canonical, page.meta_robots, page.x_robots, page.source_html,
                    page.rendered_html, page.rendered_text, page.extracted_text, page.extraction_error, json.dumps(page.extracted_fields), json.dumps(page.extraction_notes), json.dumps(page.images), json.dumps(page.structured_data), json.dumps(page.api_entry_points),
                    json.dumps(page.redirect_chain), page.fetch_error, page.render_error, int(page.robots_allowed),
                    int(page.body_truncated), page.discovered_at, page.internal_inlinks, page.content_hash,
                    getattr(page, "etag", ""), getattr(page, "last_modified", ""),
                    int(getattr(page, "is_duplicate", False)), getattr(page, "duplicate_of", ""),
                    getattr(page, "source_type", "html_page"), getattr(page, "depth", 0), getattr(page, "parent_url", ""),
                    getattr(page, "normalized_url", page.final_url or page.url),
                    getattr(page, "fetch_strategy", "static"),
                    getattr(page, "crawler_engine", "serial"),
                    getattr(page, "response_bytes", 0),
                    getattr(page, "duration_ms", 0.0),
                    getattr(page, "error_category", "none"),
                    json.dumps(getattr(page, "headers", {})),
                    getattr(page, "requested_fetch_strategy", getattr(page, "fetch_strategy", "static")),
                    getattr(page, "actual_fetch_strategy", getattr(page, "fetch_strategy", "static")),
                    int(getattr(page, "escalated", False)),
                    getattr(page, "escalation_reason", ""),
                    getattr(page, "fetch_duration_ms", getattr(page, "duration_ms", 0.0)),
                    getattr(page, "render_duration_ms", 0.0),
                ),
            )
            if links:
                conn.executemany(
                    """INSERT INTO links (crawl_id, source_url, target_url, raw_target_url, anchor_text, rel, is_internal, nofollow)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(crawl_id, source_url, target_url) DO UPDATE SET
                       raw_target_url=excluded.raw_target_url, anchor_text=excluded.anchor_text,
                       rel=excluded.rel, is_internal=excluded.is_internal, nofollow=excluded.nofollow""",
                    [
                        (crawl_id, link.source_url, link.target_url, link.raw_target_url, link.anchor_text, link.rel,
                         int(link.is_internal), int(link.nofollow)) for link in links
                    ],
                )

    def save_frontier_checkpoint(
        self,
        crawl_id: str,
        frontier: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Atomically persist complete frontier state and metadata in a single transaction."""
        meta = dict(metadata or {})
        if hasattr(frontier, "export_state"):
            exported = frontier.export_state()
            entries = exported.get("entries", [])
            combined_meta = {
                "admitted_count": exported.get("admitted_count", 0),
                "retry_count": exported.get("retry_count", 0),
                "seen_canonicals": exported.get("seen_canonicals", {}),
                "alias_map": exported.get("alias_map", {}),
                "allowed_domains": exported.get("allowed_domains", []),
                "queue": exported.get("queue", []),
                "saved_at": now(),
            }
            combined_meta.update(meta)
        else:
            entries = [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in getattr(frontier, "get_entries", lambda: [])()]
            combined_meta = {"saved_at": now()} | meta

        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM crawl_frontier_checkpoints WHERE crawl_id = ?", (crawl_id,))
            conn.executemany(
                """INSERT INTO crawl_frontier_checkpoints (
                       crawl_id, url, depth, parent_url, state, discovered_at,
                       retry_count, max_retries, next_eligible_time, error,
                       skip_reason, duplicate_of, status_code
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        crawl_id,
                        e["url"],
                        e.get("depth", 0),
                        e.get("parent_url", ""),
                        e.get("state", "queued"),
                        e.get("discovered_at", ""),
                        e.get("retry_count", 0),
                        e.get("max_retries", 3),
                        e.get("next_eligible_time", 0.0),
                        e.get("error", ""),
                        e.get("skip_reason", ""),
                        e.get("duplicate_of", ""),
                        e.get("status_code"),
                    )
                    for e in entries
                ],
            )
            conn.execute(
                "UPDATE crawls SET checkpoint_json = ?, last_attempt_at = ? WHERE id = ?",
                (json.dumps(combined_meta), now(), crawl_id),
            )

    def validate_checkpoint_compatibility(self, crawl_id: str) -> tuple[bool, str]:
        """Validate that a saved crawl checkpoint is compatible with current engine and schema."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT schema_version, engine_version, checkpoint_json FROM crawls WHERE id = ?",
                (crawl_id,),
            ).fetchone()
            if not row:
                raise CorruptStateError(f"Crawl {crawl_id} not found in database.")

            schema_version = int(row["schema_version"] or 1)
            if schema_version > CURRENT_SCHEMA_VERSION:
                raise IncompatibleStateError(
                    f"Checkpoint schema version {schema_version} is incompatible with engine supported version {CURRENT_SCHEMA_VERSION}."
                )

            engine_ver = str(row["engine_version"] or "1.0.0")
            try:
                major_ver = int(engine_ver.split(".")[0])
                current_major = int(CURRENT_ENGINE_VERSION.split(".")[0])
                if major_ver > current_major:
                    raise IncompatibleStateError(
                        f"Checkpoint engine version {engine_ver} is newer than current engine {CURRENT_ENGINE_VERSION}."
                    )
            except ValueError:
                pass

            checkpoint_raw = row["checkpoint_json"]
            if checkpoint_raw and checkpoint_raw != "{}":
                try:
                    json.loads(checkpoint_raw)
                except Exception as err:
                    raise CorruptStateError(f"Corrupt checkpoint JSON in crawl {crawl_id}: {err}") from err

            return True, "compatible"

    def get_frontier_checkpoint(self, crawl_id: str) -> tuple[list[FrontierEntry], dict[str, Any]] | None:
        """Retrieve persisted frontier entries and checkpoint metadata.

        Raises CorruptStateError if persisted records or JSON are corrupted.
        Raises IncompatibleStateError if schema/engine version is incompatible.
        """
        self.validate_checkpoint_compatibility(crawl_id)
        with self.connect() as conn:
            crawl_row = conn.execute("SELECT checkpoint_json FROM crawls WHERE id = ?", (crawl_id,)).fetchone()
            if not crawl_row or not crawl_row["checkpoint_json"] or crawl_row["checkpoint_json"] == "{}":
                return None
            try:
                meta = json.loads(crawl_row["checkpoint_json"])
            except Exception as e:
                raise CorruptStateError(f"Corrupt checkpoint metadata JSON for crawl {crawl_id}: {e}") from e

            rows = conn.execute(
                """SELECT url, depth, parent_url, state, discovered_at, retry_count,
                          max_retries, next_eligible_time, error, skip_reason, duplicate_of, status_code
                   FROM crawl_frontier_checkpoints WHERE crawl_id = ? ORDER BY depth, rowid""",
                (crawl_id,),
            ).fetchall()

            entries: list[FrontierEntry] = []
            for r in rows:
                try:
                    entries.append(FrontierEntry.from_dict(dict(r)))
                except Exception as e:
                    raise CorruptStateError(f"Corrupt frontier checkpoint entry in crawl {crawl_id}: {e}") from e

            return entries, meta

    def get_crawled_pages(self, crawl_id: str) -> list[PageRecord]:
        """Reconstruct PageRecord instances from persistent database rows."""
        raw_pages = self.get_pages(crawl_id)
        pages: list[PageRecord] = []
        for p in raw_pages:
            pages.append(
                PageRecord(
                    url=p["url"],
                    final_url=p["final_url"],
                    status_code=p["status_code"],
                    content_type=p["content_type"],
                    title=p["title"],
                    description=p["description"],
                    headings=p.get("headings", []),
                    canonical=p.get("canonical", ""),
                    meta_robots=p.get("meta_robots", ""),
                    x_robots=p.get("x_robots", ""),
                    source_html=p.get("source_html", ""),
                    rendered_html=p.get("rendered_html", ""),
                    rendered_text=p.get("rendered_text", ""),
                    extracted_text=p.get("extracted_text", ""),
                    extraction_error=p.get("extraction_error", ""),
                    extracted_fields=p.get("extracted_fields", {}),
                    extraction_notes=p.get("extraction_notes", []),
                    images=p.get("images", []),
                    structured_data=p.get("structured_data", []),
                    api_entry_points=p.get("api_entry_points", []),
                    redirect_chain=p.get("redirects", []),
                    fetch_error=p.get("fetch_error", ""),
                    render_error=p.get("render_error", ""),
                    robots_allowed=bool(p.get("robots_allowed", True)),
                    body_truncated=bool(p.get("body_truncated", False)),
                    discovered_at=p.get("discovered_at", ""),
                    internal_inlinks=int(p.get("internal_inlinks", 0)),
                    content_hash=p.get("content_hash", ""),
                    etag=p.get("etag", ""),
                    last_modified=p.get("last_modified", ""),
                    is_duplicate=bool(p.get("is_duplicate", False)),
                    duplicate_of=p.get("duplicate_of", ""),
                    source_type=p.get("source_type", "html_page"),
                    depth=int(p.get("depth", 0)),
                    parent_url=p.get("parent_url", ""),
                    normalized_url=p.get("normalized_url", ""),
                    fetch_strategy=p.get("fetch_strategy", "static"),
                    crawler_engine=p.get("crawler_engine", "serial"),
                    response_bytes=int(p.get("response_bytes", 0)),
                    duration_ms=float(p.get("duration_ms", 0.0)),
                    error_category=p.get("error_category", "none"),
                    headers=p.get("headers", {}),
                    requested_fetch_strategy=p.get("requested_fetch_strategy", "static"),
                    actual_fetch_strategy=p.get("actual_fetch_strategy", "static"),
                    escalated=bool(p.get("escalated", False)),
                    escalation_reason=p.get("escalation_reason", ""),
                    fetch_duration_ms=float(p.get("fetch_duration_ms", 0.0)),
                    render_duration_ms=float(p.get("render_duration_ms", 0.0)),
                )
            )
        return pages

    def get_crawled_links(self, crawl_id: str) -> list[LinkRecord]:
        """Reconstruct LinkRecord instances from persistent database rows."""
        raw_links = self.get_links(crawl_id)
        links: list[LinkRecord] = []
        for l in raw_links:
            links.append(
                LinkRecord(
                    source_url=l["source_url"],
                    target_url=l["target_url"],
                    raw_target_url=l["raw_target_url"],
                    anchor_text=l["anchor_text"],
                    rel=l["rel"],
                    is_internal=bool(l["is_internal"]),
                    nofollow=bool(l["nofollow"]),
                )
            )
        return links


