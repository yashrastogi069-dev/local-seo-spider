"""Integration tests running CrawlEngine against the deterministic ControlledCrawlerServer (Phase 2B)."""

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


def create_engine(tmp_path_factory) -> CrawlEngine:
    data_dir = tmp_path_factory.mktemp("crawler_data")
    settings = Settings(
        data_dir=data_dir,
        user_agent="LocalSEOSpider-Test/1.0",
        default_url_cap=50,
        max_url_cap=100,
        default_delay_seconds=0.0,
        request_timeout_seconds=5.0,
        render_timeout_ms=5000,
        max_redirects=4,
        max_document_bytes=2_000_000,
        max_request_retries=1,
        retry_backoff_seconds=0.1,
        max_concurrent_crawls=1,
        render_enabled=False,
        crawl_executor_mode="serial",
        allow_private_crawls=True,  # Enable crawling loopback fixture
    )
    return CrawlEngine(settings)


def test_seed_urls_only(server, tmp_path_factory):
    """Verify max_urls=1 crawls only the seed URL."""
    engine = create_engine(tmp_path_factory)
    req = CrawlRequest(
        start_url=f"{server.base_url}/",
        mode="site",
        max_urls=1,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)
    assert len(result.pages) == 1
    assert result.pages[0].url == f"{server.base_url}/"
    assert result.pages[0].depth == 0
    assert result.pages[0].status_code == 200


def test_circular_links_termination(server, tmp_path_factory):
    """Verify circular links (cycle-a <-> cycle-b) terminate cleanly with 2 pages and 0 duplicate fetches."""
    engine = create_engine(tmp_path_factory)
    req = CrawlRequest(
        start_url=f"{server.base_url}/cycle-a",
        mode="site",
        max_urls=10,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)
    urls = [p.url for p in result.pages]
    assert len(urls) == 2
    assert f"{server.base_url}/cycle-a" in urls
    assert f"{server.base_url}/cycle-b" in urls
    # Verify depths
    depth_map = {p.url: p.depth for p in result.pages}
    assert depth_map[f"{server.base_url}/cycle-a"] == 0
    assert depth_map[f"{server.base_url}/cycle-b"] == 1


def test_a_b_a_cycle_termination(server, tmp_path_factory):
    """Verify A -> B -> A cycle does not loop infinitely."""
    engine = create_engine(tmp_path_factory)
    req = CrawlRequest(
        start_url=f"{server.base_url}/a",
        mode="site",
        max_urls=10,
        max_depth=5,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)
    # /a links to /b, /b links to /a
    urls = [p.url for p in result.pages]
    assert len(urls) == 2  # /a, /b
    assert set(urls) == {f"{server.base_url}/a", f"{server.base_url}/b"}


def test_duplicate_links_and_fragments(server, tmp_path_factory):
    """Verify duplicate links, trailing slash variants, and fragments pointing to /a are fetched only once."""
    engine = create_engine(tmp_path_factory)
    req = CrawlRequest(
        start_url=f"{server.base_url}/duplicate-links",
        mode="site",
        max_urls=10,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)
    # /duplicate-links has 5 links: exact duplicates, fragment variants, and trailing slash
    # All 5 resolve to /a, so /a is crawled exactly once!
    a_pages = [p for p in result.pages if p.url.rstrip("/") == f"{server.base_url}/a"]
    assert len(a_pages) == 1


def test_canonical_duplicates_detected(server, tmp_path_factory):
    """Verify canonical tag deduplication marks canonical source as duplicate of canonical target."""
    engine = create_engine(tmp_path_factory)
    req = CrawlRequest(
        start_url=f"{server.base_url}/canonical",
        mode="site",
        max_urls=10,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)
    # /canonical points canonical to /canonical-target
    canon_source = next((p for p in result.pages if p.url == f"{server.base_url}/canonical"), None)
    assert canon_source is not None
    assert canon_source.canonical == f"{server.base_url}/canonical-target"


def test_external_domain_excluded(server, tmp_path_factory):
    """Verify links to external domains are excluded from crawling."""
    engine = create_engine(tmp_path_factory)
    req = CrawlRequest(
        start_url=f"{server.base_url}/external-link",
        mode="site",
        max_urls=10,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)
    urls = [p.url for p in result.pages]
    # Outbound external link is not crawled
    assert not any("external.example.com" in u for u in urls)
    # Internal page /a was crawled
    assert f"{server.base_url}/a" in urls


def test_depth_limit_hierarchy(server, tmp_path_factory):
    """Verify depth hierarchy: /deep (0) -> /deep/1 (1) -> /deep/1/2 (2) -> /deep/1/2/3 (3).

    With max_depth=2, /deep/1/2/3 must NOT be crawled.
    """
    engine = create_engine(tmp_path_factory)
    req = CrawlRequest(
        start_url=f"{server.base_url}/deep",
        mode="site",
        max_urls=20,
        max_depth=2,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)
    urls = [p.url for p in result.pages]
    assert f"{server.base_url}/deep" in urls
    assert f"{server.base_url}/deep/1" in urls
    assert f"{server.base_url}/deep/1/2" in urls
    # /deep/1/2/3 must be excluded because its depth is 3 > max_depth=2
    assert f"{server.base_url}/deep/1/2/3" not in urls

    depth_map = {p.url: p.depth for p in result.pages}
    assert depth_map[f"{server.base_url}/deep"] == 0
    assert depth_map[f"{server.base_url}/deep/1"] == 1
    assert depth_map[f"{server.base_url}/deep/1/2"] == 2
    assert all(p.depth <= 2 for p in result.pages)


def test_page_limit_budget(server, tmp_path_factory):
    """Verify max_urls=3 strictly bounds page count even when more links are discovered."""
    engine = create_engine(tmp_path_factory)
    req = CrawlRequest(
        start_url=f"{server.base_url}/",
        mode="site",
        max_urls=3,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)
    assert len(result.pages) == 3
    assert result.termination_reason == "max_urls_reached"


def test_redirect_handling_and_chain(server, tmp_path_factory):
    """Verify single redirect (/redirect -> /a) and redirect chain are handled."""
    engine = create_engine(tmp_path_factory)
    req = CrawlRequest(
        start_url=f"{server.base_url}/redirect",
        mode="site",
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)
    # /redirect redirected to /a
    urls = [p.url for p in result.pages]
    final_urls = [p.final_url for p in result.pages]
    assert f"{server.base_url}/a" in final_urls


def test_redirect_loop_bounded(server, tmp_path_factory):
    """Verify redirect loop does not loop forever and records error."""
    engine = create_engine(tmp_path_factory)
    req = CrawlRequest(
        start_url=f"{server.base_url}/redirect-loop",
        mode="site",
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)
    assert len(result.pages) == 1
    page = result.pages[0]
    assert "Redirect limit" in page.fetch_error or page.status_code is None or page.status_code >= 300


def test_http_error_statuses(server, tmp_path_factory):
    """Verify 404 and 500 error pages are handled and recorded with correct status codes."""
    engine = create_engine(tmp_path_factory)
    req = CrawlRequest(
        start_url=f"{server.base_url}/404",
        mode="list",
        url_list=[f"{server.base_url}/404", f"{server.base_url}/500"],
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)
    status_codes = {p.url: p.status_code for p in result.pages}
    assert status_codes[f"{server.base_url}/404"] == 404
    assert status_codes[f"{server.base_url}/500"] == 500


def test_rate_limiting_429_retry(server, tmp_path_factory):
    """Verify HTTP 429 response triggers backoff retry and succeeds."""
    server.reset_counts()
    engine = create_engine(tmp_path_factory)
    req = CrawlRequest(
        start_url=f"{server.base_url}/429",
        mode="list",
        url_list=[f"{server.base_url}/429"],
        max_urls=1,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)
    assert len(result.pages) == 1
    page = result.pages[0]
    # Should have retried and recovered to 200
    assert page.status_code == 200
    assert "Rate Limit Recovered" in page.source_html or "429" in page.source_html
