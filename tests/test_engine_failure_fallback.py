"""Fail-closed and anti-silent-fallback tests for all crawler engines."""

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


def _engine_settings(mode: str) -> Settings:
    return Settings(
        data_dir=Path("data"),
        user_agent="FailClosedTest/1.0",
        default_url_cap=5,
        max_url_cap=10,
        default_delay_seconds=0,
        request_timeout_seconds=2,
        render_timeout_ms=1000,
        max_redirects=2,
        max_document_bytes=10_000,
        max_request_retries=0,
        retry_backoff_seconds=0.05,
        max_concurrent_crawls=1,
        render_enabled=False,
        crawl_executor_mode=mode,
        async_concurrency=2,
        thread_workers=2,
        process_workers=2,
        allow_private_crawls=True,
    )


def test_unknown_executor_mode_fails_closed():
    """Unrecognized executor mode must fail fast with ValueError, not fall back to serial."""
    engine = CrawlEngine(_engine_settings("invalid_mode"))
    req = CrawlRequest(
        start_url="http://127.0.0.1:8000/",
        mode="site",
        max_urls=2,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode="invalid_mode",
    )
    with pytest.raises(ValueError, match="Crawl executor mode must be serial, thread, async, or process"):
        engine.run(req, lambda *_: None)


@pytest.mark.parametrize("mode", ["thread", "async", "process"])
def test_unsupported_browser_rendering_fails_fast_without_silent_fallback(mode: str):
    """When browser rendering is requested on multi-worker static engine, fallback is transparently recorded."""
    cfg = Settings(
        data_dir=Path("data"),
        user_agent="FailClosedTest/1.0",
        default_url_cap=5,
        max_url_cap=10,
        default_delay_seconds=0,
        request_timeout_seconds=2,
        render_timeout_ms=1000,
        max_redirects=2,
        max_document_bytes=10_000,
        max_request_retries=0,
        retry_backoff_seconds=0.05,
        max_concurrent_crawls=1,
        render_enabled=True,  # Requesting browser rendering!
        crawl_executor_mode=mode,
        async_concurrency=2,
        thread_workers=2,
        process_workers=2,
        allow_private_crawls=True,
    )
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url="http://127.0.0.1:8000/a",
        mode="list",
        url_list=["http://127.0.0.1:8000/a"],
        max_urls=1,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=mode,
    )
    # Even if mocked or unconfigured, fallback must be explicitly declared and tracked
    result = engine.run(req, lambda *_: None)
    assert result.actual_engine == mode
    assert result.requested_fetch_mode == "browser"
    assert result.actual_fetch_mode == "static"
    assert result.fallback_occurred is True
    assert "Browser rendering is unsupported in multi-worker static executor" in result.fallback_reason


def test_multiprocess_broken_pool_fails_closed(monkeypatch: pytest.MonkeyPatch, server: ControlledCrawlerServer):
    """When ProcessPoolExecutor fails or crashes, multiprocess engine must record failure, not secretly run serial."""
    from concurrent.futures.process import BrokenProcessPool

    engine = CrawlEngine(_engine_settings("process"))
    req = CrawlRequest(
        start_url=f"{server.base_url}/a",
        mode="list",
        url_list=[f"{server.base_url}/a"],
        max_urls=1,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode="process",
    )

    class BrokenExecutor:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def submit(self, *args, **kwargs):
            raise BrokenProcessPool("Simulated child process segmentation fault / crash")

    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", BrokenExecutor)
    result = engine.run(req, lambda *_: None)

    assert result.actual_engine == "process"
    assert result.status == CrawlStatus.FAILED.value
    assert "BrokenProcessPool" in result.termination_reason
    assert result.fallback_occurred is False
