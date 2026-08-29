"""Data structures shared by collection, analysis, exports, and templates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class LinkRecord:
    source_url: str
    target_url: str
    raw_target_url: str
    anchor_text: str
    rel: str
    is_internal: bool
    nofollow: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageRecord:
    url: str
    final_url: str
    status_code: int | None
    content_type: str
    title: str
    description: str
    headings: dict[str, list[str]]
    canonical: str
    meta_robots: str
    x_robots: str
    source_html: str
    rendered_html: str
    rendered_text: str
    images: list[dict[str, str]]
    structured_data: list[dict[str, Any]]
    redirect_chain: list[dict[str, Any]]
    fetch_error: str = ""
    render_error: str = ""
    robots_allowed: bool = True
    body_truncated: bool = False
    discovered_at: str = ""
    internal_inlinks: int = 0
    content_hash: str = ""
    extracted_text: str = ""
    extraction_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IssueRecord:
    rule_key: str
    severity: str
    title: str
    url: str
    evidence: str
    remediation: str
    fingerprint: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class CrawlRequest:
    start_url: str
    mode: str
    url_list: list[str] = field(default_factory=list)
    max_urls: int = 500
    delay_seconds: float = 0.35
    respect_nofollow: bool = True
    acknowledgment: bool = False

    def public_settings(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "max_urls": self.max_urls,
            "delay_seconds": self.delay_seconds,
            "respect_nofollow": self.respect_nofollow,
            "url_list_count": len(self.url_list),
        }

    def storage_payload(self) -> dict[str, Any]:
        """Return the complete local-only request needed to resume an approved job."""
        return asdict(self)

    @classmethod
    def from_storage_payload(cls, payload: dict[str, Any]) -> "CrawlRequest":
        return cls(
            start_url=str(payload["start_url"]),
            mode=str(payload["mode"]),
            url_list=[str(url) for url in payload.get("url_list", [])],
            max_urls=int(payload["max_urls"]),
            delay_seconds=float(payload["delay_seconds"]),
            respect_nofollow=bool(payload["respect_nofollow"]),
            acknowledgment=bool(payload["acknowledgment"]),
        )
