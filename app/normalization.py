"""Deterministic cleaning and normalization for crawl-derived records."""
from __future__ import annotations

import html
import re
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from urllib.parse import urlsplit, urlunsplit

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_SPACE = re.compile(r"\s+")


class NormalizedPagePayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    url: str = Field(min_length=1)
    final_url: str = Field(min_length=1)
    content_type: str = ""
    title: str = ""
    description: str = ""


def validate_normalized_page(payload: dict[str, Any]) -> dict[str, Any]:
    return NormalizedPagePayload.model_validate(payload).model_dump()


def clean_text(value: Any, max_chars: int = 20_000) -> str:
    """Normalize Unicode, HTML entities, invisible characters, and whitespace."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", html.unescape(str(value)))
    text = _ZERO_WIDTH.sub("", text)
    return _SPACE.sub(" ", text).strip()[:max_chars]


def clean_url(value: Any) -> str:
    """Normalize URL presentation without changing its security scope."""
    text = clean_text(value, 8_000)
    if not text:
        return ""
    parsed = urlsplit(text)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def clean_values(values: Any, max_values: int = 100, max_chars: int = 20_000) -> list[str]:
    source = values if isinstance(values, (list, tuple, set)) else [values]
    result: list[str] = []
    seen: set[str] = set()
    for value in source:
        cleaned = clean_text(value, max_chars)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
        if len(result) >= max_values:
            break
    return result


def normalize_extracted_fields(payload: dict[str, Any]) -> dict[str, Any]:
    fields = payload.get("fields", {}) if isinstance(payload, dict) else {}
    normalized: dict[str, Any] = dict(payload) if isinstance(payload, dict) else {}
    normalized["fields"] = {}
    for name, field in fields.items():
        item = dict(field) if isinstance(field, dict) else {}
        item["values"] = clean_values(item.get("values", []), 100, 20_000)
        item["found"] = bool(item["values"])
        item["note"] = clean_text(item.get("note", ""), 2_000)
        normalized["fields"][clean_text(name, 80)] = item
    return normalized


def normalize_page_payload(page: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe cleaned copy while preserving evidence fields."""
    result = dict(page)
    for key in ("url", "final_url", "canonical"):
        if key in result:
            result[key] = clean_url(result[key])
    for key in ("title", "description", "meta_robots", "x_robots", "fetch_error", "render_error", "extraction_error"):
        if key in result:
            result[key] = clean_text(result[key])
    for key in ("rendered_text", "extracted_text"):
        if key in result:
            result[key] = clean_text(result[key], 2_000_000)
    if isinstance(result.get("extracted_fields"), dict):
        result["extracted_fields"] = normalize_extracted_fields(result["extracted_fields"])
    if isinstance(result.get("extraction_notes"), list):
        result["extraction_notes"] = clean_values(result["extraction_notes"], 100, 2_000)
    return validate_normalized_page(result)
