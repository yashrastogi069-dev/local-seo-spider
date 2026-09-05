"""Top-level worker module for genuine multiprocess socket fetching and parsing (Phase 2C).

This module is designed to be executed inside child worker processes spawned by ProcessPoolExecutor
on Windows ('spawn') and POSIX platforms. Worker functions are top-level and handle pure picklable
payloads, performing genuine socket-level HTTP requests and CPU signal parsing in worker processes.
"""

from __future__ import annotations

import os
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from app.parser import extract_api_entry_points, extract_links, extract_page_signals, normalized_text, text_hash
from app.urltools import (
    UrlNormalizationPolicy,
    UrlValidationError,
    normalize_url,
    resolve_canonical_url,
)

_PRESERVE_SLASH_POLICY = UrlNormalizationPolicy(trailing_slash="preserve")
_WORKER_CLIENT: httpx.Client | None = None


def _get_worker_client(user_agent: str, timeout_seconds: float, max_retries: int) -> httpx.Client:
    """Get or initialize the process-local persistent HTTP client."""
    global _WORKER_CLIENT
    if _WORKER_CLIENT is None:
        transport = httpx.HTTPTransport(
            retries=max_retries,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4, keepalive_expiry=30.0),
        )
        _WORKER_CLIENT = httpx.Client(
            transport=transport,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,application/json,application/xml,text/csv",
            },
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        )
    return _WORKER_CLIENT


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


def execute_worker_crawl_task(task: dict[str, object]) -> dict[str, object]:
    """Execute socket fetch and HTML extraction in the spawned child worker process.
    
    Returns a picklable dictionary with complete forensic provenance and child worker PID.
    """
    worker_pid = os.getpid()
    url = str(task["url"])
    depth = int(task.get("depth", 0))
    parent_url = str(task.get("parent_url", ""))
    user_agent = str(task.get("user_agent", "LocalSEOSpider/Test"))
    timeout_seconds = float(task.get("timeout_seconds", 5.0))
    max_retries = int(task.get("max_retries", 2))
    retry_backoff_seconds = float(task.get("retry_backoff_seconds", 0.1))
    max_redirects = int(task.get("max_redirects", 5))
    delay_seconds = float(task.get("delay_seconds", 0.0))
    max_document_bytes = int(task.get("max_document_bytes", 1_000_000))
    allow_private = bool(task.get("allow_private", False))

    if delay_seconds > 0:
        time.sleep(delay_seconds)

    client = _get_worker_client(user_agent, timeout_seconds, max_retries)
    headers = {"X-Client-PID": str(worker_pid)}

    t_start = time.monotonic()
    current = url
    hops: list[dict[str, object]] = []
    transient_statuses = {408, 425, 429, 500, 502, 503, 504}
    response: httpx.Response | None = None
    fetch_error = ""

    # Socket-level fetch with redirect loop and retry handling inside worker process
    for redirect_count in range(max_redirects + 1):
        response = None
        for attempt in range(max_retries + 1):
            try:
                response = client.get(current, headers=headers)
            except httpx.HTTPError as exc:
                if attempt >= max_retries:
                    fetch_error = f"{type(exc).__name__} after {attempt + 1} attempt(s): {exc}"
                    break
                time.sleep(retry_backoff_seconds * (2 ** attempt))
                continue

            hops.append({
                "url": current,
                "status_code": response.status_code,
                "location": response.headers.get("location", ""),
                "attempt": attempt + 1,
            })

            if response.status_code in transient_statuses and attempt < max_retries:
                time.sleep(_retry_delay(response, attempt, retry_backoff_seconds))
                continue
            break

        if response is None:
            if not fetch_error:
                fetch_error = "Request ended without a response."
            break

        if response.is_redirect and response.headers.get("location"):
            try:
                current = normalize_url(
                    response.headers["location"],
                    current,
                    allow_private=allow_private,
                    policy=_PRESERVE_SLASH_POLICY,
                )
            except UrlValidationError:
                fetch_error = "Redirect location could not be normalized."
                break
            continue

        if response.status_code in transient_statuses:
            fetch_error = f"Transient HTTP status {response.status_code} remained after {max_retries + 1} attempt(s)."
        break

    if redirect_count >= max_redirects and response and response.is_redirect:
        fetch_error = f"Redirect limit ({max_redirects}) exceeded."

    t_end = time.monotonic()
    duration_ms = (t_end - t_start) * 1000.0

    # Response signal extraction in worker process
    status_code = response.status_code if response is not None else None
    resp_headers = dict(response.headers) if response is not None else {}
    content_type = resp_headers.get("content-type", "").lower()
    raw_content = response.content[:max_document_bytes] if response is not None else b""
    body_truncated = len(response.content) > max_document_bytes if response is not None else False
    final_url = str(response.url) if response is not None else current

    source_html = ""
    if "html" in content_type or "xml" in content_type:
        try:
            source_html = raw_content.decode(response.encoding or "utf-8", errors="replace")
        except Exception:
            source_html = raw_content.decode("utf-8", errors="replace")

    start_url = str(task.get("start_url") or url)
    signals = extract_page_signals(source_html, final_url, start_url, allow_private=allow_private) if source_html else {}
    page_links = extract_links(source_html, final_url, start_url, allow_private=allow_private) if source_html else []
    api_entries = extract_api_entry_points(source_html, final_url, start_url, allow_private=allow_private) if source_html else []

    title = signals.get("title", "")
    if not title and "json" in content_type:
        title = f"API {urlsplit(final_url).path}"

    canonical_raw = signals.get("canonical", "")
    canonical = resolve_canonical_url(canonical_raw, final_url, allow_private=allow_private)

    c_hash = text_hash(source_html or raw_content.decode("utf-8", errors="replace"))

    err_cat = "none"
    if fetch_error:
        err_cat = "fetch_error"
    elif status_code and status_code >= 400:
        err_cat = f"http_{status_code}"

    return {
        "url": url,
        "final_url": final_url,
        "status_code": status_code,
        "content_type": content_type,
        "title": title,
        "description": signals.get("description", ""),
        "headings": signals.get("headings", {}),
        "canonical": canonical,
        "meta_robots": signals.get("meta_robots", ""),
        "x_robots": resp_headers.get("x-robots-tag", "").lower(),
        "source_html": source_html,
        "rendered_html": "",
        "rendered_text": source_html,
        "images": signals.get("images", []),
        "structured_data": signals.get("structured_data", []),
        "api_entry_points": api_entries,
        "redirect_chain": hops,
        "fetch_error": fetch_error,
        "robots_allowed": True,
        "body_truncated": body_truncated,
        "content_hash": c_hash,
        "depth": depth,
        "parent_url": parent_url,
        "normalized_url": final_url or url,
        "fetch_strategy": "static",
        "crawler_engine": "process",
        "response_bytes": len(raw_content),
        "duration_ms": duration_ms,
        "error_category": err_cat,
        "headers": resp_headers,
        "worker_pid": worker_pid,
        "t_start": t_start,
        "t_end": t_end,
        "links": [link.to_dict() for link in page_links],
    }
