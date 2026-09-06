"""Phase 2F Test Suite: Crawl Budgets (max_pages, max_depth, max_bytes, max_duration_seconds, max_retries, redirect_limit)."""

import time
import pytest

from app.config import Settings
from app.crawler import CrawlEngine
from app.types import CrawlBudget, CrawlRequest, CrawlStatus
from tests.controlled_crawler_server import ControlledCrawlerServer


@pytest.fixture(scope="module")
def server():
    srv = ControlledCrawlerServer()
    srv.start()
    yield srv
    srv.stop()


def create_engine(tmp_path_factory, executor_mode="serial") -> CrawlEngine:
    data_dir = tmp_path_factory.mktemp(f"crawler_budget_{executor_mode}")
    settings = Settings(
        data_dir=data_dir,
        user_agent="LocalSEOSpider-Test/1.0",
        default_url_cap=50,
        max_url_cap=100,
        default_delay_seconds=0.0,
        request_timeout_seconds=5.0,
        render_timeout_ms=5000,
        max_redirects=5,
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


@pytest.mark.parametrize("engine_mode", ["serial", "thread", "async", "process"])
def test_budget_max_pages_exhaustion(server, tmp_path_factory, engine_mode):
    """Verify that reaching budget.max_pages transitions to BUDGET_EXHAUSTED with explicit reason."""
    server.reset_counts()
    server.server.robots_status_code = 200
    server.server.robots_content = "User-agent: *\nAllow: /\n"

    engine = create_engine(tmp_path_factory, engine_mode)
    budget = CrawlBudget(max_pages=2)
    req = CrawlRequest(
        start_url=f"{server.base_url}/",
        mode="site",
        max_urls=10,  # Legacy parameter higher than budget
        delay_seconds=0.0,
        acknowledgment=True,
        budget=budget,
    )
    result = engine.run(req, lambda *_: None)

    assert len(result.pages) == 2
    assert result.status == CrawlStatus.BUDGET_EXHAUSTED.value
    assert "budget_exhausted: max_pages reached (2 >= 2)" in result.termination_reason


def test_budget_max_depth_enforcement(server, tmp_path_factory):
    """Verify max_depth budget bounds queue admittance."""
    server.reset_counts()
    server.server.robots_status_code = 200
    server.server.robots_content = "User-agent: *\nAllow: /\n"

    engine = create_engine(tmp_path_factory, "serial")
    # /deep -> /deep/1 -> /deep/1/2 -> /deep/1/2/3
    budget = CrawlBudget(max_depth=1)
    req = CrawlRequest(
        start_url=f"{server.base_url}/deep",
        mode="site",
        max_urls=10,
        delay_seconds=0.0,
        acknowledgment=True,
        budget=budget,
    )
    result = engine.run(req, lambda *_: None)

    # depth 0 is /deep, depth 1 is /deep/1. /deep/1/2 should not be crawled
    urls = [p.url for p in result.pages]
    assert f"{server.base_url}/deep" in urls
    assert f"{server.base_url}/deep/1" in urls
    assert not any("/deep/1/2" in u for u in urls)
    for p in result.pages:
        assert p.depth <= 1


@pytest.mark.parametrize("engine_mode", ["serial", "thread", "async", "process"])
def test_budget_max_bytes_exhaustion(server, tmp_path_factory, engine_mode):
    """Verify that exceeding cumulative response bytes terminates crawl with BUDGET_EXHAUSTED."""
    server.reset_counts()
    server.server.robots_status_code = 200
    server.server.robots_content = "User-agent: *\nAllow: /\n"

    engine = create_engine(tmp_path_factory, engine_mode)
    # /budget/bytes/30 returns ~30 KB. With max_bytes=45_000, 2nd fetch pushes cumulative > 45 KB
    urls = [
        f"{server.base_url}/budget/bytes/30",
        f"{server.base_url}/budget/bytes/30?b=2",
        f"{server.base_url}/budget/bytes/30?b=3",
    ]
    budget = CrawlBudget(max_bytes=45_000)
    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=10,
        delay_seconds=0.0,
        acknowledgment=True,
        budget=budget,
    )
    result = engine.run(req, lambda *_: None)

    assert result.status == CrawlStatus.BUDGET_EXHAUSTED.value
    assert "budget_exhausted: max_bytes reached" in result.termination_reason
    assert result.total_response_bytes >= 45_000
    # Must have terminated before fetching all 3
    assert len(result.pages) <= 2


@pytest.mark.parametrize("engine_mode", ["serial", "thread", "async", "process"])
def test_budget_max_duration_seconds_exhaustion(server, tmp_path_factory, engine_mode):
    """Verify that wall-clock time limit terminates crawl with BUDGET_EXHAUSTED."""
    server.reset_counts()
    server.server.robots_status_code = 200
    server.server.robots_content = "User-agent: *\nAllow: /\n"

    engine = create_engine(tmp_path_factory, engine_mode)
    # 3 endpoints sleeping 0.25s each. With max_duration_seconds and per_host_concurrency=1:
    urls = [
        f"{server.base_url}/budget/slow/1?delay=0.25",
        f"{server.base_url}/budget/slow/2?delay=0.25",
        f"{server.base_url}/budget/slow/3?delay=0.25",
    ]
    max_dur = 0.6 if engine_mode == "process" else 0.35
    budget = CrawlBudget(max_duration_seconds=max_dur)
    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=10,
        delay_seconds=0.0,
        acknowledgment=True,
        budget=budget,
        per_host_concurrency=1,
    )
    t0 = time.monotonic()
    result = engine.run(req, lambda *_: None)
    t1 = time.monotonic()

    assert result.status == CrawlStatus.BUDGET_EXHAUSTED.value
    assert "budget_exhausted: max_crawl_duration exceeded" in result.termination_reason
    # Should have executed at least 1 but not all 3
    assert len(result.pages) < 3


def test_budget_redirect_limit_enforcement(server, tmp_path_factory):
    """Verify redirect_limit in budget overrides default redirect limit."""
    server.reset_counts()
    server.server.robots_status_code = 200
    server.server.robots_content = "User-agent: *\nAllow: /\n"

    engine = create_engine(tmp_path_factory, "serial")
    # /redirect-chain has 3 hops: chain-1 -> chain-2 -> chain-3 -> a
    budget = CrawlBudget(redirect_limit=1)
    req = CrawlRequest(
        start_url=f"{server.base_url}/redirect-chain",
        mode="site",
        max_urls=5,
        delay_seconds=0.0,
        acknowledgment=True,
        budget=budget,
    )
    result = engine.run(req, lambda *_: None)

    assert len(result.pages) == 1
    page = result.pages[0]
    assert page.fetch_error is not None
    assert "redirect" in page.fetch_error.lower() or "attempt" in page.fetch_error.lower()
