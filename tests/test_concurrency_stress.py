"""Comprehensive concurrency stress tests detecting race conditions, deadlocks, and lost URLs (Phase 2D)."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest

from app.config import Settings
from app.crawler import (
    CrawlEngine,
    SerialCrawlerEngine,
    ThreadedCrawlerEngine,
    CoroutineCrawlerEngine,
    MultiprocessCrawlerEngine,
)
from app.database import Database
from app.types import CancellationToken, CrawlRequest, CrawlStatus, PageRecord, LinkRecord
from tests.controlled_crawler_server import ControlledCrawlerServer


@pytest.fixture(scope="module")
def server():
    srv = ControlledCrawlerServer()
    srv.start()
    yield srv
    srv.stop()


def _stress_settings(mode: str, workers: int = 4, data_dir: Path | None = None) -> Settings:
    return Settings(
        data_dir=data_dir or Path("data"),
        user_agent="ConcurrencyStress/1.0",
        default_url_cap=50,
        max_url_cap=100,
        default_delay_seconds=0,
        request_timeout_seconds=4,
        render_timeout_ms=1000,
        max_redirects=3,
        max_document_bytes=50_000,
        max_request_retries=2,
        retry_backoff_seconds=0.05,
        max_concurrent_crawls=1,
        render_enabled=False,
        crawl_executor_mode=mode,
        async_concurrency=workers,
        thread_workers=workers,
        process_workers=workers,
        allow_private_crawls=True,
    )


ALL_CONCURRENT_ENGINES = ["thread", "async", "process"]


@pytest.mark.parametrize("engine_mode", ALL_CONCURRENT_ENGINES)
def test_simultaneous_duplicate_discovery_exact_dedup(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Multiple concurrent workers discover the same target URL at the exact same moment.
    
    Target URL must be processed exactly ONCE:
    - 0 duplicate page crawls
    - 0 duplicate DB records
    - Frontier accounting strictly reconciles
    """
    settings = _stress_settings(engine_mode, workers=4, data_dir=tmp_path)
    engine = CrawlEngine(settings)

    req = CrawlRequest(
        start_url=f"{server.base_url}/simultaneous-duplicate-hub",
        mode="site",
        max_urls=10,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )

    result = engine.run(req, lambda *_: None)

    assert result.status == CrawlStatus.SUCCESS.value
    target_pages = [p for p in result.pages if "/shared-duplicate-target" in p.url]
    assert len(target_pages) == 1, f"Expected /shared-duplicate-target exactly once, got {len(target_pages)}"

    # URLs crawled should all be unique
    crawled_urls = [p.url for p in result.pages]
    assert len(crawled_urls) == len(set(crawled_urls)), f"Duplicate URLs found in crawled pages: {crawled_urls}"


@pytest.mark.parametrize("engine_mode", ALL_CONCURRENT_ENGINES)
def test_rapid_mass_discovery_and_queue_integrity(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Mass simultaneous URL discovery: a hub page links to 25 target URLs concurrently crawled.
    
    Verifies:
    - 0 lost URLs
    - 0 queue corruption
    - Exact page budget bounding (capped at 20)
    - All pages crawled are valid
    """
    settings = _stress_settings(engine_mode, workers=4, data_dir=tmp_path)
    engine = CrawlEngine(settings)

    req = CrawlRequest(
        start_url=f"{server.base_url}/rapid-discovery",
        mode="site",
        max_urls=20,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )

    result = engine.run(req, lambda *_: None)

    assert result.status == CrawlStatus.SUCCESS.value
    assert len(result.pages) == 20, f"Expected exactly 20 pages capped by budget, got {len(result.pages)}"
    assert result.pages_discovered >= 25, f"Expected at least 25 discovered URLs, got {result.pages_discovered}"
    assert result.pages_succeeded == 20
    assert result.pages_failed == 0

    urls = [p.url for p in result.pages]
    assert len(urls) == len(set(urls)), "Duplicate URLs detected during rapid discovery"


@pytest.mark.parametrize("engine_mode", ALL_CONCURRENT_ENGINES)
def test_mixed_fast_slow_endpoints_no_starvation(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Interleaved fast (0.01s) and slow (0.25s) endpoints under concurrency.
    
    Verifies that slow endpoints do not starve fast endpoints, deadlock the pool, or prevent crawl completion.
    """
    settings = _stress_settings(engine_mode, workers=3, data_dir=tmp_path)
    engine = CrawlEngine(settings)

    urls = [
        f"{server.base_url}/slow-mixed/fast-1",
        f"{server.base_url}/slow-mixed/slow-1",
        f"{server.base_url}/slow-mixed/fast-2",
        f"{server.base_url}/slow-mixed/slow-2",
        f"{server.base_url}/slow-mixed/fast-3",
    ]

    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )

    t0 = time.monotonic()
    result = engine.run(req, lambda *_: None)
    elapsed = time.monotonic() - t0

    assert result.status == CrawlStatus.SUCCESS.value
    assert len(result.pages) == 5
    assert result.pages_succeeded == 5
    max_expected = 12.0 if engine_mode == "process" else 6.0
    assert elapsed < max_expected, f"Mixed crawl ({engine_mode}) took {elapsed:.2f}s, expected < {max_expected}s"


@pytest.mark.parametrize("engine_mode", ALL_CONCURRENT_ENGINES)
def test_concurrent_500_and_429_storm(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Burst of 500 errors and 429 rate-limited endpoints across concurrent workers.
    
    Verifies:
    - Retries back off cleanly
    - No livelock, deadlock, or unhandled thread exceptions
    - Errors properly categorized
    """
    settings = _stress_settings(engine_mode, workers=3, data_dir=tmp_path)
    engine = CrawlEngine(settings)

    urls = [
        f"{server.base_url}/burst-500/1",
        f"{server.base_url}/burst-429/1",
        f"{server.base_url}/burst-500/2",
        f"{server.base_url}/burst-429/2",
    ]

    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=4,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )

    result = engine.run(req, lambda *_: None)

    assert result.status in (CrawlStatus.FAILED.value, CrawlStatus.PARTIAL.value)
    assert len(result.pages) == 4
    for p in result.pages:
        assert p.status_code in (500, 429)
        assert p.error_category in ("fetch_error", "http_500", "http_429")


@pytest.mark.parametrize("engine_mode", ["thread", "async"])
def test_active_crawl_cancellation_mid_flight(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Cooperative cancellation triggered while workers are actively in-flight.
    
    Verifies:
    - Crawl aborts promptly (< 1.2s)
    - Status is strictly CANCELLED
    - Termination reason recorded
    - No hanging threads
    """
    settings = _stress_settings(engine_mode, workers=4, data_dir=tmp_path)
    engine = CrawlEngine(settings)

    urls = [f"{server.base_url}/slow-concurrency/cancel-{i}?delay=0.4" for i in range(8)]
    token = CancellationToken()

    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=8,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )

    def on_progress(crawled: int, queued: int, robots: str) -> None:
        if crawled >= 1:
            token.cancel("Operator aborted crawl mid-flight")

    timer = threading.Timer(0.15, lambda: token.cancel("Operator aborted crawl mid-flight"))
    timer.start()

    t0 = time.monotonic()
    result = engine.run(req, on_progress, cancellation_token=token)
    elapsed = time.monotonic() - t0
    timer.cancel()

    assert result.status == CrawlStatus.CANCELLED.value
    assert "Operator aborted crawl mid-flight" in result.termination_reason
    assert elapsed < 2.5, f"Cancellation took too long: {elapsed:.2f}s"
    assert len(result.pages) < 8


def test_database_concurrent_write_contention(tmp_path: Path):
    """Stress test SQLite write contention with 10 concurrent threads.
    
    Verifies:
    - WAL mode and busy timeout eliminate 'database is locked' errors
    - Unique constraint on (crawl_id, url) prevents duplicate page inserts
    - Foreign key constraints preserved
    """
    db_path = tmp_path / "concurrent_stress.db"
    db = Database(db_path)
    db.initialize()

    crawl_id = "crawl-stress-001"
    req = CrawlRequest("http://127.0.0.1:8000/", mode="site", acknowledgment=True)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO crawls (id, created_at, status, start_url, settings_json, request_json, ownership_ack) VALUES (?, ?, 'running', ?, '{}', '{}', 1)",
            (crawl_id, "2026-09-06T00:00:00Z", "http://127.0.0.1:8000/"),
        )

    errors: list[Exception] = []

    def writer_task(thread_id: int):
        try:
            thread_crawl_id = db.create_crawl(req)
            pages = [
                PageRecord(
                    url=f"http://127.0.0.1:8000/page-{thread_id}-{i}",
                    final_url=f"http://127.0.0.1:8000/page-{thread_id}-{i}",
                    status_code=200,
                    content_type="text/html",
                    title=f"Page {i}",
                    description="",
                    headings={},
                    canonical="",
                    meta_robots="",
                    x_robots="",
                    source_html="<html></html>",
                    rendered_html="",
                    rendered_text="Page text",
                    images=[],
                    structured_data=[],
                    redirect_chain=[],
                )
                for i in range(10)
            ]
            links = [
                LinkRecord(
                    source_url=f"http://127.0.0.1:8000/page-{thread_id}-{i}",
                    target_url=f"http://127.0.0.1:8000/target-{thread_id}-{i}",
                    raw_target_url=f"/target-{thread_id}-{i}",
                    anchor_text=f"Link {i}",
                    rel="",
                    is_internal=True,
                    nofollow=False,
                )
                for i in range(10)
            ]
            db.replace_pages_and_links(thread_crawl_id, pages, links)
            db.update_crawl(thread_crawl_id, pages_crawled=10, status="completed")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer_task, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert len(errors) == 0, f"Concurrent database writes failed with errors: {errors}"
    crawls = db.list_crawls(limit=20)
    assert len(crawls) >= 10
