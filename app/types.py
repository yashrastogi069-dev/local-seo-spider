"""Data structures shared by collection, analysis, exports, and templates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import threading
from typing import Any, Protocol, runtime_checkable


class CrawlStatus(str, Enum):
    """Lifecycle, operational, and termination states for crawl jobs."""

    # Operational lifecycle states
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    RETRYABLE = "retryable"

    # Termination states
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


class EngineMode(str, Enum):
    """Supported crawler execution engines."""

    SERIAL = "serial"
    THREAD = "thread"
    ASYNC = "async"
    PROCESS = "process"


class FetchMode(str, Enum):
    """Supported page fetch strategies."""

    STATIC = "static"
    BROWSER = "browser"
    SMART = "smart"


class CancellationToken:
    """Thread-safe, picklable cancellation token for cooperative crawler termination."""

    def __init__(self) -> None:
        self._cancelled = False
        self._reason = ""
        self._lock = threading.Lock()

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self, reason: str = "") -> None:
        with self._lock:
            self._cancelled = True
            self._reason = reason

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def __getstate__(self) -> dict[str, Any]:
        with self._lock:
            return {"cancelled": self._cancelled, "reason": self._reason}

    def __setstate__(self, state: dict[str, Any]) -> None:
        self._cancelled = state["cancelled"]
        self._reason = state["reason"]
        self._lock = threading.Lock()


@dataclass
class FrontierItem:
    """Explicit item in the crawler frontier tracking discovery hierarchy."""

    url: str
    depth: int = 0
    parent_url: str = ""
    discovered_at: str = ""
    retry_count: int = 0

    def __hash__(self) -> int:
        return hash((self.url, self.depth, self.parent_url))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FrontierItem):
            return False
        return (self.url, self.depth, self.parent_url) == (other.url, other.depth, other.parent_url)

    def to_tuple(self) -> tuple[str, int, str]:
        return (self.url, self.depth, self.parent_url)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FrontierState(str, Enum):
    """Lifecycle states for URLs managed in the crawl frontier."""

    DISCOVERED = "discovered"
    QUEUED = "queued"
    FETCHING = "fetching"
    COMPLETED = "completed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    SKIPPED = "skipped"
    DUPLICATE = "duplicate"


class InvalidStateTransitionError(ValueError):
    """Raised when an invalid frontier state transition is attempted."""


VALID_FRONTIER_TRANSITIONS: dict[FrontierState, set[FrontierState]] = {
    FrontierState.DISCOVERED: {
        FrontierState.QUEUED,
        FrontierState.SKIPPED,
        FrontierState.DUPLICATE,
    },
    FrontierState.QUEUED: {
        FrontierState.FETCHING,
        FrontierState.SKIPPED,
    },
    FrontierState.FETCHING: {
        FrontierState.COMPLETED,
        FrontierState.FAILED_RETRYABLE,
        FrontierState.FAILED_FINAL,
        FrontierState.SKIPPED,
        FrontierState.DUPLICATE,
    },
    FrontierState.FAILED_RETRYABLE: {
        FrontierState.QUEUED,
        FrontierState.FAILED_FINAL,
        FrontierState.SKIPPED,
    },
    FrontierState.COMPLETED: set(),
    FrontierState.FAILED_FINAL: set(),
    FrontierState.SKIPPED: set(),
    FrontierState.DUPLICATE: set(),
}


def validate_frontier_transition(from_state: FrontierState, to_state: FrontierState) -> None:
    """Validate that a transition between two frontier states is strictly permitted."""
    allowed = VALID_FRONTIER_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise InvalidStateTransitionError(
            f"Invalid frontier transition from {from_state.value} to {to_state.value}"
        )


@dataclass
class FrontierEntry:
    """Mutable tracking record for a URL in the crawl frontier state machine."""

    url: str
    depth: int = 0
    parent_url: str = ""
    state: FrontierState = FrontierState.DISCOVERED
    discovered_at: str = ""
    retry_count: int = 0
    max_retries: int = 3
    next_eligible_time: float = 0.0
    error: str = ""
    skip_reason: str = ""
    duplicate_of: str = ""
    status_code: int | None = None

    def transition_to(self, new_state: FrontierState) -> None:
        """Apply a validated state transition."""
        validate_frontier_transition(self.state, new_state)
        self.state = new_state

    def to_item(self) -> FrontierItem:
        return FrontierItem(
            url=self.url,
            depth=self.depth,
            parent_url=self.parent_url,
            discovered_at=self.discovered_at,
            retry_count=self.retry_count,
        )


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
    api_entry_points: list[dict[str, Any]] = field(default_factory=list)
    fetch_error: str = ""
    render_error: str = ""
    robots_allowed: bool = True
    body_truncated: bool = False
    discovered_at: str = ""
    internal_inlinks: int = 0
    content_hash: str = ""
    extracted_text: str = ""
    extraction_error: str = ""
    extracted_fields: dict[str, Any] = field(default_factory=dict)
    extraction_notes: list[str] = field(default_factory=list)
    etag: str = ""
    last_modified: str = ""
    is_duplicate: bool = False
    duplicate_of: str = ""
    source_type: str = "html_page"
    depth: int = 0
    parent_url: str = ""
    normalized_url: str = ""
    fetch_strategy: str = "static"
    crawler_engine: str = "serial"
    response_bytes: int = 0
    duration_ms: float = 0.0
    error_category: str = "none"
    headers: dict[str, str] = field(default_factory=dict)
    requested_fetch_strategy: str = ""
    actual_fetch_strategy: str = ""
    escalated: bool = False
    escalation_reason: str = ""
    fetch_duration_ms: float = 0.0
    render_duration_ms: float = 0.0

    def __post_init__(self) -> None:
        if not self.requested_fetch_strategy:
            self.requested_fetch_strategy = self.fetch_strategy
        if not self.actual_fetch_strategy:
            self.actual_fetch_strategy = self.fetch_strategy

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CrawlResult:
    """Rich crawl execution summary preserving observability invariants.

    Implements __iter__ yielding (pages, links, robots_status) to maintain full
    backward compatibility with legacy unpack callers.
    """

    crawl_id: str = ""
    requested_engine: str = "serial"
    actual_engine: str = "serial"
    requested_fetch_mode: str = "static"
    actual_fetch_mode: str = "static"
    fallback_occurred: bool = False
    fallback_reason: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    status: str = CrawlStatus.SUCCESS.value
    termination_reason: str = ""
    pages_discovered: int = 0
    pages_attempted: int = 0
    pages_succeeded: int = 0
    pages_failed: int = 0
    pages_skipped: int = 0
    pages_escalated: int = 0
    duplicates_count: int = 0
    retry_count: int = 0
    errors: list[str] = field(default_factory=list)
    pages: list[PageRecord] = field(default_factory=list)
    links: list[LinkRecord] = field(default_factory=list)
    robots_status: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.fallback_occurred:
            if (self.requested_engine and self.actual_engine and self.requested_engine != self.actual_engine) or (
                self.requested_fetch_mode and self.actual_fetch_mode and self.requested_fetch_mode != self.actual_fetch_mode
            ):
                self.fallback_occurred = True

    def __iter__(self):
        return iter((self.pages, self.links, self.robots_status))

    def __getitem__(self, index: int) -> Any:
        return (self.pages, self.links, self.robots_status)[index]

    def __len__(self) -> int:
        return 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "crawl_id": self.crawl_id,
            "requested_engine": self.requested_engine,
            "actual_engine": self.actual_engine,
            "requested_fetch_mode": self.requested_fetch_mode,
            "actual_fetch_mode": self.actual_fetch_mode,
            "fallback_occurred": self.fallback_occurred,
            "fallback_reason": self.fallback_reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "termination_reason": self.termination_reason,
            "pages_discovered": self.pages_discovered,
            "pages_attempted": self.pages_attempted,
            "pages_succeeded": self.pages_succeeded,
            "pages_failed": self.pages_failed,
            "pages_skipped": self.pages_skipped,
            "pages_escalated": self.pages_escalated,
            "duplicates_count": self.duplicates_count,
            "retry_count": self.retry_count,
            "errors": list(self.errors),
            "pages": [p.to_dict() for p in self.pages],
            "links": [link.to_dict() for link in self.links],
            "robots_status": self.robots_status,
            "metadata": dict(self.metadata),
        }


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
    mode: str = "site"
    url_list: list[str] = field(default_factory=list)
    max_urls: int = 500
    delay_seconds: float = 0.35
    respect_nofollow: bool = True
    acknowledgment: bool = False
    executor_mode: str = "serial"
    extraction_profile_path: str = ""
    follow_api_entry_points: bool = False
    crawl_id: str = ""
    max_depth: int = 10
    fetch_mode: str = "static"

    def public_settings(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "max_urls": self.max_urls,
            "delay_seconds": self.delay_seconds,
            "respect_nofollow": self.respect_nofollow,
            "url_list_count": len(self.url_list),
            "executor_mode": self.executor_mode,
            "extraction_profile": bool(self.extraction_profile_path),
            "follow_api_entry_points": self.follow_api_entry_points,
            "crawl_id": self.crawl_id,
            "max_depth": self.max_depth,
            "fetch_mode": self.fetch_mode,
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
            executor_mode=str(payload.get("executor_mode", "serial")),
            extraction_profile_path=str(payload.get("extraction_profile_path", "")),
            follow_api_entry_points=bool(payload.get("follow_api_entry_points", False)),
            crawl_id=str(payload.get("crawl_id", "")),
            max_depth=int(payload.get("max_depth", 10)),
            fetch_mode=str(payload.get("fetch_mode", "static")),
        )


@runtime_checkable
class CrawlerEngineProtocol(Protocol):
    """Abstract contract that all concrete crawler engines must satisfy."""

    def run(
        self,
        request: CrawlRequest,
        progress: Any,
        cancellation_token: CancellationToken | None = None,
    ) -> CrawlResult:
        """Execute the crawl job and return a rich, observable CrawlResult."""
        ...
