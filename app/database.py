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
                  rendered_text TEXT NOT NULL, extracted_text TEXT NOT NULL DEFAULT '', extraction_error TEXT NOT NULL DEFAULT '', extracted_fields_json TEXT NOT NULL DEFAULT '{}', extraction_notes_json TEXT NOT NULL DEFAULT '[]', images_json TEXT NOT NULL, structured_data_json TEXT NOT NULL,
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
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                  crawl_id TEXT NOT NULL REFERENCES crawls(id) ON DELETE CASCADE, url TEXT NOT NULL, title TEXT NOT NULL,
                  heading_path TEXT NOT NULL, content TEXT NOT NULL, chunk_index INTEGER NOT NULL,
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
                """
            )
            self._ensure_crawl_columns(conn)
            self._ensure_page_columns(conn)

    @staticmethod
    def _ensure_page_columns(conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(pages)")}
        required = {"extracted_text": "TEXT NOT NULL DEFAULT ''", "extraction_error": "TEXT NOT NULL DEFAULT ''", "extracted_fields_json": "TEXT NOT NULL DEFAULT '{}'", "extraction_notes_json": "TEXT NOT NULL DEFAULT '[]'"}
        for name, definition in required.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE pages ADD COLUMN {name} {definition}")

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
                   canonical, meta_robots, x_robots, source_html, rendered_html, rendered_text, extracted_text, extraction_error, extracted_fields_json, extraction_notes_json, images_json, structured_data_json,
                   redirects_json, fetch_error, render_error, robots_allowed, body_truncated, discovered_at, internal_inlinks, content_hash)
                                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                [
                    (
                        crawl_id, page.url, page.final_url, page.status_code, page.content_type, page.title, page.description,
                        json.dumps(page.headings), page.canonical, page.meta_robots, page.x_robots, page.source_html,
                        page.rendered_html, page.rendered_text, page.extracted_text, page.extraction_error, json.dumps(page.extracted_fields), json.dumps(page.extraction_notes), json.dumps(page.images), json.dumps(page.structured_data),
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

    def replace_knowledge_chunks(self, crawl_id: str, chunks: Iterable[KnowledgeChunk], embedder: EmbeddingProvider | None = None) -> None:
        """Replace one crawl's local lexical and vector indexes atomically."""
        materialized = list(chunks)
        active_embedder = embedder or HashEmbeddingProvider()
        with self.connect() as conn:
            conn.execute("DELETE FROM knowledge_fts WHERE crawl_id = ?", (crawl_id,))
            conn.execute("DELETE FROM vector_embeddings WHERE crawl_id = ?", (crawl_id,))
            conn.execute("DELETE FROM knowledge_chunks WHERE crawl_id = ?", (crawl_id,))
            for chunk in materialized:
                cursor = conn.execute(
                    """INSERT INTO knowledge_chunks (page_id, crawl_id, url, title, heading_path, content, chunk_index)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    chunk.as_row(),
                )
                conn.execute(
                    """INSERT INTO knowledge_fts (chunk_id, crawl_id, url, title, heading_path, content)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (cursor.lastrowid, crawl_id, chunk.url, chunk.title, chunk.heading_path, chunk.content),
                )
                embedding = array("f", active_embedder.embed(chunk.content))
                conn.execute(
                    """INSERT INTO vector_embeddings (chunk_id, crawl_id, provider, dimension, embedding)
                       VALUES (?, ?, ?, ?, ?)""",
                    (cursor.lastrowid, crawl_id, active_embedder.name, len(embedding), embedding.tobytes()),
                )

    def get_knowledge_chunks(self, crawl_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, page_id, url, title, heading_path, content, chunk_index FROM knowledge_chunks WHERE crawl_id = ? ORDER BY url, chunk_index",
                (crawl_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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

    def search_hybrid_knowledge(self, crawl_id: str, query: str, limit: int = 6, embedder: EmbeddingProvider | None = None) -> list[dict[str, Any]]:
        """Fuse FTS5 and cosine retrieval using reciprocal-rank fusion."""
        lexical = self.search_knowledge(crawl_id, query, max(limit * 3, 12))
        lexical_rank = {int(item["id"]): position for position, item in enumerate(lexical, start=1)}
        active_embedder = embedder or HashEmbeddingProvider()
        query_vector = active_embedder.embed(query)
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT k.id, k.page_id, k.url, k.title, k.heading_path, k.content, v.embedding
                   FROM vector_embeddings v JOIN knowledge_chunks k ON k.id = v.chunk_id
                   WHERE v.crawl_id = ? AND v.dimension = ?""",
                (crawl_id, len(query_vector)),
            ).fetchall()
        vector_candidates = []
        for row in rows:
            similarity = cosine_similarity(query_vector, array("f", row["embedding"]))
            # Feature hashing is lexical, not semantic: do not let random hash collisions answer an unrelated question.
            if active_embedder.name == "hash" and not lexical:
                continue
            if active_embedder.name != "hash" and similarity < 0.35:
                continue
            item = dict(row)
            item.pop("embedding", None)
            item["vector_similarity"] = similarity
            vector_candidates.append((item, similarity))
        vector_ranked = sorted(vector_candidates, key=lambda item: item[1], reverse=True)
        vector_rank = {int(item[0]["id"]): position for position, item in enumerate(vector_ranked, start=1)}
        candidates = {int(item["id"]): item for item in lexical}
        candidates.update({int(item[0]["id"]): item[0] for item in vector_ranked})
        scored = []
        for chunk_id, item in candidates.items():
            score = (1 / (60 + lexical_rank[chunk_id]) if chunk_id in lexical_rank else 0) + (1 / (60 + vector_rank[chunk_id]) if chunk_id in vector_rank else 0)
            scored.append((score, item))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("url", "")), int(item[1].get("chunk_index", 0))))
        return [dict(item, hybrid_score=score, retrieval_mode="hybrid") for score, item in scored[: max(1, min(limit, 20))]]

    def search_knowledge(self, crawl_id: str, query: str, limit: int = 6) -> list[dict[str, Any]]:
        """Search only one crawl and return ranked passages with verifiable provenance."""
        stop_words = {"what", "which", "where", "when", "does", "this", "that", "the", "and", "for", "from", "with", "about", "does", "are", "is", "how", "can", "tell", "please"}
        terms = [term for term in re.findall(r"[\w][\w'-]{1,}", query.lower()) if term not in stop_words]
        if not terms:
            return []
        match_query = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms[:12])
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT k.id, k.page_id, k.url, k.title, k.heading_path, k.content,
                          bm25(knowledge_fts) AS rank
                   FROM knowledge_fts f
                   JOIN knowledge_chunks k ON k.id = f.chunk_id
                   WHERE f.crawl_id = ? AND knowledge_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (crawl_id, match_query, max(1, min(limit, 20))),
            ).fetchall()
        return [dict(row) for row in rows]

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
        for key in ("headings_json", "images_json", "structured_data_json", "redirects_json", "extracted_fields_json", "extraction_notes_json"):
            page[key.removesuffix("_json")] = json.loads(page.pop(key))
        page["robots_allowed"] = bool(page["robots_allowed"])
        page["body_truncated"] = bool(page["body_truncated"])
        return page
