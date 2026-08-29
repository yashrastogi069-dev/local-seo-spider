"""Validated, evidence-preserving target-field extraction profiles."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, field_validator


SelectorType = Literal["css", "xpath", "regex", "jsonld"]
SourceMode = Literal["static", "dynamic", "either"]


class TargetField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
    selector: str = Field(min_length=1, max_length=500)
    selector_type: SelectorType = "css"
    source: SourceMode = "either"
    attribute: str | None = Field(default=None, max_length=80)
    required: bool = False
    max_values: int = Field(default=10, ge=1, le=100)
    max_chars: int = Field(default=5000, ge=1, le=20000)


class ExtractionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="default", min_length=1, max_length=80)
    fields: list[TargetField] = Field(min_length=1, max_length=32)

    @field_validator("fields")
    @classmethod
    def unique_names(cls, fields: list[TargetField]) -> list[TargetField]:
        names = [field.name for field in fields]
        if len(names) != len(set(names)):
            raise ValueError("Target field names must be unique.")
        return fields


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    values: list[str]
    found: bool
    source: str
    selector: str
    status: Literal["found", "missing", "unsupported", "invalid"]
    note: str = ""


def load_profile(path: Path | None) -> ExtractionProfile | None:
    if not path:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ExtractionProfile.model_validate(payload)


def _clean(value: Any, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _jsonld_path(value: Any, path: str) -> list[Any]:
    current: list[Any] = [value]
    for part in path.split("."):
        next_values: list[Any] = []
        for item in current:
            if isinstance(item, dict) and part in item:
                next_values.append(item[part])
            elif isinstance(item, list):
                next_values.extend(entry.get(part) for entry in item if isinstance(entry, dict) and part in entry)
        current = next_values
    flattened: list[Any] = []
    for item in current:
        flattened.extend(item if isinstance(item, list) else [item])
    return flattened


def _html_values(field: TargetField, html: str) -> tuple[list[str], str]:
    if not html:
        return [], "No HTML source was available."
    if field.selector_type == "xpath":
        try:
            from lxml import html as lxml_html
            root = lxml_html.fromstring(html)
            values = root.xpath(field.selector)
            cleaned = []
            for value in values[: field.max_values]:
                if hasattr(value, "get") and field.attribute:
                    cleaned.append(_clean(value.get(field.attribute), field.max_chars))
                elif hasattr(value, "text_content"):
                    cleaned.append(_clean(value.text_content(), field.max_chars))
                else:
                    cleaned.append(_clean(value, field.max_chars))
            return [value for value in cleaned if value], ""
        except Exception as exc:
            return [], f"XPath extraction failed: {type(exc).__name__}: {exc}"
    if field.selector_type == "regex":
        try:
            soup = BeautifulSoup(html, "html.parser")
            haystack = html + "\n" + soup.get_text(" ", strip=True)
            matches = re.findall(field.selector, haystack, flags=re.IGNORECASE)
            values = [match if isinstance(match, str) else " ".join(match) for match in matches]
            return [_clean(value, field.max_chars) for value in values[: field.max_values] if _clean(value, field.max_chars)], ""
        except re.error as exc:
            return [], f"Regex extraction failed: {exc}"
    soup = BeautifulSoup(html, "html.parser")
    try:
        elements = soup.select(field.selector)
    except Exception as exc:
        return [], f"CSS selector failed: {type(exc).__name__}: {exc}"
    values = []
    for element in elements[: field.max_values]:
        value = element.get(field.attribute) if field.attribute else element.get_text(" ", strip=True)
        cleaned = _clean(value, field.max_chars)
        if cleaned:
            values.append(cleaned)
    return values, ""


def extract_profile_fields(profile: ExtractionProfile | None, url: str, source_html: str = "", rendered_html: str = "", structured_data: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Extract fields from an explicit profile and return only JSON-serializable evidence."""
    if not profile:
        return {}
    data: dict[str, Any] = {"profile": profile.name, "url": url, "fields": {}}
    for field in profile.fields:
        source = field.source
        html = rendered_html if source == "dynamic" else source_html if source == "static" else (rendered_html or source_html)
        values: list[str] = []
        note = ""
        if field.selector_type == "jsonld":
            for block in structured_data or []:
                values.extend(_clean(value, field.max_chars) for value in _jsonld_path(block, field.selector))
                if len(values) >= field.max_values:
                    break
            values = [value for value in values[: field.max_values] if value]
        else:
            values, note = _html_values(field, html)
        status: str = "found" if values else "missing"
        if note:
            status = "unsupported" if field.selector_type == "xpath" and "failed" not in note.lower() else "invalid"
        data["fields"][field.name] = ExtractedField(name=field.name, values=values, found=bool(values), source=source, selector=field.selector, status=status, note=note).model_dump()
    return data
