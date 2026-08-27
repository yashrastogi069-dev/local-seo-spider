"""Deterministic, evidence-backed technical SEO issue transformation."""

from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
from typing import Iterable

from app.parser import normalized_text
from app.types import IssueRecord, LinkRecord, PageRecord
from app.urltools import is_same_host


def _issue(rule_key: str, severity: str, title: str, url: str, evidence: str, remediation: str) -> IssueRecord:
    fingerprint = sha256(f"{rule_key}|{url}|{evidence}".encode("utf-8")).hexdigest()[:18]
    return IssueRecord(rule_key, severity, title, url, evidence, remediation, fingerprint)


def _duplicates(values: dict[str, str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for url, value in values.items():
        normal = normalized_text(value).lower()
        if normal:
            groups[normal].append(url)
    return {value: urls for value, urls in groups.items() if len(urls) > 1}


def analyze_pages(pages: Iterable[PageRecord], links: Iterable[LinkRecord], start_url: str) -> list[IssueRecord]:
    page_list = list(pages)
    link_list = list(links)
    issues: list[IssueRecord] = []
    by_url = {page.url: page for page in page_list}
    by_final_url = {page.final_url: page for page in page_list}
    inbound: Counter[str] = Counter()

    for link in link_list:
        if link.is_internal and not link.nofollow:
            inbound[link.target_url] += 1

    for page in page_list:
        page.internal_inlinks = inbound[page.url] + inbound[page.final_url]
        if page.fetch_error:
            issues.append(_issue("fetch_error", "high", "Page could not be fetched", page.url, page.fetch_error, "Check server availability, DNS, or the URL before recrawling."))
            continue
        if page.status_code and page.status_code >= 500:
            issues.append(_issue("server_error", "critical", "Server error", page.url, f"HTTP {page.status_code}", "Resolve the server error and verify that the page returns a successful response."))
        if page.status_code and 400 <= page.status_code < 500:
            issues.append(_issue("client_error", "high", "Client error", page.url, f"HTTP {page.status_code}", "Restore the page or update internal links to a valid destination."))
        if not page.title:
            issues.append(_issue("missing_title", "high", "Missing page title", page.url, "No <title> text was found in the inspected document.", "Add a concise, page-specific <title> that describes the page’s primary purpose."))
        if not page.description:
            issues.append(_issue("missing_description", "medium", "Missing meta description", page.url, "No meta[name=description] content was found.", "Add a unique, descriptive meta description that summarizes this page for search-result snippets."))
        if not page.headings.get("h1"):
            issues.append(_issue("missing_h1", "medium", "Missing H1", page.url, "No H1 heading was found.", "Add one clear H1 that describes the page’s main topic."))
        if page.status_code and page.status_code < 400 and len(normalized_text(page.rendered_text).split()) < 50:
            issues.append(_issue("thin_rendered_text", "low", "Low rendered-text volume", page.url, f"Only {len(normalized_text(page.rendered_text).split())} rendered words were captured.", "Review whether this page gives users enough distinct, useful on-page information for its purpose; do not add filler text."))
        if page.body_truncated:
            issues.append(_issue("document_truncated", "low", "Document capture capped", page.url, "The response exceeded the configured local document-size limit.", "Increase SPIDER_MAX_DOCUMENT_BYTES only if you need the full source stored locally."))
        if page.render_error:
            issues.append(_issue("render_unavailable", "low", "Rendered inspection unavailable", page.url, page.render_error, "Install Chromium with the documented local command and retry; raw HTML findings remain available."))
        for index, image in enumerate(page.images, start=1):
            if not image.get("has_alt") or not normalized_text(image.get("alt", "")):
                issues.append(_issue("missing_image_alt", "low", "Image missing alternate text", page.url, f"Image {index}: {image.get('src') or '(no src)'}", "Add meaningful alt text for informative images; use an empty alt attribute only for decorative images."))
        for schema in page.structured_data:
            if not schema.get("valid"):
                issues.append(_issue("invalid_jsonld", "medium", "Invalid JSON-LD", page.url, schema.get("error", "JSON-LD could not be parsed."), "Correct the JSON-LD syntax, then validate its content against the applicable structured-data requirements."))
        if page.redirect_chain and len(page.redirect_chain) > 1:
            chain = " → ".join(f"{hop['status_code']} {hop['url']}" for hop in page.redirect_chain)
            issues.append(_issue("redirect_chain", "medium", "Redirect chain", page.url, chain, "Update internal links and redirect rules so visitors reach the final destination in one hop."))
        canonical = page.canonical
        directives = f"{page.meta_robots} {page.x_robots}".lower()
        if canonical:
            try:
                canonical_in_scope = is_same_host(canonical, start_url)
            except ValueError:
                canonical_in_scope = False
            if not canonical_in_scope:
                issues.append(_issue("canonical_out_of_scope", "medium", "Canonical points outside crawl scope", page.url, f"Canonical: {canonical}", "Confirm that this cross-host canonical is intentional and points to the preferred equivalent page."))
            target = by_url.get(canonical) or by_final_url.get(canonical)
            if target and "noindex" in f"{target.meta_robots} {target.x_robots}".lower():
                issues.append(_issue("canonical_to_noindex", "high", "Canonical target is noindex", page.url, f"Canonical {canonical} has a noindex directive.", "Choose an indexable canonical target or revise the canonical and robots directives so they agree."))
            if "noindex" in directives and canonical == page.final_url:
                issues.append(_issue("noindex_self_canonical", "medium", "Self-canonical conflicts with noindex", page.url, "The page self-canonicalizes while carrying a noindex directive.", "Decide whether the page should be indexed; then align its canonical and robots directives."))
        if "noindex" in page.meta_robots and "index" in page.x_robots and "noindex" not in page.x_robots:
            issues.append(_issue("robots_directive_conflict", "high", "Conflicting indexability directives", page.url, f"meta robots: {page.meta_robots}; X-Robots-Tag: {page.x_robots}", "Make the HTML and HTTP robots directives agree on whether the page should be indexed."))

    for url, pages_with_title in _duplicates({page.url: page.title for page in page_list}).items():
        evidence = f"Duplicate title across {len(pages_with_title)} URLs: {url[:180]}"
        for page_url in pages_with_title:
            issues.append(_issue("duplicate_title", "medium", "Duplicate page title", page_url, evidence, "Write a unique title that differentiates this page from the other affected pages."))
    for description, urls in _duplicates({page.url: page.description for page in page_list}).items():
        evidence = f"Duplicate description across {len(urls)} URLs: {description[:180]}"
        for page_url in urls:
            issues.append(_issue("duplicate_description", "low", "Duplicate meta description", page_url, evidence, "Write a distinctive description that accurately summarizes this specific page."))
    for content_hash, urls in _duplicates({page.url: page.content_hash for page in page_list}).items():
        evidence = f"Identical normalized rendered-text hash {content_hash[:16]} across {len(urls)} URLs."
        for page_url in urls:
            issues.append(_issue("duplicate_content", "medium", "Duplicate rendered content", page_url, evidence, "Consolidate equivalent pages, differentiate their content, or use consistent canonical signals."))

    for page in page_list:
        if page.url != start_url and page.status_code and page.status_code < 400 and page.internal_inlinks == 0:
            issues.append(_issue("orphan_candidate", "low", "Orphan candidate", page.url, "No followable internal inlink was found in this crawl.", "Check navigation, sitemaps, and known entry points; add a relevant internal link if this page should be discoverable."))

    broken_targets = {page.url for page in page_list if page.status_code and page.status_code >= 400} | {page.final_url for page in page_list if page.status_code and page.status_code >= 400}
    for link in link_list:
        if link.is_internal and link.target_url in broken_targets:
            issues.append(_issue("broken_internal_link", "high", "Broken internal link", link.source_url, f"Link target: {link.target_url}; anchor: {link.anchor_text or '(empty)'}", "Update or remove this link so it points to a successful, relevant destination."))
    return issues
