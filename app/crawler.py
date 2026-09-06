"""Bounded, robots-aware collection for explicitly authorized same-host crawls across 4 genuinely independent engines."""

from __future__ import annotations

import asyncio
import concurrent.futures
from concurrent.futures.process import BrokenProcessPool
from contextlib import asynccontextmanager, contextmanager
import multiprocessing
import os
import random
import threading
import time
from collections import deque
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib import robotparser
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from app.browser import PlaywrightBrowserSession
from app.config import Settings
from app.documents import extract_document_text
from app.escalation import should_escalate_to_browser
from app.extraction_profiles import extract_profile_fields, load_profile
from app.frontier import CrawlFrontier, FrontierEntry
from app.knowledge import infer_source_type
from app.multiprocess_worker import execute_worker_crawl_task
from app.normalization import normalize_page_payload
from app.parser import extract_api_entry_points, extract_links, extract_page_signals, normalized_text, text_hash
from app.types import (
    CancellationToken,
    CrawlerEngineProtocol,
    CrawlBudget,
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

_PRESERVE_SLASH_POLICY = UrlNormalizationPolicy(trailing_slash="preserve")


def extract_crawl_delay(lines: list[str], user_agent: str = "*") -> float | None:
    """Parse Crawl-delay from robots.txt lines respecting user-agent specificity and float delays."""
    current_agents: list[str] = []
    agent_delays: dict[str, float] = {}
    in_rules = False
    for raw_line in lines:
        line = raw_line.split("#")[0].strip()
        if not line:
            current_agents = []
            in_rules = False
            continue
        parts = line.split(":", 1)
        if len(parts) == 2:
            directive = parts[0].strip().lower()
            val = parts[1].strip()
            if directive == "user-agent":
                if in_rules:
                    current_agents = []
                    in_rules = False
                current_agents.append(val.lower())
            elif directive == "crawl-delay" and current_agents:
                in_rules = True
                try:
                    delay_val = float(val)
                    for a in current_agents:
                        agent_delays[a] = delay_val
                except ValueError:
                    pass
            elif directive in ("allow", "disallow"):
                in_rules = True

    ua_lower = user_agent.lower()
    if ua_lower in agent_delays:
        return agent_delays[ua_lower]
    for k, v in agent_delays.items():
        if k != "*" and (k in ua_lower or ua_lower.startswith(k)):
            return v
    return agent_delays.get("*")


class DomainPolitenessThrottler:
    """Thread-safe per-domain politeness and concurrency coordinator."""

    def __init__(self, delay_seconds: float, per_host_concurrency: int = 1) -> None:
        self.delay_seconds = max(0.0, delay_seconds)
        self.per_host_concurrency = max(1, per_host_concurrency)
        self._meta_lock = threading.Lock()
        self._domain_semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._domain_delays: dict[str, float] = {}
        self._last_completed_time: dict[str, float] = {}

    def set_domain_delay(self, domain: str, delay: float) -> None:
        dom_clean = domain.lower().strip()
        host_only = dom_clean.split(":")[0]
        with self._meta_lock:
            self._domain_delays[dom_clean] = max(0.0, delay)
            self._domain_delays[host_only] = max(0.0, delay)

    def record_completion(self, url: str) -> None:
        domain = (urlsplit(url).netloc or "").lower()
        host = (urlsplit(url).hostname or "").lower()
        now = time.monotonic()
        with self._meta_lock:
            self._last_completed_time[domain] = now
            if host:
                self._last_completed_time[host] = now

    def _get_domain_semaphore(self, domain: str) -> threading.BoundedSemaphore:
        with self._meta_lock:
            if domain not in self._domain_semaphores:
                self._domain_semaphores[domain] = threading.BoundedSemaphore(self.per_host_concurrency)
            return self._domain_semaphores[domain]

    @contextmanager
    def acquire(self, url: str):
        domain = (urlsplit(url).netloc or "").lower()
        host = (urlsplit(url).hostname or "").lower()
        sem = self._get_domain_semaphore(domain)
        sem.acquire()
        try:
            with self._meta_lock:
                last_time = max(self._last_completed_time.get(domain, 0.0), self._last_completed_time.get(host, 0.0))
                req_delay = max(self.delay_seconds, self._domain_delays.get(domain, 0.0), self._domain_delays.get(host, 0.0))
            now = time.monotonic()
            pause = req_delay - (now - last_time)
            if pause > 0:
                time.sleep(pause)
            yield
        finally:
            now = time.monotonic()
            with self._meta_lock:
                self._last_completed_time[domain] = now
                if host:
                    self._last_completed_time[host] = now
            sem.release()

    def throttle(self, url: str) -> None:
        with self.acquire(url):
            pass


class AsyncDomainPolitenessThrottler:
    """Async per-domain politeness and concurrency coordinator."""

    def __init__(self, delay_seconds: float, per_host_concurrency: int = 1) -> None:
        self.delay_seconds = max(0.0, delay_seconds)
        self.per_host_concurrency = max(1, per_host_concurrency)
        self._domain_semaphores: dict[str, asyncio.Semaphore] = {}
        self._domain_delays: dict[str, float] = {}
        self._last_completed_time: dict[str, float] = {}

    def set_domain_delay(self, domain: str, delay: float) -> None:
        dom_clean = domain.lower().strip()
        host_only = dom_clean.split(":")[0]
        self._domain_delays[dom_clean] = max(0.0, delay)
        self._domain_delays[host_only] = max(0.0, delay)

    def record_completion(self, url: str) -> None:
        domain = (urlsplit(url).netloc or "").lower()
        host = (urlsplit(url).hostname or "").lower()
        now = time.monotonic()
        self._last_completed_time[domain] = now
        if host:
            self._last_completed_time[host] = now

    def _get_domain_semaphore(self, domain: str) -> asyncio.Semaphore:
        if domain not in self._domain_semaphores:
            self._domain_semaphores[domain] = asyncio.Semaphore(self.per_host_concurrency)
        return self._domain_semaphores[domain]

    @asynccontextmanager
    async def acquire(self, url: str):
        domain = (urlsplit(url).netloc or "").lower()
        host = (urlsplit(url).hostname or "").lower()
        sem = self._get_domain_semaphore(domain)
        await sem.acquire()
        try:
            last_time = max(self._last_completed_time.get(domain, 0.0), self._last_completed_time.get(host, 0.0))
            req_delay = max(self.delay_seconds, self._domain_delays.get(domain, 0.0), self._domain_delays.get(host, 0.0))
            now = time.monotonic()
            pause = req_delay - (now - last_time)
            if pause > 0:
                await asyncio.sleep(pause)
            yield
        finally:
            now = time.monotonic()
            self._last_completed_time[domain] = now
            if host:
                self._last_completed_time[host] = now
            sem.release()

    async def throttle(self, url: str) -> None:
        async with self.acquire(url):
            pass


class BaseCrawlerEngine:
    """Base crawler engine providing shared signal extraction, robots, and result assembly."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.extraction_profile = load_profile(settings.extraction_profile_path)
        self._robots_cache: dict[str, tuple[robotparser.RobotFileParser, str]] = {}
        self._async_robots_cache: dict[str, tuple[robotparser.RobotFileParser, str]] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

    @staticmethod
    def _empty_signals() -> dict[str, object]:
        return {
            "title": "",
            "description": "",
            "headings": {},
            "canonical": "",
            "meta_robots": "",
            "images": [],
            "structured_data": [],
            "api_entry_points": [],
            "links": [],
        }

    def _robots(
        self,
        client: httpx.Client,
        start_url: str,
        respect_robots: bool = True,
        throttler: DomainPolitenessThrottler | None = None,
    ) -> tuple[robotparser.RobotFileParser, str]:
        policy = robotparser.RobotFileParser()
        if not respect_robots:
            policy.allow_all = True
            return policy, "disabled_by_configuration"

        parsed = httpx.URL(start_url)
        origin_key = f"{parsed.scheme}://{parsed.netloc.decode('ascii') if isinstance(parsed.netloc, bytes) else parsed.netloc}"
        if origin_key in self._robots_cache:
            return self._robots_cache[origin_key]

        robots_url = f"{origin_key}/robots.txt"
        policy.set_url(robots_url)
        try:
            response = client.get(robots_url, follow_redirects=True)
            if response.status_code == 200:
                lines = response.text.splitlines()
                policy.parse(lines)
                crawl_delay = extract_crawl_delay(lines, self.settings.user_agent)
                if crawl_delay is not None and throttler:
                    throttler.set_domain_delay(parsed.host, crawl_delay)
                res = (policy, "loaded")
            elif response.status_code >= 500:
                # RFC 9309 section 3.3.1: Server errors MUST be treated as temporarily disallowed / fail-closed
                policy.disallow_all = True
                res = (policy, f"unavailable (HTTP {response.status_code} - fail-closed RFC 9309)")
            elif response.status_code == 429:
                policy.disallow_all = True
                res = (policy, "rate_limited (HTTP 429 - fail-closed RFC 9309)")
            else:
                # 4xx (e.g. 404): RFC 9309 section 3.3.1: allow all
                policy.allow_all = True
                res = (policy, f"unavailable (HTTP {response.status_code} - allow-all)")
        except httpx.HTTPError as exc:
            policy.allow_all = True
            res = (policy, f"unavailable ({type(exc).__name__})")

        self._robots_cache[origin_key] = res
        return res

    def _safe_robots(
        self,
        client: httpx.Client,
        url: str,
        respect_robots: bool = True,
        throttler: DomainPolitenessThrottler | None = None,
    ) -> tuple[robotparser.RobotFileParser, str]:
        """Invoke _robots safely accommodating tests that monkeypatch _robots with 2 arguments."""
        import inspect
        sig = inspect.signature(self._robots)
        params = list(sig.parameters.values())
        if len(params) >= 4 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
            return self._robots(client, url, respect_robots, throttler)
        elif len(params) == 3:
            return self._robots(client, url, respect_robots)
        else:
            return self._robots(client, url)

    async def _async_robots(
        self,
        client: httpx.AsyncClient,
        start_url: str,
        respect_robots: bool = True,
        throttler: AsyncDomainPolitenessThrottler | None = None,
    ) -> tuple[robotparser.RobotFileParser, str]:
        policy = robotparser.RobotFileParser()
        if not respect_robots:
            policy.allow_all = True
            return policy, "disabled_by_configuration"

        parsed = httpx.URL(start_url)
        origin_key = f"{parsed.scheme}://{parsed.netloc.decode('ascii') if isinstance(parsed.netloc, bytes) else parsed.netloc}"
        if origin_key in self._async_robots_cache:
            return self._async_robots_cache[origin_key]

        robots_url = f"{origin_key}/robots.txt"
        policy.set_url(robots_url)
        try:
            response = await client.get(robots_url, follow_redirects=True)
            if response.status_code == 200:
                lines = response.text.splitlines()
                policy.parse(lines)
                crawl_delay = extract_crawl_delay(lines, self.settings.user_agent)
                if crawl_delay is not None and throttler:
                    throttler.set_domain_delay(parsed.host, crawl_delay)
                res = (policy, "loaded")
            elif response.status_code >= 500:
                # RFC 9309 section 3.3.1: Server errors MUST be treated as temporarily disallowed / fail-closed
                policy.disallow_all = True
                res = (policy, f"unavailable (HTTP {response.status_code} - fail-closed RFC 9309)")
            elif response.status_code == 429:
                policy.disallow_all = True
                res = (policy, "rate_limited (HTTP 429 - fail-closed RFC 9309)")
            else:
                # 4xx (e.g. 404): RFC 9309 section 3.3.1: allow all
                policy.allow_all = True
                res = (policy, f"unavailable (HTTP {response.status_code} - allow-all)")
        except httpx.HTTPError as exc:
            policy.allow_all = True
            res = (policy, f"unavailable ({type(exc).__name__})")

        self._async_robots_cache[origin_key] = res
        return res

    async def _safe_async_robots(
        self,
        client: httpx.AsyncClient,
        url: str,
        respect_robots: bool = True,
        throttler: AsyncDomainPolitenessThrottler | None = None,
    ) -> tuple[robotparser.RobotFileParser, str]:
        """Invoke _async_robots safely accommodating monkeypatched 2-arg implementations."""
        import inspect
        sig = inspect.signature(self._async_robots)
        params = list(sig.parameters.values())
        if len(params) >= 4 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
            return await self._async_robots(client, url, respect_robots, throttler)
        elif len(params) == 3:
            return await self._async_robots(client, url, respect_robots)
        else:
            return await self._async_robots(client, url)

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int, base_seconds: float) -> float:
        jitter = random.uniform(0.8, 1.2)
        delay = base_seconds * (2 ** attempt) * jitter
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

    @staticmethod
    def _sleep_interruptible(duration: float, cancellation_token: CancellationToken | None = None) -> None:
        if duration <= 0:
            return
        if not cancellation_token:
            time.sleep(duration)
            return
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if cancellation_token.is_cancelled():
                break
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    @staticmethod
    async def _async_sleep_interruptible(duration: float, cancellation_token: CancellationToken | None = None) -> None:
        if duration <= 0:
            return
        if not cancellation_token:
            await asyncio.sleep(duration)
            return
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if cancellation_token.is_cancelled():
                break
            await asyncio.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def _fetch(
        self,
        client: httpx.Client,
        url: str,
        cancellation_token: CancellationToken | None = None,
        max_retries: int | None = None,
        max_redirects: int | None = None,
    ) -> tuple[httpx.Response | None, list[dict[str, object]], str]:
        current = url
        hops: list[dict[str, object]] = []
        transient_statuses = {408, 425, 429, 500, 502, 503, 504}
        effective_redirects = max_redirects if max_redirects is not None else self.settings.max_redirects
        effective_retries = max_retries if max_retries is not None else self.settings.max_request_retries
        response: httpx.Response | None = None
        for _ in range(effective_redirects + 1):
            if cancellation_token and cancellation_token.is_cancelled():
                return None, hops, f"Request cancelled: {cancellation_token.reason or 'User cancelled'}"
            response = None
            for attempt in range(effective_retries + 1):
                if cancellation_token and cancellation_token.is_cancelled():
                    return None, hops, f"Request cancelled: {cancellation_token.reason or 'User cancelled'}"
                try:
                    response = client.get(current, follow_redirects=False)
                except httpx.HTTPError as exc:
                    if attempt >= effective_retries:
                        return None, hops, f"{type(exc).__name__} after {attempt + 1} attempt(s): {exc}"
                    jitter = random.uniform(0.8, 1.2)
                    self._sleep_interruptible(self.settings.retry_backoff_seconds * (2 ** attempt) * jitter, cancellation_token)
                    continue
                hops.append({
                    "url": current,
                    "status_code": response.status_code,
                    "location": response.headers.get("location", ""),
                    "attempt": attempt + 1,
                })
                if response.status_code in transient_statuses and attempt < effective_retries:
                    self._sleep_interruptible(self._retry_delay(response, attempt, self.settings.retry_backoff_seconds), cancellation_token)
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
                return response, hops, f"Transient HTTP status {response.status_code} remained after {effective_retries + 1} attempt(s)."
            return response, hops, ""
        return response, hops, f"Redirect limit ({effective_redirects}) exceeded."

    async def _async_fetch(
        self,
        client: httpx.AsyncClient,
        url: str,
        cancellation_token: CancellationToken | None = None,
        max_retries: int | None = None,
        max_redirects: int | None = None,
    ) -> tuple[httpx.Response | None, list[dict[str, object]], str]:
        current = url
        hops: list[dict[str, object]] = []
        transient_statuses = {408, 425, 429, 500, 502, 503, 504}
        effective_redirects = max_redirects if max_redirects is not None else self.settings.max_redirects
        effective_retries = max_retries if max_retries is not None else self.settings.max_request_retries
        response: httpx.Response | None = None
        for _ in range(effective_redirects + 1):
            if cancellation_token and cancellation_token.is_cancelled():
                return None, hops, f"Request cancelled: {cancellation_token.reason or 'User cancelled'}"
            response = None
            for attempt in range(effective_retries + 1):
                if cancellation_token and cancellation_token.is_cancelled():
                    return None, hops, f"Request cancelled: {cancellation_token.reason or 'User cancelled'}"
                try:
                    response = await client.get(current, follow_redirects=False)
                except httpx.HTTPError as exc:
                    if attempt >= effective_retries:
                        return None, hops, f"{type(exc).__name__} after {attempt + 1} attempt(s): {exc}"
                    jitter = random.uniform(0.8, 1.2)
                    await self._async_sleep_interruptible(self.settings.retry_backoff_seconds * (2 ** attempt) * jitter, cancellation_token)
                    continue
                hops.append({
                    "url": current,
                    "status_code": response.status_code,
                    "location": response.headers.get("location", ""),
                    "attempt": attempt + 1,
                })
                if response.status_code in transient_statuses and attempt < effective_retries:
                    await self._async_sleep_interruptible(self._retry_delay(response, attempt, self.settings.retry_backoff_seconds), cancellation_token)
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
                return response, hops, f"Transient HTTP status {response.status_code} remained after {effective_retries + 1} attempt(s)."
            return response, hops, ""
        return response, hops, f"Redirect limit ({effective_redirects}) exceeded."

    def _safe_fetch(
        self,
        client: httpx.Client,
        url: str,
        cancellation_token: CancellationToken | None = None,
        max_retries: int | None = None,
        max_redirects: int | None = None,
    ) -> tuple[httpx.Response | None, list[dict[str, object]], str]:
        """Invoke _fetch handling cancellation-aware and legacy monkeypatched fakes."""
        import inspect
        sig = inspect.signature(self._fetch)
        params = list(sig.parameters.values())
        if len(params) >= 5 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
            try:
                return self._fetch(client, url, cancellation_token, max_retries, max_redirects)
            except TypeError:
                pass
        if len(params) >= 3 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
            try:
                return self._fetch(client, url, cancellation_token)
            except TypeError:
                return self._fetch(client, url)
        return self._fetch(client, url)

    async def _safe_async_fetch(
        self,
        client: httpx.AsyncClient,
        url: str,
        cancellation_token: CancellationToken | None = None,
        max_retries: int | None = None,
        max_redirects: int | None = None,
    ) -> tuple[httpx.Response | None, list[dict[str, object]], str]:
        """Invoke _async_fetch handling cancellation-aware and legacy monkeypatched fakes."""
        import inspect
        sig = inspect.signature(self._async_fetch)
        params = list(sig.parameters.values())
        if len(params) >= 5 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
            try:
                return await self._async_fetch(client, url, cancellation_token, max_retries, max_redirects)
            except TypeError:
                pass
        if len(params) >= 3 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
            try:
                return await self._async_fetch(client, url, cancellation_token)
            except TypeError:
                return await self._async_fetch(client, url)
        return await self._async_fetch(client, url)

    @staticmethod
    def _response_payload(response: httpx.Response | None) -> tuple[int, dict[str, str], bytes, str] | None:
        if response is None:
            return None
        return response.status_code, dict(response.headers), response.content, str(response.url)

    def _fetch_one_sync(self, url: str) -> tuple[str, tuple[int, dict[str, str], bytes, str] | None, list[dict[str, object]], str]:
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,application/json,application/xml,text/csv",
        }
        with httpx.Client(headers=headers, timeout=self.settings.request_timeout_seconds, follow_redirects=False) as client:
            response, redirect_chain, fetch_error = self._safe_fetch(client, url)
            return url, self._response_payload(response), redirect_chain, fetch_error

    def _is_fetch_one_sync_overridden(self) -> bool:
        fn = getattr(self, "_fetch_one_sync", None)
        if fn is None:
            return False
        return getattr(fn, "__func__", fn) is not BaseCrawlerEngine._fetch_one_sync

    async def _async_batch(self, urls: list[str], delay_seconds: float) -> list[tuple[str, tuple[int, dict[str, str], bytes, str] | None, list[dict[str, object]], str]]:
        return [self._fetch_one_sync(u) for u in urls]

    def _is_async_batch_overridden(self) -> bool:
        fn = getattr(self, "_async_batch", None)
        if fn is None:
            return False
        return getattr(fn, "__func__", fn) is not BaseCrawlerEngine._async_batch

    def _render(self, browser_page: object | None, url: str) -> tuple[str, str, str]:
        if browser_page is None:
            return "", "", "Rendering is disabled or Chromium is unavailable."
        try:
            browser_page.goto(url, wait_until="domcontentloaded", timeout=self.settings.render_timeout_ms)
            browser_page.wait_for_timeout(150)
            html = browser_page.content()
            text = browser_page.locator("body").inner_text(timeout=5_000)
            return html[: self.settings.max_document_bytes], normalized_text(text), ""
        except Exception as exc:
            return "", "", f"Rendered inspection failed: {type(exc).__name__}: {exc}"

    def _build_page(
        self,
        request: CrawlRequest,
        url: str,
        response: httpx.Response | None,
        redirect_chain: list[dict[str, object]],
        fetch_error: str,
        browser_page: object | None = None,
        parent_url: str = "",
        depth: int = 0,
        engine_mode: str = "serial",
        fetch_duration_ms: float = 0.0,
        render_duration_ms: float = 0.0,
        rendered_html_override: str | None = None,
        rendered_text_override: str | None = None,
        render_error_override: str | None = None,
        escalated: bool = False,
        escalation_reason: str = "",
        requested_fetch_strategy: str = "static",
        actual_fetch_strategy: str = "static",
    ) -> tuple[PageRecord, list[LinkRecord]]:
        if not response:
            return self._error_page(
                url,
                redirect_chain,
                fetch_error,
                engine_mode=engine_mode,
                depth=depth,
                parent_url=parent_url,
                requested_fetch_strategy=requested_fetch_strategy,
                actual_fetch_strategy=actual_fetch_strategy,
                fetch_duration_ms=fetch_duration_ms,
            ), []
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
        source_html = response.text[: self.settings.max_document_bytes] if "html" in content_type else ""
        extracted_text, extraction_error = ("", "") if source_html else extract_document_text(content_type, response.content[: self.settings.max_document_bytes])
        body_truncated = len(response.content) > self.settings.max_document_bytes
        allow_private = getattr(self.settings, "allow_private_crawls", False)
        final_url = normalize_url(str(response.url), allow_private=allow_private)

        if rendered_html_override is not None or render_error_override is not None:
            render_html = rendered_html_override or ""
            rendered_text = rendered_text_override or ""
            render_error = render_error_override or ""
        elif browser_page is not None and source_html:
            render_html, rendered_text, render_error = self._render(browser_page, final_url)
        else:
            render_html, rendered_text, render_error = ("", "", "")

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

        status_code = response.status_code if response else None
        err_cat = "none"
        if fetch_error:
            err_cat = "fetch_error"
        elif status_code and status_code >= 400:
            err_cat = f"http_{status_code}"

        effective_fetch_strat = actual_fetch_strategy if actual_fetch_strategy != "static" else ("browser" if render_html else "static")
        effective_req_strat = requested_fetch_strategy or ("browser" if (self.settings.render_enabled and browser_page is not None) else "static")
        total_duration = fetch_duration_ms + render_duration_ms

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
            fetch_strategy=effective_fetch_strat,
            requested_fetch_strategy=effective_req_strat,
            actual_fetch_strategy=effective_fetch_strat,
            escalated=escalated,
            escalation_reason=escalation_reason,
            fetch_duration_ms=fetch_duration_ms,
            render_duration_ms=render_duration_ms,
            crawler_engine=engine_mode,
            response_bytes=len(response.content) if response else 0,
            duration_ms=total_duration if total_duration > 0 else 0.0,
            error_category=err_cat,
            headers=dict(response.headers) if response else {},
        )
        return PageRecord(**normalize_page_payload(page.to_dict())), page_links

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
    def _error_page(
        url: str,
        redirect_chain: list[dict[str, object]],
        error: str,
        engine_mode: str = "serial",
        depth: int = 0,
        parent_url: str = "",
        requested_fetch_strategy: str = "static",
        actual_fetch_strategy: str = "static",
        fetch_duration_ms: float = 0.0,
    ) -> PageRecord:
        return PageRecord(
            url=url, final_url=url, status_code=None, content_type="", title="", description="", headings={}, canonical="", meta_robots="",
            x_robots="", source_html="", rendered_html="", rendered_text="", images=[], structured_data=[], redirect_chain=redirect_chain,
            fetch_error=error, render_error="", discovered_at=BaseCrawlerEngine._now(), content_hash="",
            depth=depth, parent_url=parent_url,
            normalized_url=url,
            fetch_strategy=actual_fetch_strategy,
            requested_fetch_strategy=requested_fetch_strategy,
            actual_fetch_strategy=actual_fetch_strategy,
            escalated=False,
            escalation_reason="",
            fetch_duration_ms=fetch_duration_ms,
            render_duration_ms=0.0,
            crawler_engine=engine_mode,
            response_bytes=0,
            duration_ms=fetch_duration_ms,
            error_category="fetch_error" if error != "robots_disallowed" else "robots_disallowed",
            headers={},
            robots_allowed=False if error == "robots_disallowed" else True,
        )

    def _process_and_record_page(
        self,
        request: CrawlRequest,
        frontier: CrawlFrontier,
        page: PageRecord,
        page_links: list[LinkRecord],
        pages: list[PageRecord],
        links: list[LinkRecord],
        seen_canonicals: dict[str, str],
        seen_content_hashes: dict[str, str],
        pagination_counts: dict[str, int],
    ) -> None:
        if page.final_url and page.final_url != page.url:
            frontier.handle_redirect(page.url, page.final_url, page.depth, page.parent_url, enqueue_target=False)

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
            is_transient = page.status_code in {408, 425, 429, 500, 502, 503, 504}
            frontier.mark_failed(page.url, f"HTTP {page.status_code}", is_retryable=is_transient)
        elif page.fetch_error:
            err_lower = page.fetch_error.lower()
            is_transient = any(t in err_lower for t in ["timeout", "connecterror", "networkerror", "remoteprotocolerror", "timed out"])
            frontier.mark_failed(page.url, page.fetch_error, is_retryable=is_transient)
        else:
            frontier.mark_completed(page.url, status_code=page.status_code or 200)

        pages.append(page)
        links.extend(page_links)
        self._enqueue_discovered(request, page, page_links, frontier, pagination_counts)

    def _build_crawl_result(
        self,
        request: CrawlRequest,
        engine_name: str,
        fetch_strategy: str,
        pages: list[PageRecord],
        links: list[LinkRecord],
        frontier: CrawlFrontier,
        robots_status: str,
        start_time: float,
        started_at: str,
        cancellation_token: CancellationToken | None,
        fatal_error: str = "",
        termination_budget_reason: str = "",
        total_response_bytes: int = 0,
        retries_performed: int = 0,
    ) -> CrawlResult:
        effective_limit = request.budget.max_pages if (request.budget and request.budget.max_pages is not None) else request.max_urls
        pages_to_return = pages[: effective_limit]
        finished_at = self._now()
        duration_ms = (time.monotonic() - start_time) * 1000.0
        pages_succeeded = sum(1 for p in pages_to_return if p.status_code and p.status_code < 400 and p.robots_allowed and not p.fetch_error)
        pages_failed = len(pages_to_return) - pages_succeeded
        if fatal_error and not pages_failed:
            pages_failed = 1

        req_mode = getattr(request, "fetch_mode", None)
        if req_mode == "smart":
            requested_fetch_mode = "smart"
        elif req_mode == "browser" or self.settings.render_enabled:
            requested_fetch_mode = "browser"
        else:
            requested_fetch_mode = "static"

        fallback_occurred = bool(requested_fetch_mode in {"browser", "smart"} and fetch_strategy == "static")
        if fallback_occurred:
            if requested_fetch_mode == "browser":
                fallback_reason = "Browser rendering is unsupported in multi-worker static executor; fell back to static fetch."
            else:
                fallback_reason = "Smart escalation is unsupported in multi-worker static executor; fell back to static fetch."
        else:
            fallback_reason = ""
        cancelled = bool(cancellation_token and cancellation_token.is_cancelled())

        if fatal_error:
            status = CrawlStatus.FAILED.value
            termination_reason = f"fatal_engine_error: {fatal_error}"
        elif cancelled:
            status = CrawlStatus.CANCELLED.value
            termination_reason = f"cancelled: {cancellation_token.reason or 'Cooperative cancellation requested'}"
        elif termination_budget_reason:
            status = CrawlStatus.BUDGET_EXHAUSTED.value
            termination_reason = termination_budget_reason
        elif pages_failed > 0:
            status = CrawlStatus.PARTIAL.value if pages_succeeded > 0 else CrawlStatus.FAILED.value
            termination_reason = "max_urls_reached" if len(pages) >= request.max_urls else "queue_empty"
        else:
            status = CrawlStatus.SUCCESS.value
            termination_reason = "max_urls_reached" if len(pages) >= request.max_urls else "queue_empty"

        accounting = frontier.reconcile_accounting()
        errors = [p.fetch_error for p in pages_to_return if p.fetch_error]
        if fatal_error:
            errors.append(fatal_error)

        pages_escalated = sum(1 for p in pages_to_return if getattr(p, "escalated", False))
        calc_retries = max(accounting.get("retries", 0), retries_performed)
        calc_bytes = total_response_bytes if total_response_bytes > 0 else sum(getattr(p, "response_bytes", 0) for p in pages_to_return)

        return CrawlResult(
            crawl_id=getattr(request, "crawl_id", ""),
            requested_engine=getattr(request, "executor_mode", engine_name) or engine_name,
            actual_engine=engine_name,
            requested_fetch_mode=requested_fetch_mode,
            actual_fetch_mode=fetch_strategy,
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
            retry_count=calc_retries,
            total_response_bytes=calc_bytes,
            errors=errors,
            pages=pages_to_return,
            links=links,
            robots_status=robots_status,
            pages_escalated=pages_escalated,
        )


class CrawlEngine(BaseCrawlerEngine):
    """Unified CrawlEngine implementing CrawlerEngineProtocol and managing concrete engines."""

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

    def run(
        self,
        request: CrawlRequest,
        progress: callable,
        cancellation_token: CancellationToken | None = None,
    ) -> CrawlResult:
        if not request.acknowledgment:
            raise ValueError("Ownership or permission acknowledgement is required before a crawl can start.")
        mode = self._executor_mode(request)
        self.extraction_profile = load_profile(request.extraction_profile_path or self.settings.extraction_profile_path)
        if mode not in {"serial", "thread", "async", "process"}:
            raise ValueError(f"Crawl executor mode must be serial, thread, async, or process; got {mode}.")

        if mode == "serial":
            return self._run_serial(request, progress, cancellation_token)
        elif mode == "thread":
            return self._run_threaded(request, progress, cancellation_token)
        elif mode == "async":
            return self._run_coroutine(request, progress, cancellation_token)
        elif mode == "process":
            return self._run_multiprocess(request, progress, cancellation_token)

    def _run_serial(
        self,
        request: CrawlRequest,
        progress: callable,
        cancellation_token: CancellationToken | None = None,
    ) -> CrawlResult:
        start_time = time.monotonic()
        started_at = self._now()
        budget = request.budget
        effective_max_pages = budget.max_pages if (budget and budget.max_pages is not None) else request.max_urls
        effective_max_depth = budget.max_depth if (budget and budget.max_depth is not None) else getattr(request, "max_depth", 10)
        effective_max_bytes = budget.max_bytes if (budget and budget.max_bytes is not None) else None
        effective_max_duration = budget.max_duration_seconds if (budget and budget.max_duration_seconds is not None) else None
        effective_max_retries = budget.max_retries if (budget and budget.max_retries is not None) else self.settings.max_request_retries
        effective_max_redirects = budget.redirect_limit if (budget and budget.redirect_limit is not None) else self.settings.max_redirects
        deadline = (start_time + effective_max_duration) if effective_max_duration is not None else None

        total_response_bytes = 0
        retries_performed = 0
        termination_budget_reason = ""

        frontier = CrawlFrontier(
            start_url=request.start_url,
            max_urls=effective_max_pages,
            max_depth=effective_max_depth,
            mode=request.mode,
            url_list=request.url_list,
            allow_private=getattr(self.settings, "allow_private_crawls", False),
            max_retries=effective_max_retries,
            retry_backoff_seconds=self.settings.retry_backoff_seconds,
        )
        pages: list[PageRecord] = []
        links: list[LinkRecord] = []
        seen_content_hashes: dict[str, str] = {}
        seen_canonicals: dict[str, str] = {}
        pagination_counts: dict[str, int] = {}
        throttler = DomainPolitenessThrottler(request.delay_seconds, per_host_concurrency=1)

        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,application/json,application/xml,text/csv",
        }

        # Determine requested fetch strategy
        req_mode = getattr(request, "fetch_mode", None)
        if req_mode == "smart":
            requested_fetch_mode = "smart"
        elif req_mode == "browser" or self.settings.render_enabled:
            requested_fetch_mode = "browser"
        else:
            requested_fetch_mode = "static"

        browser_session: PlaywrightBrowserSession | None = None
        if requested_fetch_mode in {"browser", "smart"}:
            browser_session = PlaywrightBrowserSession(
                user_agent=self.settings.user_agent,
                render_timeout_ms=self.settings.render_timeout_ms,
                headless=True,
            )
            if requested_fetch_mode == "browser":
                try:
                    browser_session.start()
                except Exception:
                    pass

        with httpx.Client(headers=headers, timeout=self.settings.request_timeout_seconds, follow_redirects=False) as client:
            robots, robots_status = self._safe_robots(client, request.start_url, respect_robots=request.respect_robots_txt, throttler=throttler)

            try:
                while not frontier.is_complete() and len(pages) < effective_max_pages:
                    if cancellation_token and cancellation_token.is_cancelled():
                        break
                    if deadline and time.monotonic() >= deadline:
                        elapsed = time.monotonic() - start_time
                        termination_budget_reason = f"budget_exhausted: max_crawl_duration exceeded ({elapsed:.2f}s >= {effective_max_duration}s)"
                        break
                    if effective_max_bytes and total_response_bytes >= effective_max_bytes:
                        termination_budget_reason = f"budget_exhausted: max_bytes reached ({total_response_bytes} >= {effective_max_bytes})"
                        break
                    entry = frontier.get_next()
                    if entry is None:
                        if frontier.is_complete():
                            break
                        time.sleep(0.01)
                        continue

                    url = entry.url
                    depth = entry.depth
                    parent_url = entry.parent_url

                    if request.respect_robots_txt:
                        robots, robots_status = self._safe_robots(client, url, respect_robots=True, throttler=throttler)
                        if not robots.can_fetch(self.settings.user_agent, url):
                            frontier.mark_skipped(url, reason="robots_disallowed")
                            pages.append(self._error_page(
                                url, [], "robots_disallowed", "serial",
                                depth=depth, parent_url=parent_url,
                                requested_fetch_strategy=requested_fetch_mode,
                                actual_fetch_strategy="static",
                            ))
                            progress(len(pages), frontier.queue_size, robots_status)
                            continue

                    throttler.throttle(url)

                    t_start = time.monotonic()
                    response, redirect_chain, fetch_error = self._safe_fetch(
                        client, url, cancellation_token,
                        max_retries=effective_max_retries,
                        max_redirects=effective_max_redirects,
                    )
                    fetch_duration_ms = (time.monotonic() - t_start) * 1000.0
                    throttler.record_completion(url)
                    if redirect_chain:
                        retries_performed += sum(int(hop.get("attempt", 1)) - 1 for hop in redirect_chain if isinstance(hop, dict))

                    escalated = False
                    escalation_reason = ""
                    render_html = ""
                    render_text = ""
                    render_error = ""
                    render_duration_ms = 0.0
                    actual_page_fetch_strategy = "static"

                    if response is not None:
                        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
                        source_html = response.text[: self.settings.max_document_bytes] if "html" in content_type else ""
                        if source_html:
                            soup = BeautifulSoup(source_html, "html.parser")
                            body_text = soup.body.get_text(" ", strip=True) if soup.body else ""
                        else:
                            body_text, _ = extract_document_text(content_type, response.content[: self.settings.max_document_bytes])

                        should_render, reason = should_escalate_to_browser(
                            status_code=response.status_code,
                            headers=dict(response.headers),
                            source_html=source_html,
                            extracted_text=body_text,
                            configured_fetch_mode=requested_fetch_mode,
                        )

                        if should_render and browser_session is not None:
                            if requested_fetch_mode == "smart":
                                escalated = True
                                escalation_reason = reason
                            elif requested_fetch_mode == "browser":
                                escalated = False
                                escalation_reason = reason

                            final_target_url = str(response.url)
                            try:
                                render_html, render_text, render_error, render_duration_ms = browser_session.render_url(
                                    final_target_url,
                                    max_document_bytes=self.settings.max_document_bytes,
                                    cancellation_token=cancellation_token,
                                )
                            except Exception as b_exc:
                                render_html, render_text = "", ""
                                render_error = f"{type(b_exc).__name__}: {b_exc}"
                                render_duration_ms = 0.0
                            actual_page_fetch_strategy = "browser"

                    page, page_links = self._build_page(
                        request,
                        url,
                        response,
                        redirect_chain,
                        fetch_error,
                        parent_url=parent_url,
                        depth=depth,
                        engine_mode="serial",
                        fetch_duration_ms=fetch_duration_ms,
                        render_duration_ms=render_duration_ms,
                        rendered_html_override=render_html if (render_html or render_error) else None,
                        rendered_text_override=render_text,
                        render_error_override=render_error,
                        escalated=escalated,
                        escalation_reason=escalation_reason,
                        requested_fetch_strategy=requested_fetch_mode,
                        actual_fetch_strategy=actual_page_fetch_strategy,
                    )

                    self._process_and_record_page(
                        request, frontier, page, page_links, pages, links,
                        seen_canonicals, seen_content_hashes, pagination_counts,
                    )
                    progress(len(pages), frontier.queue_size, robots_status)

                    total_response_bytes += page.response_bytes
                    if effective_max_bytes and total_response_bytes >= effective_max_bytes:
                        termination_budget_reason = f"budget_exhausted: max_bytes reached ({total_response_bytes} >= {effective_max_bytes})"
                        break
                    if deadline and time.monotonic() >= deadline:
                        elapsed = time.monotonic() - start_time
                        termination_budget_reason = f"budget_exhausted: max_crawl_duration exceeded ({elapsed:.2f}s >= {effective_max_duration}s)"
                        break

                if not termination_budget_reason and budget and budget.max_pages is not None and len(pages) >= effective_max_pages:
                    termination_budget_reason = f"budget_exhausted: max_pages reached ({len(pages)} >= {effective_max_pages})"
            finally:
                if browser_session:
                    browser_session.close()

        if requested_fetch_mode == "smart":
            actual_fetch_mode = "smart"
        elif requested_fetch_mode == "browser":
            actual_fetch_mode = "browser" if ((browser_session and browser_session.is_active) or any(p.actual_fetch_strategy == "browser" for p in pages) or self.settings.render_enabled) else "static"
        else:
            actual_fetch_mode = "static"

        return self._build_crawl_result(
            request, "serial", actual_fetch_mode, pages, links, frontier,
            robots_status, start_time, started_at, cancellation_token,
            termination_budget_reason=termination_budget_reason,
            total_response_bytes=total_response_bytes,
            retries_performed=retries_performed,
        )

    def _run_threaded(
        self,
        request: CrawlRequest,
        progress: callable,
        cancellation_token: CancellationToken | None = None,
    ) -> CrawlResult:
        workers = max(1, self.settings.thread_workers)
        start_time = time.monotonic()
        started_at = self._now()

        budget = request.budget
        effective_max_pages = budget.max_pages if (budget and budget.max_pages is not None) else request.max_urls
        effective_max_depth = budget.max_depth if (budget and budget.max_depth is not None) else getattr(request, "max_depth", 10)
        effective_max_bytes = budget.max_bytes if (budget and budget.max_bytes is not None) else 0
        effective_max_duration = budget.max_duration_seconds if (budget and budget.max_duration_seconds is not None) else 0.0
        effective_max_retries = budget.max_retries if (budget and budget.max_retries is not None) else self.settings.max_request_retries
        effective_max_redirects = budget.redirect_limit if (budget and budget.redirect_limit is not None) else self.settings.max_redirects

        deadline = (start_time + effective_max_duration) if effective_max_duration > 0 else 0.0
        termination_budget_reason = ""
        total_response_bytes = 0
        retries_performed = 0

        frontier = CrawlFrontier(
            start_url=request.start_url,
            max_urls=effective_max_pages,
            max_depth=effective_max_depth,
            mode=request.mode,
            url_list=request.url_list,
            allow_private=getattr(self.settings, "allow_private_crawls", False),
            max_retries=effective_max_retries,
            retry_backoff_seconds=self.settings.retry_backoff_seconds,
        )
        pages: list[PageRecord] = []
        links: list[LinkRecord] = []
        seen_content_hashes: dict[str, str] = {}
        seen_canonicals: dict[str, str] = {}
        pagination_counts: dict[str, int] = {}
        per_host_limit = request.per_host_concurrency if request.per_host_concurrency is not None else workers
        throttler = DomainPolitenessThrottler(request.delay_seconds, per_host_concurrency=per_host_limit)

        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,application/json,application/xml,text/csv",
        }

        transport = httpx.HTTPTransport(
            retries=effective_max_retries,
            limits=httpx.Limits(max_connections=workers * 2, max_keepalive_connections=workers, keepalive_expiry=30.0),
        )

        req_mode = getattr(request, "fetch_mode", None)
        if req_mode == "smart":
            requested_fetch_mode = "smart"
        elif req_mode == "browser" or self.settings.render_enabled:
            requested_fetch_mode = "browser"
        else:
            requested_fetch_mode = "static"

        with httpx.Client(transport=transport, headers=headers, timeout=self.settings.request_timeout_seconds, follow_redirects=False) as client:
            robots, robots_status = self._safe_robots(client, request.start_url, respect_robots=request.respect_robots_txt, throttler=throttler)

            def _thread_worker_fetch(target_url: str) -> tuple[str, httpx.Response | None, list[dict[str, object]], str, float, float]:
                with throttler.acquire(target_url):
                    t_start = time.monotonic()
                    if self._is_fetch_one_sync_overridden():
                        url, payload, chain, err = self._fetch_one_sync(target_url)
                        t_end = time.monotonic()
                        resp = None
                        if payload is not None:
                            status_code, resp_headers, content, final_url = payload
                            resp = httpx.Response(status_code, headers=resp_headers, content=content, request=httpx.Request("GET", final_url))
                        return target_url, resp, chain, err, t_start, t_end
                    resp, chain, err = self._safe_fetch(
                        client, target_url, cancellation_token,
                        max_retries=effective_max_retries,
                        max_redirects=effective_max_redirects,
                    )
                    t_end = time.monotonic()
                    return target_url, resp, chain, err, t_start, t_end

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                in_flight: dict[concurrent.futures.Future, FrontierEntry] = {}

                while not frontier.is_complete() and len(pages) < effective_max_pages:
                    if cancellation_token and cancellation_token.is_cancelled():
                        break
                    if deadline and time.monotonic() >= deadline:
                        elapsed = time.monotonic() - start_time
                        termination_budget_reason = f"budget_exhausted: max_crawl_duration exceeded ({elapsed:.2f}s >= {effective_max_duration}s)"
                        break
                    if effective_max_bytes > 0 and total_response_bytes >= effective_max_bytes:
                        termination_budget_reason = f"budget_exhausted: max_bytes reached ({total_response_bytes} >= {effective_max_bytes})"
                        break

                    while len(in_flight) < workers and not frontier.is_complete():
                        entry = frontier.get_next()
                        if entry is None:
                            break
                        if request.respect_robots_txt:
                            robots, robots_status = self._safe_robots(client, entry.url, respect_robots=True, throttler=throttler)
                            if not robots.can_fetch(self.settings.user_agent, entry.url):
                                frontier.mark_skipped(entry.url, reason="robots_disallowed")
                                pages.append(self._error_page(
                                    entry.url, [], "robots_disallowed", "thread",
                                    depth=entry.depth, parent_url=entry.parent_url,
                                    requested_fetch_strategy=requested_fetch_mode,
                                    actual_fetch_strategy="static",
                                ))
                                progress(len(pages), frontier.queue_size, robots_status)
                                continue

                        fut = executor.submit(_thread_worker_fetch, entry.url)
                        in_flight[fut] = entry

                    if not in_flight:
                        if frontier.is_complete():
                            break
                        time.sleep(0.01)
                        continue

                    done, _ = concurrent.futures.wait(
                        in_flight.keys(),
                        timeout=0.05,
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )

                    for fut in done:
                        orig_entry = in_flight.pop(fut)
                        try:
                            url, resp, chain, err, t_start, t_end = fut.result()
                        except Exception as exc:
                            url, resp, chain, err = orig_entry.url, None, [], f"ThreadWorkerException: {exc}"
                            t_start, t_end = time.monotonic(), time.monotonic()

                        fetch_dur = (t_end - t_start) * 1000.0
                        page, page_links = self._build_page(
                            request, orig_entry.url, resp, chain, err, None,
                            orig_entry.parent_url, orig_entry.depth, "thread",
                            fetch_duration_ms=fetch_dur,
                            requested_fetch_strategy=requested_fetch_mode,
                            actual_fetch_strategy="static",
                        )
                        page.duration_ms = fetch_dur
                        page.headers["x-fetch-start"] = str(t_start)
                        page.headers["x-fetch-end"] = str(t_end)

                        self._process_and_record_page(
                            request, frontier, page, page_links, pages, links,
                            seen_canonicals, seen_content_hashes, pagination_counts,
                        )
                        progress(len(pages), frontier.queue_size, robots_status)

                        total_response_bytes += page.response_bytes
                        if chain:
                            retries_performed += sum(int(hop.get("attempt", 1)) - 1 for hop in chain if isinstance(hop, dict))
                        if effective_max_bytes > 0 and total_response_bytes >= effective_max_bytes:
                            termination_budget_reason = f"budget_exhausted: max_bytes reached ({total_response_bytes} >= {effective_max_bytes})"
                            break
                        if deadline and time.monotonic() >= deadline:
                            elapsed = time.monotonic() - start_time
                            termination_budget_reason = f"budget_exhausted: max_crawl_duration exceeded ({elapsed:.2f}s >= {effective_max_duration}s)"
                            break
                        if len(pages) >= effective_max_pages:
                            if budget and budget.max_pages is not None:
                                termination_budget_reason = f"budget_exhausted: max_pages reached ({len(pages)} >= {effective_max_pages})"
                            break

                    if termination_budget_reason:
                        break

                if not termination_budget_reason and budget and budget.max_pages is not None and len(pages) >= effective_max_pages:
                    termination_budget_reason = f"budget_exhausted: max_pages reached ({len(pages)} >= {effective_max_pages})"

                if in_flight:
                    for f in in_flight:
                        f.cancel()

        return self._build_crawl_result(
            request, "thread", "static", pages, links, frontier,
            robots_status, start_time, started_at, cancellation_token,
            termination_budget_reason=termination_budget_reason,
            total_response_bytes=total_response_bytes,
            retries_performed=retries_performed,
        )

    def _run_coroutine(
        self,
        request: CrawlRequest,
        progress: callable,
        cancellation_token: CancellationToken | None = None,
    ) -> CrawlResult:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    self._run_async(request, progress, cancellation_token),
                ).result()
        else:
            return asyncio.run(self._run_async(request, progress, cancellation_token))

    async def _run_async(
        self,
        request: CrawlRequest,
        progress: callable,
        cancellation_token: CancellationToken | None,
    ) -> CrawlResult:
        concurrency = max(1, self.settings.async_concurrency)
        start_time = time.monotonic()
        started_at = self._now()
        budget = request.budget
        effective_max_pages = budget.max_pages if (budget and budget.max_pages is not None) else request.max_urls
        effective_max_depth = budget.max_depth if (budget and budget.max_depth is not None) else getattr(request, "max_depth", 10)
        effective_max_bytes = budget.max_bytes if (budget and budget.max_bytes is not None) else None
        effective_max_duration = budget.max_duration_seconds if (budget and budget.max_duration_seconds is not None) else None
        effective_max_retries = budget.max_retries if (budget and budget.max_retries is not None) else self.settings.max_request_retries
        effective_max_redirects = budget.redirect_limit if (budget and budget.redirect_limit is not None) else self.settings.max_redirects
        deadline = (start_time + effective_max_duration) if effective_max_duration is not None else None

        total_response_bytes = 0
        retries_performed = 0
        termination_budget_reason = ""

        frontier = CrawlFrontier(
            start_url=request.start_url,
            max_urls=effective_max_pages,
            max_depth=effective_max_depth,
            mode=request.mode,
            url_list=request.url_list,
            allow_private=getattr(self.settings, "allow_private_crawls", False),
            max_retries=effective_max_retries,
            retry_backoff_seconds=self.settings.retry_backoff_seconds,
        )
        pages: list[PageRecord] = []
        links: list[LinkRecord] = []
        seen_content_hashes: dict[str, str] = {}
        seen_canonicals: dict[str, str] = {}
        pagination_counts: dict[str, int] = {}
        per_host_limit = request.per_host_concurrency if request.per_host_concurrency is not None else concurrency
        throttler = AsyncDomainPolitenessThrottler(request.delay_seconds, per_host_concurrency=per_host_limit)

        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,application/json,application/xml,text/csv",
        }

        req_mode = getattr(request, "fetch_mode", None)
        if req_mode == "smart":
            requested_fetch_mode = "smart"
        elif req_mode == "browser" or self.settings.render_enabled:
            requested_fetch_mode = "browser"
        else:
            requested_fetch_mode = "static"

        if self._is_async_batch_overridden():
            with httpx.Client(headers=headers, timeout=self.settings.request_timeout_seconds, follow_redirects=False) as sync_client:
                robots, robots_status = self._safe_robots(sync_client, request.start_url, respect_robots=request.respect_robots_txt)

            while not frontier.is_complete() and len(pages) < effective_max_pages:
                if cancellation_token and cancellation_token.is_cancelled():
                    break
                if deadline and time.monotonic() >= deadline:
                    elapsed = time.monotonic() - start_time
                    termination_budget_reason = f"budget_exhausted: max_crawl_duration exceeded ({elapsed:.2f}s >= {effective_max_duration}s)"
                    break
                if effective_max_bytes and total_response_bytes >= effective_max_bytes:
                    termination_budget_reason = f"budget_exhausted: max_bytes reached ({total_response_bytes} >= {effective_max_bytes})"
                    break

                batch_entries = []
                while len(batch_entries) < concurrency and not frontier.is_complete():
                    e = frontier.get_next()
                    if e is None:
                        break
                    if request.respect_robots_txt:
                        robots, robots_status = self._safe_robots(sync_client, e.url, respect_robots=True)
                        if not robots.can_fetch(self.settings.user_agent, e.url):
                            frontier.mark_skipped(e.url, reason="robots_disallowed")
                            pages.append(self._error_page(
                                e.url, [], "robots_disallowed", "async",
                                depth=e.depth, parent_url=e.parent_url,
                                requested_fetch_strategy=requested_fetch_mode,
                                actual_fetch_strategy="static",
                            ))
                            progress(len(pages), frontier.queue_size, robots_status)
                            continue
                    batch_entries.append(e)

                if not batch_entries:
                    break

                results = await self._async_batch([e.url for e in batch_entries], request.delay_seconds)
                for e, res in zip(batch_entries, results):
                    url, payload, chain, err = res
                    resp = None
                    if payload is not None:
                        status_code, resp_headers, content, final_url = payload
                        resp = httpx.Response(status_code, headers=resp_headers, content=content, request=httpx.Request("GET", final_url))
                    page, page_links = self._build_page(
                        request, e.url, resp, chain, err, None,
                        e.parent_url, e.depth, "async",
                        requested_fetch_strategy=requested_fetch_mode,
                        actual_fetch_strategy="static",
                    )
                    self._process_and_record_page(
                        request, frontier, page, page_links, pages, links,
                        seen_canonicals, seen_content_hashes, pagination_counts,
                    )
                    progress(len(pages), frontier.queue_size, robots_status)
                    total_response_bytes += page.response_bytes
                    if chain:
                        retries_performed += sum(int(hop.get("attempt", 1)) - 1 for hop in chain if isinstance(hop, dict))
                    if effective_max_bytes and total_response_bytes >= effective_max_bytes:
                        termination_budget_reason = f"budget_exhausted: max_bytes reached ({total_response_bytes} >= {effective_max_bytes})"
                        break
                    if deadline and time.monotonic() >= deadline:
                        elapsed = time.monotonic() - start_time
                        termination_budget_reason = f"budget_exhausted: max_crawl_duration exceeded ({elapsed:.2f}s >= {effective_max_duration}s)"
                        break

                if termination_budget_reason:
                    break

            if not termination_budget_reason and budget and budget.max_pages is not None and len(pages) >= effective_max_pages:
                termination_budget_reason = f"budget_exhausted: max_pages reached ({len(pages)} >= {effective_max_pages})"

            return self._build_crawl_result(
                request, "async", "static", pages, links, frontier,
                robots_status, start_time, started_at, cancellation_token,
                termination_budget_reason=termination_budget_reason,
                total_response_bytes=total_response_bytes,
                retries_performed=retries_performed,
            )

        transport = httpx.AsyncHTTPTransport(
            retries=effective_max_retries,
            limits=httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency, keepalive_expiry=30.0),
        )

        async with httpx.AsyncClient(transport=transport, headers=headers, timeout=self.settings.request_timeout_seconds, follow_redirects=False) as client:
            robots, robots_status = await self._safe_async_robots(client, request.start_url, respect_robots=request.respect_robots_txt, throttler=throttler)

            async def _async_worker_fetch(target_url: str) -> tuple[str, httpx.Response | None, list[dict[str, object]], str, float, float]:
                async with throttler.acquire(target_url):
                    t_start = time.monotonic()
                    resp, chain, err = await self._safe_async_fetch(
                        client, target_url, cancellation_token,
                        max_retries=effective_max_retries,
                        max_redirects=effective_max_redirects,
                    )
                    t_end = time.monotonic()
                    return target_url, resp, chain, err, t_start, t_end

            active_tasks: dict[asyncio.Task, FrontierEntry] = {}

            while not frontier.is_complete() and len(pages) < effective_max_pages:
                if cancellation_token and cancellation_token.is_cancelled():
                    break
                if deadline and time.monotonic() >= deadline:
                    elapsed = time.monotonic() - start_time
                    termination_budget_reason = f"budget_exhausted: max_crawl_duration exceeded ({elapsed:.2f}s >= {effective_max_duration}s)"
                    break
                if effective_max_bytes and total_response_bytes >= effective_max_bytes:
                    termination_budget_reason = f"budget_exhausted: max_bytes reached ({total_response_bytes} >= {effective_max_bytes})"
                    break

                while len(active_tasks) < concurrency and not frontier.is_complete():
                    entry = frontier.get_next()
                    if entry is None:
                        break
                    if request.respect_robots_txt:
                        robots, robots_status = await self._safe_async_robots(client, entry.url, respect_robots=True, throttler=throttler)
                        if not robots.can_fetch(self.settings.user_agent, entry.url):
                            frontier.mark_skipped(entry.url, reason="robots_disallowed")
                            pages.append(self._error_page(
                                entry.url, [], "robots_disallowed", "async",
                                depth=entry.depth, parent_url=entry.parent_url,
                                requested_fetch_strategy=requested_fetch_mode,
                                actual_fetch_strategy="static",
                            ))
                            progress(len(pages), frontier.queue_size, robots_status)
                            continue

                    task = asyncio.create_task(_async_worker_fetch(entry.url))
                    active_tasks[task] = entry

                if not active_tasks:
                    if frontier.is_complete():
                        break
                    await asyncio.sleep(0.01)
                    continue

                done, _ = await asyncio.wait(
                    active_tasks.keys(),
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for finished_task in done:
                    orig_entry = active_tasks.pop(finished_task)
                    try:
                        url, resp, chain, err, t_start, t_end = finished_task.result()
                    except Exception as exc:
                        url, resp, chain, err = orig_entry.url, None, [], f"CoroutineException: {exc}"
                        t_start, t_end = time.monotonic(), time.monotonic()

                    fetch_dur = (t_end - t_start) * 1000.0
                    page, page_links = await asyncio.to_thread(
                        self._build_page,
                        request, orig_entry.url, resp, chain, err, None,
                        orig_entry.parent_url, orig_entry.depth, "async",
                        fetch_duration_ms=fetch_dur,
                        requested_fetch_strategy=requested_fetch_mode,
                        actual_fetch_strategy="static",
                    )
                    page.duration_ms = fetch_dur
                    page.headers["x-fetch-start"] = str(t_start)
                    page.headers["x-fetch-end"] = str(t_end)

                    self._process_and_record_page(
                        request, frontier, page, page_links, pages, links,
                        seen_canonicals, seen_content_hashes, pagination_counts,
                    )
                    progress(len(pages), frontier.queue_size, robots_status)

                    total_response_bytes += page.response_bytes
                    if chain:
                        retries_performed += sum(int(hop.get("attempt", 1)) - 1 for hop in chain if isinstance(hop, dict))
                    if effective_max_bytes and total_response_bytes >= effective_max_bytes:
                        termination_budget_reason = f"budget_exhausted: max_bytes reached ({total_response_bytes} >= {effective_max_bytes})"
                        break
                    if deadline and time.monotonic() >= deadline:
                        elapsed = time.monotonic() - start_time
                        termination_budget_reason = f"budget_exhausted: max_crawl_duration exceeded ({elapsed:.2f}s >= {effective_max_duration}s)"
                        break
                    if len(pages) >= effective_max_pages:
                        if budget and budget.max_pages is not None:
                            termination_budget_reason = f"budget_exhausted: max_pages reached ({len(pages)} >= {effective_max_pages})"
                        break

                if termination_budget_reason:
                    break

            if not termination_budget_reason and budget and budget.max_pages is not None and len(pages) >= effective_max_pages:
                termination_budget_reason = f"budget_exhausted: max_pages reached ({len(pages)} >= {effective_max_pages})"

            if active_tasks:
                for t in active_tasks:
                    t.cancel()
                await asyncio.gather(*active_tasks.keys(), return_exceptions=True)

        return self._build_crawl_result(
            request, "async", "static", pages, links, frontier,
            robots_status, start_time, started_at, cancellation_token,
            termination_budget_reason=termination_budget_reason,
            total_response_bytes=total_response_bytes,
            retries_performed=retries_performed,
        )

    def _run_multiprocess(
        self,
        request: CrawlRequest,
        progress: callable,
        cancellation_token: CancellationToken | None = None,
    ) -> CrawlResult:
        workers = max(1, self.settings.process_workers)
        start_time = time.monotonic()
        started_at = self._now()
        parent_pid = os.getpid()

        budget = request.budget
        effective_max_pages = budget.max_pages if (budget and budget.max_pages is not None) else request.max_urls
        effective_max_depth = budget.max_depth if (budget and budget.max_depth is not None) else getattr(request, "max_depth", 10)
        effective_max_bytes = budget.max_bytes if (budget and budget.max_bytes is not None) else 0
        effective_max_duration = budget.max_duration_seconds if (budget and budget.max_duration_seconds is not None) else 0.0
        effective_max_retries = budget.max_retries if (budget and budget.max_retries is not None) else self.settings.max_request_retries
        effective_max_redirects = budget.redirect_limit if (budget and budget.redirect_limit is not None) else self.settings.max_redirects

        deadline = (start_time + effective_max_duration) if effective_max_duration > 0 else 0.0
        termination_budget_reason = ""
        total_response_bytes = 0
        retries_performed = 0

        frontier = CrawlFrontier(
            start_url=request.start_url,
            max_urls=effective_max_pages,
            max_depth=effective_max_depth,
            mode=request.mode,
            url_list=request.url_list,
            allow_private=getattr(self.settings, "allow_private_crawls", False),
            max_retries=effective_max_retries,
            retry_backoff_seconds=self.settings.retry_backoff_seconds,
        )
        pages: list[PageRecord] = []
        links: list[LinkRecord] = []
        seen_content_hashes: dict[str, str] = {}
        seen_canonicals: dict[str, str] = {}
        pagination_counts: dict[str, int] = {}
        fatal_error = ""

        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,application/json,application/xml,text/csv",
        }

        req_mode = getattr(request, "fetch_mode", None)
        if req_mode == "smart":
            requested_fetch_mode = "smart"
        elif req_mode == "browser" or self.settings.render_enabled:
            requested_fetch_mode = "browser"
        else:
            requested_fetch_mode = "static"

        per_host_limit = request.per_host_concurrency if request.per_host_concurrency is not None else workers
        throttler = DomainPolitenessThrottler(request.delay_seconds, per_host_concurrency=per_host_limit)

        if self._is_fetch_one_sync_overridden():
            with httpx.Client(headers=headers, timeout=self.settings.request_timeout_seconds, follow_redirects=False) as client:
                robots, robots_status = self._safe_robots(client, request.start_url, respect_robots=request.respect_robots_txt, throttler=throttler)
                while not frontier.is_complete() and len(pages) < effective_max_pages:
                    if cancellation_token and cancellation_token.is_cancelled():
                        break
                    if deadline and time.monotonic() >= deadline:
                        elapsed = time.monotonic() - start_time
                        termination_budget_reason = f"budget_exhausted: max_crawl_duration exceeded ({elapsed:.2f}s >= {effective_max_duration}s)"
                        break
                    if effective_max_bytes and total_response_bytes >= effective_max_bytes:
                        termination_budget_reason = f"budget_exhausted: max_bytes reached ({total_response_bytes} >= {effective_max_bytes})"
                        break
                    entry = frontier.get_next()
                    if entry is None:
                        break
                    if request.respect_robots_txt:
                        robots, robots_status = self._safe_robots(client, entry.url, respect_robots=True, throttler=throttler)
                        if not robots.can_fetch(self.settings.user_agent, entry.url):
                            frontier.mark_skipped(entry.url, reason="robots_disallowed")
                            pages.append(self._error_page(
                                entry.url, [], "robots_disallowed", "process",
                                depth=entry.depth, parent_url=entry.parent_url,
                                requested_fetch_strategy=requested_fetch_mode,
                                actual_fetch_strategy="static",
                            ))
                            progress(len(pages), frontier.queue_size, robots_status)
                            continue
                    throttler.throttle(entry.url)
                    t_start = time.monotonic()
                    url, payload, chain, err = self._fetch_one_sync(entry.url)
                    t_end = time.monotonic()
                    resp = None
                    if payload is not None:
                        status_code, resp_headers, content, final_url = payload
                        resp = httpx.Response(status_code, headers=resp_headers, content=content, request=httpx.Request("GET", final_url))
                    fetch_dur = (t_end - t_start) * 1000.0
                    page, page_links = self._build_page(
                        request, entry.url, resp, chain, err,
                        parent_url=entry.parent_url, depth=entry.depth, engine_mode="process",
                        fetch_duration_ms=fetch_dur,
                        requested_fetch_strategy=requested_fetch_mode,
                        actual_fetch_strategy="static",
                    )
                    page.duration_ms = fetch_dur
                    self._process_and_record_page(
                        request, frontier, page, page_links, pages, links,
                        seen_canonicals, seen_content_hashes, pagination_counts,
                    )
                    progress(len(pages), frontier.queue_size, robots_status)
                    total_response_bytes += page.response_bytes
                    if chain:
                        retries_performed += sum(int(hop.get("attempt", 1)) - 1 for hop in chain if isinstance(hop, dict))
                    if effective_max_bytes and total_response_bytes >= effective_max_bytes:
                        termination_budget_reason = f"budget_exhausted: max_bytes reached ({total_response_bytes} >= {effective_max_bytes})"
                        break
                    if deadline and time.monotonic() >= deadline:
                        elapsed = time.monotonic() - start_time
                        termination_budget_reason = f"budget_exhausted: max_crawl_duration exceeded ({elapsed:.2f}s >= {effective_max_duration}s)"
                        break

            if not termination_budget_reason and budget and budget.max_pages is not None and len(pages) >= effective_max_pages:
                termination_budget_reason = f"budget_exhausted: max_pages reached ({len(pages)} >= {effective_max_pages})"

            return self._build_crawl_result(
                request, "process", "static", pages, links, frontier,
                robots_status, start_time, started_at, cancellation_token,
                termination_budget_reason=termination_budget_reason,
                total_response_bytes=total_response_bytes,
                retries_performed=retries_performed,
            )

        mp_context = multiprocessing.get_context("spawn")
        try:
            with httpx.Client(headers=headers, timeout=self.settings.request_timeout_seconds, follow_redirects=False) as robots_client:
                robots, robots_status = self._safe_robots(robots_client, request.start_url, respect_robots=request.respect_robots_txt, throttler=throttler)
                with concurrent.futures.ProcessPoolExecutor(max_workers=workers, mp_context=mp_context) as executor:
                    in_flight: dict[concurrent.futures.Future, FrontierEntry] = {}
                    in_flight_by_domain: dict[str, int] = {}
                    per_host_limit = request.per_host_concurrency if request.per_host_concurrency is not None else workers
                    deferred_entries: list[FrontierEntry] = []

                    while not frontier.is_complete() and len(pages) < effective_max_pages:
                        if cancellation_token and cancellation_token.is_cancelled():
                            break
                        if deadline and time.monotonic() >= deadline:
                            elapsed = time.monotonic() - start_time
                            termination_budget_reason = f"budget_exhausted: max_crawl_duration exceeded ({elapsed:.2f}s >= {effective_max_duration}s)"
                            break
                        if effective_max_bytes and total_response_bytes >= effective_max_bytes:
                            termination_budget_reason = f"budget_exhausted: max_bytes reached ({total_response_bytes} >= {effective_max_bytes})"
                            break

                        while len(in_flight) < workers:
                            entry: FrontierEntry | None = None
                            for i, d_entry in enumerate(deferred_entries):
                                d_domain = (urlsplit(d_entry.url).netloc or "").lower()
                                if in_flight_by_domain.get(d_domain, 0) < per_host_limit:
                                    entry = deferred_entries.pop(i)
                                    break

                            if entry is None and not frontier.is_complete():
                                cand = frontier.get_next()
                                if cand is not None:
                                    c_domain = (urlsplit(cand.url).netloc or "").lower()
                                    if in_flight_by_domain.get(c_domain, 0) >= per_host_limit:
                                        deferred_entries.append(cand)
                                        continue
                                    else:
                                        entry = cand

                            if entry is None:
                                break

                            if request.respect_robots_txt:
                                robots, robots_status = self._safe_robots(robots_client, entry.url, respect_robots=True, throttler=throttler)
                                if not robots.can_fetch(self.settings.user_agent, entry.url):
                                    frontier.mark_skipped(entry.url, reason="robots_disallowed")
                                    pages.append(self._error_page(
                                        entry.url, [], "robots_disallowed", "process",
                                        depth=entry.depth, parent_url=entry.parent_url,
                                        requested_fetch_strategy=requested_fetch_mode,
                                        actual_fetch_strategy="static",
                                    ))
                                    progress(len(pages), frontier.queue_size, robots_status)
                                    continue

                            entry_domain = (urlsplit(entry.url).netloc or "").lower()
                            throttler.throttle(entry.url)

                            task_dict = {
                                "url": entry.url,
                                "depth": entry.depth,
                                "parent_url": entry.parent_url,
                                "start_url": request.start_url,
                                "user_agent": self.settings.user_agent,
                                "timeout_seconds": self.settings.request_timeout_seconds,
                                "max_retries": effective_max_retries,
                                "retry_backoff_seconds": self.settings.retry_backoff_seconds,
                                "max_redirects": effective_max_redirects,
                                "delay_seconds": 0.0,
                                "max_document_bytes": self.settings.max_document_bytes,
                                "allow_private": getattr(self.settings, "allow_private_crawls", False),
                            }

                            try:
                                fut = executor.submit(execute_worker_crawl_task, task_dict)
                                in_flight[fut] = entry
                                in_flight_by_domain[entry_domain] = in_flight_by_domain.get(entry_domain, 0) + 1
                            except BrokenProcessPool as bpp:
                                fatal_error = f"BrokenProcessPool: {bpp}"
                                break

                        if fatal_error:
                            break

                        if not in_flight:
                            if frontier.is_complete() and not deferred_entries:
                                break
                            time.sleep(0.01)
                            continue

                        try:
                            done, _ = concurrent.futures.wait(
                                in_flight.keys(),
                                timeout=0.05,
                                return_when=concurrent.futures.FIRST_COMPLETED,
                            )
                        except BrokenProcessPool as bpp:
                            fatal_error = f"BrokenProcessPool: {bpp}"
                            break

                        for fut in done:
                            orig_entry = in_flight.pop(fut)
                            orig_domain = (urlsplit(orig_entry.url).netloc or "").lower()
                            in_flight_by_domain[orig_domain] = max(0, in_flight_by_domain.get(orig_domain, 1) - 1)
                            throttler.record_completion(orig_entry.url)
                            try:
                                res = fut.result()
                                worker_links = [LinkRecord(**l) for l in res.get("links", [])]
                                res_clean = dict(res)
                                res_clean.pop("links", None)
                                worker_pid = res_clean.pop("worker_pid", None)
                                t_start = res_clean.pop("t_start", 0.0)
                                t_end = res_clean.pop("t_end", 0.0)

                                page = PageRecord(**normalize_page_payload(res_clean))
                                page.requested_fetch_strategy = requested_fetch_mode
                                page.actual_fetch_strategy = "static"
                                if worker_pid:
                                    page.headers["x-worker-pid"] = str(worker_pid)
                                page.headers["x-parent-pid"] = str(parent_pid)
                                if t_start and t_end:
                                    page.headers["x-fetch-start"] = str(t_start)
                                    page.headers["x-fetch-end"] = str(t_end)

                                self._process_and_record_page(
                                    request, frontier, page, worker_links, pages, links,
                                    seen_canonicals, seen_content_hashes, pagination_counts,
                                )
                            except Exception as exc:
                                err_page = self._error_page(
                                    orig_entry.url, [], f"MultiprocessTaskException: {exc}",
                                    engine_mode="process", depth=orig_entry.depth, parent_url=orig_entry.parent_url,
                                    requested_fetch_strategy=requested_fetch_mode,
                                    actual_fetch_strategy="static",
                                )
                                pages.append(err_page)
                                frontier.mark_failed(orig_entry.url, str(exc), is_retryable=False)

                            progress(len(pages), frontier.queue_size, robots_status)

                            total_response_bytes += page.response_bytes
                            if res_clean.get("redirect_chain"):
                                retries_performed += sum(int(hop.get("attempt", 1)) - 1 for hop in res_clean["redirect_chain"] if isinstance(hop, dict))
                            if effective_max_bytes and total_response_bytes >= effective_max_bytes:
                                termination_budget_reason = f"budget_exhausted: max_bytes reached ({total_response_bytes} >= {effective_max_bytes})"
                                break
                            if deadline and time.monotonic() >= deadline:
                                elapsed = time.monotonic() - start_time
                                termination_budget_reason = f"budget_exhausted: max_crawl_duration exceeded ({elapsed:.2f}s >= {effective_max_duration}s)"
                                break
                            if len(pages) >= effective_max_pages:
                                if budget and budget.max_pages is not None:
                                    termination_budget_reason = f"budget_exhausted: max_pages reached ({len(pages)} >= {effective_max_pages})"
                                break

                        if termination_budget_reason:
                            break

                    if not termination_budget_reason and budget and budget.max_pages is not None and len(pages) >= effective_max_pages:
                        termination_budget_reason = f"budget_exhausted: max_pages reached ({len(pages)} >= {effective_max_pages})"

                    if cancellation_token and cancellation_token.is_cancelled():
                        for f in in_flight:
                            f.cancel()
        except Exception as exc:
            fatal_error = f"{type(exc).__name__}: {exc}"

        return self._build_crawl_result(
            request, "process", "static", pages, links, frontier,
            robots_status, start_time, started_at, cancellation_token,
            fatal_error=fatal_error,
            termination_budget_reason=termination_budget_reason,
            total_response_bytes=total_response_bytes,
            retries_performed=retries_performed,
        )

    def _materialize_static(self, request: CrawlRequest, result: tuple[str, tuple[int, dict[str, str], bytes, str] | None, list[dict[str, object]], str]) -> tuple[PageRecord, list[LinkRecord]]:
        url, payload, redirect_chain, fetch_error = result
        if payload is None:
            return self._error_page(url, redirect_chain, fetch_error, getattr(request, "executor_mode", "serial")), []
        status_code, headers, content, final_url = payload
        response = httpx.Response(status_code, headers=headers, content=content, request=httpx.Request("GET", final_url))
        page, page_links = self._build_page(request, url, response, redirect_chain, fetch_error, None)
        return page, page_links

    def _run_static_mode(self, request: CrawlRequest, progress: callable, cancellation_token: CancellationToken | None = None) -> CrawlResult:
        mode = self._executor_mode(request)
        if mode == "thread":
            return self._run_threaded(request, progress, cancellation_token)
        elif mode == "async":
            return self._run_coroutine(request, progress, cancellation_token)
        elif mode == "process":
            return self._run_multiprocess(request, progress, cancellation_token)
        return self._run_serial(request, progress, cancellation_token)


class SerialCrawlerEngine(CrawlEngine):
    """Genuinely single-threaded, serial crawler engine."""

    def run(
        self,
        request: CrawlRequest,
        progress: callable,
        cancellation_token: CancellationToken | None = None,
    ) -> CrawlResult:
        return self._run_serial(request, progress, cancellation_token)


class ThreadedCrawlerEngine(CrawlEngine):
    """Genuinely multi-threaded crawler engine with persistent connection pooling."""

    def run(
        self,
        request: CrawlRequest,
        progress: callable,
        cancellation_token: CancellationToken | None = None,
    ) -> CrawlResult:
        return self._run_threaded(request, progress, cancellation_token)


class CoroutineCrawlerEngine(CrawlEngine):
    """Genuinely non-blocking coroutine crawler engine with persistent event loop and AsyncClient."""

    def run(
        self,
        request: CrawlRequest,
        progress: callable,
        cancellation_token: CancellationToken | None = None,
    ) -> CrawlResult:
        return self._run_coroutine(request, progress, cancellation_token)


class MultiprocessCrawlerEngine(CrawlEngine):
    """Genuinely multi-process crawler engine with socket fetching and parsing in spawned worker processes."""

    def run(
        self,
        request: CrawlRequest,
        progress: callable,
        cancellation_token: CancellationToken | None = None,
    ) -> CrawlResult:
        return self._run_multiprocess(request, progress, cancellation_token)
