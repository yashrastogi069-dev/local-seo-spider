"""URL validation and normalization for a bounded, same-host crawler."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit


class UrlValidationError(ValueError):
    """Raised for malformed or unsafe crawl input."""


def normalize_url(value: str, base_url: str | None = None) -> str:
    candidate = urljoin(base_url, value) if base_url else value
    parsed = urlsplit(candidate.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UrlValidationError("Only http:// and https:// URLs are supported.")
    if not parsed.hostname:
        raise UrlValidationError("Enter a complete URL with a hostname.")
    if parsed.username or parsed.password:
        raise UrlValidationError("URLs containing credentials are not accepted.")
    host = parsed.hostname.lower().rstrip(".")
    port = parsed.port
    netloc = host
    if port and not ((parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def is_same_host(url: str, seed_url: str) -> bool:
    candidate = urlsplit(url)
    seed = urlsplit(seed_url)
    return candidate.hostname == seed.hostname and candidate.port == seed.port and candidate.scheme == seed.scheme


def safe_filename(value: str, fallback: str = "export") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-_")
    return (cleaned[:80] or fallback).lower()


def visible_url(value: str, limit: int = 86) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"
