"""Extract source and rendered HTML signals without executing page actions."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any

from bs4 import BeautifulSoup

from app.types import LinkRecord
from app.urltools import UrlValidationError, is_same_host, normalize_url


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def text_hash(value: str) -> str:
    return sha256(normalized_text(value).lower().encode("utf-8")).hexdigest()


def _schema_types(value: Any) -> list[str]:
    if isinstance(value, dict):
        own = value.get("@type", [])
        found = [own] if isinstance(own, str) else [item for item in own if isinstance(item, str)]
        for nested in value.values():
            found.extend(_schema_types(nested))
        return found
    if isinstance(value, list):
        return [entry for item in value for entry in _schema_types(item)]
    return []


def parse_structured_data(soup: BeautifulSoup) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    for position, tag in enumerate(soup.select('script[type="application/ld+json"]'), start=1):
        raw = tag.string or tag.get_text()
        if not raw or not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
            extracted.append({"position": position, "types": sorted(set(_schema_types(parsed))), "valid": True, "error": ""})
        except json.JSONDecodeError as exc:
            extracted.append({"position": position, "types": [], "valid": False, "error": f"JSON-LD parse error: {exc.msg}"})
    return extracted


def extract_links(html: str, page_url: str, seed_url: str) -> list[LinkRecord]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[LinkRecord] = []
    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href", "")).strip()
        if not raw_href or raw_href.startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        try:
            target = normalize_url(raw_href, page_url)
        except UrlValidationError:
            continue
        rel_values = [str(item).lower() for item in (anchor.get("rel") or [])]
        rel = " ".join(sorted(set(rel_values)))
        records.append(
            LinkRecord(
                source_url=page_url,
                target_url=target,
                raw_target_url=raw_href,
                anchor_text=normalized_text(anchor.get_text(" ", strip=True))[:500],
                rel=rel,
                is_internal=is_same_host(target, seed_url),
                nofollow="nofollow" in rel_values,
            )
        )
    return records


def extract_api_entry_points(html: str, page_url: str, seed_url: str) -> list[dict[str, Any]]:
    """Record explicit API-like references for review; never fetch or submit them automatically."""
    soup = BeautifulSoup(html or "", "html.parser")
    candidates: list[tuple[str, str, str]] = []
    for script in soup.find_all("script", src=True):
        candidates.append((str(script.get("src", "")), "script-src", "GET"))
    patterns = (
        (r"(?:fetch|axios\.(?:get|post|put|patch|request))\s*\(\s*[\"']([^\"']+)", "javascript-call", "GET"),
        (r"[\"']((?:https?:)?//[^\"']+/(?:api|graphql)(?:/[^\"']*)?)[\"']", "inline-url", "GET"),
        (r"[\"']((?:/|\./)?(?:api|graphql)(?:/[^\"']*)?)[\"']", "inline-path", "GET"),
    )
    raw_html = html or ""
    for pattern, kind, method in patterns:
        candidates.extend((match, kind, method) for match in re.findall(pattern, raw_html, flags=re.IGNORECASE))
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw, kind, method in candidates:
        if not raw or raw.startswith(("data:", "javascript:", "mailto:", "tel:")):
            continue
        try:
            target = normalize_url(raw, page_url)
        except UrlValidationError:
            continue
        key = (target, kind)
        if key in seen:
            continue
        seen.add(key)
        results.append({"url": target, "raw": raw, "kind": kind, "method": method, "is_internal": is_same_host(target, seed_url), "fetched": False})
    return results[:100]


def extract_page_signals(html: str, page_url: str, seed_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    title = normalized_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    description = normalized_text(str(description_tag.get("content", ""))) if description_tag else ""
    robots_tag = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    meta_robots = normalized_text(str(robots_tag.get("content", ""))).lower() if robots_tag else ""
    canonical_tag = soup.find("link", attrs={"rel": lambda values: values and "canonical" in [str(v).lower() for v in values]})
    canonical = ""
    if canonical_tag and canonical_tag.get("href"):
        try:
            canonical = normalize_url(str(canonical_tag["href"]), page_url)
        except UrlValidationError:
            canonical = str(canonical_tag["href"]).strip()
    headings = {f"h{level}": [normalized_text(node.get_text(" ", strip=True)) for node in soup.find_all(f"h{level}")] for level in range(1, 7)}
    images = [{"src": str(image.get("src", "")), "alt": str(image.get("alt", "")), "has_alt": "alt" in image.attrs} for image in soup.find_all("img")]
    return {
        "title": title,
        "description": description,
        "meta_robots": meta_robots,
        "canonical": canonical,
        "headings": headings,
        "images": images,
        "structured_data": parse_structured_data(soup),
        "api_entry_points": extract_api_entry_points(html, page_url, seed_url),
        "links": extract_links(html, page_url, seed_url),
    }
