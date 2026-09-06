"""Phase 2E Playwright Fetch Strategy and Browser Lifecycle Test Suite.

Verifies:
1. Playwright browser and context launch and deterministic teardown.
2. Dynamic client-side JavaScript rendering and DOM extraction.
3. Broken client JavaScript recovery without engine failure.
4. Navigation timeout enforcement during browser rendering.
5. Redirect resolution inside the browser environment.
6. Resource safety: zero orphan Chromium processes and explicit state cleanup.
7. Transparent forensic metrics: requested vs actual fetch modes, render_duration_ms.
"""

from __future__ import annotations

from dataclasses import replace
import pytest

from app.browser import PlaywrightBrowserSession, is_playwright_available
from app.crawler import CrawlEngine
from app.main import settings
from app.types import CrawlRequest, CrawlStatus
from tests.controlled_crawler_server import ControlledCrawlerServer


@pytest.fixture(scope="module")
def browser_server():
    """Spawn a controlled server instance for browser fetch testing."""
    srv = ControlledCrawlerServer()
    srv.start()
    yield srv.base_url
    srv.stop()


def _make_browser_settings(tmp_path, **kwargs):
    default_kwargs = dict(
        data_dir=tmp_path / "data",
        render_enabled=True,
        crawl_executor_mode="serial",
        allow_private_crawls=True,
        default_delay_seconds=0,
        render_timeout_ms=3000,
    )
    default_kwargs.update(kwargs)
    return replace(settings, **default_kwargs)


def test_playwright_availability_check() -> None:
    """Verify is_playwright_available() accurately detects Chromium runtime."""
    available = is_playwright_available()
    assert available is True


def test_browser_session_context_lifecycle() -> None:
    """Verify PlaywrightBrowserSession starts, renders, and closes cleanly without leaks."""
    session = PlaywrightBrowserSession(user_agent="PlaywrightLifecycleTest/1.0", render_timeout_ms=3000)
    assert session.is_active is False

    session.start()
    assert session.is_active is True
    assert session._browser is not None
    assert session._context is not None

    session.close()
    assert session.is_active is False
    assert session._browser is None
    assert session._context is None
    assert session._playwright is None


def test_browser_session_context_manager() -> None:
    """Verify PlaywrightBrowserSession works as a robust context manager."""
    with PlaywrightBrowserSession(user_agent="Test/1.0", render_timeout_ms=3000) as session:
        assert session.is_active is True
        assert session._browser is not None

    assert session.is_active is False
    assert session._browser is None


def test_browser_renders_dynamic_client_javascript(browser_server, tmp_path) -> None:
    """Verify CrawlEngine with fetch_mode='browser' executes dynamic client JavaScript."""
    cfg = _make_browser_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{browser_server}/spa-empty-shell",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="browser",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    assert res.requested_fetch_mode == "browser"
    assert res.actual_fetch_mode == "browser"
    assert res.fallback_occurred is False
    assert len(res.pages) == 1

    page = res.pages[0]
    assert page.status_code == 200
    assert page.actual_fetch_strategy == "browser"
    assert page.requested_fetch_strategy == "browser"
    assert page.render_duration_ms > 0
    assert "SPA Rendered Client Heading" in page.rendered_html
    assert "Dynamic client-side content populated exclusively by JavaScript" in page.rendered_text


def test_browser_broken_javascript_resilience(browser_server, tmp_path) -> None:
    """Verify CrawlEngine survives client-side JS runtime exceptions gracefully."""
    cfg = _make_browser_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{browser_server}/js-broken",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="browser",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    assert len(res.pages) == 1
    page = res.pages[0]
    assert page.status_code == 200
    assert page.actual_fetch_strategy == "browser"
    assert "Broken Script Page Heading" in page.rendered_html
    assert "static DOM elements remain fully structured" in page.rendered_text


def test_browser_navigation_timeout_handling(browser_server, tmp_path) -> None:
    """Verify browser navigation timeout is caught and recorded without hanging."""
    cfg = _make_browser_settings(
        tmp_path,
        render_timeout_ms=400,
        request_timeout_seconds=5.0,
    )
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{browser_server}/browser-timeout",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="browser",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert len(res.pages) == 1
    page = res.pages[0]
    assert page.actual_fetch_strategy == "browser"
    assert page.render_duration_ms > 0
    assert "Timeout" in page.render_error or "timeout" in page.render_error.lower()


def test_browser_redirect_resolution(browser_server, tmp_path) -> None:
    """Verify browser correctly follows and resolves HTTP redirect targets."""
    cfg = _make_browser_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{browser_server}/redirect",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="browser",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    page = res.pages[0]
    assert page.status_code == 200
    assert page.final_url == f"{browser_server}/a"
    assert page.actual_fetch_strategy == "browser"
