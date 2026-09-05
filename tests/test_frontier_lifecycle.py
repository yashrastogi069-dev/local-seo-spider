"""Unit, state machine, invariant, and completion detection tests for CrawlFrontier (Phase 2B)."""

import time
import pytest

from app.frontier import CrawlFrontier
from app.types import (
    FrontierEntry,
    FrontierState,
    InvalidStateTransitionError,
    validate_frontier_transition,
)
from app.urltools import UrlNormalizationPolicy


def test_frontier_valid_transitions():
    """Verify all legitimate state transitions in the frontier lifecycle."""
    entry = FrontierEntry(url="https://example.com/test", state=FrontierState.DISCOVERED)

    # DISCOVERED -> QUEUED
    entry.transition_to(FrontierState.QUEUED)
    assert entry.state == FrontierState.QUEUED

    # QUEUED -> FETCHING
    entry.transition_to(FrontierState.FETCHING)
    assert entry.state == FrontierState.FETCHING

    # FETCHING -> FAILED_RETRYABLE
    entry.transition_to(FrontierState.FAILED_RETRYABLE)
    assert entry.state == FrontierState.FAILED_RETRYABLE

    # FAILED_RETRYABLE -> QUEUED
    entry.transition_to(FrontierState.QUEUED)
    assert entry.state == FrontierState.QUEUED

    # QUEUED -> FETCHING
    entry.transition_to(FrontierState.FETCHING)
    assert entry.state == FrontierState.FETCHING

    # FETCHING -> COMPLETED (terminal)
    entry.transition_to(FrontierState.COMPLETED)
    assert entry.state == FrontierState.COMPLETED


def test_frontier_impossible_transitions_raise_error():
    """Verify illegal transitions are strictly rejected by the state machine."""
    # Terminal states cannot transition to anything
    entry_completed = FrontierEntry(url="https://example.com/1", state=FrontierState.COMPLETED)
    with pytest.raises(InvalidStateTransitionError):
        entry_completed.transition_to(FrontierState.QUEUED)

    with pytest.raises(InvalidStateTransitionError):
        entry_completed.transition_to(FrontierState.FETCHING)

    entry_failed = FrontierEntry(url="https://example.com/2", state=FrontierState.FAILED_FINAL)
    with pytest.raises(InvalidStateTransitionError):
        entry_failed.transition_to(FrontierState.FETCHING)

    entry_skipped = FrontierEntry(url="https://example.com/3", state=FrontierState.SKIPPED)
    with pytest.raises(InvalidStateTransitionError):
        entry_skipped.transition_to(FrontierState.COMPLETED)

    entry_dup = FrontierEntry(url="https://example.com/4", state=FrontierState.DUPLICATE)
    with pytest.raises(InvalidStateTransitionError):
        entry_dup.transition_to(FrontierState.QUEUED)

    # Non-terminal illegal transitions
    entry_disc = FrontierEntry(url="https://example.com/5", state=FrontierState.DISCOVERED)
    with pytest.raises(InvalidStateTransitionError):
        entry_disc.transition_to(FrontierState.COMPLETED)


def test_seed_urls_initialization():
    """Verify seed URLs are admitted, normalized, and placed into queue at depth 0."""
    frontier = CrawlFrontier(start_url="https://Example.Com:443/root#frag", max_urls=10)
    assert frontier.queue_size == 1
    assert frontier.total_discovered == 1

    entry = frontier.get_next()
    assert entry is not None
    assert entry.url == "https://example.com/root"
    assert entry.depth == 0
    assert entry.parent_url == ""
    assert entry.state == FrontierState.FETCHING
    assert frontier.active_workers == 1


def test_duplicate_scheduling_prevention():
    """Verify a normalized URL is never scheduled twice into the queue."""
    frontier = CrawlFrontier(start_url="https://example.com/", max_urls=10)
    seed = frontier.get_next()
    assert seed is not None
    frontier.mark_completed(seed.url)

    # Discovering the exact same URL multiple times from different pages
    new1 = frontier.discover(["https://example.com/", "https://example.com/#frag2"], parent_url="https://example.com/page1", parent_depth=1)
    new2 = frontier.discover(["https://example.com/"], parent_url="https://example.com/page2", parent_depth=2)

    assert len(new1) == 0
    assert len(new2) == 0
    assert frontier.queue_size == 0


def test_circular_and_self_links():
    """Verify circular links (A -> B -> A) and self-links (A -> A) do not cause duplicate scheduling."""
    frontier = CrawlFrontier(start_url="https://example.com/a", max_urls=10, max_depth=5)
    page_a = frontier.get_next()
    assert page_a is not None
    assert page_a.url == "https://example.com/a"

    # Self link: page A linking to page A
    frontier.discover(["https://example.com/a"], parent_url="https://example.com/a", parent_depth=0)
    assert frontier.queue_size == 0

    # A discovers B
    frontier.discover(["https://example.com/b"], parent_url="https://example.com/a", parent_depth=0)
    assert frontier.queue_size == 1
    frontier.mark_completed(page_a.url)

    # B discovers A
    page_b = frontier.get_next()
    assert page_b is not None
    assert page_b.url == "https://example.com/b"
    assert page_b.depth == 1
    assert page_b.parent_url == "https://example.com/a"

    new_from_b = frontier.discover(["https://example.com/a"], parent_url="https://example.com/b", parent_depth=1)
    assert len(new_from_b) == 0  # A is not scheduled again
    frontier.mark_completed(page_b.url)

    assert frontier.is_complete()


def test_domain_restriction_and_external_links():
    """Verify links pointing outside allowed host domains are recorded as SKIPPED, not QUEUED."""
    frontier = CrawlFrontier(start_url="https://owned.example/start", max_urls=10)
    seed = frontier.get_next()
    frontier.mark_completed(seed.url)

    frontier.discover(
        ["https://owned.example/internal", "https://external.com/outbound", "https://other.net/api"],
        parent_url=seed.url,
        parent_depth=0,
    )

    assert frontier.queue_size == 1  # only internal is queued
    internal = frontier.get_next()
    assert internal.url == "https://owned.example/internal"

    ledger = frontier.reconcile_accounting()
    assert ledger["skipped"] == 2  # both external domains skipped


def test_depth_limit_enforcement():
    """Verify URLs exceeding max_depth are recorded as SKIPPED with max_depth_exceeded."""
    frontier = CrawlFrontier(start_url="https://example.com/0", max_urls=20, max_depth=2)
    p0 = frontier.get_next()
    assert p0.depth == 0
    frontier.discover(["https://example.com/1"], parent_url=p0.url, parent_depth=0)
    frontier.mark_completed(p0.url)

    p1 = frontier.get_next()
    assert p1.depth == 1
    frontier.discover(["https://example.com/2"], parent_url=p1.url, parent_depth=1)
    frontier.mark_completed(p1.url)

    p2 = frontier.get_next()
    assert p2.depth == 2
    # At depth 2, discovering depth 3 must exceed max_depth=2
    newly = frontier.discover(["https://example.com/3"], parent_url=p2.url, parent_depth=2)
    assert len(newly) == 0  # Not queued
    frontier.mark_completed(p2.url)

    assert frontier.queue_size == 0
    assert frontier.is_complete()

    ledger = frontier.reconcile_accounting()
    assert ledger["completed"] == 3
    assert ledger["skipped"] == 1


def test_page_budget_limit_enforcement():
    """Verify frontier stops queueing items once max_urls budget is reached."""
    frontier = CrawlFrontier(start_url="https://example.com/start", max_urls=3)
    p1 = frontier.get_next()
    frontier.mark_completed(p1.url)

    # Discover 5 pages
    new_urls = [f"https://example.com/p{i}" for i in range(2, 7)]
    frontier.discover(new_urls, parent_url=p1.url, parent_depth=0)

    # Exactly 2 more pages admitted (3 total including start)
    assert frontier.queue_size == 2
    ledger = frontier.reconcile_accounting()
    # 1 completed, 2 queued, 3 skipped due to budget
    assert ledger["completed"] == 1
    assert ledger["queued"] == 2
    assert ledger["skipped"] == 3


def test_completion_detection_invariants():
    """Verify completion semantics: empty queue alone is NOT complete if workers are active or retries eligible."""
    frontier = CrawlFrontier(start_url="https://example.com/seed", max_urls=5)
    assert not frontier.is_complete()

    # Worker leases seed
    entry = frontier.get_next()
    assert entry is not None
    # Queue is now EMPTY, but worker is FETCHING: MUST NOT be complete!
    assert frontier.queue_size == 0
    assert frontier.active_workers == 1
    assert not frontier.is_complete()

    # Worker marks retryable failure
    frontier.mark_failed(entry.url, error="HTTP 429", is_retryable=True, retry_delay=0.1)
    # Queue is empty, active workers is 0, but retry pool has item: MUST NOT be complete!
    assert frontier.queue_size == 0
    assert frontier.active_workers == 0
    assert not frontier.is_complete()

    # Wait for backoff to expire
    time.sleep(0.12)
    # get_next() retrieves the retry item
    retry_entry = frontier.get_next()
    assert retry_entry is not None
    assert retry_entry.url == entry.url
    assert retry_entry.retry_count == 1
    assert not frontier.is_complete()

    # Complete the item
    frontier.mark_completed(retry_entry.url)
    # Now queue=0, active=0, retries=0 -> COMPLETE
    assert frontier.is_complete()


def test_canonical_and_redirect_deduplication():
    """Verify canonical tags and redirect targets are correctly deduplicated in frontier."""
    frontier = CrawlFrontier(start_url="https://example.com/main", max_urls=10)
    seed = frontier.get_next()
    frontier.mark_completed(seed.url)

    # Page 1 declares canonical as /main
    frontier.discover(["https://example.com/alias1"], parent_url=seed.url, parent_depth=0)
    alias_entry = frontier.get_next()
    is_dup = frontier.handle_canonical(alias_entry.url, "https://example.com/main")
    assert not is_dup  # First page declaring /main as canonical records it

    # Page 2 also declares canonical as /main
    frontier.discover(["https://example.com/alias2"], parent_url=seed.url, parent_depth=0)
    alias2_entry = frontier.get_next()
    is_dup2 = frontier.handle_canonical(alias2_entry.url, "https://example.com/main")
    assert is_dup2  # Duplicate detected!
    assert alias2_entry.state == FrontierState.DUPLICATE

    # Redirect handling
    frontier.discover(["https://example.com/old-url"], parent_url=seed.url, parent_depth=0)
    old_entry = frontier.get_next()
    norm_dest = frontier.handle_redirect(old_entry.url, "https://example.com/new-url", depth=1, parent_url=seed.url)
    assert norm_dest == "https://example.com/new-url"
    assert old_entry.state == FrontierState.COMPLETED
    assert frontier.queue_size == 1  # new-url is queued


def test_accounting_reconciliation():
    """Verify reconcile_accounting() mathematically accounts for all states and invariants."""
    frontier = CrawlFrontier(start_url="https://example.com/root", max_urls=10, max_depth=3)
    seed = frontier.get_next()
    frontier.mark_completed(seed.url)

    frontier.discover(
        [
            "https://example.com/ok",
            "https://example.com/will-fail",
            "https://external.org/out",
        ],
        parent_url=seed.url,
        parent_depth=0,
    )

    ok_item = frontier.get_next()
    frontier.mark_completed(ok_item.url)

    fail_item = frontier.get_next()
    frontier.mark_failed(fail_item.url, "404 Not Found", is_retryable=False)

    ledger = frontier.reconcile_accounting()
    assert ledger["discovered"] == 4
    assert ledger["completed"] == 2
    assert ledger["failed_final"] == 1
    assert ledger["skipped"] == 1
    assert ledger["queued"] == 0
    assert ledger["fetching"] == 0
    assert frontier.is_complete()
