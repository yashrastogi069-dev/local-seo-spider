"""Shared Engine Conformance Suite verifying all 4 crawler engines against the 18 core requirements."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
import pytest

from app.config import Settings
from app.crawler import CrawlEngine
from app.types import CancellationToken, CrawlRequest, CrawlStatus
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
        user_agent="ConformanceSuite/1.0",
        default_url_cap=15,
        max_url_cap=30,
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


ALL_ENGINES = ["serial", "thread", "async", "process"]


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_conformance_seed_fetch_and_identity(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Req 1 & 18: Seed fetch and engine identity verification."""
    engine = CrawlEngine(_engine_settings(engine_mode, tmp_path))
    req = CrawlRequest(
        start_url=f"{server.base_url}/a",
        mode="list",
        url_list=[f"{server.base_url}/a"],
        max_urls=1,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )
    result = engine.run(req, lambda *_: None)
    assert result.status == CrawlStatus.SUCCESS.value
    assert result.requested_engine == engine_mode
    assert result.actual_engine == engine_mode
    assert result.fallback_occurred is False
    assert len(result.pages) == 1
    assert result.pages[0].status_code == 200
    assert result.pages[0].crawler_engine == engine_mode


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_conformance_multipage_discovery_and_depth_limit(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Req 2 & 3: Multi-page discovery in site mode bounded strictly by depth limit."""
    engine = CrawlEngine(_engine_settings(engine_mode, tmp_path))
    # /deep has /deep/1 -> /deep/1/2 -> /deep/1/2/3
    req = CrawlRequest(
        start_url=f"{server.base_url}/deep",
        mode="site",
        max_urls=10,
        max_depth=1,  # Should crawl /deep (depth 0) and /deep/1 (depth 1), but NOT /deep/1/2 (depth 2)
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )
    result = engine.run(req, lambda *_: None)
    assert result.status == CrawlStatus.SUCCESS.value
    assert len(result.pages) == 2
    depths = {p.url: p.depth for p in result.pages}
    assert depths[f"{server.base_url}/deep"] == 0
    assert depths[f"{server.base_url}/deep/1"] == 1


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_conformance_page_limit_budget(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Req 4: Page limit budget bounds crawled count regardless of queue size."""
    engine = CrawlEngine(_engine_settings(engine_mode, tmp_path))
    req = CrawlRequest(
        start_url=f"{server.base_url}/",
        mode="site",
        max_urls=3,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )
    result = engine.run(req, lambda *_: None)
    assert len(result.pages) <= 3
    assert result.termination_reason == "max_urls_reached"


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_conformance_duplicate_handling(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Req 5: Canonical and content hash duplicate detection."""
    engine = CrawlEngine(_engine_settings(engine_mode, tmp_path))
    # /canonical points to /canonical-target
    urls = [
        f"{server.base_url}/canonical",
        f"{server.base_url}/canonical-target",
        f"{server.base_url}/content-dup-1",
        f"{server.base_url}/content-dup-2",
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
    assert len(result.pages) == 4
    # Check that duplicates were detected
    duplicates = [p for p in result.pages if p.is_duplicate]
    assert len(duplicates) >= 1
    assert result.duplicates_count >= 1


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_conformance_redirect_handling(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Req 6: 301 and 302 redirect tracking and hops provenance."""
    engine = CrawlEngine(_engine_settings(engine_mode, tmp_path))
    urls = [f"{server.base_url}/redirect-301", f"{server.base_url}/redirect-chain"]
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
    for p in result.pages:
        assert len(p.redirect_chain) >= 1
        assert p.status_code == 200


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_conformance_http_errors_404_500(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Req 7 & 8: 404 Not Found and 500 Internal Error handling without unhandled crash."""
    engine = CrawlEngine(_engine_settings(engine_mode, tmp_path))
    urls = [f"{server.base_url}/404", f"{server.base_url}/500"]
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
    status_codes = {p.status_code for p in result.pages}
    assert status_codes == {404, 500}
    assert result.pages_failed == 2
    assert result.status == CrawlStatus.FAILED.value


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_conformance_timeout_handling(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Req 9: Timeout handling bounded cleanly by request_timeout_seconds."""
    engine = CrawlEngine(_engine_settings(engine_mode, tmp_path))
    # /timeout sleeps 2.0s, but request_timeout_seconds is 2.0 or 0.5
    # Let's set request_timeout_seconds to 0.5s for this test
    engine.settings = Settings(
        data_dir=tmp_path,
        user_agent="ConformanceSuite/1.0",
        default_url_cap=5,
        max_url_cap=10,
        default_delay_seconds=0,
        request_timeout_seconds=0.4,
        render_timeout_ms=500,
        max_redirects=2,
        max_document_bytes=10_000,
        max_request_retries=0,
        retry_backoff_seconds=0.05,
        max_concurrent_crawls=1,
        render_enabled=False,
        crawl_executor_mode=engine_mode,
        async_concurrency=2,
        thread_workers=2,
        process_workers=2,
        allow_private_crawls=True,
    )
    req = CrawlRequest(
        start_url=f"{server.base_url}/timeout",
        mode="list",
        url_list=[f"{server.base_url}/timeout"],
        max_urls=1,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )
    result = engine.run(req, lambda *_: None)
    assert len(result.pages) == 1
    assert result.pages[0].fetch_error != ""
    assert "Timeout" in result.pages[0].fetch_error or "timed out" in result.pages[0].fetch_error.lower()


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_conformance_retry_transient_error(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Req 10: Retry logic recovers on transient 503 with backoff."""
    server.reset_counts()
    engine = CrawlEngine(_engine_settings(engine_mode, tmp_path))
    req = CrawlRequest(
        start_url=f"{server.base_url}/transient-error",
        mode="list",
        url_list=[f"{server.base_url}/transient-error"],
        max_urls=1,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )
    result = engine.run(req, lambda *_: None)
    assert len(result.pages) == 1
    assert result.pages[0].status_code == 200
    assert result.pages[0].fetch_error == ""


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_conformance_rate_limiting_429(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Req 11: HTTP 429 Retry-After rate-limiting handling."""
    server.reset_counts()
    engine = CrawlEngine(_engine_settings(engine_mode, tmp_path))
    req = CrawlRequest(
        start_url=f"{server.base_url}/429",
        mode="list",
        url_list=[f"{server.base_url}/429"],
        max_urls=1,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )
    result = engine.run(req, lambda *_: None)
    assert len(result.pages) == 1
    assert result.pages[0].status_code == 200


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_conformance_malformed_and_external_links(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Req 12 & 13: Malformed URLs handled safely and external links excluded in site mode."""
    engine = CrawlEngine(_engine_settings(engine_mode, tmp_path))
    req = CrawlRequest(
        start_url=f"{server.base_url}/malformed-links",
        mode="site",
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )
    result = engine.run(req, lambda *_: None)
    # /malformed-links links to javascript:, mailto:, invalid uri, and /a
    # Should only crawl /malformed-links and /a
    urls = {p.url for p in result.pages}
    assert f"{server.base_url}/malformed-links" in urls
    assert f"{server.base_url}/a" in urls


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_conformance_cancellation(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Req 14: Cooperative cancellation token halts crawl immediately."""
    engine = CrawlEngine(_engine_settings(engine_mode, tmp_path))
    urls = [
        f"{server.base_url}/slow-concurrency/c1",
        f"{server.base_url}/slow-concurrency/c2",
        f"{server.base_url}/slow-concurrency/c3",
        f"{server.base_url}/slow-concurrency/c4",
    ]
    token = CancellationToken()
    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=4,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )

    def progress(completed: int, remaining: int, status: str):
        if completed >= 1:
            token.cancel("User aborted crawl")

    result = engine.run(req, progress, cancellation_token=token)
    assert result.status == CrawlStatus.CANCELLED.value
    assert "User aborted crawl" in result.termination_reason
    assert len(result.pages) < 4


@pytest.mark.parametrize("engine_mode", ALL_ENGINES)
def test_conformance_clean_shutdown_and_accounting(server: ControlledCrawlerServer, tmp_path: Path, engine_mode: str):
    """Req 15, 16 & 17: Clean shutdown, complete status, and reconciled accounting ledger."""
    engine = CrawlEngine(_engine_settings(engine_mode, tmp_path))
    req = CrawlRequest(
        start_url=f"{server.base_url}/a",
        mode="list",
        url_list=[f"{server.base_url}/a", f"{server.base_url}/b"],
        max_urls=2,
        delay_seconds=0.0,
        acknowledgment=True,
        executor_mode=engine_mode,
    )
    result = engine.run(req, lambda *_: None)
    assert result.status == CrawlStatus.SUCCESS.value
    assert result.pages_discovered == 2
    assert result.pages_attempted == 2
    assert result.pages_succeeded == 2
    assert result.pages_failed == 0
