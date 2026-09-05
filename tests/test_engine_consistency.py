"""Cross-engine result consistency comparator verifying identical logical outputs across all 4 crawler engines."""

from __future__ import annotations

from pathlib import Path
import pytest

from app.config import Settings
from app.crawler import CrawlEngine
from app.types import CrawlRequest
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
        user_agent="ConsistencyComparator/1.0",
        default_url_cap=15,
        max_url_cap=30,
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
        async_concurrency=2,
        thread_workers=2,
        process_workers=2,
        allow_private_crawls=True,
    )


def test_cross_engine_deterministic_result_consistency(server: ControlledCrawlerServer, tmp_path: Path):
    """Verify Serial, Threaded, Coroutine, and Multiprocess produce logically equivalent crawl results on the same fixture."""
    engines = ["serial", "thread", "async", "process"]
    results = {}

    for mode in engines:
        engine = CrawlEngine(_engine_settings(mode, tmp_path / mode))
        req = CrawlRequest(
            start_url=f"{server.base_url}/",
            mode="site",
            max_urls=8,
            max_depth=2,
            delay_seconds=0.0,
            acknowledgment=True,
            executor_mode=mode,
        )
        res = engine.run(req, lambda *_: None)
        results[mode] = res

    # 1. Compare total page counts
    page_counts = {mode: len(res.pages) for mode, res in results.items()}
    assert len(set(page_counts.values())) == 1, f"Inconsistent page counts across engines: {page_counts}"

    # 2. Compare crawled URL sets
    url_sets = {mode: {p.url for p in res.pages} for mode, res in results.items()}
    serial_urls = url_sets["serial"]
    for mode in ["thread", "async", "process"]:
        assert url_sets[mode] == serial_urls, f"Discovered URLs differ between serial and {mode}: {url_sets[mode] ^ serial_urls}"

    # 3. Compare per-URL status codes and depths
    for url in serial_urls:
        statuses = {mode: next(p.status_code for p in results[mode].pages if p.url == url) for mode in engines}
        assert len(set(statuses.values())) == 1, f"Status code mismatch for {url}: {statuses}"

        depths = {mode: next(p.depth for p in results[mode].pages if p.url == url) for mode in engines}
        assert len(set(depths.values())) == 1, f"Depth mismatch for {url}: {depths}"

    # 4. Compare content hashes for identical endpoints
    for url in serial_urls:
        hashes = {mode: next(p.content_hash for p in results[mode].pages if p.url == url) for mode in engines}
        assert len(set(hashes.values())) == 1, f"Content hash mismatch for {url}: {hashes}"
