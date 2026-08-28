"""Focused tests for the durable single-worker local crawl-job ledger."""

from app.database import Database
from app.types import CrawlRequest


def approved_request() -> CrawlRequest:
    return CrawlRequest(
        start_url="https://owned.example/", mode="list", url_list=["https://owned.example/"],
        max_urls=1, delay_seconds=0.1, respect_nofollow=True, acknowledgment=True,
    )


def test_local_job_ledger_claims_one_job_then_defers_pauses_and_resumes(tmp_path) -> None:
    database = Database(tmp_path / "local.sqlite3")
    database.initialize()
    crawl_id = database.create_crawl(approved_request())

    queued = database.get_crawl(crawl_id)
    assert queued and queued["status"] == "queued" and queued["attempts"] == 0
    assert database.get_crawl_request(crawl_id) == approved_request()

    claimed = database.claim_next_job()
    assert claimed and claimed["id"] == crawl_id and claimed["status"] == "running"
    assert claimed["attempts"] == 1
    assert database.claim_next_job() is None

    retryable = database.defer_or_pause_job(crawl_id, "Temporary worker error")
    assert retryable and retryable["status"] == "retryable"
    assert retryable["next_run_at"] and "Retry scheduled" in retryable["pause_reason"]

    paused = database.pause_job(crawl_id)
    assert paused and paused["status"] == "paused"
    assert database.claim_next_job() is None

    resumed = database.resume_job(crawl_id)
    assert resumed and resumed["status"] == "queued" and resumed["attempts"] == 0


def test_interrupted_and_repeated_worker_failures_enter_recoverable_states(tmp_path) -> None:
    database = Database(tmp_path / "local.sqlite3")
    database.initialize()
    crawl_id = database.create_crawl(approved_request())

    claimed = database.claim_next_job()
    assert claimed and claimed["status"] == "running"
    assert database.recover_interrupted_jobs() == 1
    recovered = database.get_crawl(crawl_id)
    assert recovered and recovered["status"] == "retryable"

    database.update_crawl(crawl_id, status="running", attempts=3)
    paused = database.defer_or_pause_job(crawl_id, "Repeated local worker error")
    assert paused and paused["status"] == "paused"
    assert "Circuit breaker opened" in paused["pause_reason"]
