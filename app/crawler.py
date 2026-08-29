"""Bounded, robots-aware collection for explicitly authorized same-host crawls."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from threading import Lock
from datetime import UTC, datetime
from urllib import robotparser

import httpx

from app.config import Settings
from app.documents import extract_document_text
from app.extraction_profiles import extract_profile_fields, load_profile
from app.parser import extract_links, extract_page_signals, normalized_text, text_hash
from app.types import CrawlRequest, LinkRecord, PageRecord
from app.urltools import UrlValidationError, is_same_host, normalize_url


class CrawlEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.extraction_profile = load_profile(settings.extraction_profile_path)

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

    def _build_page(self, request: CrawlRequest, url: str, response: httpx.Response | None, redirect_chain: list[dict[str, object]], fetch_error: str, browser_page: object | None = None) -> tuple[PageRecord, list[LinkRecord]]:
        if not response:
            return self._error_page(url, redirect_chain, fetch_error), []
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        source_html = response.text[: self.settings.max_document_bytes] if "html" in content_type else ""
        extracted_text, extraction_error = ("", "") if source_html else extract_document_text(content_type, response.content[: self.settings.max_document_bytes])
        body_truncated = len(response.content) > self.settings.max_document_bytes
        final_url = normalize_url(str(response.url))
        render_html, rendered_text, render_error = self._render(browser_page, final_url) if source_html else ("", "", "")
        source_signals = extract_page_signals(source_html, final_url, request.start_url) if source_html else self._empty_signals()
        rendered_signals = extract_page_signals(render_html, final_url, request.start_url) if render_html else self._empty_signals()
        selected_structured_data = rendered_signals["structured_data"] or source_signals["structured_data"]
        extracted_fields = extract_profile_fields(self.extraction_profile, final_url, source_html, render_html, selected_structured_data)
        extraction_notes = [
            f"{name}: {field.get('status')}" + (f" — {field.get('note')}" if field.get("note") else "")
            for name, field in extracted_fields.get("fields", {}).items() if field.get("status") != "found"
        ]
        selected = rendered_signals if rendered_signals["title"] or rendered_signals["links"] else source_signals
        page_links = self._dedupe_links(source_signals["links"] + rendered_signals["links"])
        page = PageRecord(
            url=url, final_url=final_url, status_code=response.status_code, content_type=content_type,
            title=selected["title"] or source_signals["title"], description=selected["description"] or source_signals["description"],
            headings=selected["headings"] or source_signals["headings"], canonical=selected["canonical"] or source_signals["canonical"],
            meta_robots=selected["meta_robots"] or source_signals["meta_robots"], x_robots=response.headers.get("x-robots-tag", "").lower(),
            source_html=source_html, rendered_html=render_html, rendered_text=rendered_text, extracted_text=extracted_text, extraction_error=extraction_error, images=selected["images"] or source_signals["images"],
            structured_data=selected["structured_data"] or source_signals["structured_data"], redirect_chain=redirect_chain,
            fetch_error=fetch_error, render_error=render_error, robots_allowed=True, body_truncated=body_truncated,
            extracted_fields=extracted_fields, extraction_notes=extraction_notes,
            discovered_at=self._now(), content_hash=text_hash(rendered_text or source_html or extracted_text),
        )
        return page, page_links

    @staticmethod
    def _response_payload(response: httpx.Response | None) -> tuple[int, dict[str, str], bytes, str] | None:
        if response is None:
            return None
        return response.status_code, dict(response.headers), response.content, str(response.url)

    def _fetch_one_sync(self, url: str) -> tuple[str, tuple[int, dict[str, str], bytes, str] | None, list[dict[str, object]], str]:
        with httpx.Client(headers={"User-Agent": self.settings.user_agent, "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,application/json,application/xml,text/csv"}, timeout=self.settings.request_timeout_seconds, follow_redirects=False) as client:
            response, redirect_chain, fetch_error = self._fetch(client, url)
            return url, self._response_payload(response), redirect_chain, fetch_error

    async def _fetch_one_async(self, client: httpx.AsyncClient, url: str, gate: asyncio.Lock, last_request: dict[str, float], delay_seconds: float) -> tuple[str, tuple[int, dict[str, str], bytes, str] | None, list[dict[str, object]], str]:
        async with gate:
            pause = delay_seconds - (time.monotonic() - last_request["value"])
            if pause > 0:
                await asyncio.sleep(pause)
            last_request["value"] = time.monotonic()
        current = url
        hops: list[dict[str, object]] = []
        transient_statuses = {408, 425, 429, 500, 502, 503, 504}
        for _ in range(self.settings.max_redirects + 1):
            response: httpx.Response | None = None
            for attempt in range(self.settings.max_request_retries + 1):
                try:
                    response = await client.get(current, follow_redirects=False)
                except httpx.HTTPError as exc:
                    if attempt >= self.settings.max_request_retries:
                        return url, None, hops, f"{type(exc).__name__} after {attempt + 1} attempt(s): {exc}"
                    await asyncio.sleep(self.settings.retry_backoff_seconds * (2 ** attempt))
                    continue
                hops.append({"url": current, "status_code": response.status_code, "location": response.headers.get("location", ""), "attempt": attempt + 1})
                if response.status_code in transient_statuses and attempt < self.settings.max_request_retries:
                    await asyncio.sleep(self.settings.retry_backoff_seconds * (2 ** attempt))
                    continue
                break
            if response is None:
                return url, None, hops, "Request ended without a response."
            if response.is_redirect and response.headers.get("location"):
                try:
                    current = normalize_url(response.headers["location"], current)
                except UrlValidationError:
                    return url, self._response_payload(response), hops, "Redirect location could not be normalized."
                continue
            if response.status_code in transient_statuses:
                return url, self._response_payload(response), hops, f"Transient HTTP status {response.status_code} remained after {self.settings.max_request_retries + 1} attempt(s)."
            return url, self._response_payload(response), hops, ""
        return url, self._response_payload(response), hops, f"Redirect limit ({self.settings.max_redirects}) exceeded."

    def _wait_thread_slot(self, gate: Lock, last_request: dict[str, float], delay_seconds: float) -> None:
        with gate:
            pause = delay_seconds - (time.monotonic() - last_request["value"])
            if pause > 0:
                time.sleep(pause)
            last_request["value"] = time.monotonic()

    def _thread_fetch_with_gate(self, url: str, gate: Lock, last_request: dict[str, float], delay_seconds: float) -> tuple[str, tuple[int, dict[str, str], bytes, str] | None, list[dict[str, object]], str]:
        self._wait_thread_slot(gate, last_request, delay_seconds)
        return self._fetch_one_sync(url)

    async def _async_batch(self, urls: list[str], delay_seconds: float) -> list[tuple[str, tuple[int, dict[str, str], bytes, str] | None, list[dict[str, object]], str]]:
        headers = {"User-Agent": self.settings.user_agent, "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,application/json,application/xml,text/csv"}
        gate = asyncio.Lock()
        last_request = {"value": time.monotonic()}
        async with httpx.AsyncClient(headers=headers, timeout=self.settings.request_timeout_seconds, follow_redirects=False) as client:
            return await asyncio.gather(*(self._fetch_one_async(client, url, gate, last_request, delay_seconds) for url in urls))

    def _materialize_static(self, request: CrawlRequest, result: tuple[str, tuple[int, dict[str, str], bytes, str] | None, list[dict[str, object]], str]) -> tuple[PageRecord, list[LinkRecord]]:
        url, payload, redirect_chain, fetch_error = result
        if payload is None:
            return self._error_page(url, redirect_chain, fetch_error), []
        status_code, headers, content, final_url = payload
        response = httpx.Response(status_code, headers=headers, content=content, request=httpx.Request("GET", final_url))
        page, page_links = self._build_page(request, url, response, redirect_chain, fetch_error, None)
        return page, page_links


def _materialize_static_process(args: tuple[Settings, CrawlRequest, tuple[str, tuple[int, dict[str, str], bytes, str] | None, list[dict[str, object]], str]]) -> tuple[dict[str, object], list[dict[str, object]]]:
    settings, request, result = args
    page, links = CrawlEngine(settings)._materialize_static(request, result)
    return page.to_dict(), [link.to_dict() for link in links]


class CrawlEngine(CrawlEngine):
    def _run_static_mode(self, request: CrawlRequest, progress: callable) -> tuple[list[PageRecord], list[LinkRecord], str]:
        queue = deque(request.url_list if request.mode == "list" else [request.start_url])
        queued = set(queue)
        pages: list[PageRecord] = []
        links: list[LinkRecord] = []
        headers = {"User-Agent": self.settings.user_agent, "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,application/json,application/xml,text/csv"}
        with httpx.Client(headers=headers, timeout=self.settings.request_timeout_seconds, follow_redirects=False) as client:
            robots, robots_status = self._robots(client, request.start_url)
        thread_gate = Lock()
        last_request = {"value": time.monotonic()}
        while queue and len(pages) < request.max_urls:
            batch: list[str] = []
            while queue and len(batch) < self._worker_count(request):
                url = queue.popleft()
                if robots.can_fetch(self.settings.user_agent, url):
                    batch.append(url)
                else:
                    pages.append(PageRecord(url=url, final_url=url, status_code=None, content_type="", title="", description="", headings={}, canonical="", meta_robots="", x_robots="", source_html="", rendered_html="", rendered_text="", images=[], structured_data=[], redirect_chain=[], robots_allowed=False, discovered_at=self._now(), content_hash=""))
            if pages and not batch:
                progress(len(pages), len(queue), robots_status)
                continue
            if self._executor_mode(request) == "async":
                results = asyncio.run(self._async_batch(batch, request.delay_seconds))
                materialized = [self._materialize_static(request, result) for result in results]
            elif self._executor_mode(request) == "process":
                fetched = [self._thread_fetch_with_gate(url, thread_gate, last_request, request.delay_seconds) for url in batch]
                with ProcessPoolExecutor(max_workers=self.settings.process_workers) as executor:
                    processed = executor.map(_materialize_static_process, [(self.settings, request, result) for result in fetched])
                    materialized = [(PageRecord(**page), [LinkRecord(**link) for link in page_links]) for page, page_links in processed]
            else:
                with ThreadPoolExecutor(max_workers=self.settings.thread_workers) as executor:
                    fetched = list(executor.map(lambda url: self._thread_fetch_with_gate(url, thread_gate, last_request, request.delay_seconds), batch))
                materialized = [self._materialize_static(request, result) for result in fetched]
            for page, page_links in materialized:
                pages.append(page)
                links.extend(page_links)
                if request.mode == "site":
                    for link in page_links:
                        if not link.is_internal or (request.respect_nofollow and link.nofollow) or link.target_url in queued:
                            continue
                        if len(queued) >= request.max_urls:
                            break
                        queued.add(link.target_url)
                        queue.append(link.target_url)
                progress(len(pages), len(queue), robots_status)
        return pages[: request.max_urls], links, robots_status

    def _executor_mode(self, request: CrawlRequest) -> str:
        return request.executor_mode or self.settings.crawl_executor_mode

    def _worker_count(self, request: CrawlRequest) -> int:
        mode = self._executor_mode(request)
        if mode == "async":
            return self.settings.async_concurrency
        if mode == "thread":
            return self.settings.thread_workers
        if mode == "process":
            return self.settings.process_workers
        return 1

    def run(self, request: CrawlRequest, progress: callable) -> tuple[list[PageRecord], list[LinkRecord], str]:
        if not request.acknowledgment:
            raise ValueError("Ownership or permission acknowledgement is required before a crawl can start.")
        mode = self._executor_mode(request)
        self.extraction_profile = load_profile(request.extraction_profile_path or self.settings.extraction_profile_path)
        if mode not in {"serial", "thread", "async", "process"}:
            raise ValueError("Crawl executor mode must be serial, thread, async, or process.")
        if mode != "serial":
            return self._run_static_mode(request, progress)
        queue = deque(request.url_list if request.mode == "list" else [request.start_url])
        queued = set(queue)
        pages: list[PageRecord] = []
        links: list[LinkRecord] = []
        last_request_at = 0.0
        headers = {"User-Agent": self.settings.user_agent, "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,application/json,application/xml,text/csv"}

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
                    page, page_links = self._build_page(request, url, response, redirect_chain, fetch_error, browser_page)
                    links.extend(page_links)
                    pages.append(page)
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
