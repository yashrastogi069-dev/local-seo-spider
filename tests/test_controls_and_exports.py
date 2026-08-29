"""Focused verification of local crawl boundaries and reproducible export behavior."""

from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.crawler import CrawlEngine
from app.exports import write_csv_exports, write_html_report
from app.parser import extract_page_signals
from app.types import CrawlRequest
from app.urltools import UrlValidationError, is_same_host, normalize_url, safe_filename


def sample_crawl() -> dict[str, object]:
    return {"start_url": "https://owned.example/a path", "created_at": "2026-08-27T18:00:00+00:00", "completed_at": "2026-08-27T18:01:00+00:00"}


def sample_page() -> dict[str, object]:
    return {
        "url": "https://owned.example/", "final_url": "https://owned.example/", "status_code": 200, "content_type": "text/html",
        "title": "<Unsafe title>", "description": "Useful description", "headings": {"h1": ["One heading"]}, "canonical": "https://owned.example/",
        "meta_robots": "", "x_robots": "", "robots_allowed": True, "internal_inlinks": 1, "rendered_text": "local rendered copy",
        "images": [{"has_alt": False, "alt": ""}], "structured_data": [{"types": ["Article"]}], "fetch_error": "", "render_error": "",
    }


def test_url_controls_normalize_scope_and_reject_unsafe_inputs() -> None:
    assert normalize_url("HTTPS://Owned.Example:443/a#part") == "https://owned.example/a"
    assert normalize_url("?view=a", "https://owned.example/path") == "https://owned.example/path?view=a"
    assert is_same_host("https://owned.example/a", "https://owned.example/")
    assert not is_same_host("http://owned.example/a", "https://owned.example/")
    assert safe_filename("../../SEO Audit: Example!") == "seo-audit-example"
    with pytest.raises(UrlValidationError, match="credentials"):
        normalize_url("https://name:secret@owned.example/")
    with pytest.raises(UrlValidationError, match="Only http"):
        normalize_url("file:///etc/passwd")


def test_crawler_tracks_redirects_respects_robots_and_keeps_rendering_recoverable() -> None:
    settings = Settings(
        data_dir=Path("data"), user_agent="LocalSEOSpider/Test", default_url_cap=5, max_url_cap=10,
        default_delay_seconds=0.1, request_timeout_seconds=2, render_timeout_ms=1_000, max_redirects=2,
        max_document_bytes=20_000, max_request_retries=2, retry_backoff_seconds=0.1, max_concurrent_crawls=1, render_enabled=False,
    )
    engine = CrawlEngine(settings)

    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "/final"})
        return httpx.Response(200, text="<html></html>")

    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        robots, state = engine._robots(client, "https://owned.example/start")
        response, chain, error = engine._fetch(client, "https://owned.example/start")

    assert state == "loaded"
    assert not robots.can_fetch(settings.user_agent, "https://owned.example/private")
    assert response is not None and response.status_code == 200
    assert [hop["status_code"] for hop in chain] == [301, 200]
    assert error == ""
    assert engine._render(None, "https://owned.example/")[2] == "Rendering is disabled or Chromium is unavailable."


def test_fetch_retries_transient_http_errors_with_a_bounded_attempt_count() -> None:
    settings = Settings(
        data_dir=Path("data"), user_agent="LocalSEOSpider/Test", default_url_cap=5, max_url_cap=10,
        default_delay_seconds=0.1, request_timeout_seconds=2, render_timeout_ms=1_000, max_redirects=2,
        max_document_bytes=20_000, max_request_retries=2, retry_backoff_seconds=0.1, max_concurrent_crawls=1, render_enabled=False,
    )
    attempts = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path == "/unstable":
            attempts += 1
            if attempts < 3:
                return httpx.Response(503, request=request)
        return httpx.Response(200, request=request, text="<html><title>OK</title></html>")

    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        response, chain, error = CrawlEngine(settings)._fetch(client, "https://owned.example/unstable")

    assert attempts == 3
    assert response is not None and response.status_code == 200
    assert [hop["status_code"] for hop in chain] == [503, 503, 200]
    assert error == ""


def test_windows_launcher_uses_browser_safe_loopback_address() -> None:
    launcher = Path(__file__).parents[1] / "run-local.cmd"
    content = launcher.read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in content
    assert "--host 0.0.0.0" not in content


def test_fetch_retries_transport_timeout_then_continues_with_bounded_error() -> None:
    settings = Settings(
        data_dir=Path("data"), user_agent="LocalSEOSpider/Test", default_url_cap=5, max_url_cap=10,
        default_delay_seconds=0.1, request_timeout_seconds=2, render_timeout_ms=1_000, max_redirects=2,
        max_document_bytes=20_000, max_request_retries=2, retry_backoff_seconds=0.1, max_concurrent_crawls=1, render_enabled=False,
    )
    attempts = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("fixture timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        response, chain, error = CrawlEngine(settings)._fetch(client, "https://owned.example/timeout")

    assert response is None
    assert attempts == 3
    assert chain == []
    assert "after 3 attempt(s)" in error


def test_fetch_stops_after_redirect_limit() -> None:
    settings = Settings(
        data_dir=Path("data"), user_agent="LocalSEOSpider/Test", default_url_cap=5, max_url_cap=10,
        default_delay_seconds=0.1, request_timeout_seconds=2, render_timeout_ms=1_000, max_redirects=2,
        max_document_bytes=20_000, max_request_retries=0, retry_backoff_seconds=0.1, max_concurrent_crawls=1, render_enabled=False,
    )

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, request=request, headers={"location": "/loop"})

    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        response, chain, error = CrawlEngine(settings)._fetch(client, "https://owned.example/loop")

    assert response is not None and response.status_code == 302
    assert len(chain) == 3
    assert "Redirect limit" in error


def test_malformed_html_and_non_html_are_safe_and_render_failure_is_recoverable(monkeypatch: pytest.MonkeyPatch) -> None:
    signals = extract_page_signals("<html><head><title>Unclosed", "https://owned.example/", "https://owned.example/")
    assert signals["title"] == "Unclosed"

    settings = Settings(
        data_dir=Path("data"), user_agent="LocalSEOSpider/Test", default_url_cap=5, max_url_cap=10,
        default_delay_seconds=0.1, request_timeout_seconds=2, render_timeout_ms=1_000, max_redirects=2,
        max_document_bytes=20_000, max_request_retries=0, retry_backoff_seconds=0.1, max_concurrent_crawls=1, render_enabled=False,
    )

    class FixtureClient:
        def __enter__(self) -> "FixtureClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, follow_redirects: bool = False) -> httpx.Response:
            request = httpx.Request("GET", str(url))
            if str(url).endswith("/robots.txt"):
                return httpx.Response(404, request=request)
            return httpx.Response(200, request=request, headers={"content-type": "application/pdf"}, content=b"pdf data")

    monkeypatch.setattr("app.crawler.httpx.Client", lambda **kwargs: FixtureClient())
    pages, links, _ = CrawlEngine(settings).run(
        CrawlRequest(start_url="https://owned.example/", mode="site", max_urls=1, acknowledgment=True),
        lambda *args: None,
    )

    assert not links
    assert pages[0].content_type == "application/pdf"
    assert pages[0].source_html == ""
    assert pages[0].extracted_text == ""
    assert "PDF text extraction failed" in pages[0].extraction_error

    class BrokenPage:
        def goto(self, *args: object, **kwargs: object) -> None:
            raise TimeoutError("fixture render timeout")

    _, _, render_error = CrawlEngine(settings)._render(BrokenPage(), "https://owned.example/")
    assert "Rendered inspection failed" in render_error


def test_exports_are_local_csv_and_self_contained_html_with_escaped_evidence(tmp_path: Path) -> None:
    pages = [sample_page()]
    issues = [{"severity": "high", "title": "<script>bad</script>", "url": "https://owned.example/", "evidence": "<b>evidence</b>", "remediation": "Fix it", "rule_key": "test", "fingerprint": "fp"}]

    pages_csv, issues_csv = write_csv_exports(tmp_path, sample_crawl(), pages, issues)
    report = write_html_report(tmp_path, sample_crawl(), pages, issues)

    assert pages_csv.parent == tmp_path / "exports"
    assert "/" not in pages_csv.name and ":" not in pages_csv.name
    assert "structured_data_types" in pages_csv.read_text(encoding="utf-8")
    assert "<script>bad</script>" in issues_csv.read_text(encoding="utf-8")
    report_text = report.read_text(encoding="utf-8")
    assert "<style>" in report_text and "https://" not in report_text.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "&lt;script&gt;bad&lt;/script&gt;" in report_text
