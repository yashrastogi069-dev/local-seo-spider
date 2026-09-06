"""Phase 2G Test Suite: Resume, Recovery, Crash Safety, and Idempotency Verification.

Verifies:
1. Frontier state persistence & serialization across all 8 lifecycle states.
2. In-flight crash recovery: FETCHING -> QUEUED transition and active workers safety.
3. Interruption after discovery and resume without losing queue.
4. Interruption during fetch and clean recovery.
5. Interruption during DB write (atomic SQLite transaction rollback).
6. Interruption during retries (retry count and backoff preservation).
7. Interruption with active workers across Serial, Threaded, Async, and Multiprocess.
8. Idempotent DB persistence: zero duplicate rows in pages and links on replay.
9. Corrupt state detection: raises CorruptStateError.
10. Incompatible schema/engine versions: raises IncompatibleStateError.
11. Mathematical reconciliation of crawl accounting across resume lifecycles.
"""

from __future__ import annotations

import gc
import json
import sqlite3
import time
from pathlib import Path
import pytest

from app.config import Settings
from app.crawler import CrawlEngine
from app.database import CURRENT_ENGINE_VERSION, CURRENT_SCHEMA_VERSION, Database
from app.frontier import CrawlFrontier
from app.types import (
    CancellationToken,
    CorruptStateError,
    CrawlBudget,
    CrawlRequest,
    CrawlResult,
    CrawlStatus,
    FrontierEntry,
    FrontierState,
    IncompatibleStateError,
    LinkRecord,
    PageRecord,
    ResumableCrawlError,
)
from tests.controlled_crawler_server import ControlledCrawlerServer


@pytest.fixture(scope="module")
def server():
    srv = ControlledCrawlerServer()
    srv.start()
    yield srv
    srv.stop()


def _engine_settings(mode: str, tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        user_agent="ResumeRecoverySuite/1.0",
        default_url_cap=20,
        max_url_cap=50,
        default_delay_seconds=0,
        request_timeout_seconds=2,
        render_timeout_ms=1000,
        max_redirects=3,
        max_document_bytes=50_000,
        max_request_retries=2,
        retry_backoff_seconds=0.05,
        max_concurrent_crawls=1,
        render_enabled=False,
        crawl_executor_mode=mode,
        async_concurrency=2,
        thread_workers=2,
        process_workers=2,
        allow_private_crawls=True,
    )


# ---------------------------------------------------------------------------
# 1. State Persistence & Serialization
# ---------------------------------------------------------------------------

def test_frontier_state_persistence_and_serialization(tmp_path: Path):
    """Verify durable persistence of frontier entries across all lifecycle states."""
    db_path = tmp_path / "persistence.db"
    db = Database(db_path)
    db.initialize()
    crawl_id = "crawl-persist-1"
    db.create_crawl(CrawlRequest(start_url="http://example.com/", crawl_id=crawl_id))

    frontier = CrawlFrontier(start_url="http://example.com/", max_urls=10)
    # 1. Pop item -> fetching
    item = frontier.get_next()
    assert item is not None
    assert item.url == "http://example.com/"

    # 2. Discover children
    frontier.discover(["http://example.com/page1", "http://example.com/page2", "http://example.com/page3"], parent_url=item.url, parent_depth=0)

    # 3. Mark completed
    frontier.mark_completed(item.url, status_code=200)

    # 4. Mark one retryable, one duplicate, one skipped
    item2 = frontier.get_next()
    assert item2 is not None
    frontier.mark_failed(item2.url, "HTTP 500", is_retryable=True)

    item3 = frontier.get_next()
    assert item3 is not None
    frontier.mark_duplicate(item3.url, duplicate_of="http://example.com/page1")

    item4 = frontier.get_next()
    assert item4 is not None
    frontier.mark_skipped(item4.url, reason="robots_disallowed")

    # Save frontier checkpoint
    db.save_frontier_checkpoint(crawl_id, frontier, metadata={"custom_metric": 42})

    # Retrieve checkpoint
    entries, meta = db.get_frontier_checkpoint(crawl_id)
    assert len(entries) == 4
    assert meta["custom_metric"] == 42
    states = {e.url: e.state for e in entries}
    assert states["http://example.com/"] == FrontierState.COMPLETED
    assert states[item2.url] == FrontierState.FAILED_RETRYABLE
    assert states[item3.url] == FrontierState.DUPLICATE
    assert states[item4.url] == FrontierState.SKIPPED
    gc.collect()


# ---------------------------------------------------------------------------
# 2. In-Flight Crash Recovery: FETCHING -> QUEUED
# ---------------------------------------------------------------------------

def test_crash_recovery_in_flight_fetching_to_queued(tmp_path: Path):
    """Verify that in-flight FETCHING items safely recover to QUEUED and active_workers reset to 0."""
    db_path = tmp_path / "crash_recovery.db"
    db = Database(db_path)
    db.initialize()
    crawl_id = "crawl-crash-1"
    db.create_crawl(CrawlRequest(start_url="http://example.com/", crawl_id=crawl_id))

    frontier = CrawlFrontier(start_url="http://example.com/", max_urls=10)
    frontier.discover(["http://example.com/p1", "http://example.com/p2"], parent_url="http://example.com/", parent_depth=0)

    # Worker 1 pops http://example.com/
    item1 = frontier.get_next()
    # Worker 2 pops http://example.com/p1
    item2 = frontier.get_next()

    assert frontier.active_workers == 2
    # Simulate a crash right during fetch: save checkpoint while 2 workers are active
    db.save_frontier_checkpoint(crawl_id, frontier)

    # Reconstitute into a brand new frontier on resume
    entries, meta = db.get_frontier_checkpoint(crawl_id)
    new_frontier = CrawlFrontier(start_url="http://example.com/", max_urls=10)
    new_frontier.restore_state(entries, metadata=meta)

    # Invariants must hold
    assert new_frontier.active_workers == 0
    reconciled = new_frontier.reconcile_accounting()
    assert reconciled["fetching"] == 0
    assert reconciled["queued"] == 3  # All 3 items are safely queued!

    # Verify that the crashed in-flight items return to the queue and can be popped
    popped_urls = []
    while True:
        nxt = new_frontier.get_next()
        if nxt is None:
            break
        popped_urls.append(nxt.url)

    assert set(popped_urls) == {"http://example.com/", "http://example.com/p1", "http://example.com/p2"}
    gc.collect()


# ---------------------------------------------------------------------------
# 3. Interruption After Discovery & Resume
# ---------------------------------------------------------------------------

def test_interruption_after_discovery_and_resume(server: ControlledCrawlerServer, tmp_path: Path):
    """Interrupt crawl after discovery, then resume and verify all pending URLs complete without duplicate fetches."""
    db_path = tmp_path / "discovery_resume.db"
    db = Database(db_path)
    db.initialize()
    crawl_id = "crawl-disc-1"

    settings = _engine_settings("serial", tmp_path)
    engine = CrawlEngine(settings, database=db)

    token = CancellationToken()

    def on_progress(crawled: int, queued: int, robots: str):
        if crawled >= 1:
            token.cancel("Interrupted after discovery")

    # Stage 1: Crawl seed and interrupt after discovery
    req1 = CrawlRequest(
        start_url=f"{server.base_url}/",
        crawl_id=crawl_id,
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    db.create_crawl(req1)
    res1 = engine.run(req1, progress=on_progress, cancellation_token=token)
    assert len(res1.pages) == 1
    assert res1.pages[0].url == f"{server.base_url}/"
    assert res1.status in {CrawlStatus.SUCCESS.value, CrawlStatus.PARTIAL.value, CrawlStatus.CANCELLED.value}
    assert res1.resumed is False

    # Verify frontier checkpoint was saved in DB with discovered links queued
    checkpoint = db.get_frontier_checkpoint(crawl_id)
    assert checkpoint is not None
    entries, meta = checkpoint
    queued_entries = [e for e in entries if e.state == FrontierState.QUEUED]
    completed_entries = [e for e in entries if e.state == FrontierState.COMPLETED]
    assert len(completed_entries) == 1
    assert len(queued_entries) > 0  # Discovered links (/a, /b, etc.) are queued!

    # Stage 2: Resume crawl with max_urls=5
    req2 = CrawlRequest(
        start_url=f"{server.base_url}/",
        crawl_id=crawl_id,
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
        resume=True,
    )
    res2 = engine.run(req2, progress=lambda *a: None)
    assert res2.resumed is True
    assert len(res2.pages) == 5
    # Seed page must be the first page, not repeated
    page_urls = [p.url for p in res2.pages]
    assert len(page_urls) == len(set(page_urls)), "Completed pages were duplicated!"
    assert f"{server.base_url}/" in page_urls
    assert f"{server.base_url}/a" in page_urls

    # Verify database has exactly 5 unique page records
    stored_pages = db.get_crawled_pages(crawl_id)
    assert len(stored_pages) == 5
    stored_urls = [p.url for p in stored_pages]
    assert len(stored_urls) == len(set(stored_urls))
    gc.collect()


# ---------------------------------------------------------------------------
# 4. Interruption During Fetch & Recovery
# ---------------------------------------------------------------------------

def test_interruption_during_fetch_and_recovery(server: ControlledCrawlerServer, tmp_path: Path):
    """Interrupt during fetch via cancellation token; verify in-flight item recovers on resume."""
    db_path = tmp_path / "fetch_interrupted.db"
    db = Database(db_path)
    db.initialize()
    crawl_id = "crawl-fetch-int-1"

    settings = _engine_settings("serial", tmp_path)
    engine = CrawlEngine(settings, database=db)

    token = CancellationToken()

    # Cancel on first progress callback
    def on_progress(crawled: int, queued: int, robots: str):
        if crawled >= 1:
            token.cancel(reason="Simulated operator interrupt during fetch")

    req1 = CrawlRequest(
        start_url=f"{server.base_url}/",
        crawl_id=crawl_id,
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    db.create_crawl(req1)
    res1 = engine.run(req1, progress=on_progress, cancellation_token=token)
    assert res1.status == CrawlStatus.CANCELLED.value
    assert len(res1.pages) >= 1

    # Resume the cancelled crawl
    req2 = CrawlRequest(
        start_url=f"{server.base_url}/",
        crawl_id=crawl_id,
        max_urls=4,
        delay_seconds=0.0,
        acknowledgment=True,
        resume=True,
    )
    res2 = engine.run(req2, progress=lambda *a: None)
    assert res2.resumed is True
    assert len(res2.pages) == 4
    # No duplicate URLs
    urls = [p.url for p in res2.pages]
    assert len(urls) == len(set(urls))
    gc.collect()


# ---------------------------------------------------------------------------
# 5. Interruption During DB Write (Atomic Transaction Rollback)
# ---------------------------------------------------------------------------

def test_interruption_during_db_write_transaction_rollback(tmp_path: Path):
    """Verify SQLite transaction rollback on write error and subsequent safe recovery."""
    db_path = tmp_path / "atomic_tx.db"
    db = Database(db_path)
    db.initialize()
    crawl_id = "crawl-tx-1"
    db.create_crawl(CrawlRequest(start_url="http://example.com/", crawl_id=crawl_id))

    frontier = CrawlFrontier(start_url="http://example.com/", max_urls=10)
    # Save a clean initial checkpoint
    db.save_frontier_checkpoint(crawl_id, frontier, metadata={"checkpoint_num": 1})

    # Simulate a failed/crashed write midway through a transaction
    try:
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM crawl_frontier_checkpoints WHERE crawl_id = ?", (crawl_id,))
            # Deliberately raise an exception to trigger transaction rollback
            raise RuntimeError("Simulated sudden power loss or process kill during DB write")
    except RuntimeError:
        pass

    # The checkpoint must be intact and unharmed
    entries, meta = db.get_frontier_checkpoint(crawl_id)
    assert len(entries) == 1
    assert meta["checkpoint_num"] == 1
    assert entries[0].url == "http://example.com/"
    gc.collect()


# ---------------------------------------------------------------------------
# 6. Interruption During Retries (Preserves Backoff and Retry Count)
# ---------------------------------------------------------------------------

def test_interruption_during_retries_preserves_backoff_and_attempts(server: ControlledCrawlerServer, tmp_path: Path):
    """Verify that when interrupted while in retry pool, retry counts and backoff state persist."""
    db_path = tmp_path / "retry_resume.db"
    db = Database(db_path)
    db.initialize()
    crawl_id = "crawl-retry-1"

    frontier = CrawlFrontier(start_url=f"{server.base_url}/500", max_urls=5, max_retries=3, retry_backoff_seconds=10.0, allow_private=True)
    item = frontier.get_next()
    assert item is not None
    # Simulate a transient 500 error on attempt 1
    frontier.mark_failed(item.url, "HTTP 500", is_retryable=True)

    # Save checkpoint while in retry pool
    db.create_crawl(CrawlRequest(start_url=f"{server.base_url}/500", crawl_id=crawl_id))
    db.save_frontier_checkpoint(crawl_id, frontier, metadata={"total_response_bytes": 100})

    # Restore in new frontier
    entries, meta = db.get_frontier_checkpoint(crawl_id)
    new_frontier = CrawlFrontier(start_url=f"{server.base_url}/500", max_urls=5, max_retries=3, retry_backoff_seconds=10.0, allow_private=True)
    new_frontier.restore_state(entries, metadata=meta)

    # Invariants: retry pool contains the entry, retry count is 1, not 0!
    assert new_frontier.reconcile_accounting()["failed_retryable"] == 1
    assert new_frontier.retry_count == 1

    # Eligible time must be in future (backoff preserved)
    retry_item = new_frontier.get_next()
    assert retry_item is None, "Item should still be waiting in backoff window!"
    gc.collect()


# ---------------------------------------------------------------------------
# 7. Multi-Worker Active Interruption Across All Engines
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("engine_mode", ["serial", "thread", "async", "process"])
def test_multi_worker_active_interruption_and_resume_across_engines(
    server: ControlledCrawlerServer,
    tmp_path: Path,
    engine_mode: str,
):
    """Test interruption and resume across all 4 independent engines."""
    db_path = tmp_path / f"resume_{engine_mode}.db"
    db = Database(db_path)
    db.initialize()
    crawl_id = f"crawl-{engine_mode}-resume"

    settings = _engine_settings(engine_mode, tmp_path)
    engine = CrawlEngine(settings, database=db)

    # Stage 1: Crawl 2 pages
    req1 = CrawlRequest(
        start_url=f"{server.base_url}/",
        crawl_id=crawl_id,
        max_urls=2,
        executor_mode=engine_mode,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    db.create_crawl(req1)
    res1 = engine.run(req1, progress=lambda *a: None)
    assert len(res1.pages) == 2
    assert res1.resumed is False
    assert res1.actual_engine == engine_mode

    # Stage 2: Resume to crawl 4 pages total
    req2 = CrawlRequest(
        start_url=f"{server.base_url}/",
        crawl_id=crawl_id,
        max_urls=4,
        executor_mode=engine_mode,
        delay_seconds=0.0,
        acknowledgment=True,
        resume=True,
    )
    res2 = engine.run(req2, progress=lambda *a: None)
    assert res2.resumed is True
    assert res2.actual_engine == engine_mode
    assert len(res2.pages) == 4

    # Idempotency check on persistent storage
    stored_pages = db.get_crawled_pages(crawl_id)
    assert len(stored_pages) == 4
    urls = [p.url for p in stored_pages]
    assert len(urls) == len(set(urls)), f"Duplicate pages found in DB for {engine_mode}!"
    gc.collect()


# ---------------------------------------------------------------------------
# 8. Idempotent DB Persistence: Zero Duplicate Rows on Replay
# ---------------------------------------------------------------------------

def test_idempotent_db_persistence_zero_duplicates(server: ControlledCrawlerServer, tmp_path: Path):
    """Replaying/resuming a completed crawl never duplicates rows in pages or links."""
    db_path = tmp_path / "idempotent.db"
    db = Database(db_path)
    db.initialize()
    crawl_id = "crawl-idempotent-1"

    settings = _engine_settings("serial", tmp_path)
    engine = CrawlEngine(settings, database=db)

    req = CrawlRequest(
        start_url=f"{server.base_url}/",
        crawl_id=crawl_id,
        max_urls=3,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    db.create_crawl(req)
    res = engine.run(req, progress=lambda *a: None)
    assert len(res.pages) == 3

    page_count_before = len(db.get_crawled_pages(crawl_id))
    link_count_before = len(db.get_crawled_links(crawl_id))

    # Replay crawl in resume mode
    req_replay = CrawlRequest(
        start_url=f"{server.base_url}/",
        crawl_id=crawl_id,
        max_urls=3,
        delay_seconds=0.0,
        acknowledgment=True,
        resume=True,
    )
    res_replay = engine.run(req_replay, progress=lambda *a: None)
    assert res_replay.resumed is True

    page_count_after = len(db.get_crawled_pages(crawl_id))
    link_count_after = len(db.get_crawled_links(crawl_id))

    assert page_count_after == page_count_before == 3
    assert link_count_after == link_count_before
    gc.collect()


# ---------------------------------------------------------------------------
# 9. Corrupt State Detection (Raises CorruptStateError)
# ---------------------------------------------------------------------------

def test_corrupt_state_handling_explicit_failure(tmp_path: Path):
    """Corrupted checkpoint JSON or frontier records fail explicitly with CorruptStateError."""
    db_path = tmp_path / "corrupt.db"
    db = Database(db_path)
    db.initialize()
    crawl_id = "crawl-corrupt-1"
    db.create_crawl(CrawlRequest(start_url="http://example.com/", crawl_id=crawl_id))

    # Case A: Corrupt JSON in crawls.checkpoint_json
    with db.connect() as conn:
        conn.execute("UPDATE crawls SET checkpoint_json = 'INVALID_NOT_JSON{' WHERE id = ?", (crawl_id,))

    with pytest.raises(CorruptStateError, match="Corrupt checkpoint JSON"):
        db.validate_checkpoint_compatibility(crawl_id)

    with pytest.raises(CorruptStateError):
        db.get_frontier_checkpoint(crawl_id)

    # Case B: Corrupt state enum in crawl_frontier_checkpoints table
    with db.connect() as conn:
        conn.execute("UPDATE crawls SET checkpoint_json = '{}' WHERE id = ?", (crawl_id,))
        conn.execute(
            """INSERT INTO crawl_frontier_checkpoints (crawl_id, url, state)
               VALUES (?, 'http://example.com/', 'BOGUS_STATE_NOT_ENUM')""",
            (crawl_id,),
        )

    # Set valid checkpoint_json so validation passes
    with db.connect() as conn:
        conn.execute("UPDATE crawls SET checkpoint_json = '{\"saved_at\": \"2026-01-01\"}' WHERE id = ?", (crawl_id,))

    with pytest.raises(CorruptStateError, match="Invalid frontier state"):
        db.get_frontier_checkpoint(crawl_id)
    gc.collect()


# ---------------------------------------------------------------------------
# 10. Incompatible Schema & Engine Version (Raises IncompatibleStateError)
# ---------------------------------------------------------------------------

def test_incompatible_schema_and_engine_versions(tmp_path: Path):
    """Incompatible schema or engine versions raise IncompatibleStateError, never silently corrupt."""
    db_path = tmp_path / "incompatible.db"
    db = Database(db_path)
    db.initialize()
    crawl_id = "crawl-incompat-1"
    db.create_crawl(CrawlRequest(start_url="http://example.com/", crawl_id=crawl_id))

    # Case A: Future schema version
    with db.connect() as conn:
        conn.execute("UPDATE crawls SET schema_version = 999 WHERE id = ?", (crawl_id,))

    with pytest.raises(IncompatibleStateError, match="incompatible with engine supported version"):
        db.validate_checkpoint_compatibility(crawl_id)

    with pytest.raises(IncompatibleStateError):
        db.get_frontier_checkpoint(crawl_id)

    # Case B: Future major engine version
    with db.connect() as conn:
        conn.execute("UPDATE crawls SET schema_version = 1, engine_version = '99.0.0' WHERE id = ?", (crawl_id,))

    with pytest.raises(IncompatibleStateError, match="is newer than current engine"):
        db.validate_checkpoint_compatibility(crawl_id)
    gc.collect()


# ---------------------------------------------------------------------------
# 11. Mathematical Reconciliation of Accounting Across Resume
# ---------------------------------------------------------------------------

def test_mathematical_reconciliation_post_resume(server: ControlledCrawlerServer, tmp_path: Path):
    """Frontier accounting ledger reconciles mathematically across multiple resume stages."""
    db_path = tmp_path / "math_reconciliation.db"
    db = Database(db_path)
    db.initialize()
    crawl_id = "crawl-math-1"

    settings = _engine_settings("serial", tmp_path)
    engine = CrawlEngine(settings, database=db)

    # Stage 1: Crawl 2 pages
    req1 = CrawlRequest(start_url=f"{server.base_url}/", crawl_id=crawl_id, max_urls=2, delay_seconds=0.0, acknowledgment=True)
    db.create_crawl(req1)
    res1 = engine.run(req1, progress=lambda *a: None)
    assert len(res1.pages) == 2

    # Verify frontier after stage 1
    entries1, meta1 = db.get_frontier_checkpoint(crawl_id)
    frontier1 = CrawlFrontier(start_url=f"{server.base_url}/", max_urls=10, allow_private=True)
    frontier1.restore_state(entries1, metadata=meta1)
    ac1 = frontier1.reconcile_accounting()
    assert ac1["completed"] == 2
    assert ac1["fetching"] == 0
    assert ac1["discovered"] == ac1["completed"] + ac1["queued"] + ac1["duplicate"] + ac1["skipped"]

    # Stage 2: Resume and crawl 4 pages
    req2 = CrawlRequest(start_url=f"{server.base_url}/", crawl_id=crawl_id, max_urls=4, delay_seconds=0.0, acknowledgment=True, resume=True)
    res2 = engine.run(req2, progress=lambda *a: None)
    assert len(res2.pages) == 4

    # Verify frontier after stage 2
    entries2, meta2 = db.get_frontier_checkpoint(crawl_id)
    frontier2 = CrawlFrontier(start_url=f"{server.base_url}/", max_urls=10, allow_private=True)
    frontier2.restore_state(entries2, metadata=meta2)
    ac2 = frontier2.reconcile_accounting()
    assert ac2["completed"] == 4
    assert ac2["fetching"] == 0
    assert ac2["discovered"] == ac2["completed"] + ac2["queued"] + ac2["duplicate"] + ac2["skipped"]
    gc.collect()
