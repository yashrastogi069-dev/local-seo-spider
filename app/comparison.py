"""Evidence-only comparison between two locally stored completed crawl records."""

from __future__ import annotations

from typing import Any


def compare_crawls(current_pages: list[dict[str, Any]], current_issues: list[dict[str, Any]], baseline_pages: list[dict[str, Any]], baseline_issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Return deterministic changes without ranking or traffic claims."""
    current_by_url = {page["url"]: page for page in current_pages}
    baseline_by_url = {page["url"]: page for page in baseline_pages}
    added_urls = sorted(set(current_by_url) - set(baseline_by_url))
    removed_urls = sorted(set(baseline_by_url) - set(current_by_url))
    changed_pages: list[dict[str, str]] = []
    for url in sorted(set(current_by_url) & set(baseline_by_url)):
        before, after = baseline_by_url[url], current_by_url[url]
        fields = []
        for key, label in (("status_code", "HTTP status"), ("title", "title"), ("description", "meta description"), ("canonical", "canonical"), ("meta_robots", "meta robots"), ("content_hash", "rendered text")):
            if before.get(key) != after.get(key):
                fields.append(label)
        if fields:
            changed_pages.append({"url": url, "changes": ", ".join(fields)})
    current_fingerprints = {issue["fingerprint"]: issue for issue in current_issues}
    baseline_fingerprints = {issue["fingerprint"]: issue for issue in baseline_issues}
    return {
        "new_urls": added_urls,
        "removed_urls": removed_urls,
        "changed_pages": changed_pages,
        "new_issues": [current_fingerprints[key] for key in sorted(set(current_fingerprints) - set(baseline_fingerprints))],
        "resolved_issues": [baseline_fingerprints[key] for key in sorted(set(baseline_fingerprints) - set(current_fingerprints))],
    }
