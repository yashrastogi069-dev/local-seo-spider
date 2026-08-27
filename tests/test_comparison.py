"""Focused test for repeatable local crawl comparison evidence."""

from app.comparison import compare_crawls


def test_compare_crawls_reports_observable_page_and_issue_changes() -> None:
    baseline_pages = [{"url": "https://owned.example/", "status_code": 200, "title": "Before", "description": "Old", "canonical": "https://owned.example/", "meta_robots": "", "content_hash": "old"}]
    current_pages = [
        {"url": "https://owned.example/", "status_code": 200, "title": "After", "description": "Old", "canonical": "https://owned.example/", "meta_robots": "", "content_hash": "new"},
        {"url": "https://owned.example/new", "status_code": 200, "title": "New", "description": "New", "canonical": "", "meta_robots": "", "content_hash": "new-page"},
    ]
    baseline_issues = [{"fingerprint": "old-issue", "title": "Missing H1", "severity": "medium", "url": "https://owned.example/"}]
    current_issues = [{"fingerprint": "new-issue", "title": "Missing title", "severity": "high", "url": "https://owned.example/new"}]

    result = compare_crawls(current_pages, current_issues, baseline_pages, baseline_issues)

    assert result["new_urls"] == ["https://owned.example/new"]
    assert result["changed_pages"] == [{"url": "https://owned.example/", "changes": "title, rendered text"}]
    assert result["new_issues"] == current_issues
    assert result["resolved_issues"] == baseline_issues
