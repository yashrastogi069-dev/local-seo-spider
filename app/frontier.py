"""Thread-safe, invariant-preserving crawl frontier with explicit lifecycle state transitions."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from app.types import (
    FrontierEntry,
    FrontierItem,
    FrontierState,
    InvalidStateTransitionError,
    validate_frontier_transition,
)
from app.urltools import (
    UrlNormalizationPolicy,
    UrlValidationError,
    is_same_host,
    normalize_url,
)


_TERMINAL_FRONTIER_STATES = {
    FrontierState.COMPLETED,
    FrontierState.FAILED_FINAL,
    FrontierState.SKIPPED,
    FrontierState.DUPLICATE,
}


class CrawlFrontier:
    """Centralized crawl frontier enforcing URL deduplication, depth limits,

    retry backoff eligibility, and strict completion detection.
    """

    def __init__(
        self,
        start_url: str = "",
        max_urls: int = 500,
        max_depth: int = 10,
        mode: str = "site",
        url_list: list[str] | None = None,
        allowed_domains: set[str] | None = None,
        allow_private: bool = False,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        policy: UrlNormalizationPolicy | None = None,
    ) -> None:
        self.start_url = start_url.strip()
        self.max_urls = max(1, max_urls)
        self.max_depth = max(0, max_depth)
        self.mode = mode
        self.allow_private = allow_private
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.policy = policy or UrlNormalizationPolicy()

        self._lock = threading.Lock()
        self._entries: dict[str, FrontierEntry] = {}
        self._queue: deque[str] = deque()
        self._active_workers: int = 0
        self._retry_pool: dict[str, FrontierEntry] = {}
        self._seen_canonicals: dict[str, str] = {}
        self._alias_map: dict[str, str] = {}

        # Allowed host(s)
        self.allowed_domains = set(allowed_domains or [])
        if self.start_url:
            try:
                seed_host = urlsplit(self.start_url).hostname
                if seed_host:
                    self.allowed_domains.add(seed_host.lower())
            except Exception:
                pass

        # Admitted count (queued or processed towards max_urls)
        self._admitted_count: int = 0
        self._retry_count: int = 0

        # Enqueue seeds
        if mode == "list" and url_list:
            for raw in url_list:
                self.add_seed(raw)
        elif self.start_url:
            self.add_seed(self.start_url)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

    def add_seed(self, raw_url: str) -> FrontierEntry | None:
        """Normalize and admit a seed URL into the frontier."""
        with self._lock:
            try:
                norm_url = normalize_url(raw_url, allow_private=self.allow_private, policy=self.policy)
            except (UrlValidationError, ValueError):
                return None

            if norm_url in self._entries:
                return self._entries[norm_url]

            if self._admitted_count >= self.max_urls:
                entry = FrontierEntry(
                    url=norm_url,
                    depth=0,
                    parent_url="",
                    state=FrontierState.SKIPPED,
                    discovered_at=self._now(),
                    skip_reason="page_limit_reached",
                )
                self._entries[norm_url] = entry
                return entry

            entry = FrontierEntry(
                url=norm_url,
                depth=0,
                parent_url="",
                state=FrontierState.QUEUED,
                discovered_at=self._now(),
                max_retries=self.max_retries,
            )
            self._entries[norm_url] = entry
            self._queue.append(norm_url)
            self._admitted_count += 1
            return entry

    def is_allowed_host(self, url: str) -> bool:
        """Check if URL host belongs to allowed domains."""
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower()
            if not host:
                return False
            if not self.allowed_domains:
                return True
            return host in self.allowed_domains or any(host.endswith("." + d) for d in self.allowed_domains)
        except Exception:
            return False

    def discover(self, target_urls: list[str], parent_url: str, parent_depth: int) -> list[str]:
        """Discover and conditionally enqueue target URLs discovered from a crawled parent page."""
        newly_queued: list[str] = []
        with self._lock:
            for raw in target_urls:
                if not raw:
                    continue
                try:
                    norm_url = normalize_url(raw, base_url=parent_url, allow_private=self.allow_private, policy=self.policy)
                except (UrlValidationError, ValueError):
                    continue

                if not norm_url:
                    continue

                # Check self-link
                if norm_url == parent_url:
                    if norm_url not in self._entries:
                        entry = FrontierEntry(
                            url=norm_url,
                            depth=parent_depth,
                            parent_url=parent_url,
                            state=FrontierState.DUPLICATE,
                            discovered_at=self._now(),
                            duplicate_of=parent_url,
                        )
                        self._entries[norm_url] = entry
                    continue

                # Check alias map
                target_key = self._alias_map.get(norm_url, norm_url)

                # Check if already in frontier
                if target_key in self._entries:
                    continue

                # Check domain restriction
                if not self.is_allowed_host(target_key):
                    entry = FrontierEntry(
                        url=target_key,
                        depth=parent_depth + 1,
                        parent_url=parent_url,
                        state=FrontierState.SKIPPED,
                        discovered_at=self._now(),
                        skip_reason="external_domain",
                    )
                    self._entries[target_key] = entry
                    continue

                # Check depth limit
                new_depth = parent_depth + 1
                if new_depth > self.max_depth:
                    entry = FrontierEntry(
                        url=target_key,
                        depth=new_depth,
                        parent_url=parent_url,
                        state=FrontierState.SKIPPED,
                        discovered_at=self._now(),
                        skip_reason="max_depth_exceeded",
                    )
                    self._entries[target_key] = entry
                    continue

                # Check page budget
                if self._admitted_count >= self.max_urls:
                    entry = FrontierEntry(
                        url=target_key,
                        depth=new_depth,
                        parent_url=parent_url,
                        state=FrontierState.SKIPPED,
                        discovered_at=self._now(),
                        skip_reason="page_limit_reached",
                    )
                    self._entries[target_key] = entry
                    continue

                # Admit and queue
                entry = FrontierEntry(
                    url=target_key,
                    depth=new_depth,
                    parent_url=parent_url,
                    state=FrontierState.QUEUED,
                    discovered_at=self._now(),
                    max_retries=self.max_retries,
                )
                self._entries[target_key] = entry
                self._queue.append(target_key)
                self._admitted_count += 1
                newly_queued.append(target_key)

        return newly_queued

    def get_next(self) -> FrontierEntry | None:
        """Fetch the next runnable URL entry from queue or eligible retry pool."""
        with self._lock:
            # First, check retry pool for items whose backoff expired
            now_ts = time.monotonic()
            ready_retries = [url for url, e in self._retry_pool.items() if now_ts >= e.next_eligible_time]
            for url in ready_retries:
                e = self._retry_pool.pop(url)
                e.transition_to(FrontierState.QUEUED)
                self._queue.append(url)

            if not self._queue:
                return None

            url = self._queue.popleft()
            entry = self._entries[url]
            entry.transition_to(FrontierState.FETCHING)
            self._active_workers += 1
            return entry

    def mark_completed(self, url: str, status_code: int = 200) -> None:
        """Mark a fetching URL as successfully completed."""
        with self._lock:
            entry = self._entries.get(url)
            if entry is None:
                return
            if entry.state in _TERMINAL_FRONTIER_STATES:
                if entry.state == FrontierState.COMPLETED:
                    entry.status_code = status_code
                return
            entry.status_code = status_code
            was_fetching = entry.state == FrontierState.FETCHING
            entry.transition_to(FrontierState.COMPLETED)
            if was_fetching:
                self._active_workers = max(0, self._active_workers - 1)

    def mark_failed(
        self,
        url: str,
        error: str,
        is_retryable: bool = False,
        retry_delay: float | None = None,
    ) -> None:
        """Mark a URL as failed, placing it into the retry pool if retryable."""
        with self._lock:
            entry = self._entries.get(url)
            if entry is None:
                return
            if entry.state in _TERMINAL_FRONTIER_STATES:
                if entry.state == FrontierState.FAILED_FINAL and error:
                    entry.error = error
                return
            entry.error = error
            was_fetching = entry.state == FrontierState.FETCHING
            if is_retryable and entry.retry_count < entry.max_retries:
                entry.retry_count += 1
                self._retry_count += 1
                delay = (
                    retry_delay
                    if retry_delay is not None
                    else self.retry_backoff_seconds * (2 ** (entry.retry_count - 1))
                )
                entry.next_eligible_time = time.monotonic() + delay
                entry.transition_to(FrontierState.FAILED_RETRYABLE)
                self._retry_pool[url] = entry
                if was_fetching:
                    self._active_workers = max(0, self._active_workers - 1)
            else:
                entry.transition_to(FrontierState.FAILED_FINAL)
                if was_fetching:
                    self._active_workers = max(0, self._active_workers - 1)

    def mark_skipped(self, url: str, reason: str) -> None:
        """Mark a URL as skipped."""
        with self._lock:
            entry = self._entries.get(url)
            if entry is None:
                return
            if entry.state in _TERMINAL_FRONTIER_STATES:
                if entry.state == FrontierState.SKIPPED and reason:
                    entry.skip_reason = reason
                return
            entry.skip_reason = reason
            was_fetching = entry.state == FrontierState.FETCHING
            entry.transition_to(FrontierState.SKIPPED)
            if was_fetching:
                self._active_workers = max(0, self._active_workers - 1)

    def mark_duplicate(self, url: str, duplicate_of: str) -> None:
        """Mark a URL as a duplicate of an existing canonical or redirected URL."""
        with self._lock:
            entry = self._entries.get(url)
            if entry is None:
                return
            if entry.state in _TERMINAL_FRONTIER_STATES:
                if entry.state == FrontierState.DUPLICATE and duplicate_of:
                    entry.duplicate_of = duplicate_of
                return
            if duplicate_of:
                entry.duplicate_of = duplicate_of
            was_fetching = entry.state == FrontierState.FETCHING
            entry.transition_to(FrontierState.DUPLICATE)
            if was_fetching:
                self._active_workers = max(0, self._active_workers - 1)

    def handle_redirect(
        self,
        from_url: str,
        to_url: str,
        depth: int,
        parent_url: str,
        enqueue_target: bool = True,
    ) -> str:
        """Record redirect destination, deduplicate if already known, or enqueue target."""
        with self._lock:
            self._alias_map[from_url] = to_url
            norm_to = normalize_url(to_url, allow_private=self.allow_private, policy=self.policy)

            if norm_to in self._entries:
                # Target already scheduled or completed; mark origin as duplicate of target
                entry_from = self._entries.get(from_url)
                if entry_from and entry_from.state not in _TERMINAL_FRONTIER_STATES:
                    entry_from.duplicate_of = norm_to
                    was_fetching = entry_from.state == FrontierState.FETCHING
                    entry_from.transition_to(FrontierState.DUPLICATE)
                    if was_fetching:
                        self._active_workers = max(0, self._active_workers - 1)
                return norm_to

            # If target within allowed host and budget, discover target
            if self.is_allowed_host(norm_to):
                if enqueue_target:
                    if self._admitted_count < self.max_urls and depth <= self.max_depth:
                        new_entry = FrontierEntry(
                            url=norm_to,
                            depth=depth,
                            parent_url=parent_url or from_url,
                            state=FrontierState.QUEUED,
                            discovered_at=self._now(),
                            max_retries=self.max_retries,
                        )
                        self._entries[norm_to] = new_entry
                        self._queue.append(norm_to)
                        self._admitted_count += 1
                    else:
                        new_entry = FrontierEntry(
                            url=norm_to,
                            depth=depth,
                            parent_url=parent_url or from_url,
                            state=FrontierState.SKIPPED,
                            discovered_at=self._now(),
                            skip_reason="page_limit_reached" if self._admitted_count >= self.max_urls else "max_depth_exceeded",
                        )
                        self._entries[norm_to] = new_entry
                else:
                    # Target was already fetched over wire by the caller; register as completed
                    target_entry = FrontierEntry(
                        url=norm_to,
                        depth=depth,
                        parent_url=parent_url or from_url,
                        state=FrontierState.COMPLETED,
                        discovered_at=self._now(),
                        status_code=200,
                    )
                    self._entries[norm_to] = target_entry

            # Mark from_url as completed redirect
            entry_from = self._entries.get(from_url)
            if entry_from and entry_from.state not in _TERMINAL_FRONTIER_STATES:
                entry_from.status_code = 302
                was_fetching = entry_from.state == FrontierState.FETCHING
                entry_from.transition_to(FrontierState.COMPLETED)
                if was_fetching:
                    self._active_workers = max(0, self._active_workers - 1)

            return norm_to

    def handle_canonical(self, page_url: str, canonical_url: str) -> bool:
        """Check if declared canonical makes page_url a duplicate of an existing canonical."""
        with self._lock:
            if not canonical_url or canonical_url == page_url:
                return False

            norm_canon = normalize_url(canonical_url, page_url, allow_private=self.allow_private, policy=self.policy)
            if norm_canon == page_url:
                return False

            if norm_canon in self._seen_canonicals:
                rep_url = self._seen_canonicals[norm_canon]
                entry = self._entries.get(page_url)
                if entry and entry.state not in _TERMINAL_FRONTIER_STATES:
                    entry.duplicate_of = rep_url
                    was_fetching = entry.state == FrontierState.FETCHING
                    entry.transition_to(FrontierState.DUPLICATE)
                    if was_fetching:
                        self._active_workers = max(0, self._active_workers - 1)
                return True

            self._seen_canonicals[norm_canon] = page_url
            return False

    def is_complete(self) -> bool:
        """Completion invariant:

        No runnable items in queue
        AND no workers actively fetching
        AND no retry items eligible/pending.
        """
        with self._lock:
            return len(self._queue) == 0 and self._active_workers == 0 and len(self._retry_pool) == 0

    def reconcile_accounting(self) -> dict[str, int]:
        """Verify frontier invariants and return reconciled accounting ledger."""
        with self._lock:
            counts = {
                "discovered": len(self._entries),
                "queued": sum(1 for e in self._entries.values() if e.state == FrontierState.QUEUED),
                "fetching": sum(1 for e in self._entries.values() if e.state == FrontierState.FETCHING),
                "completed": sum(1 for e in self._entries.values() if e.state == FrontierState.COMPLETED),
                "failed_retryable": sum(1 for e in self._entries.values() if e.state == FrontierState.FAILED_RETRYABLE),
                "failed_final": sum(1 for e in self._entries.values() if e.state == FrontierState.FAILED_FINAL),
                "skipped": sum(1 for e in self._entries.values() if e.state == FrontierState.SKIPPED),
                "duplicate": sum(1 for e in self._entries.values() if e.state == FrontierState.DUPLICATE),
            }

            # Invariant 1: Total matches sum of all individual states
            summed = (
                counts["queued"]
                + counts["fetching"]
                + counts["completed"]
                + counts["failed_retryable"]
                + counts["failed_final"]
                + counts["skipped"]
                + counts["duplicate"]
            )
            assert counts["discovered"] == summed, (
                f"Frontier accounting mismatch: discovered={counts['discovered']}, summed={summed}"
            )

            # Invariant 2: Completed URLs cannot be in queue or retry pool
            for url, e in self._entries.items():
                if e.state == FrontierState.COMPLETED:
                    assert url not in self._queue, f"Completed URL {url} is still in queue"
                    assert url not in self._retry_pool, f"Completed URL {url} is in retry pool"

            # Invariant 3: Completed URL depths must not exceed max_depth
            for url, e in self._entries.items():
                if e.state == FrontierState.COMPLETED:
                    assert e.depth <= self.max_depth, (
                        f"Completed URL {url} depth={e.depth} exceeds max_depth={self.max_depth}"
                    )

            # Invariant 4: Active workers matches fetching count
            assert self._active_workers == counts["fetching"], (
                f"Active worker count mismatch: active={self._active_workers}, fetching={counts['fetching']}"
            )

            return counts

    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def active_workers(self) -> int:
        with self._lock:
            return self._active_workers

    @property
    def total_discovered(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def completed_count(self) -> int:
        with self._lock:
            return sum(1 for e in self._entries.values() if e.state == FrontierState.COMPLETED)
