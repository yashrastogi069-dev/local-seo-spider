"""Runtime concurrency proof tests verifying non-serialized parallel execution and distinct worker PIDs."""

from __future__ import annotations

import os
import time
from pathlib import Path
import pytest

from app.config import Settings
from app.crawler import CrawlEngine
from app.types import CrawlRequest, CrawlStatus
from tests.controlled_crawler_server import ControlledCrawlerServer


@pytest.fixture(scope="module")
def server():
    srv = ControlledCrawlerServer()
    srv.start()
    yield srv
    srv.stop()


def _make_settings(mode: str, workers: int = 3) -> Settings:
    return Settings(
        data_dir=Path("data"),
        user_agent="ConcurrencyProof/1.0",
        default_url_cap=10,
        max_url_cap=20,
        default_delay_seconds=0,
        request_timeout_seconds=5,
        render_timeout_ms=1000,
        max_redirects=3,
        max_document_bytes=50_000,
        max_request_retries=1,
        retry_backoff_seconds=0.05,
        max_concurrent_crawls=1,
        render_enabled=False,
        crawl_executor_mode=mode,
        async_concurrency=workers,
        thread_workers=workers,
        process_workers=workers,
        allow_private_crawls=True,
    )


def test_serial_engine_executes_sequentially(server: ControlledCrawlerServer):
    """Serial engine must execute requests sequentially with duration >= sum of fetch delays."""
    server.reset_concurrency_stats()
    urls = [
        f"{server.base_url}/slow-concurrency/s1",
        f"{server.base_url}/slow-concurrency/s2",
        f"{server.base_url}/slow-concurrency/s3",
    ]
    engine = CrawlEngine(_make_settings("serial"))
    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=3,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode="serial",
    )

    t0 = time.monotonic()
    result = engine.run(req, lambda *_: None)
    elapsed = time.monotonic() - t0

    assert result.status == CrawlStatus.SUCCESS.value
    assert len(result.pages) == 3
    assert result.actual_engine == "serial"

    # Server logs verification
    logs = server.get_request_logs()
    assert len(logs) == 3
    fetch_span = max(l["t_end"] for l in logs) - min(l["t_start"] for l in logs)
    # 3 sequential requests of 0.25s must span >= 0.70s
    assert fetch_span >= 0.70, f"Serial fetch span {fetch_span:.3f}s was too fast; expected >= 0.70s"
    assert server.get_peak_concurrency() == 1, f"Serial peak concurrency must be 1, got {server.get_peak_concurrency()}"


def test_threaded_engine_executes_concurrently(server: ControlledCrawlerServer):
    """Threaded engine must achieve overlapping intervals, fetch span < sum of delays, and peak concurrency >= 2."""
    server.reset_concurrency_stats()
    urls = [
        f"{server.base_url}/slow-concurrency/t1",
        f"{server.base_url}/slow-concurrency/t2",
        f"{server.base_url}/slow-concurrency/t3",
    ]
    engine = CrawlEngine(_make_settings("thread", workers=3))
    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=3,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode="thread",
    )

    result = engine.run(req, lambda *_: None)

    assert result.status == CrawlStatus.SUCCESS.value
    assert len(result.pages) == 3
    assert result.actual_engine == "thread"
    assert server.get_peak_concurrency() >= 2, f"Threaded peak concurrency must be >= 2, got {server.get_peak_concurrency()}"

    # Server logs verification: 3 requests running with 3 workers must span < 0.45s (each takes 0.25s)
    logs = server.get_request_logs()
    assert len(logs) == 3
    fetch_span = max(l["t_end"] for l in logs) - min(l["t_start"] for l in logs)
    assert fetch_span < 0.45, f"Threaded fetch span took {fetch_span:.3f}s; expected < 0.45s"

    # Verify overlapping intervals
    intervals = [(l["t_start"], l["t_end"]) for l in logs]
    has_overlap = any(
        max(i1[0], i2[0]) < min(i1[1], i2[1])
        for idx, i1 in enumerate(intervals)
        for i2 in intervals[idx + 1:]
    )
    assert has_overlap, "Threaded requests must have overlapping execution intervals"


def test_coroutine_engine_executes_concurrently(server: ControlledCrawlerServer):
    """Coroutine (async) engine must achieve overlapping intervals, fetch span < sum of delays, and peak concurrency >= 2."""
    server.reset_concurrency_stats()
    urls = [
        f"{server.base_url}/slow-concurrency/a1",
        f"{server.base_url}/slow-concurrency/a2",
        f"{server.base_url}/slow-concurrency/a3",
    ]
    engine = CrawlEngine(_make_settings("async", workers=3))
    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=3,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode="async",
    )

    result = engine.run(req, lambda *_: None)

    assert result.status == CrawlStatus.SUCCESS.value
    assert len(result.pages) == 3
    assert result.actual_engine == "async"
    assert server.get_peak_concurrency() >= 2, f"Coroutine peak concurrency must be >= 2, got {server.get_peak_concurrency()}"

    # Server logs verification: 3 requests running with 3 concurrency must span < 0.45s
    logs = server.get_request_logs()
    assert len(logs) == 3
    fetch_span = max(l["t_end"] for l in logs) - min(l["t_start"] for l in logs)
    assert fetch_span < 0.45, f"Coroutine fetch span took {fetch_span:.3f}s; expected < 0.45s"

    # Verify overlapping intervals
    intervals = [(l["t_start"], l["t_end"]) for l in logs]
    has_overlap = any(
        max(i1[0], i2[0]) < min(i1[1], i2[1])
        for idx, i1 in enumerate(intervals)
        for i2 in intervals[idx + 1:]
    )
    assert has_overlap, "Coroutine requests must have overlapping execution intervals"


def test_multiprocess_engine_executes_concurrently_with_distinct_pids(server: ControlledCrawlerServer):
    """Multiprocess engine must achieve parallel timing, peak concurrency >= 2, and distinct child worker PIDs."""
    server.reset_concurrency_stats()
    urls = [
        f"{server.base_url}/slow-concurrency/p1?delay=0.45",
        f"{server.base_url}/slow-concurrency/p2?delay=0.45",
        f"{server.base_url}/slow-concurrency/p3?delay=0.45",
    ]
    engine = CrawlEngine(_make_settings("process", workers=3))
    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=3,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode="process",
    )

    parent_pid = os.getpid()
    result = engine.run(req, lambda *_: None)

    assert result.status == CrawlStatus.SUCCESS.value
    assert len(result.pages) == 3
    assert result.actual_engine == "process"

    # Concurrency verification
    assert server.get_peak_concurrency() >= 2, f"Multiprocess peak concurrency must be >= 2, got {server.get_peak_concurrency()}"

    # Verify distinct worker PIDs recorded in page headers
    worker_pids = set()
    for page in result.pages:
        w_pid = page.headers.get("x-worker-pid")
        if w_pid:
            worker_pids.add(int(w_pid))
        # Ensure worker is NOT the main parent process
        assert page.headers.get("x-worker-pid") != str(parent_pid), "Worker PID must not be parent PID"

    assert len(worker_pids) >= 2, f"Expected at least 2 distinct child worker PIDs, got {worker_pids}"

    # Server logs verification: 3 requests running across worker processes with delay 0.45s
    # In serial, 3 * 0.45s = 1.35s; multiprocess must complete in < 1.0s
    logs = server.get_request_logs()
    assert len(logs) == 3
    fetch_span = max(l["t_end"] for l in logs) - min(l["t_start"] for l in logs)
    assert fetch_span < 1.30, f"Multiprocess fetch span took {fetch_span:.3f}s; expected < 1.30s (serial is 1.35s)"

    # Verify overlapping intervals from server logs
    intervals = [(l["t_start"], l["t_end"]) for l in logs]
    has_overlap = any(
        max(i1[0], i2[0]) < min(i1[1], i2[1])
        for idx, i1 in enumerate(intervals)
        for i2 in intervals[idx + 1:]
    )
    assert has_overlap, "Multiprocess requests must have overlapping execution intervals"
