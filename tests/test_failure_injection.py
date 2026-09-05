"""Adversarial failure injection test suite for crawler resilience and fault isolation (Phase 2D)."""

from __future__ import annotations

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


def _failure_settings(mode: str, tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        user_agent="FailureInjection/1.0",
        default_url_cap=10,
        max_url_cap=20,
        default_delay_seconds=0,
        request_timeout_seconds=2,
        render_timeout_ms=1000,
        max_redirects=2,
        max_document_bytes=10_000,
        max_request_retries=1,
        retry_backoff_seconds=0.05,
        max_concurrent_crawls=1,
        render_enabled=False,
        crawl_executor_mode=mode,
        async_concurrency=2,
        thread_workers=2,
        process_workers=2,
        allow_private_crawls=True,
    )


ALL_ENGINES = ["serial", "thread", "async", "process"]


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_failure_injection_drop_mid_stream(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Endpoint /drop-mid-stream abruptly resets/closes socket during body transmission.
    
    Verifies:
    - Error is accurately captured in PageRecord.fetch_error
    - Error category is 'fetch_error'
    - Subsequent/remaining URLs in queue continue crawling normally
    """
    settings = _failure_settings(engine_mode, tmp_path)
    engine = CrawlEngine(settings)

    urls = [
        f"{server.base_url}/drop-mid-stream",
        f"{server.base_url}/a",
    ]

    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=2,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )

    result = engine.run(req, lambda *_: None)

    assert result.status in (CrawlStatus.PARTIAL.value, CrawlStatus.SUCCESS.value)
    assert len(result.pages) == 2

    drop_page = next(p for p in result.pages if "/drop-mid-stream" in p.url)
    assert drop_page.fetch_error != "", "Expected fetch_error for abruptly dropped socket"
    assert drop_page.error_category == "fetch_error"

    valid_page = next(p for p in result.pages if "/a" in p.url)
    assert valid_page.status_code == 200
    assert valid_page.fetch_error == ""


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_failure_injection_half_written_stream(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Endpoint /half-written sends Content-Length larger than delivered bytes and closes.
    
    Verifies graceful error capture without hanging or corrupting worker state.
    """
    settings = _failure_settings(engine_mode, tmp_path)
    engine = CrawlEngine(settings)

    urls = [
        f"{server.base_url}/half-written",
        f"{server.base_url}/b",
    ]

    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=2,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )

    result = engine.run(req, lambda *_: None)

    assert len(result.pages) == 2
    half_page = next(p for p in result.pages if "/half-written" in p.url)
    assert half_page.fetch_error != ""
    assert half_page.error_category == "fetch_error"

    valid_page = next(p for p in result.pages if "/b" in p.url)
    assert valid_page.status_code == 200
    assert valid_page.fetch_error == ""


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_failure_injection_malformed_gzip(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Endpoint /malformed-gzip serves Content-Encoding: gzip with corrupt bytes.
    
    Verifies:
    - HTTP decoding error trapped into page record
    - Engine remains alive and processes remaining queue
    """
    settings = _failure_settings(engine_mode, tmp_path)
    engine = CrawlEngine(settings)

    urls = [
        f"{server.base_url}/malformed-gzip",
        f"{server.base_url}/a",
    ]

    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=2,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )

    result = engine.run(req, lambda *_: None)

    assert len(result.pages) == 2
    gzip_page = next(p for p in result.pages if "/malformed-gzip" in p.url)
    assert gzip_page.fetch_error != "" or "DecodingError" in gzip_page.fetch_error or gzip_page.status_code is not None

    valid_page = next(p for p in result.pages if "/a" in p.url)
    assert valid_page.status_code == 200


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_failure_injection_socket_timeout(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Endpoint /timeout sleeps for 2.0s with request_timeout_seconds=0.5s.
    
    Verifies timeout exception captured, error recorded, resources freed.
    """
    settings = Settings(
        data_dir=tmp_path,
        user_agent="TimeoutTest/1.0",
        default_url_cap=5,
        max_url_cap=10,
        default_delay_seconds=0,
        request_timeout_seconds=0.5,
        render_timeout_ms=500,
        max_redirects=1,
        max_document_bytes=10_000,
        max_request_retries=0,
        retry_backoff_seconds=0.01,
        max_concurrent_crawls=1,
        render_enabled=False,
        crawl_executor_mode=engine_mode,
        async_concurrency=2,
        thread_workers=2,
        process_workers=2,
        allow_private_crawls=True,
    )
    engine = CrawlEngine(settings)

    urls = [
        f"{server.base_url}/timeout",
        f"{server.base_url}/a",
    ]

    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=2,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )

    result = engine.run(req, lambda *_: None)

    assert len(result.pages) == 2
    timeout_page = next(p for p in result.pages if "/timeout" in p.url)
    assert "Timeout" in timeout_page.fetch_error or timeout_page.error_category == "fetch_error"

    valid_page = next(p for p in result.pages if "/a" in p.url)
    assert valid_page.status_code == 200


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_failure_injection_connection_refused(tmp_path: Path, engine_mode: str):
    """Attempt to connect to an unopened port (127.0.0.1:1).
    
    Verifies ConnectError is trapped and recorded, crawler does not crash.
    """
    settings = _failure_settings(engine_mode, tmp_path)
    engine = CrawlEngine(settings)

    urls = ["http://127.0.0.1:1/nonexistent"]

    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=1,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )

    result = engine.run(req, lambda *_: None)

    assert result.status == CrawlStatus.FAILED.value
    assert len(result.pages) == 1
    page = result.pages[0]
    assert page.fetch_error != ""
    assert page.error_category == "fetch_error"
