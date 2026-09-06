"""Phase 2F Test Suite: Robots.txt RFC 9309 compliance and Politeness Throttling."""

import time
import pytest

from app.config import Settings
from app.crawler import CrawlEngine, extract_crawl_delay, DomainPolitenessThrottler, AsyncDomainPolitenessThrottler
from app.types import CrawlRequest, CrawlStatus
from tests.controlled_crawler_server import ControlledCrawlerServer


@pytest.fixture(scope="module")
def server():
    srv = ControlledCrawlerServer()
    srv.start()
    yield srv
    srv.stop()


def create_engine(tmp_path_factory, executor_mode="serial", user_agent="LocalSEOSpider-Test/1.0") -> CrawlEngine:
    data_dir = tmp_path_factory.mktemp(f"crawler_robots_{executor_mode}")
    settings = Settings(
        data_dir=data_dir,
        user_agent=user_agent,
        default_url_cap=50,
        max_url_cap=100,
        default_delay_seconds=0.0,
        request_timeout_seconds=5.0,
        render_timeout_ms=5000,
        max_redirects=4,
        max_document_bytes=2_000_000,
        max_request_retries=1,
        retry_backoff_seconds=0.05,
        max_concurrent_crawls=1,
        render_enabled=False,
        crawl_executor_mode=executor_mode,
        thread_workers=3,
        async_concurrency=3,
        process_workers=2,
        allow_private_crawls=True,
    )
    return CrawlEngine(settings)


def test_extract_crawl_delay():
    """Verify extract_crawl_delay parses integer and float values with user-agent specificity."""
    # 1. Global float delay
    lines1 = [
        "User-agent: *",
        "Disallow: /admin",
        "Crawl-delay: 2.5",
    ]
    assert extract_crawl_delay(lines1, "MyBot/1.0") == 2.5

    # 2. Specific user agent takes precedence
    lines2 = [
        "User-agent: *",
        "Crawl-delay: 10",
        "User-agent: LocalSEOSpider",
        "Crawl-delay: 0.5",
    ]
    assert extract_crawl_delay(lines2, "LocalSEOSpider/2.0") == 0.5
    assert extract_crawl_delay(lines2, "OtherBot/1.0") == 10.0

    # 3. Missing crawl delay
    lines3 = [
        "User-agent: *",
        "Disallow: /secret",
    ]
    assert extract_crawl_delay(lines3, "MyBot/1.0") is None


def test_robots_allow_and_disallow(server, tmp_path_factory):
    """Verify disallow rules are enforced and disallowed pages marked skipped and recorded."""
    server.reset_counts()
    server.server.robots_status_code = 200
    server.server.robots_content = "User-agent: *\nDisallow: /blocked\nAllow: /\n"

    engine = create_engine(tmp_path_factory, "serial")
    req = CrawlRequest(
        start_url=f"{server.base_url}/robots-test",
        mode="site",
        max_urls=10,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)

    urls = [p.url for p in result.pages]
    assert any("/robots-allowed" in u for u in urls)
    blocked_pages = [p for p in result.pages if "/blocked" in p.url]
    assert len(blocked_pages) == 1
    assert blocked_pages[0].fetch_error == "robots_disallowed"
    assert result.robots_status == "loaded"


def test_robots_missing_404_allow_all(server, tmp_path_factory):
    """RFC 9309 section 3.3.1: Missing robots.txt (404) MUST result in allow-all."""
    server.reset_counts()
    server.server.robots_status_code = 404

    engine = create_engine(tmp_path_factory, "serial")
    req = CrawlRequest(
        start_url=f"{server.base_url}/",
        mode="site",
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)

    assert "404" in result.robots_status
    assert "allow-all" in result.robots_status
    assert len(result.pages) > 0
    # In allow-all, even /blocked is allowed to be crawled
    blocked_page = next((p for p in result.pages if "/blocked" in p.url), None)
    if blocked_page:
        assert blocked_page.status_code == 200
        assert blocked_page.fetch_error == ""


def test_robots_server_error_500_fail_closed(server, tmp_path_factory):
    """RFC 9309 section 3.3.1: Server errors (5xx) MUST fail-closed / disallow-all."""
    server.reset_counts()
    server.server.robots_status_code = 500

    engine = create_engine(tmp_path_factory, "serial")
    req = CrawlRequest(
        start_url=f"{server.base_url}/",
        mode="site",
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)

    assert "fail-closed RFC 9309" in result.robots_status
    # With fail-closed, start_url cannot be fetched
    assert len(result.pages) == 1
    assert result.pages[0].fetch_error == "robots_disallowed"


def test_robots_malformed_syntax_graceful(server, tmp_path_factory):
    """Verify malformed robots.txt content does not crash the parser and valid rules apply."""
    server.reset_counts()
    server.server.robots_status_code = 200
    server.server.robots_content = (
        "GARBAGE LINE WITHOUT COLON\n"
        "::::invalid::::\n"
        "User-agent: *\n"
        "Disallow: /blocked\n"
        "Random unexpected string\n"
    )

    engine = create_engine(tmp_path_factory, "serial")
    req = CrawlRequest(
        start_url=f"{server.base_url}/",
        mode="site",
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)

    assert result.robots_status == "loaded"
    blocked = [p for p in result.pages if "/blocked" in p.url]
    if blocked:
        assert blocked[0].fetch_error == "robots_disallowed"


def test_robots_user_agent_specificity(server, tmp_path_factory):
    """Verify user-agent specific blocks are honored over wildcard rules."""
    server.reset_counts()
    server.server.robots_status_code = 200
    server.server.robots_content = (
        "User-agent: OtherBot\n"
        "Disallow: /a\n"
        "\n"
        "User-agent: LocalSEOSpider-Test\n"
        "Disallow: /b\n"
        "\n"
        "User-agent: *\n"
        "Disallow: /blocked\n"
    )

    engine = create_engine(tmp_path_factory, "serial", user_agent="LocalSEOSpider-Test/1.0")
    req = CrawlRequest(
        start_url=f"{server.base_url}/",
        mode="site",
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
    )
    result = engine.run(req, lambda *_: None)

    # LocalSEOSpider-Test has Disallow: /b, but /a is allowed
    a_page = next((p for p in result.pages if "/a" in p.url and not "/blocked" in p.url), None)
    b_page = next((p for p in result.pages if "/b" in p.url), None)
    if a_page:
        assert a_page.status_code == 200
    if b_page:
        assert b_page.fetch_error == "robots_disallowed"


def test_respect_robots_txt_disabled(server, tmp_path_factory):
    """When respect_robots_txt=False, robots disallow rules are completely bypassed."""
    server.reset_counts()
    server.server.robots_status_code = 200
    server.server.robots_content = "User-agent: *\nDisallow: /\n"

    engine = create_engine(tmp_path_factory, "serial")
    req = CrawlRequest(
        start_url=f"{server.base_url}/",
        mode="site",
        max_urls=3,
        delay_seconds=0.0,
        acknowledgment=True,
        respect_robots_txt=False,
    )
    result = engine.run(req, lambda *_: None)

    assert result.robots_status == "disabled_by_configuration"
    assert len(result.pages) > 0
    assert result.pages[0].status_code == 200
    assert result.pages[0].fetch_error == ""


@pytest.mark.parametrize("engine_mode", ["thread", "async", "process"])
def test_per_host_concurrency_bounded(server, tmp_path_factory, engine_mode):
    """Verify that per_host_concurrency=1 restricts in-flight requests to the same host to 1."""
    server.reset_counts()
    server.reset_concurrency_stats()
    server.server.robots_status_code = 200
    server.server.robots_content = "User-agent: *\nAllow: /\n"

    engine = create_engine(tmp_path_factory, engine_mode)
    
    # We request 3 slow concurrency items on the same host with per_host_concurrency=1
    urls = [
        f"{server.base_url}/slow-concurrency/1?delay=0.15",
        f"{server.base_url}/slow-concurrency/2?delay=0.15",
        f"{server.base_url}/slow-concurrency/3?delay=0.15",
    ]
    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=3,
        delay_seconds=0.0,
        acknowledgment=True,
        per_host_concurrency=1,
    )
    t0 = time.monotonic()
    result = engine.run(req, lambda *_: None)
    t1 = time.monotonic()

    assert result.status == CrawlStatus.SUCCESS.value
    assert len(result.pages) == 3
    # With per_host_concurrency=1 and 3 items of 0.15s delay, serial execution takes >= 0.40s
    assert t1 - t0 >= 0.35, f"Expected serialization due to per_host_concurrency=1, took {t1 - t0:.2f}s"
    # Peak server concurrency must not exceed 1
    assert server.get_peak_concurrency() <= 1


def test_domain_throttler_multi_host_isolation():
    """Verify DomainPolitenessThrottler allows different hosts to execute concurrently."""
    throttler = DomainPolitenessThrottler(delay_seconds=0.2, per_host_concurrency=1)

    t0 = time.monotonic()
    with throttler.acquire("http://host-a.com/page1"):
        pass
    with throttler.acquire("http://host-b.com/page1"):
        pass
    t1 = time.monotonic()

    # Host A and Host B are different domains, so host B does not wait for host A's delay
    assert t1 - t0 < 0.15, f"Multi-host requests should not block each other, took {t1 - t0:.2f}s"


def test_serial_respects_robots_crawl_delay(server, tmp_path_factory):
    """Verify that serial crawler engine respects Crawl-delay directive parsed from robots.txt."""
    server.reset_counts()
    server.server.robots_status_code = 200
    # Set crawl delay to 0.2s for our bot
    server.server.robots_content = "User-agent: *\nCrawl-delay: 0.2\nAllow: /\n"

    engine = create_engine(tmp_path_factory, "serial")
    urls = [
        f"{server.base_url}/robots-allowed",
        f"{server.base_url}/robots-test",
    ]
    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=2,
        delay_seconds=0.0,  # Request specifies 0s, but robots.txt has 0.2s
        acknowledgment=True,
    )
    t0 = time.monotonic()
    result = engine.run(req, lambda *_: None)
    t1 = time.monotonic()

    assert result.status == CrawlStatus.SUCCESS.value
    assert len(result.pages) == 2
    # Crawling 2 pages with Crawl-delay of 0.2s must take >= 0.18s
    assert t1 - t0 >= 0.18, f"Expected crawl-delay spacing of >=0.18s, took {t1 - t0:.2f}s"
