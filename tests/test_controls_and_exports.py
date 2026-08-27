"""Focused verification of local crawl boundaries and reproducible export behavior."""

from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.crawler import CrawlEngine
from app.exports import write_csv_exports, write_html_report
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
        max_document_bytes=20_000, max_concurrent_crawls=1, render_enabled=False,
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
