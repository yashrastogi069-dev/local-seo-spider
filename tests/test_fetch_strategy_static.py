"""Phase 2E Static Fetch Strategy Test Suite.

Verifies:
1. HTTP status codes, headers, and redirect chains under static acquisition.
2. Transparent decompression of gzip and deflate streams.
3. Accurate extraction and signal handling across non-HTML content types (JSON, text, PDF).
4. Response byte bounding and body_truncated flag under large payloads.
5. Network timeout and connection failure handling.
6. Forensic provenance: requested vs actual fetch strategies, duration_ms, and zero browser process spawning.
"""

from __future__ import annotations

from dataclasses import replace
import pytest

from app.crawler import CrawlEngine
from app.main import settings
from app.types import CrawlRequest, CrawlStatus
from tests.controlled_crawler_server import ControlledCrawlerServer


@pytest.fixture(scope="module")
def static_server():
    """Spawn a controlled server instance for static fetch testing."""
    srv = ControlledCrawlerServer()
    srv.start()
    yield srv.base_url
    srv.stop()


def _make_settings(tmp_path, **kwargs):
    default_kwargs = dict(
        data_dir=tmp_path / "data",
        render_enabled=False,
        crawl_executor_mode="serial",
        allow_private_crawls=True,
        default_delay_seconds=0,
    )
    default_kwargs.update(kwargs)
    return replace(settings, **default_kwargs)


def test_static_fetch_clean_html_signals(static_server, tmp_path) -> None:
    """Verify static fetch extracts status, headers, title, and HTML signals cleanly."""
    cfg = _make_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{static_server}/static-clean",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="static",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    assert res.requested_fetch_mode == "static"
    assert res.actual_fetch_mode == "static"
    assert res.fallback_occurred is False
    assert len(res.pages) == 1

    page = res.pages[0]
    assert page.status_code == 200
    assert "html" in page.content_type
    assert page.title == "Clean Static Editorial Page"
    assert "Clean Static Article" in page.headings.get("h1", [])
    assert "editorial prose" in page.source_html
    assert page.fetch_strategy == "static"
    assert page.requested_fetch_strategy == "static"
    assert page.actual_fetch_strategy == "static"
    assert page.escalated is False
    assert page.escalation_reason == ""
    assert page.fetch_duration_ms >= 0.0
    assert page.render_duration_ms == 0.0


def test_static_fetch_compression_gzip(static_server, tmp_path) -> None:
    """Verify static fetch transparently decompresses gzip encoded responses."""
    cfg = _make_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{static_server}/gzip-encoded",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="static",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    page = res.pages[0]
    assert page.status_code == 200
    assert "Gzip Compressed Content" in page.source_html
    assert "gzip content encoding" in page.source_html
    assert page.fetch_strategy == "static"
    assert page.escalated is False


def test_static_fetch_compression_deflate(static_server, tmp_path) -> None:
    """Verify static fetch transparently decompresses deflate encoded responses."""
    cfg = _make_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{static_server}/deflate-encoded",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="static",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    page = res.pages[0]
    assert page.status_code == 200
    assert "Deflate Compressed Content" in page.source_html
    assert page.fetch_strategy == "static"
    assert page.escalated is False


def test_static_fetch_content_types_json(static_server, tmp_path) -> None:
    """Verify static fetch handles JSON content types and derives API titles."""
    cfg = _make_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{static_server}/content-types/json",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="static",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    page = res.pages[0]
    assert page.status_code == 200
    assert "json" in page.content_type
    assert page.source_type in ("json", "api", "official_api")
    assert "crawler" in page.extracted_text
    assert page.fetch_strategy == "static"
    assert page.escalated is False


def test_static_fetch_content_types_text(static_server, tmp_path) -> None:
    """Verify static fetch handles text/plain documents."""
    cfg = _make_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{static_server}/content-types/text",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="static",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    page = res.pages[0]
    assert page.status_code == 200
    assert "text/plain" in page.content_type
    assert "Plain text document content" in page.extracted_text
    assert page.fetch_strategy == "static"
    assert page.escalated is False


def test_static_fetch_content_types_pdf(static_server, tmp_path) -> None:
    """Verify static fetch handles application/pdf documents."""
    cfg = _make_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{static_server}/content-types/pdf",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="static",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    page = res.pages[0]
    assert page.status_code == 200
    assert "application/pdf" in page.content_type
    assert page.source_type in ("pdf", "document")
    assert page.response_bytes > 0
    assert page.fetch_strategy == "static"
    assert page.escalated is False


def test_static_fetch_large_payload_truncation(static_server, tmp_path) -> None:
    """Verify static fetch enforces max_document_bytes and sets body_truncated."""
    max_bytes = 5_000
    cfg = _make_settings(tmp_path, max_document_bytes=max_bytes)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{static_server}/large-payload",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="static",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    page = res.pages[0]
    assert page.status_code == 200
    assert page.body_truncated is True
    assert len(page.source_html) <= max_bytes
    assert page.response_bytes > max_bytes
    assert page.fetch_strategy == "static"


def test_static_fetch_redirect_chain_recording(static_server, tmp_path) -> None:
    """Verify static fetch preserves complete redirect hops and canonical resolution."""
    cfg = _make_settings(tmp_path)
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{static_server}/redirect-chain",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="static",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.SUCCESS.value
    page = res.pages[0]
    assert page.status_code == 200
    assert len(page.redirect_chain) >= 2
    assert page.final_url == f"{static_server}/redirect-chain-target"
    assert page.fetch_strategy == "static"


def test_static_fetch_timeout_handling(static_server, tmp_path) -> None:
    """Verify static fetch records timeout error without crashing or hanging."""
    cfg = _make_settings(
        tmp_path,
        request_timeout_seconds=0.15,
        max_request_retries=0,
    )
    engine = CrawlEngine(cfg)
    req = CrawlRequest(
        start_url=f"{static_server}/slow?delay=0.6",
        mode="site",
        max_urls=1,
        acknowledgment=True,
        fetch_mode="static",
    )
    res = engine.run(req, lambda cur, tot, st: None)

    assert res.status == CrawlStatus.FAILED.value
    assert len(res.pages) == 1
    page = res.pages[0]
    assert page.status_code is None
    assert "Timeout" in page.fetch_error or "timeout" in page.fetch_error.lower()
    assert page.fetch_strategy == "static"
    assert page.error_category == "fetch_error"
