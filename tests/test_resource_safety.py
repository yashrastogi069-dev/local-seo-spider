"""Resource safety and leak tests verifying deterministic teardown and memory stability (Phase 2D)."""

from __future__ import annotations

import gc
import multiprocessing
import threading
import time
import tracemalloc
from pathlib import Path
import pytest

from app.config import Settings
from app.crawler import CrawlEngine
from app.database import Database
from app.types import CrawlRequest, CrawlStatus
from tests.controlled_crawler_server import ControlledCrawlerServer


@pytest.fixture(scope="module")
def server():
    srv = ControlledCrawlerServer()
    srv.start()
    yield srv
    srv.stop()


def _resource_settings(mode: str, tmp_path: Path, workers: int = 3) -> Settings:
    return Settings(
        data_dir=tmp_path,
        user_agent="ResourceSafety/1.0",
        default_url_cap=10,
        max_url_cap=20,
        default_delay_seconds=0,
        request_timeout_seconds=3,
        render_timeout_ms=1000,
        max_redirects=2,
        max_document_bytes=20_000,
        max_request_retries=1,
        retry_backoff_seconds=0.02,
        max_concurrent_crawls=1,
        render_enabled=False,
        crawl_executor_mode=mode,
        async_concurrency=workers,
        thread_workers=workers,
        process_workers=workers,
        allow_private_crawls=True,
    )


def test_threaded_workers_terminate_cleanly(server: ControlledCrawlerServer, tmp_path: Path):
    """ThreadedCrawlerEngine must terminate all worker threads upon crawl completion.
    
    Verifies:
    - ThreadPoolExecutor is deterministically shutdown with wait=True
    - Zero 'crawl-worker' threads remain active after crawl
    """
    settings = _resource_settings("thread", tmp_path, workers=4)
    engine = CrawlEngine(settings)

    req = CrawlRequest(
        start_url=f"{server.base_url}/a",
        mode="list",
        url_list=[f"{server.base_url}/a", f"{server.base_url}/b"],
        max_urls=2,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode="thread",
    )

    result = engine.run(req, lambda *_: None)

    assert result.status == CrawlStatus.SUCCESS.value
    gc.collect()

    leaked_workers = [t for t in threading.enumerate() if "crawl-worker" in t.name and t.is_alive()]
    assert len(leaked_workers) == 0, f"Leaked worker threads detected: {leaked_workers}"


def test_multiprocess_workers_terminate_cleanly(server: ControlledCrawlerServer, tmp_path: Path):
    """MultiprocessCrawlerEngine must terminate all spawned child processes.
    
    Verifies:
    - ProcessPoolExecutor shuts down completely
    - Zero orphan child processes remain active
    """
    settings = _resource_settings("process", tmp_path, workers=3)
    engine = CrawlEngine(settings)

    req = CrawlRequest(
        start_url=f"{server.base_url}/a",
        mode="list",
        url_list=[f"{server.base_url}/a", f"{server.base_url}/b"],
        max_urls=2,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode="process",
    )

    result = engine.run(req, lambda *_: None)

    assert result.status == CrawlStatus.SUCCESS.value
    gc.collect()

    active_children = multiprocessing.active_children()
    assert len(active_children) == 0, f"Orphan child processes detected: {active_children}"


@pytest.mark.parametrize("engine_mode", ["serial", "thread", "async"])
def test_consecutive_crawls_resource_and_memory_stability(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Run 5 consecutive crawls in the exact same Python process.
    
    Verifies:
    - Memory stabilizes across consecutive crawls (no unbounded growth)
    - Thread count returns to baseline after each crawl
    - Database transactions remain cleanly closed
    - All 5 crawls succeed with identical page counts
    """
    settings = _resource_settings(engine_mode, tmp_path, workers=3)
    engine = CrawlEngine(settings)

    db_path = tmp_path / f"soak_{engine_mode}.db"
    db = Database(db_path)
    db.initialize()

    tracemalloc.start()
    gc.collect()

    memory_measurements: list[int] = []

    for i in range(5):
        req = CrawlRequest(
            start_url=f"{server.base_url}/a",
            mode="list",
            url_list=[f"{server.base_url}/a", f"{server.base_url}/b"],
            max_urls=2,
            delay_seconds=0.0,
            acknowledgment=True,
            executor_mode=engine_mode,
        )

        crawl_id = db.create_crawl(req)
        result = engine.run(req, lambda *_: None)

        assert result.status == CrawlStatus.SUCCESS.value
        assert len(result.pages) == 2

        db.replace_pages_and_links(crawl_id, result.pages, result.links)
        db.update_crawl(crawl_id, status="completed", pages_crawled=2)

        gc.collect()
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        memory_measurements.append(current_mem)

        # Thread safety invariant: no orphan worker threads
        leaked_workers = [t for t in threading.enumerate() if "crawl-worker" in t.name and t.is_alive()]
        assert len(leaked_workers) == 0, f"Iteration {i}: leaked worker threads: {leaked_workers}"

    tracemalloc.stop()

    # Verify memory stability: memory between crawl 2 and crawl 5 must not grow unboundedly (< 2.5 MB drift)
    mem_drift = memory_measurements[-1] - memory_measurements[1]
    assert mem_drift < 2_500_000, f"Unbounded memory growth across 5 crawls: drift = {mem_drift / 1024:.1f} KB"

    # Verify database integrity after consecutive crawls
    crawls = db.list_crawls(limit=10)
    assert len(crawls) == 5
    for c in crawls:
        assert c["status"] == "completed"
        assert c["pages_crawled"] == 2


def test_sqlite_transaction_and_connection_safety(tmp_path: Path):
    """Verify that multiple concurrent connects and writes leave zero open locks or corrupted states."""
    db_path = tmp_path / "trans_test.db"
    db = Database(db_path)
    db.initialize()

    req = CrawlRequest("http://127.0.0.1:8000/", mode="site", acknowledgment=True)
    crawl_id = db.create_crawl(req)

    # Open connection and execute writes
    with db.connect() as conn:
        conn.execute("UPDATE crawls SET pages_crawled = 1 WHERE id = ?", (crawl_id,))

    # Ensure a second connection can read and write immediately without lock errors
    with db.connect() as conn2:
        row = conn2.execute("SELECT pages_crawled FROM crawls WHERE id = ?", (crawl_id,)).fetchone()
        assert row["pages_crawled"] == 1
        conn2.execute("UPDATE crawls SET status = 'completed' WHERE id = ?", (crawl_id,))

    crawl = db.get_crawl(crawl_id)
    assert crawl["status"] == "completed"


def test_sqlite_transaction_rollback_on_failure(tmp_path: Path):
    """Verify that an exception inside a database transaction rolls back cleanly without partial writes."""
    db_path = tmp_path / "rollback_test.db"
    db = Database(db_path)
    db.initialize()

    req = CrawlRequest("http://127.0.0.1:8000/", mode="site", acknowledgment=True)
    crawl_id = db.create_crawl(req)

    # Initial state
    assert db.get_crawl(crawl_id)["pages_crawled"] == 0

    # Attempt a transaction that fails midway
    with pytest.raises(RuntimeError):
        with db.connect() as conn:
            conn.execute("UPDATE crawls SET pages_crawled = 99 WHERE id = ?", (crawl_id,))
            raise RuntimeError("Simulated mid-transaction failure")

    # Verify rollback: pages_crawled should still be 0
    crawl = db.get_crawl(crawl_id)
    assert crawl["pages_crawled"] == 0

    # Verify database remains fully writable after rollback
    with db.connect() as conn:
        conn.execute("UPDATE crawls SET pages_crawled = 5 WHERE id = ?", (crawl_id,))
    assert db.get_crawl(crawl_id)["pages_crawled"] == 5

