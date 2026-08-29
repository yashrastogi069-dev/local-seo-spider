"""Pydantic boundaries for reproducible local exports."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PageExport(BaseModel):
    model_config = ConfigDict(extra="allow")

    url: str
    final_url: str
    status_code: int | None = None
    content_type: str = ""
    title: str = ""
    description: str = ""
    headings: dict[str, list[str]] = Field(default_factory=dict)
    canonical: str = ""
    meta_robots: str = ""
    x_robots: str = ""
    source_html: str = ""
    rendered_html: str = ""
    rendered_text: str = ""
    extracted_text: str = ""
    extraction_error: str = ""
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    extraction_notes: list[str] = Field(default_factory=list)
    images: list[dict[str, Any]] = Field(default_factory=list)
    structured_data: list[dict[str, Any]] = Field(default_factory=list)
    redirect_chain: list[dict[str, Any]] = Field(default_factory=list)
    fetch_error: str = ""
    render_error: str = ""
    robots_allowed: bool = True
    body_truncated: bool = False
    discovered_at: str = ""
    internal_inlinks: int = 0
    content_hash: str = ""


class IssueExport(BaseModel):
    model_config = ConfigDict(extra="allow")

    rule_key: str
    severity: str
    title: str
    url: str
    evidence: str
    remediation: str
    fingerprint: str = ""


def validate_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [PageExport.model_validate(page).model_dump(mode="json") for page in pages]


def validate_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [IssueExport.model_validate(issue).model_dump(mode="json") for issue in issues]
