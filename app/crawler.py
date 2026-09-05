"""Bounded, robots-aware collection for explicitly authorized same-host crawls."""

from __future__ import annotations

import asyncio
import time
from email.utils import parsedate_to_datetime
from collections import deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from threading import Lock
from datetime import UTC, datetime
from urllib import robotparser

import httpx

from app.config import Settings
from app.documents import extract_document_text
from app.knowledge import infer_source_type
from app.normalization import normalize_page_payload
from app.extraction_profiles import extract_profile_fields, load_profile
from app.parser import extract_api_entry_points, extract_links, extract_page_signals, normalized_text, text_hash
from app.frontier import CrawlFrontier
from app.types import (
    CancellationToken,
    CrawlRequest,
    CrawlResult,
    CrawlStatus,
    EngineMode,
    FetchMode,
    LinkRecord,
    PageRecord,
)
from app.urltools import (
    UrlNormalizationPolicy,
    UrlValidationError,
    detect_api_pagination,
    is_same_host,
    normalize_url,
    redact_secrets_in_text,
    resolve_canonical_url,
)
from urllib.parse import urlsplit

_PRESERVE_SLASH_POLICY = UrlNormalizationPolicy(trailing_slash="preserve")


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

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int, base_seconds: float) -> float:
        delay = base_seconds * (2 ** attempt)
        value = response.headers.get("retry-after", "").strip()
        if value:
            try:
                delay = max(delay, min(300.0, float(value)))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(value)
                    delay = max(delay, min(300.0, max(0.0, retry_at.timestamp() - time.time())))
                except (TypeError, ValueError, OverflowError):
                    pass
        return delay

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
                    time.sleep(self._retry_delay(response, attempt, self.settings.retry_backoff_seconds))
                    continue
                break
            if response is None:
                return None, hops, "Request ended without a response."
            if response.is_redirect and response.headers.get("location"):
                try:
                    current = normalize_url(
                        response.headers["location"],
                        current,
                        allow_private=getattr(self.settings, "allow_private_crawls", False),
                        policy=_PRESERVE_SLASH_POLICY,
                    )
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

    def _build_page(self, request: CrawlRequest, url: str, response: httpx.Response | None, redirect_chain: list[dict[str, object]], fetch_error: str, browser_page: object | None = None, parent_url: str = "", depth: int = 0) -> tuple[PageRecord, list[LinkRecord]]:
        if not response:
            return self._error_page(url, redirect_chain, fetch_error), []
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
        source_html = response.text[: self.settings.max_document_bytes] if "html" in content_type else ""
        extracted_text, extraction_error = ("", "") if source_html else extract_document_text(content_type, response.content[: self.settings.max_document_bytes])
        body_truncated = len(response.content) > self.settings.max_document_bytes
        allow_private = getattr(self.settings, "allow_private_crawls", False)
        final_url = normalize_url(str(response.url), allow_private=allow_private)
        render_html, rendered_text, render_error = self._render(browser_page, final_url) if source_html else ("", "", "")
        effective_rendered_text = rendered_text or extracted_text
        source_signals = extract_page_signals(source_html, final_url, request.start_url, allow_private=allow_private) if source_html else self._empty_signals()
        rendered_signals = extract_page_signals(render_html, final_url, request.start_url, allow_private=allow_private) if render_html else self._empty_signals()
        payload_api_entries = extract_api_entry_points(extracted_text, final_url, request.start_url, allow_private=allow_private) if extracted_text and not source_html else []
        selected_structured_data = rendered_signals["structured_data"] or source_signals["structured_data"]
        extracted_fields = extract_profile_fields(self.extraction_profile, final_url, source_html, render_html, selected_structured_data)
        extraction_notes = [
            f"{name}: {field.get('status')}" + (f" — {field.get('note')}" if field.get("note") else "")
            for name, field in extracted_fields.get("fields", {}).items() if field.get("status") != "found"
        ]
        selected = rendered_signals if rendered_signals["title"] or rendered_signals["links"] else source_signals
        page_links = self._dedupe_links(source_signals["links"] + rendered_signals["links"])
        api_entry_points = self._dedupe_api_entry_points(source_signals["api_entry_points"] + rendered_signals["api_entry_points"] + payload_api_entries)
        title = selected["title"] or source_signals["title"]
        if not title and "json" in content_type:
            title = f"API {urlsplit(final_url).path}"
        source_type = infer_source_type(final_url, content_type)
        etag = response.headers.get("etag", "").strip()
        last_modified = response.headers.get("last-modified", "").strip()
        canonical_raw = selected["canonical"] or source_signals["canonical"]
        canonical = resolve_canonical_url(canonical_raw, final_url, allow_private=allow_private)

        engine_mode = getattr(request, "executor_mode", "serial") or getattr(self.settings, "crawl_executor_mode", "serial")
        status_code = response.status_code if response else None
        err_cat = "none"
        if fetch_error:
            err_cat = "fetch_error"
        elif status_code and status_code >= 400:
            err_cat = f"http_{status_code}"

        page = PageRecord(
            url=url, final_url=final_url, status_code=status_code, content_type=content_type,
            title=title, description=selected["description"] or source_signals["description"],
            headings=selected["headings"] or source_signals["headings"], canonical=canonical,
            meta_robots=selected["meta_robots"] or source_signals["meta_robots"], x_robots=response.headers.get("x-robots-tag", "").lower(),
            source_html=source_html, rendered_html=render_html, rendered_text=effective_rendered_text, extracted_text=extracted_text, extraction_error=extraction_error, images=selected["images"] or source_signals["images"],
            structured_data=selected["structured_data"] or source_signals["structured_data"], api_entry_points=api_entry_points, redirect_chain=redirect_chain,
            fetch_error=fetch_error, render_error=render_error, robots_allowed=True, body_truncated=body_truncated,
            extracted_fields=extracted_fields, extraction_notes=extraction_notes,
            discovered_at=self._now(), content_hash=text_hash(effective_rendered_text or source_html or extracted_text),
            etag=etag, last_modified=last_modified, source_type=source_type, depth=depth, parent_url=parent_url,
            normalized_url=final_url or url,
            fetch_strategy="browser" if render_html else "static",
            requested_fetch_strategy="browser" if (self.settings.render_enabled and browser_page is not None) else "static",
            actual_fetch_strategy="browser" if render_html else "static",
            crawler_engine=engine_mode,
            response_bytes=len(response.content) if response else 0,
            duration_ms=0.0,
            error_category=err_cat,
            headers=dict(response.headers) if response else {},
        )
        return PageRecord(**normalize_page_payload(page.to_dict())), page_links


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
                    await asyncio.sleep(self._retry_delay(response, attempt, self.settings.retry_backoff_seconds))
                    continue
                break
            if response is None:
                return url, None, hops, "Request ended without a response."
            if response.is_redirect and response.headers.get("location"):
                try:
                    current = normalize_url(
                        response.headers["location"],
                        current,
                        allow_private=getattr(self.settings, "allow_private_crawls", False),
                        policy=_PRESERVE_SLASH_POLICY,
                    )
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
            return self._error_page(url, redirect_chain, fetch_error, getattr(request, "executor_mode", "serial")), []
        status_code, headers, content, final_url = payload
        response = httpx.Response(status_code, headers=headers, content=content, request=httpx.Request("GET", final_url))
        page, page_links = self._build_page(request, url, response, redirect_chain, fetch_error, None)
        return page, page_links


def _materialize_static_process(args: tuple[Settings, CrawlRequest, tuple[str, tuple[int, dict[str, str], bytes, str] | None, list[dict[str, object]], str]]) -> tuple[dict[str, object], list[dict[str, object]]]:
    settings, request, result = args
    page, links = CrawlEngine(settings)._materialize_static(request, result)
    return page.to_dict(), [link.to_dict() for link in links]


class CrawlEngine(CrawlEngine):
    def _run_static_mode(self, request: CrawlRequest, progress: callable, cancellation_token: CancellationToken | None = None) -> CrawlResult:
        start_time = time.monotonic()
        started_at = self._now()
        mode = self._executor_mode(request)
        frontier = CrawlFrontier(
            start_url=request.start_url,
            max_urls=request.max_urls,
            max_depth=getattr(request, "max_depth", 10),
            mode=request.mode,
            url_list=request.url_list,
            allow_private=getattr(self.settings, "allow_private_crawls", False),
            max_retries=self.settings.max_request_retries,
            retry_backoff_seconds=self.settings.retry_backoff_seconds,
        )
        pages: list[PageRecord] = []
        links: list[LinkRecord] = []
        seen_content_hashes: dict[str, str] = {}
        seen_canonicals: dict[str, str] = {}
        pagination_counts: dict[str, int] = {}
        headers = {"User-Agent": self.settings.user_agent, "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,application/json,application/xml,text/csv"}
        with httpx.Client(headers=headers, timeout=self.settings.request_timeout_seconds, follow_redirects=False) as client:
            robots, robots_status = self._robots(client, request.start_url)
        thread_gate = Lock()
        last_request = {"value": time.monotonic()}
        while not frontier.is_complete() and len(pages) < request.max_urls:
            if cancellation_token and cancellation_token.is_cancelled():
                break
            batch_entries: list[FrontierEntry] = []
            while len(batch_entries) < self._worker_count(request) and not frontier.is_complete():
                entry = frontier.get_next()
                if entry is None:
                    break
                if robots.can_fetch(self.settings.user_agent, entry.url):
                    batch_entries.append(entry)
                else:
                    frontier.mark_skipped(entry.url, reason="robots_disallowed")
                    pages.append(
                        PageRecord(
                            url=entry.url, final_url=entry.url, depth=entry.depth, parent_url=entry.parent_url, status_code=None, content_type="", title="", description="", headings={}, canonical="",
                            meta_robots="", x_robots="", source_html="", rendered_html="", rendered_text="", images=[], structured_data=[],
                            redirect_chain=[], fetch_error="", render_error="", robots_allowed=False, discovered_at=self._now(), content_hash="",
                            normalized_url=entry.url, fetch_strategy="static", crawler_engine=mode, response_bytes=0, duration_ms=0.0,
                            error_category="robots_disallowed", headers={},
                        )
                    )
            if pages and not batch_entries:
                progress(len(pages), frontier.queue_size, robots_status)
                if frontier.is_complete():
                    break
                time.sleep(0.02)
                continue

            batch = [e.url for e in batch_entries]
            batch_map = {e.url: e for e in batch_entries}
            if self._executor_mode(request) == "async":
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        results = pool.submit(asyncio.run, self._async_batch(batch, request.delay_seconds)).result()
                else:
                    results = asyncio.run(self._async_batch(batch, request.delay_seconds))
                materialized = [self._materialize_static(request, result) for result in results]
            elif self._executor_mode(request) == "process":
                try:
                    fetched = [self._thread_fetch_with_gate(url, thread_gate, last_request, request.delay_seconds) for url in batch]
                    with ProcessPoolExecutor(max_workers=self.settings.process_workers) as executor:
                        processed = list(executor.map(_materialize_static_process, [(self.settings, request, result) for result in fetched]))
                        materialized = [(PageRecord(**page), [LinkRecord(**link) for link in page_links]) for page, page_links in processed]
                except Exception as exc:
                    raise RuntimeError(f"Process executor mode failed: {type(exc).__name__}: {exc}") from exc
            else:
                with ThreadPoolExecutor(max_workers=self.settings.thread_workers) as executor:
                    fetched = list(executor.map(lambda url: self._thread_fetch_with_gate(url, thread_gate, last_request, request.delay_seconds), batch))
                materialized = [self._materialize_static(request, result) for result in fetched]

            for page, page_links in materialized:
                orig_entry = batch_map.get(page.url)
                if orig_entry:
                    page.depth = orig_entry.depth
                    page.parent_url = orig_entry.parent_url

                if page.final_url and page.final_url != page.url:
                    frontier.handle_redirect(page.url, page.final_url, page.depth, page.parent_url, enqueue_target=False)

                # Deduplication detection
                is_dup = False
                dup_of = ""
                if page.canonical and page.canonical != page.final_url:
                    is_canon_dup = frontier.handle_canonical(page.final_url, page.canonical)
                    if is_canon_dup:
                        is_dup = True
                        dup_of = page.canonical
                    elif page.canonical in seen_canonicals:
                        is_dup = True
                        dup_of = seen_canonicals[page.canonical]
                    else:
                        seen_canonicals[page.canonical] = page.final_url
                elif page.content_hash and page.content_hash in seen_content_hashes and (page.rendered_text or page.extracted_text or page.source_html):
                    is_dup = True
                    dup_of = seen_content_hashes[page.content_hash]
                else:
                    if page.canonical:
                        seen_canonicals[page.canonical] = page.final_url
                    if page.content_hash:
                        seen_content_hashes[page.content_hash] = page.final_url
                page.is_duplicate = is_dup
                page.duplicate_of = dup_of

                if is_dup:
                    frontier.mark_duplicate(page.url, dup_of)
                elif page.status_code and page.status_code >= 400:
                    frontier.mark_failed(page.url, f"HTTP {page.status_code}", is_retryable=False)
                else:
                    frontier.mark_completed(page.url, status_code=page.status_code or 200)

                pages.append(page)
                links.extend(page_links)
                self._enqueue_discovered(request, page, page_links, frontier, pagination_counts)
                progress(len(pages), frontier.queue_size, robots_status)

        pages_to_return = pages[: request.max_urls]
        finished_at = self._now()
        duration_ms = (time.monotonic() - start_time) * 1000.0
        pages_succeeded = sum(1 for p in pages_to_return if p.status_code and p.status_code < 400 and p.robots_allowed and not p.fetch_error)
        pages_failed = len(pages_to_return) - pages_succeeded
        fallback_occurred = bool(self.settings.render_enabled)
        fallback_reason = "Browser rendering is unsupported in multi-worker static executor; fell back to static fetch." if fallback_occurred else ""
        cancelled = bool(cancellation_token and cancellation_token.is_cancelled())
        status = CrawlStatus.CANCELLED.value if cancelled else CrawlStatus.SUCCESS.value
        if not cancelled and pages_failed > 0:
            status = CrawlStatus.PARTIAL.value if pages_succeeded > 0 else CrawlStatus.FAILED.value

        termination_reason = (
            f"cancelled: {cancellation_token.reason or 'Cooperative cancellation requested'}"
            if cancelled
            else ("max_urls_reached" if len(pages) >= request.max_urls else "queue_empty")
        )

        accounting = frontier.reconcile_accounting()

        return CrawlResult(
            crawl_id=getattr(request, "crawl_id", ""),
            requested_engine=mode,
            actual_engine=mode,
            requested_fetch_mode="browser" if self.settings.render_enabled else "static",
            actual_fetch_mode="static",
            fallback_occurred=fallback_occurred,
            fallback_reason=fallback_reason,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            status=status,
            termination_reason=termination_reason,
            pages_discovered=frontier.total_discovered,
            pages_attempted=len(pages_to_return),
            pages_succeeded=pages_succeeded,
            pages_failed=pages_failed,
            pages_skipped=accounting.get("skipped", 0),
            duplicates_count=sum(1 for p in pages_to_return if p.is_duplicate),
            retry_count=0,
            errors=[p.fetch_error for p in pages_to_return if p.fetch_error],
            pages=pages_to_return,
            links=links,
            robots_status=robots_status,
        )

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

    def run(self, request: CrawlRequest, progress: callable, cancellation_token: CancellationToken | None = None) -> CrawlResult:
        if not request.acknowledgment:
            raise ValueError("Ownership or permission acknowledgement is required before a crawl can start.")
        mode = self._executor_mode(request)
        self.extraction_profile = load_profile(request.extraction_profile_path or self.settings.extraction_profile_path)
        if mode not in {"serial", "thread", "async", "process"}:
            raise ValueError("Crawl executor mode must be serial, thread, async, or process.")
        if mode != "serial":
            return self._run_static_mode(request, progress, cancellation_token)
        start_time = time.monotonic()
        started_at = self._now()
        frontier = CrawlFrontier(
            start_url=request.start_url,
            max_urls=request.max_urls,
            max_depth=getattr(request, "max_depth", 10),
            mode=request.mode,
            url_list=request.url_list,
            allow_private=getattr(self.settings, "allow_private_crawls", False),
            max_retries=self.settings.max_request_retries,
            retry_backoff_seconds=self.settings.retry_backoff_seconds,
        )
        pages: list[PageRecord] = []
        links: list[LinkRecord] = []
        seen_content_hashes: dict[str, str] = {}
        seen_canonicals: dict[str, str] = {}
        pagination_counts: dict[str, int] = {}
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
                while not frontier.is_complete() and len(pages) < request.max_urls:
                    if cancellation_token and cancellation_token.is_cancelled():
                        break
                    entry = frontier.get_next()
                    if entry is None:
                        if frontier.is_complete():
                            break
                        time.sleep(0.02)
                        continue
                    url = entry.url
                    depth = entry.depth
                    parent_url = entry.parent_url
                    if not robots.can_fetch(self.settings.user_agent, url):
                        frontier.mark_skipped(url, reason="robots_disallowed")
                        pages.append(
                            PageRecord(
                                url=url, final_url=url, depth=depth, parent_url=parent_url, status_code=None, content_type="", title="", description="", headings={}, canonical="",
                                meta_robots="", x_robots="", source_html="", rendered_html="", rendered_text="", images=[], structured_data=[],
                                redirect_chain=[], fetch_error="", render_error="", robots_allowed=False, discovered_at=self._now(), content_hash="",
                                normalized_url=url, fetch_strategy="static", crawler_engine="serial", response_bytes=0, duration_ms=0.0,
                                error_category="robots_disallowed", headers={},
                            )
                        )
                        progress(len(pages), frontier.queue_size, robots_status)
                        continue
                    pause = request.delay_seconds - (time.monotonic() - last_request_at)
                    if pause > 0:
                        time.sleep(pause)
                    response, redirect_chain, fetch_error = self._fetch(client, url)
                    last_request_at = time.monotonic()
                    if not response:
                        frontier.mark_failed(url, fetch_error, is_retryable=False)
                        pages.append(self._error_page(url, redirect_chain, fetch_error, "serial", depth=depth, parent_url=parent_url))
                        progress(len(pages), frontier.queue_size, robots_status)
                        continue

                    final_url = normalize_url(str(response.url), allow_private=getattr(self.settings, "allow_private_crawls", False))
                    if final_url != url:
                        frontier.handle_redirect(url, final_url, depth, parent_url, enqueue_target=False)

                    page, page_links = self._build_page(request, url, response, redirect_chain, fetch_error, browser_page, parent_url=parent_url, depth=depth)

                    # Deduplication detection
                    is_dup = False
                    dup_of = ""
                    if page.canonical and page.canonical != page.final_url:
                        is_canon_dup = frontier.handle_canonical(page.final_url, page.canonical)
                        if is_canon_dup:
                            is_dup = True
                            dup_of = page.canonical
                        elif page.canonical in seen_canonicals:
                            is_dup = True
                            dup_of = seen_canonicals[page.canonical]
                        else:
                            seen_canonicals[page.canonical] = page.final_url
                    elif page.content_hash and page.content_hash in seen_content_hashes and (page.rendered_text or page.extracted_text or page.source_html):
                        is_dup = True
                        dup_of = seen_content_hashes[page.content_hash]
                    else:
                        if page.canonical:
                            seen_canonicals[page.canonical] = page.final_url
                        if page.content_hash:
                            seen_content_hashes[page.content_hash] = page.final_url
                    page.is_duplicate = is_dup
                    page.duplicate_of = dup_of

                    if is_dup:
                        frontier.mark_duplicate(url, dup_of)
                    elif response.status_code and response.status_code >= 400:
                        frontier.mark_failed(url, f"HTTP {response.status_code}", is_retryable=False)
                    else:
                        frontier.mark_completed(url, status_code=response.status_code or 200)

                    links.extend(page_links)
                    pages.append(page)
                    self._enqueue_discovered(request, page, page_links, frontier, pagination_counts)
                    progress(len(pages), frontier.queue_size, robots_status)
            finally:
                if browser:
                    browser.close()
                if playwright:
                    playwright.stop()

        pages_to_return = pages[: request.max_urls]
        finished_at = self._now()
        duration_ms = (time.monotonic() - start_time) * 1000.0
        pages_succeeded = sum(1 for p in pages_to_return if p.status_code and p.status_code < 400 and p.robots_allowed and not p.fetch_error)
        pages_failed = len(pages_to_return) - pages_succeeded
        requested_fetch_mode = "browser" if self.settings.render_enabled else "static"
        actual_fetch_mode = "browser" if (self.settings.render_enabled and browser_page is not None) else "static"
        fallback_occurred = (requested_fetch_mode == "browser" and actual_fetch_mode == "static")
        fallback_reason = "Playwright/Chromium was unavailable for rendering; fell back to static fetch." if fallback_occurred else ""
        cancelled = bool(cancellation_token and cancellation_token.is_cancelled())
        status = CrawlStatus.CANCELLED.value if cancelled else CrawlStatus.SUCCESS.value
        if not cancelled and pages_failed > 0:
            status = CrawlStatus.PARTIAL.value if pages_succeeded > 0 else CrawlStatus.FAILED.value

        termination_reason = (
            f"cancelled: {cancellation_token.reason or 'Cooperative cancellation requested'}"
            if cancelled
            else ("max_urls_reached" if len(pages) >= request.max_urls else "queue_empty")
        )

        accounting = frontier.reconcile_accounting()

        return CrawlResult(
            crawl_id=getattr(request, "crawl_id", ""),
            requested_engine="serial",
            actual_engine="serial",
            requested_fetch_mode=requested_fetch_mode,
            actual_fetch_mode=actual_fetch_mode,
            fallback_occurred=fallback_occurred,
            fallback_reason=fallback_reason,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            status=status,
            termination_reason=termination_reason,
            pages_discovered=frontier.total_discovered,
            pages_attempted=len(pages_to_return),
            pages_succeeded=pages_succeeded,
            pages_failed=pages_failed,
            pages_skipped=accounting.get("skipped", 0),
            duplicates_count=sum(1 for p in pages_to_return if p.is_duplicate),
            retry_count=0,
            errors=[p.fetch_error for p in pages_to_return if p.fetch_error],
            pages=pages_to_return,
            links=links,
            robots_status=robots_status,
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

    @staticmethod
    def _empty_signals() -> dict[str, object]:
        return {"title": "", "description": "", "headings": {}, "canonical": "", "meta_robots": "", "images": [], "structured_data": [], "api_entry_points": [], "links": []}

    def _enqueue_discovered(
        self,
        request: CrawlRequest,
        page: PageRecord,
        page_links: list[LinkRecord],
        frontier: Any,
        pagination_counts: Any = None,
    ) -> None:
        if request.mode != "site":
            return
        targets: list[str] = [link.target_url for link in page_links if link.is_internal and not (request.respect_nofollow and link.nofollow)]
        if request.follow_api_entry_points:
            targets.extend(str(entry.get("url", "")) for entry in page.api_entry_points if entry.get("method", "GET") == "GET" and entry.get("is_internal"))
        valid_targets: list[str] = []
        for raw_target in targets:
            if not raw_target:
                continue
            # API pagination loop detection & budgeting
            is_pag, base_path, pag_val = detect_api_pagination(raw_target)
            if is_pag and isinstance(pagination_counts, dict):
                count = pagination_counts.get(base_path, 0)
                if count >= 3 or pag_val > 90:
                    continue
                pagination_counts[base_path] = count + 1
            valid_targets.append(raw_target)

        if hasattr(frontier, "discover"):
            frontier.discover(valid_targets, parent_url=page.final_url or page.url, parent_depth=page.depth)
        else:
            # Legacy deque + set support for internal test compatibility
            queued = pagination_counts if isinstance(pagination_counts, set) else set()
            for raw_t in valid_targets:
                if raw_t not in queued and len(queued) < request.max_urls:
                    queued.add(raw_t)
                    frontier.append(raw_t)


    @staticmethod
    def _dedupe_api_entry_points(entries: list[dict[str, object]]) -> list[dict[str, object]]:
        seen: set[tuple[str, str]] = set()
        result: list[dict[str, object]] = []
        for entry in entries:
            key = (str(entry.get("url", "")), str(entry.get("method", "GET")).upper())
            if key[0] and key not in seen:
                seen.add(key)
                result.append(dict(entry))
        return result[:100]

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
    def _error_page(url: str, redirect_chain: list[dict[str, object]], error: str, engine_mode: str = "serial", depth: int = 0, parent_url: str = "") -> PageRecord:
        return PageRecord(
            url=url, final_url=url, status_code=None, content_type="", title="", description="", headings={}, canonical="", meta_robots="",
            x_robots="", source_html="", rendered_html="", rendered_text="", images=[], structured_data=[], redirect_chain=redirect_chain,
            fetch_error=error, render_error="", discovered_at=CrawlEngine._now(), content_hash="",
            depth=depth, parent_url=parent_url,
            normalized_url=url,
            fetch_strategy="static",
            crawler_engine=engine_mode,
            response_bytes=0,
            duration_ms=0.0,
            error_category="fetch_error",
            headers={},
        )
