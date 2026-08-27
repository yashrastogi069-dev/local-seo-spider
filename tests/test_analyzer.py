"""Focused tests for deterministic issue generation from page and link evidence."""

from app.analyzer import analyze_pages
from app.types import LinkRecord, PageRecord


def page(url: str, **overrides: object) -> PageRecord:
    defaults: dict[str, object] = {
        "url": url, "final_url": url, "status_code": 200, "content_type": "text/html", "title": "", "description": "", "headings": {"h1": []},
        "canonical": "", "meta_robots": "", "x_robots": "", "source_html": "", "rendered_html": "", "rendered_text": "", "images": [],
        "structured_data": [], "redirect_chain": [], "content_hash": "empty", "discovered_at": "2026-01-01T00:00:00+00:00",
    }
    defaults.update(overrides)
    return PageRecord(**defaults)  # type: ignore[arg-type]


def test_analyzer_emits_prioritized_evidence_for_common_audit_conflicts() -> None:
    root = "https://example.test/"
    broken = page("https://example.test/gone", status_code=404, title="Gone", description="Gone page", headings={"h1": ["Gone"]}, content_hash="gone")
    primary = page(
        root,
        title="Duplicate heading",
        description="Shared description",
        headings={"h1": ["Home"]},
        canonical=root,
        meta_robots="noindex",
        images=[{"src": "/hero.jpg", "alt": "", "has_alt": False}],
        structured_data=[{"valid": False, "error": "JSON-LD parse error: Expecting value", "types": []}],
        redirect_chain=[{"url": root, "status_code": 301}, {"url": "https://example.test/home", "status_code": 200}],
        content_hash="same-content",
    )
    duplicate = page("https://example.test/other", title="Duplicate heading", description="Shared description", headings={"h1": ["Other"]}, content_hash="same-content")
    links = [LinkRecord(root, broken.url, "/gone", "Read more", "", True, False)]

    issues = analyze_pages([primary, duplicate, broken], links, root)
    by_key = {issue.rule_key: issue for issue in issues}

    assert by_key["client_error"].severity == "high"
    assert by_key["broken_internal_link"].url == root
    assert by_key["redirect_chain"].evidence.startswith("301")
    assert by_key["noindex_self_canonical"].severity == "medium"
    assert by_key["missing_image_alt"].remediation.startswith("Add meaningful alt text")
    assert "JSON-LD parse error" in by_key["invalid_jsonld"].evidence
    assert by_key["duplicate_title"].severity == "medium"
    assert by_key["duplicate_description"].severity == "low"
    assert by_key["duplicate_content"].title == "Duplicate rendered content"
