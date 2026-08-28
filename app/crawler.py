"""Bounded, robots-aware collection for explicitly authorized same-host crawls."""

from __future__ import annotations

import time
from collections import deque
from datetime import UTC, datetime
from urllib import robotparser

import httpx

from app.config import Settings
from app.parser import extract_links, extract_page_signals, normalized_text, text_hash
from app.types import CrawlRequest, LinkRecord, PageRecord
from app.urltools import UrlValidationError, is_same_host, normalize_url


class CrawlEngine:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _robots(self, client: httpx.Client, start_url: str) -> tuple[robotparser.RobotFileParser, str]:
        parsed = httpx.URL(start_url)
        robots_url = str(parsed.copy_with(path="/robots.txt", query=None, fragment=None))
        policy = robotparser.RobotFileParser()
        policy.set_url(robots_url)
        try:
            response = client.get(robots_url, follow_redirects=True)
            if response.status_code == 200:
                policy.parse(response.text.splitlines())
                return policy, "loaded"
            policy.allow_all = True
            return policy, f"unavailable (HTTP {response.status_code})"
        except httpx.HTTPError as exc:
            policy.allow_all = True
            return policy, f"unavailable ({type(exc).__name__})"

    def _fetch(self, client: httpx.Client, url: str) -> tuple[httpx.Response | None, list[dict[str, object]], str]:
        current = url
        hops: list[dict[str, object]] = []
        transient_statuses = {408, 425, 429, 500, 502, 503, 504}
        for _ in range(self.settings.max_redirects + 1):
            response: httpx.Response | None = None
            for attempt in range(self.settings.max_request_retries + 1):
                try:
                    response = client.get(current, follow_redirects=False)
                except httpx.HTTPError as exc:
                    if attempt >= self.settings.max_request_retries:
                        return None, hops, f"{type(exc).__name__} after {attempt + 1} attempt(s): {exc}"
                    time.sleep(self.settings.retry_backoff_seconds * (2 ** attempt))
                    continue
                hops.append({"url": current, "status_code": response.status_code, "location": response.headers.get("location", ""), "attempt": attempt + 1})
                if response.status_code in transient_statuses and attempt < self.settings.max_request_retries:
                    time.sleep(self.settings.retry_backoff_seconds * (2 ** attempt))
                    continue
                break
            if response is None:
                return None, hops, "Request ended without a response."
            if response.is_redirect and response.headers.get("location"):
                try:
                    current = normalize_url(response.headers["location"], current)
                except UrlValidationError:
                    return response, hops, "Redirect location could not be normalized."
                continue
            if response.status_code in transient_statuses:
                return response, hops, f"Transient HTTP status {response.status_code} remained after {self.settings.max_request_retries + 1} attempt(s)."
            return response, hops, ""
        return response, hops, f"Redirect limit ({self.settings.max_redirects}) exceeded."

    def _render(self, browser_page: object | None, url: str) -> tuple[str, str, str]:
        if browser_page is None:
            return "", "", "Rendering is disabled or Chromium is unavailable."
        try:
            browser_page.goto(url, wait_until="domcontentloaded", timeout=self.settings.render_timeout_ms)
            browser_page.wait_for_timeout(150)
            html = browser_page.content()
            text = browser_page.locator("body").inner_text(timeout=5_000)
            return html[: self.settings.max_document_bytes], normalized_text(text), ""
        except Exception as exc:  # Browser-originated errors are recoverable per page.
            return "", "", f"Rendered inspection failed: {type(exc).__name__}: {exc}"

    def run(self, request: CrawlRequest, progress: callable) -> tuple[list[PageRecord], list[LinkRecord], str]:
        if not request.acknowledgment:
            raise ValueError("Ownership or permission acknowledgement is required before a crawl can start.")
        queue = deque(request.url_list if request.mode == "list" else [request.start_url])
        queued = set(queue)
        pages: list[PageRecord] = []
        links: list[LinkRecord] = []
        last_request_at = 0.0
        headers = {"User-Agent": self.settings.user_agent, "Accept": "text/html,application/xhtml+xml"}

        with httpx.Client(headers=headers, timeout=self.settings.request_timeout_seconds, follow_redirects=False) as client:
            robots, robots_status = self._robots(client, request.start_url)
            browser = None
            browser_page = None
            playwright = None
            if self.settings.render_enabled:
                try:
                    from playwright.sync_api import sync_playwright

                    playwright = sync_playwright().start()
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context(user_agent=self.settings.user_agent, java_script_enabled=True)
                    browser_page = context.new_page()
                except Exception:
                    browser_page = None
            try:
                while queue and len(pages) < request.max_urls:
                    url = queue.popleft()
                    if not robots.can_fetch(self.settings.user_agent, url):
                        pages.append(
                            PageRecord(
                                url=url, final_url=url, status_code=None, content_type="", title="", description="", headings={}, canonical="",
                                meta_robots="", x_robots="", source_html="", rendered_html="", rendered_text="", images=[], structured_data=[],
                                redirect_chain=[], fetch_error="", render_error="", robots_allowed=False, discovered_at=self._now(), content_hash="",
                            )
                        )
                        progress(len(pages), len(queue), robots_status)
                        continue
                    pause = request.delay_seconds - (time.monotonic() - last_request_at)
                    if pause > 0:
                        time.sleep(pause)
                    response, redirect_chain, fetch_error = self._fetch(client, url)
                    last_request_at = time.monotonic()
                    if not response:
                        pages.append(self._error_page(url, redirect_chain, fetch_error))
                        progress(len(pages), len(queue), robots_status)
                        continue
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    source_html = response.text[: self.settings.max_document_bytes] if "html" in content_type else ""
                    body_truncated = len(response.content) > self.settings.max_document_bytes
                    final_url = normalize_url(str(response.url))
                    render_html, rendered_text, render_error = self._render(browser_page, final_url) if source_html else ("", "", "")
                    source_signals = extract_page_signals(source_html, final_url, request.start_url) if source_html else self._empty_signals()
                    rendered_signals = extract_page_signals(render_html, final_url, request.start_url) if render_html else self._empty_signals()
                    selected = rendered_signals if rendered_signals["title"] or rendered_signals["links"] else source_signals
                    page_links = self._dedupe_links(source_signals["links"] + rendered_signals["links"])
                    links.extend(page_links)
                    pages.append(
                        PageRecord(
                            url=url, final_url=final_url, status_code=response.status_code, content_type=content_type,
                            title=selected["title"] or source_signals["title"], description=selected["description"] or source_signals["description"],
                            headings=selected["headings"] or source_signals["headings"], canonical=selected["canonical"] or source_signals["canonical"],
                            meta_robots=selected["meta_robots"] or source_signals["meta_robots"], x_robots=response.headers.get("x-robots-tag", "").lower(),
                            source_html=source_html, rendered_html=render_html, rendered_text=rendered_text, images=selected["images"] or source_signals["images"],
                            structured_data=selected["structured_data"] or source_signals["structured_data"], redirect_chain=redirect_chain,
                            fetch_error=fetch_error, render_error=render_error, robots_allowed=True, body_truncated=body_truncated,
                            discovered_at=self._now(), content_hash=text_hash(rendered_text or source_html),
                        )
                    )
                    if request.mode == "site":
                        for link in page_links:
                            if not link.is_internal or (request.respect_nofollow and link.nofollow) or link.target_url in queued:
                                continue
                            if len(queued) >= request.max_urls:
                                break
                            queued.add(link.target_url)
                            queue.append(link.target_url)
                    progress(len(pages), len(queue), robots_status)
            finally:
                if browser:
                    browser.close()
                if playwright:
                    playwright.stop()
        return pages, links, robots_status

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

    @staticmethod
    def _empty_signals() -> dict[str, object]:
        return {"title": "", "description": "", "headings": {}, "canonical": "", "meta_robots": "", "images": [], "structured_data": [], "links": []}

    @staticmethod
    def _dedupe_links(links: list[LinkRecord]) -> list[LinkRecord]:
        seen: set[tuple[str, str, str, str]] = set()
        result: list[LinkRecord] = []
        for link in links:
            key = (link.source_url, link.target_url, link.anchor_text, link.rel)
            if key not in seen:
                seen.add(key)
                result.append(link)
        return result

    @staticmethod
    def _error_page(url: str, redirect_chain: list[dict[str, object]], error: str) -> PageRecord:
        return PageRecord(
            url=url, final_url=url, status_code=None, content_type="", title="", description="", headings={}, canonical="", meta_robots="",
            x_robots="", source_html="", rendered_html="", rendered_text="", images=[], structured_data=[], redirect_chain=redirect_chain,
            fetch_error=error, render_error="", discovered_at=CrawlEngine._now(), content_hash="",
        )
