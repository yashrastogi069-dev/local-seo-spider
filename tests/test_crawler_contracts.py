"""Contract tests for Crawler Core state models, contracts, and provenance.

Validates Phase 2A requirements:
- REQ-CRAWL-001: Unified Engine Contract and result states
- REQ-CRAWL-002: Frontier item with depth and parent tracking
- REQ-CRAWL-007: No silent fallback detection (engine and fetch mode mismatches)
- REQ-CRAWL-008: Fetch strategy transparency (static vs browser)
- REQ-CRAWL-012: Cancellation token contract
- Resource provenance tracking on PageRecord
- Backward-compatibility tuple unpacking of CrawlResult
"""

from __future__ import annotations

import json
from dataclasses import asdict
import pytest

from app.types import (
    CancellationToken,
    CrawlRequest,
    CrawlResult,
    CrawlStatus,
    EngineMode,
    FetchMode,
    FrontierItem,
    LinkRecord,
    PageRecord,
)


def test_crawl_status_enum_values() -> None:
    """Verify all 5 required crawl result states are defined."""
    assert CrawlStatus.SUCCESS == "success"
    assert CrawlStatus.PARTIAL == "partial"
    assert CrawlStatus.FAILED == "failed"
    assert CrawlStatus.CANCELLED == "cancelled"
    assert CrawlStatus.BUDGET_EXHAUSTED == "budget_exhausted"


def test_engine_mode_enum_values() -> None:
    """Verify all 4 engine modes are defined."""
    assert EngineMode.SERIAL == "serial"
    assert EngineMode.THREAD == "thread"
    assert EngineMode.ASYNC == "async"
    assert EngineMode.PROCESS == "process"


def test_fetch_mode_enum_values() -> None:
    """Verify fetch modes are defined."""
    assert FetchMode.STATIC == "static"
    assert FetchMode.BROWSER == "browser"


def test_crawl_result_initialization_and_contracts() -> None:
    """Verify CrawlResult exposes all required observability and accounting metrics."""
    result = CrawlResult(
        crawl_id="crawl-test-1",
        requested_engine=EngineMode.SERIAL.value,
        actual_engine=EngineMode.SERIAL.value,
        requested_fetch_mode=FetchMode.STATIC.value,
        actual_fetch_mode=FetchMode.STATIC.value,
        fallback_occurred=False,
        fallback_reason="",
        started_at="2026-09-05T12:00:00Z",
        finished_at="2026-09-05T12:00:02Z",
        duration_ms=2000.0,
        status=CrawlStatus.SUCCESS.value,
        termination_reason="queue_empty",
        pages_discovered=5,
        pages_attempted=5,
        pages_succeeded=4,
        pages_failed=1,
        pages_skipped=0,
        duplicates_count=0,
        retry_count=1,
        errors=["HTTP 404 on /missing"],
        pages=[],
        links=[],
        robots_status="loaded",
    )

    assert result.status == CrawlStatus.SUCCESS.value
    assert result.requested_engine == result.actual_engine
    assert result.requested_fetch_mode == result.actual_fetch_mode
    assert not result.fallback_occurred
    assert result.pages_attempted == result.pages_succeeded + result.pages_failed


def test_crawl_result_backward_compatible_tuple_unpacking() -> None:
    """Verify CrawlResult can be unpacked as (pages, links, robots_status) for legacy callers."""
    page = PageRecord(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        content_type="text/html",
        title="Example",
        description="Desc",
        headings={},
        canonical="https://example.com",
        meta_robots="",
        x_robots="",
        source_html="<p>Test</p>",
        rendered_html="",
        rendered_text="Test",
        images=[],
        structured_data=[],
        redirect_chain=[],
    )
    link = LinkRecord(
        source_url="https://example.com",
        target_url="https://example.com/about",
        raw_target_url="/about",
        anchor_text="About",
        rel="",
        is_internal=True,
        nofollow=False,
    )
    result = CrawlResult(
        requested_engine="serial",
        actual_engine="serial",
        requested_fetch_mode="static",
        actual_fetch_mode="static",
        pages=[page],
        links=[link],
        robots_status="loaded",
    )

    # Legacy tuple unpacking: pages, links, robots_status = engine.run(...)
    pages, links, robots_status = result
    assert len(pages) == 1
    assert len(links) == 1
    assert robots_status == "loaded"
    assert pages[0].title == "Example"

    # Sequence indexing and length
    assert len(result) == 3
    assert result[0] is pages
    assert result[1] is links
    assert result[2] == "loaded"


def test_fallback_detection_contract() -> None:
    """Verify fallback detection correctly flags when actual engine or fetch mode diverges."""
    mismatched = CrawlResult(
        requested_engine=EngineMode.THREAD.value,
        actual_engine=EngineMode.SERIAL.value,
        requested_fetch_mode=FetchMode.BROWSER.value,
        actual_fetch_mode=FetchMode.STATIC.value,
        fallback_occurred=True,
        fallback_reason="Browser rendering unsupported in thread mode",
        status=CrawlStatus.PARTIAL.value,
    )
    assert mismatched.fallback_occurred
    assert mismatched.requested_engine != mismatched.actual_engine
    assert mismatched.requested_fetch_mode != mismatched.actual_fetch_mode
    assert "Browser rendering unsupported" in mismatched.fallback_reason


def test_page_record_provenance_fields() -> None:
    """Verify PageRecord preserves all required resource provenance fields."""
    page = PageRecord(
        url="https://example.com/start",
        final_url="https://example.com/final",
        status_code=200,
        content_type="text/html",
        title="Provenance Test",
        description="",
        headings={},
        canonical="https://example.com/final",
        meta_robots="",
        x_robots="",
        source_html="<html></html>",
        rendered_html="",
        rendered_text="",
        images=[],
        structured_data=[],
        redirect_chain=[{"url": "https://example.com/start", "status_code": 301, "location": "/final"}],
        # Phase 2A Provenance fields:
        normalized_url="https://example.com/start",
        parent_url="https://example.com/seed",
        depth=2,
        fetch_strategy="static",
        crawler_engine="thread",
        response_bytes=1024,
        duration_ms=45.2,
        error_category="none",
        headers={"content-type": "text/html", "etag": "xyz-123"},
    )

    assert page.depth == 2
    assert page.parent_url == "https://example.com/seed"
    assert page.fetch_strategy == "static"
    assert page.crawler_engine == "thread"
    assert page.response_bytes == 1024
    assert page.duration_ms == 45.2
    assert page.error_category == "none"
    assert page.headers["etag"] == "xyz-123"

    # Verify serialization
    data = page.to_dict()
    assert data["depth"] == 2
    assert data["parent_url"] == "https://example.com/seed"
    assert data["fetch_strategy"] == "static"
    assert data["crawler_engine"] == "thread"
    assert data["response_bytes"] == 1024
    assert data["duration_ms"] == 45.2
    assert data["error_category"] == "none"


def test_frontier_item_contract() -> None:
    """Verify FrontierItem tracks URL, depth, parent_url, and retry state."""
    item = FrontierItem(
        url="https://example.com/blog/post-1",
        depth=3,
        parent_url="https://example.com/blog",
        discovered_at="2026-09-05T12:00:00Z",
        retry_count=1,
    )
    assert item.url == "https://example.com/blog/post-1"
    assert item.depth == 3
    assert item.parent_url == "https://example.com/blog"
    assert item.retry_count == 1
    assert item.to_tuple() == ("https://example.com/blog/post-1", 3, "https://example.com/blog")


def test_cancellation_token_contract() -> None:
    """Verify CancellationToken tracks cancellation state and reason."""
    token = CancellationToken()
    assert not token.is_cancelled()
    assert token.reason == ""

    token.cancel(reason="User clicked abort button")
    assert token.is_cancelled()
    assert token.reason == "User clicked abort button"


def test_crawl_result_serialization() -> None:
    """Verify CrawlResult serializes to dictionary and JSON cleanly."""
    result = CrawlResult(
        crawl_id="test-json",
        requested_engine="async",
        actual_engine="async",
        requested_fetch_mode="static",
        actual_fetch_mode="static",
        status=CrawlStatus.SUCCESS.value,
        pages_discovered=10,
        pages_attempted=10,
        pages_succeeded=10,
    )
    d = result.to_dict()
    assert d["crawl_id"] == "test-json"
    assert d["status"] == "success"
    assert d["requested_engine"] == "async"
    assert d["pages_discovered"] == 10

    # Ensure JSON serializable
    dumped = json.dumps(d)
    assert "test-json" in dumped


def test_crawl_engine_run_returns_crawl_result_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that CrawlEngine.run() returns a CrawlResult satisfying all contracts."""
    from pathlib import Path
    import httpx
    from app.config import Settings
    from app.crawler import CrawlEngine

    cfg = Settings(
        data_dir=Path("data"), user_agent="LocalSEOSpider/Test", default_url_cap=5, max_url_cap=10,
        default_delay_seconds=0, request_timeout_seconds=2, render_timeout_ms=1_000, max_redirects=2,
        max_document_bytes=20_000, max_request_retries=0, retry_backoff_seconds=0.1, max_concurrent_crawls=1,
        render_enabled=False, crawl_executor_mode="serial",
    )
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url="https://owned.example/",
        mode="list",
        url_list=["https://owned.example/a", "https://owned.example/b"],
        max_urls=2,
        delay_seconds=0,
        respect_nofollow=True,
        acknowledgment=True,
        executor_mode="serial",
    )

    monkeypatch.setattr(engine, "_robots", lambda client, start_url: (type("Policy", (), {"can_fetch": lambda self, agent, url: True})(), "loaded"))

    resp_a = httpx.Response(200, headers={"content-type": "text/html", "etag": "a1"}, content=b"<html><head><title>Page A</title></head><body><a href=\"/b\">B</a></body></html>", request=httpx.Request("GET", "https://owned.example/a"))
    resp_b = httpx.Response(200, headers={"content-type": "text/html", "etag": "b2"}, content=b"<html><head><title>Page B</title></head><body>Done</body></html>", request=httpx.Request("GET", "https://owned.example/b"))
    responses = {"https://owned.example/a": resp_a, "https://owned.example/b": resp_b}

    def fake_fetch(client, url):
        return responses[url], [], ""

    monkeypatch.setattr(engine, "_fetch", fake_fetch)

    result = engine.run(req, lambda *_: None)
    assert isinstance(result, CrawlResult)
    assert result.status == CrawlStatus.SUCCESS.value
    assert result.requested_engine == "serial"
    assert result.actual_engine == "serial"
    assert result.requested_fetch_mode == "static"
    assert result.actual_fetch_mode == "static"
    assert not result.fallback_occurred
    assert result.pages_discovered == 2
    assert result.pages_attempted == 2
    assert result.pages_succeeded == 2
    assert result.pages_failed == 0
    assert result.duration_ms >= 0.0

    # Test unpacking compatibility
    pages, links, robots = result
    assert len(pages) == 2
    assert robots == "loaded"

    # Test provenance on PageRecord
    for page in pages:
        assert page.crawler_engine == "serial"
        assert page.fetch_strategy == "static"
        assert page.requested_fetch_strategy == "static"
        assert page.actual_fetch_strategy == "static"
        assert page.response_bytes > 0
        assert page.error_category == "none"
        assert "content-type" in page.headers


def test_frontier_item_hashability_and_set_operations() -> None:
    """Verify FrontierItem can be hashed and added to sets for deduplication."""
    item1 = FrontierItem(url="https://example.com/a", depth=1, parent_url="https://example.com/")
    item2 = FrontierItem(url="https://example.com/a", depth=1, parent_url="https://example.com/")
    item3 = FrontierItem(url="https://example.com/b", depth=2, parent_url="https://example.com/a")

    visited = {item1}
    assert item2 in visited
    assert item3 not in visited
    visited.add(item3)
    assert len(visited) == 2


def test_ipc_picklability_for_multiprocess_engine() -> None:
    """Verify state models and tokens can be pickled across process boundaries."""
    import pickle

    # 1. CancellationToken picklability
    token = CancellationToken()
    token.cancel(reason="test abort")
    pickled_token = pickle.dumps(token)
    restored_token = pickle.loads(pickled_token)
    assert restored_token.is_cancelled()
    assert restored_token.reason == "test abort"

    # 2. FrontierItem picklability
    f_item = FrontierItem(url="https://example.com", depth=1, parent_url="https://seed.example")
    restored_f = pickle.loads(pickle.dumps(f_item))
    assert restored_f.url == f_item.url
    assert restored_f.depth == 1

    # 3. PageRecord picklability
    page = PageRecord(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        content_type="text/html",
        title="Pickle",
        description="",
        headings={},
        canonical="",
        meta_robots="",
        x_robots="",
        source_html="",
        rendered_html="",
        rendered_text="",
        images=[],
        structured_data=[],
        redirect_chain=[],
        headers={"content-type": "text/html"},
    )
    restored_page = pickle.loads(pickle.dumps(page))
    assert restored_page.title == "Pickle"
    assert restored_page.headers["content-type"] == "text/html"

    # 4. CrawlResult picklability
    result = CrawlResult(
        crawl_id="ipc-123",
        requested_engine="process",
        actual_engine="process",
        pages=[page],
    )
    restored_result = pickle.loads(pickle.dumps(result))
    assert restored_result.crawl_id == "ipc-123"
    assert len(restored_result.pages) == 1


def test_crawler_engine_protocol_conformance() -> None:
    """Verify CrawlerEngine conforms to CrawlerEngineProtocol."""
    from app.crawler import CrawlEngine
    from app.types import CrawlerEngineProtocol

    assert issubclass(CrawlEngine, CrawlerEngineProtocol)


def test_cooperative_cancellation_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify CrawlEngine cooperatively terminates and transitions to CANCELLED state."""
    from pathlib import Path
    from app.config import Settings
    from app.crawler import CrawlEngine

    cfg = Settings(
        data_dir=Path("data"), user_agent="LocalSEOSpider/Test", default_url_cap=5, max_url_cap=10,
        default_delay_seconds=0, request_timeout_seconds=2, render_timeout_ms=1_000, max_redirects=2,
        max_document_bytes=20_000, max_request_retries=0, retry_backoff_seconds=0.1, max_concurrent_crawls=1,
        render_enabled=False, crawl_executor_mode="serial",
    )
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url="https://owned.example/",
        mode="list",
        url_list=["https://owned.example/1", "https://owned.example/2", "https://owned.example/3"],
        max_urls=3,
        delay_seconds=0,
        respect_nofollow=True,
        acknowledgment=True,
        executor_mode="serial",
        crawl_id="test-cancel-job",
    )
    monkeypatch.setattr(engine, "_robots", lambda client, start_url: (type("Policy", (), {"can_fetch": lambda self, agent, url: True})(), "loaded"))

    token = CancellationToken()
    # Cancel token before starting or after first item
    token.cancel(reason="Operator issued abort")

    result = engine.run(req, lambda *_: None, cancellation_token=token)
    assert result.status == CrawlStatus.CANCELLED.value
    assert "Operator issued abort" in result.termination_reason
    assert result.crawl_id == "test-cancel-job"
    assert len(result.pages) == 0


def test_database_persistence_of_phase_2a_provenance(tmp_path: Path) -> None:
    """Verify database persists and retrieves all Phase 2A PageRecord provenance fields."""
    from pathlib import Path
    from app.database import Database

    db = Database(tmp_path / "test_contracts.db")
    db.initialize()
    crawl_id = "crawl-contract-db"

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO crawls (id, created_at, status, start_url, settings_json, ownership_ack) VALUES (?, '2026-09-05', 'completed', 'https://example.com', '{}', 1)",
            (crawl_id,),
        )

    page = PageRecord(
        url="https://example.com/page",
        final_url="https://example.com/page-final",
        status_code=200,
        content_type="text/html",
        title="DB Provenance",
        description="Desc",
        headings={},
        canonical="https://example.com/page-final",
        meta_robots="",
        x_robots="",
        source_html="<html></html>",
        rendered_html="",
        rendered_text="",
        images=[],
        structured_data=[],
        redirect_chain=[],
        normalized_url="https://example.com/page",
        fetch_strategy="browser",
        crawler_engine="thread",
        response_bytes=2048,
        duration_ms=123.4,
        error_category="none",
        headers={"content-type": "text/html", "x-custom": "verified"},
    )

    db.replace_pages_and_links(crawl_id, [page], [])
    retrieved = db.get_pages(crawl_id)
    assert len(retrieved) == 1
    p = retrieved[0]
    assert p["normalized_url"] == "https://example.com/page"
    assert p["fetch_strategy"] == "browser"
    assert p["crawler_engine"] == "thread"
    assert p["response_bytes"] == 2048
    assert p["duration_ms"] == 123.4
    assert p["error_category"] == "none"
    assert p["headers"]["x-custom"] == "verified"
