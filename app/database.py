"""SQLite persistence for local crawl inputs, evidence, and reproducible results."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from app.types import CrawlRequest, IssueRecord, LinkRecord, PageRecord


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as conn:
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
                  rendered_text TEXT NOT NULL, images_json TEXT NOT NULL, structured_data_json TEXT NOT NULL,
                  redirects_json TEXT NOT NULL, fetch_error TEXT NOT NULL, render_error TEXT NOT NULL,
                  robots_allowed INTEGER NOT NULL, body_truncated INTEGER NOT NULL, discovered_at TEXT NOT NULL,
                  internal_inlinks INTEGER NOT NULL DEFAULT 0, content_hash TEXT NOT NULL
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
                """
            )
            self._ensure_crawl_columns(conn)

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
        }
        for name, definition in required.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE crawls ADD COLUMN {name} {definition}")

    def create_crawl(self, request: CrawlRequest) -> str:
        crawl_id = str(uuid4())
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO crawls (id, created_at, status, start_url, settings_json, request_json, ownership_ack, next_run_at)
                   VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)""",
                (crawl_id, now(), request.start_url, json.dumps(request.public_settings()), json.dumps(request.storage_payload()), int(request.acknowledgment), now()),
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
                   canonical, meta_robots, x_robots, source_html, rendered_html, rendered_text, images_json, structured_data_json,
                   redirects_json, fetch_error, render_error, robots_allowed, body_truncated, discovered_at, internal_inlinks, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        crawl_id, page.url, page.final_url, page.status_code, page.content_type, page.title, page.description,
                        json.dumps(page.headings), page.canonical, page.meta_robots, page.x_robots, page.source_html,
                        page.rendered_html, page.rendered_text, json.dumps(page.images), json.dumps(page.structured_data),
                        json.dumps(page.redirect_chain), page.fetch_error, page.render_error, int(page.robots_allowed),
                        int(page.body_truncated), page.discovered_at, page.internal_inlinks, page.content_hash,
                    ) for page in pages
                ],
            )
            conn.executemany(
                """INSERT INTO links (crawl_id, source_url, target_url, raw_target_url, anchor_text, rel, is_internal, nofollow)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
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
        for key in ("headings_json", "images_json", "structured_data_json", "redirects_json"):
            page[key.removesuffix("_json")] = json.loads(page.pop(key))
        page["robots_allowed"] = bool(page["robots_allowed"])
        page["body_truncated"] = bool(page["body_truncated"])
        return page
