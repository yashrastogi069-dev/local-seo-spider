"""Phase 2E Smart Escalation Test Suite.

Verifies:
1. Normal static pages with or without script tags do NOT escalate to browser.
2. Empty application shells (SPAs) dynamically escalate to browser rendering.
3. Bot / JS challenges dynamically escalate to browser rendering.
4. Non-HTML content types are never escalated.
5. Transparency invariants: requested vs actual fetch modes, escalation reasons, and timing.
6. Multi-page mixed crawl accurately counts pages_escalated.
7. Database persistence preserves all Phase 2E strategy and escalation columns.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import pytest

from app.crawler import CrawlEngine
from app.database import Database
from app.escalation import should_escalate_to_browser
from app.main import settings
from app.types import CrawlRequest, CrawlStatus
from tests.controlled_crawler_server import ControlledCrawlerServer


@pytest.fixture(scope="module")
def escalation_server():
    """Spawn a controlled server instance for smart escalation testing."""
    srv = ControlledCrawlerServer()
    srv.start()
    yield srv.base_url
    srv.stop()


def _make_smart_settings(tmp_path: Path, **kwargs):
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


def test_unit_escalation_rules() -> None:
    """Verify should_escalate_to_browser function with fine-grained unit assertions."""
    # Rule 1: Configured browser requirement
    escalate, reason = should_escalate_to_browser(200, {"content-type": "text/html"}, "<p>Hi</p>", "Hi", configured_fetch_mode="browser")
    assert escalate is True
    assert reason == "configured_browser_requirement"

    # Rule 2: Static mode never escalates
    escalate, reason = should_escalate_to_browser(200, {"content-type": "text/html"}, '<div id="root"></div><script src="app.js"></script>', "", configured_fetch_mode="static")
    assert escalate is False
    assert reason == ""

    # Rule 3: Non-HTML content never escalates
    escalate, reason = should_escalate_to_browser(200, {"content-type": "application/json"}, '{"id": 1}', "id 1", configured_fetch_mode="smart")
    assert escalate is False
    assert reason == ""

    # Rule 4: Normal static HTML with script tags (analytics) does NOT escalate
    static_html = """
    <html><head><script src="analytics.js"></script></head>
    <body><h1>Blog Post</h1><p>Full article body copy with plenty of text explaining everything clearly.</p></body></html>
    """
    escalate, reason = should_escalate_to_browser(200, {"content-type": "text/html"}, static_html, "Blog Post Full article body copy with plenty of text explaining everything clearly.", configured_fetch_mode="smart")
    assert escalate is False
    assert reason == ""

    # Rule 5: SPA empty shell escalates
    spa_html = '<html><body><div id="root"></div><script src="bundle.js"></script></body></html>'
    escalate, reason = should_escalate_to_browser(200, {"content-type": "text/html"}, spa_html, "", configured_fetch_mode="smart")
    assert escalate is True
    assert reason == "empty_application_shell"

    # Rule 6: JS challenge escalates
    challenge_html = '<html><head><title>Just a moment...</title></head><body><h1>Checking your browser before accessing</h1></body></html>'
    escalate, reason = should_escalate_to_browser(200, {"content-type": "text/html"}, challenge_html, "Checking your browser", configured_fetch_mode="smart")
    assert escalate is True
    assert reason == "js_challenge"


def test_smart_mode_clean_static_page_does_not_escalate(escalation_server, tmp_path) -> None:
    """Verify clean static HTML stays in static fetch with zero escalation."""
    cfg = _make_smart_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{escalation_server}/static-clean",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="smart",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    assert res.requested_fetch_mode == "smart"
    assert res.actual_fetch_mode == "smart"
    assert res.pages_escalated == 0
    assert len(res.pages) == 1

    page = res.pages[0]
    assert page.requested_fetch_strategy == "smart"
    assert page.actual_fetch_strategy == "static"
    assert page.escalated is False
    assert page.escalation_reason == ""
    assert page.render_duration_ms == 0.0


def test_smart_mode_static_page_with_scripts_does_not_escalate(escalation_server, tmp_path) -> None:
    """Verify static HTML containing script tags (analytics) does NOT trigger escalation."""
    cfg = _make_smart_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{escalation_server}/static-with-scripts",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="smart",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    assert res.pages_escalated == 0
    assert len(res.pages) == 1

    page = res.pages[0]
    assert page.requested_fetch_strategy == "smart"
    assert page.actual_fetch_strategy == "static"
    assert page.escalated is False
    assert page.escalation_reason == ""
    assert page.render_duration_ms == 0.0
    assert "Static Page With Script Tags" in page.headings.get("h1", [])


def test_smart_mode_spa_shell_escalates_to_browser(escalation_server, tmp_path) -> None:
    """Verify empty SPA shell triggers smart escalation and renders client-side JS DOM."""
    cfg = _make_smart_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{escalation_server}/spa-empty-shell",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="smart",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    assert res.requested_fetch_mode == "smart"
    assert res.actual_fetch_mode == "smart"
    assert res.pages_escalated == 1
    assert len(res.pages) == 1

    page = res.pages[0]
    assert page.requested_fetch_strategy == "smart"
    assert page.actual_fetch_strategy == "browser"
    assert page.escalated is True
    assert page.escalation_reason == "empty_application_shell"
    assert page.render_duration_ms > 0
    assert "SPA Rendered Client Heading" in page.rendered_html
    assert "Dynamic client-side content populated exclusively by JavaScript" in page.rendered_text


def test_smart_mode_js_challenge_escalates_to_browser(escalation_server, tmp_path) -> None:
    """Verify bot / JS verification gate triggers smart escalation."""
    cfg = _make_smart_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{escalation_server}/js-challenge",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="smart",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    assert res.pages_escalated == 1
    assert len(res.pages) == 1

    page = res.pages[0]
    assert page.requested_fetch_strategy == "smart"
    assert page.actual_fetch_strategy == "browser"
    assert page.escalated is True
    assert page.escalation_reason == "js_challenge"
    assert page.render_duration_ms > 0
    assert "Protected Content Unlocked" in page.rendered_html


def test_mixed_crawl_smart_escalation_accounting(escalation_server, tmp_path) -> None:
    """Verify mixed crawl correctly segregates static vs escalated pages."""
    cfg = _make_smart_settings(tmp_path)
    engine = CrawlEngine(cfg)
    urls = [
        f"{escalation_server}/static-clean",
        f"{escalation_server}/spa-empty-shell",
        f"{escalation_server}/static-with-scripts",
    ]
    req = CrawlRequest(
        start_url=urls[0],
        mode="list",
        url_list=urls,
        max_urls=3,
        acknowledgment=True,
        fetch_mode="smart",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    assert len(res.pages) == 3
    assert res.pages_escalated == 1

    page_map = {p.url: p for p in res.pages}
    assert page_map[urls[0]].escalated is False
    assert page_map[urls[0]].actual_fetch_strategy == "static"

    assert page_map[urls[1]].escalated is True
    assert page_map[urls[1]].actual_fetch_strategy == "browser"
    assert page_map[urls[1]].escalation_reason == "empty_application_shell"

    assert page_map[urls[2]].escalated is False
    assert page_map[urls[2]].actual_fetch_strategy == "static"


def test_database_persistence_of_phase_2e_fields(escalation_server, tmp_path) -> None:
    """Verify Phase 2E strategy and escalation columns persist to SQLite and deserialize faithfully."""
    cfg = _make_smart_settings(tmp_path)
    db = Database(cfg.database_path)
    db.initialize()

    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{escalation_server}/spa-empty-shell",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="smart",
    )
    crawl_id = db.create_crawl(req)
    req.crawl_id = crawl_id

    res = engine.run(req, lambda cur, tot, st: None)
    assert len(res.pages) == 1

    # Persist crawl to database
    db.replace_pages_and_links(crawl_id, res.pages, res.links)

    # Query back from database
    stored_pages = db.get_pages(crawl_id=crawl_id)
    assert len(stored_pages) == 1
    stored = stored_pages[0]

    assert stored["url"] == f"{escalation_server}/spa-empty-shell"
    assert stored["requested_fetch_strategy"] == "smart"
    assert stored["actual_fetch_strategy"] == "browser"
    assert stored["escalated"] is True
    assert stored["escalation_reason"] == "empty_application_shell"
    assert stored["render_duration_ms"] > 0


def test_crawl_result_to_dict_includes_pages_escalated(escalation_server, tmp_path) -> None:
    """Verify CrawlResult.to_dict() includes pages_escalated field (DEF-2E-01)."""
    cfg = _make_smart_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{escalation_server}/spa-empty-shell",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="smart",
    )
    res = engine.run(req, lambda cur, tot, st: None)
    d = res.to_dict()
    assert "pages_escalated" in d
    assert d["pages_escalated"] == 1


def test_multi_worker_smart_mode_reports_explicit_fallback(escalation_server, tmp_path) -> None:
    """Verify multi-worker engine running smart mode reports fallback_occurred and fallback_reason (DEF-2E-02)."""
    cfg = _make_smart_settings(
        tmp_path,
        crawl_executor_mode="thread",
        thread_workers=2,
    )
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{escalation_server}/spa-empty-shell",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="smart",
        executor_mode="thread",
    )
    res = engine.run(req, lambda cur, tot, st: None)
    assert res.fallback_occurred is True
    assert "Smart escalation is unsupported in multi-worker static executor" in res.fallback_reason
    assert res.requested_fetch_mode == "smart"
    assert res.actual_fetch_mode == "static"


def test_spa_container_with_attributes_escalates() -> None:
    """Verify SPA container with extra attributes is detected and escalates (DEF-2E-04)."""
    html_with_attrs = '<html><body><div class="react-mount" id="root" data-testid="app"></div><script src="bundle.js"></script></body></html>'
    escalate, reason = should_escalate_to_browser(
        status_code=200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        source_html=html_with_attrs,
        extracted_text="",
        configured_fetch_mode="smart",
    )
    assert escalate is True
    assert reason == "empty_application_shell"
