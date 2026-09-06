"""Tests for Phase 2G.2: Pipeline Decoupling, Status Tracking & Re-Indexability.

Verifies:
1. Pipeline Model: Independent stage tracking across crawl, storage, extraction, chunking, embedding, indexing, rag.
2. Critical Rule: Embedding API failure NEVER destroys a successful crawl (pages, links, issues 100% durable).
3. Fault Isolation: Lexical chunks committed before vector embedding.
4. Partial Indexing: Provider failure midway leaves successful vectors intact and records failed chunks with retryable=True.
5. Rate Limit (429): Classified as retryable.
6. Content Hashing: Unchanged chunks with identical model/dimension skip embedding; model change forces re-embedding.
7. Model/Dimension Change Detection: detect_embedding_generation_mismatch identifies mismatch and requires reindex.
8. Retry Workflow: retry_failed_embeddings only embeds failed chunks without recrawling or re-embedding successful chunks.
9. Retry Failure: Increments attempt_count while preserving existing vectors.
10. Observability: GET /crawls/{crawl_id}/pipeline and POST /crawls/{crawl_id}/pipeline/retry-embedding.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.database import Database, now
from app.embeddings import EmbeddingProvider, HashEmbeddingProvider
from app.knowledge import KnowledgeChunk
from app.main import app
from app.types import (
    CrawlRequest,
    IssueRecord,
    LinkRecord,
    PageRecord,
    PipelineStage,
    StageStatus,
)


def _seed_durable_crawl(db: Database, crawl_id: str) -> tuple[int, PageRecord, LinkRecord, IssueRecord]:
    """Helper to seed a durable crawl with pages, links, and issues."""
    request = CrawlRequest(
        start_url="https://example.com",
        mode="site",
        url_list=[],
        max_urls=10,
        delay_seconds=0.1,
        respect_nofollow=True,
        acknowledgment=True,
        crawl_id=crawl_id,
    )
    db.create_crawl(request)
    db.update_crawl(crawl_id, status="completed", pages_crawled=1, issues_found=1)

    page = PageRecord(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        content_type="text/html",
        title="Example Title",
        description="Example Description",
        headings={"h1": ["Main Heading"]},
        canonical="",
        meta_robots="",
        x_robots="",
        source_html="<html><body><h1>Main Heading</h1><p>This is example page text with relevant information.</p></body></html>",
        rendered_html="",
        rendered_text="This is example page text with relevant information.",
        extracted_text="This is example page text with relevant information.",
        images=[],
        structured_data=[],
        redirect_chain=[],
        discovered_at="2026-09-06T12:00:00Z",
        content_hash="pagehash123",
    )
    link = LinkRecord(
        source_url="https://example.com",
        target_url="https://example.com/about",
        raw_target_url="/about",
        anchor_text="About",
        rel="",
        is_internal=True,
        nofollow=False,
    )
    issue = IssueRecord(
        rule_key="title_length",
        severity="info",
        title="Title Length Optimal",
        url="https://example.com",
        evidence="Title is 13 chars",
        remediation="None needed",
        fingerprint="fp123",
    )

    db.replace_pages_and_links(crawl_id, [page], [link])
    db.replace_issues(crawl_id, [issue])

    with db.connect() as conn:
        row = conn.execute("SELECT id FROM pages WHERE crawl_id = ?", (crawl_id,)).fetchone()
        page_id = row["id"]

    return page_id, page, link, issue


class MockFailingProvider(HashEmbeddingProvider):
    """Embedding provider that can be configured to fail or raise 429."""

    def __init__(self, dimension: int = 64, fail_mode: str = "always", fail_after: int = 0):
        super().__init__(dimension=dimension)
        self.fail_mode = fail_mode
        self.fail_after = fail_after
        self.call_count = 0
        self.batch_size = 2

    def embed_batch(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
        self.call_count += len(texts)
        if self.fail_mode == "always":
            raise RuntimeError("Provider connection failed: Service Unavailable")
        elif self.fail_mode == "429":
            raise RuntimeError("HTTP 429: Rate limit exceeded. Try again in 60s.")
        elif self.fail_mode == "after_n":
            if self.call_count > self.fail_after:
                raise RuntimeError(f"Midway failure: Process crashed after {self.fail_after} items")
            return [self.embed(t, task_type) for t in texts]
        return [self.embed(t, task_type) for t in texts]


# ---------------------------------------------------------------------------
# Test 1: Provider unavailable before indexing
# ---------------------------------------------------------------------------

def test_provider_unavailable_before_indexing_preserves_crawl(tmp_path: Path) -> None:
    """Verify raw crawl data remains 100% intact when embedding provider fails before indexing."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    crawl_id = "crawl-provider-down"
    page_id, page, link, issue = _seed_durable_crawl(db, crawl_id)

    # Record crawl and storage stages as SUCCESS
    db.update_pipeline_stage(crawl_id, PipelineStage.CRAWL, StageStatus.SUCCESS, total_items=1, successful_items=1)
    db.update_pipeline_stage(crawl_id, PipelineStage.STORAGE, StageStatus.SUCCESS, total_items=2, successful_items=2)

    chunk = KnowledgeChunk(
        page_id=page_id,
        crawl_id=crawl_id,
        url="https://example.com",
        title="Example Title",
        heading_path="Main Heading",
        content="This is chunk content.",
        chunk_index=0,
        content_hash="chunkhash1",
    )

    failing_provider = MockFailingProvider(fail_mode="always")
    res = db.index_knowledge_pipeline(crawl_id, [chunk], embedder=failing_provider)

    # Indexing status reports failed with retryable flag
    assert res["status"] == StageStatus.FAILED.value
    assert res["failed_items"] == 1
    assert res["successful_items"] == 0

    # Pipeline stages reflect exact forensic truth
    pipeline = db.get_pipeline_status(crawl_id)
    assert pipeline["stages"]["crawl"]["status"] == StageStatus.SUCCESS.value
    assert pipeline["stages"]["storage"]["status"] == StageStatus.SUCCESS.value
    assert pipeline["stages"]["extraction"]["status"] == StageStatus.SUCCESS.value
    assert pipeline["stages"]["chunking"]["status"] == StageStatus.SUCCESS.value
    assert pipeline["stages"]["embedding"]["status"] == StageStatus.FAILED.value
    assert pipeline["stages"]["indexing"]["status"] == StageStatus.FAILED.value

    # Critical Rule: Raw crawl data (pages, links, issues) is 100% intact
    pages = db.get_pages(crawl_id)
    assert len(pages) == 1
    assert pages[0]["url"] == "https://example.com"

    links = db.get_links(crawl_id)
    assert len(links) == 1
    assert links[0]["target_url"] == "https://example.com/about"

    issues = db.get_issues(crawl_id)
    assert len(issues) == 1

    # Lexical chunks and FTS are 100% intact and searchable!
    chunks = db.get_knowledge_chunks(crawl_id)
    assert len(chunks) == 1
    lexical_matches = db.search_knowledge(crawl_id, "chunk content")
    assert len(lexical_matches) == 1

    # Failed chunk was recorded for retry
    with db.connect() as conn:
        failed = conn.execute("SELECT * FROM failed_embedding_chunks WHERE crawl_id = ?", (crawl_id,)).fetchall()
        assert len(failed) == 1
        assert failed[0]["chunk_id"] == chunks[0]["id"]
        assert failed[0]["retryable"] == 1


# ---------------------------------------------------------------------------
# Test 2: Provider fails midway through chunk batch
# ---------------------------------------------------------------------------

def test_provider_fails_midway_records_partial_and_failed_chunks(tmp_path: Path) -> None:
    """Verify provider failure midway through chunks leaves successful vectors intact and marks stage PARTIAL."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    crawl_id = "crawl-midway-fail"
    page_id, _, _, _ = _seed_durable_crawl(db, crawl_id)

    chunks = [
        KnowledgeChunk(
            page_id=page_id, crawl_id=crawl_id, url=f"https://example.com/p{i}",
            title=f"Page {i}", heading_path="H", content=f"Content for chunk {i}",
            chunk_index=i, content_hash=f"hash{i}",
        )
        for i in range(4)
    ]

    # Batch size is 2; first batch (2 chunks) succeeds, second batch fails
    failing_provider = MockFailingProvider(fail_mode="after_n", fail_after=2)
    failing_provider.batch_size = 2

    res = db.index_knowledge_pipeline(crawl_id, chunks, embedder=failing_provider)

    assert res["status"] == StageStatus.PARTIAL.value
    assert res["successful_items"] == 2
    assert res["failed_items"] == 2

    pipeline = db.get_pipeline_status(crawl_id)
    assert pipeline["stages"]["embedding"]["status"] == StageStatus.PARTIAL.value
    assert pipeline["stages"]["embedding"]["successful_items"] == 2
    assert pipeline["stages"]["embedding"]["failed_items"] == 2
    assert pipeline["stages"]["indexing"]["status"] == StageStatus.PARTIAL.value

    # First 2 vectors exist in vector_embeddings
    with db.connect() as conn:
        vecs = conn.execute("SELECT * FROM vector_embeddings WHERE crawl_id = ?", (crawl_id,)).fetchall()
        assert len(vecs) == 2
        failed = conn.execute("SELECT * FROM failed_embedding_chunks WHERE crawl_id = ?", (crawl_id,)).fetchall()
        assert len(failed) == 2


# ---------------------------------------------------------------------------
# Test 3: Rate limit (429) midway through chunk batch
# ---------------------------------------------------------------------------

def test_rate_limit_429_classified_as_retryable(tmp_path: Path) -> None:
    """Verify HTTP 429 is classified as retryable in pipeline stage and failed_embedding_chunks."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    crawl_id = "crawl-429"
    page_id, _, _, _ = _seed_durable_crawl(db, crawl_id)

    chunks = [
        KnowledgeChunk(
            page_id=page_id, crawl_id=crawl_id, url=f"https://example.com/p{i}",
            title=f"Page {i}", heading_path="H", content=f"Content for chunk {i}",
            chunk_index=i, content_hash=f"hash429_{i}",
        )
        for i in range(2)
    ]

    provider_429 = MockFailingProvider(fail_mode="429")
    res = db.index_knowledge_pipeline(crawl_id, chunks, embedder=provider_429)

    assert res["status"] == StageStatus.FAILED.value
    assert res["retryable"] is True
    assert "429" in res["error_message"]

    pipeline = db.get_pipeline_status(crawl_id)
    assert pipeline["stages"]["embedding"]["retryable"] is True
    assert pipeline["stages"]["indexing"]["retryable"] is True

    with db.connect() as conn:
        failed = conn.execute("SELECT * FROM failed_embedding_chunks WHERE crawl_id = ?", (crawl_id,)).fetchall()
        assert len(failed) == 2
        assert all(r["retryable"] == 1 for r in failed)


# ---------------------------------------------------------------------------
# Test 4: Content hashing skip logic & restart recovery
# ---------------------------------------------------------------------------

def test_content_hashing_skips_unchanged_chunks_on_restart(tmp_path: Path) -> None:
    """Verify unchanged chunks with identical content_hash and model/dimension are skipped during re-index."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    crawl_id = "crawl-content-hash"
    page_id, _, _, _ = _seed_durable_crawl(db, crawl_id)

    chunks = [
        KnowledgeChunk(
            page_id=page_id, crawl_id=crawl_id, url=f"https://example.com/p{i}",
            title=f"Page {i}", heading_path="H", content=f"Content for chunk {i}",
            chunk_index=i, content_hash=f"hash_{i}",
        )
        for i in range(4)
    ]

    # First run: embed with working provider
    embedder = HashEmbeddingProvider(dimension=64)
    res1 = db.index_knowledge_pipeline(crawl_id, chunks, embedder=embedder)
    assert res1["status"] == StageStatus.SUCCESS.value
    assert res1["successful_items"] == 4

    # Second run without force_reembed: all 4 chunks should be detected as unchanged and skipped!
    mock_embedder = MagicMock(wraps=HashEmbeddingProvider(dimension=64))
    mock_embedder.dimension = 64
    mock_embedder.name = "hash"
    mock_embedder.model_name = "hash"
    mock_embedder.provider_type = "hash"
    mock_embedder.batch_size = 100

    res2 = db.index_knowledge_pipeline(crawl_id, chunks, embedder=mock_embedder, force_reembed=False)
    assert res2["status"] == StageStatus.SUCCESS.value
    assert res2["skipped_unchanged"] == 4
    # embed_batch was NOT called because all 4 chunks were already embedded!
    mock_embedder.embed_batch.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5: Model changed after partial index
# ---------------------------------------------------------------------------

def test_model_change_detected_and_reembeds_without_mixing(tmp_path: Path) -> None:
    """Verify model change is detected and forces re-embedding even if text hash is unchanged."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    crawl_id = "crawl-model-change"
    page_id, _, _, _ = _seed_durable_crawl(db, crawl_id)

    chunks = [
        KnowledgeChunk(
            page_id=page_id, crawl_id=crawl_id, url="https://example.com",
            title="Title", heading_path="H", content="Content text",
            chunk_index=0, content_hash="samehash",
        )
    ]

    # Index with Model A (hash 64)
    model_a = HashEmbeddingProvider(dimension=64)
    db.index_knowledge_pipeline(crawl_id, chunks, embedder=model_a)

    # Configure Model B (hash 128)
    model_b = HashEmbeddingProvider(dimension=128)
    mismatch = db.detect_embedding_generation_mismatch(crawl_id, model_b)

    assert mismatch["mismatch"] is True
    assert mismatch["requires_reindex"] is True
    assert mismatch["existing"]["dimension"] == 64
    assert mismatch["requested"]["dimension"] == 128

    # Re-embed with Model B
    reembed_res = db.reembed_knowledge(crawl_id, model_b)
    assert reembed_res["chunks_embedded"] == 1
    assert reembed_res["dimension"] == 128

    # Verify vector search with Model B isolates Model B vectors
    search_res = db.search_hybrid_knowledge(crawl_id, "Content", limit=5, embedder=model_b)
    assert len(search_res) >= 1

    # And vector search with Model A returns lexical without mixing incompatible dimensions
    search_res_a = db.search_hybrid_knowledge(crawl_id, "Content", limit=5, embedder=model_a)
    assert len(search_res_a) >= 1


# ---------------------------------------------------------------------------
# Test 6: Retry succeeds
# ---------------------------------------------------------------------------

def test_retry_succeeds_for_failed_chunks(tmp_path: Path) -> None:
    """Verify retry_failed_embeddings embeds only failed chunks and transitions stage to SUCCESS."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    crawl_id = "crawl-retry-success"
    page_id, _, _, _ = _seed_durable_crawl(db, crawl_id)

    chunks = [
        KnowledgeChunk(
            page_id=page_id, crawl_id=crawl_id, url=f"https://example.com/p{i}",
            title=f"Page {i}", heading_path="H", content=f"Content for chunk {i}",
            chunk_index=i, content_hash=f"retry_hash_{i}",
        )
        for i in range(4)
    ]

    # Initial indexing: first 2 succeed, next 2 fail
    failing_provider = MockFailingProvider(fail_mode="after_n", fail_after=2)
    failing_provider.batch_size = 2
    res = db.index_knowledge_pipeline(crawl_id, chunks, embedder=failing_provider)
    assert res["status"] == StageStatus.PARTIAL.value

    # Verify 2 failed chunks
    status_before = db.get_pipeline_status(crawl_id)
    assert status_before["failed_chunks_count"] == 2
    assert status_before["stages"]["embedding"]["status"] == StageStatus.PARTIAL.value

    # Working provider retries the failed chunks
    working_provider = HashEmbeddingProvider(dimension=64)
    retry_res = db.retry_failed_embeddings(crawl_id, working_provider)

    assert retry_res["retried"] == 2
    assert retry_res["succeeded"] == 2
    assert retry_res["remaining_failed"] == 0
    assert retry_res["status"] == StageStatus.SUCCESS.value

    # Pipeline stages transitioned to SUCCESS
    status_after = db.get_pipeline_status(crawl_id)
    assert status_after["failed_chunks_count"] == 0
    assert status_after["stages"]["embedding"]["status"] == StageStatus.SUCCESS.value
    assert status_after["stages"]["embedding"]["successful_items"] == 4
    assert status_after["stages"]["embedding"]["failed_items"] == 0
    assert status_after["stages"]["indexing"]["status"] == StageStatus.SUCCESS.value

    # All 4 vectors now exist in vector_embeddings
    with db.connect() as conn:
        vecs = conn.execute("SELECT * FROM vector_embeddings WHERE crawl_id = ?", (crawl_id,)).fetchall()
        assert len(vecs) == 4


# ---------------------------------------------------------------------------
# Test 7: Retry fails
# ---------------------------------------------------------------------------

def test_retry_fails_increments_attempt_count_and_preserves_vectors(tmp_path: Path) -> None:
    """Verify failed retry increments attempt_count and leaves existing vectors intact."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    crawl_id = "crawl-retry-fail"
    page_id, _, _, _ = _seed_durable_crawl(db, crawl_id)

    chunks = [
        KnowledgeChunk(
            page_id=page_id, crawl_id=crawl_id, url=f"https://example.com/p{i}",
            title=f"Page {i}", heading_path="H", content=f"Content for chunk {i}",
            chunk_index=i, content_hash=f"retry_fail_hash_{i}",
        )
        for i in range(2)
    ]

    failing_provider = MockFailingProvider(fail_mode="always")
    db.index_knowledge_pipeline(crawl_id, chunks, embedder=failing_provider)

    # First attempt: attempt_count = 1
    with db.connect() as conn:
        failed1 = conn.execute("SELECT attempt_count FROM failed_embedding_chunks WHERE crawl_id = ?", (crawl_id,)).fetchall()
        assert all(r["attempt_count"] == 1 for r in failed1)

    # Retry fails again
    retry_res = db.retry_failed_embeddings(crawl_id, failing_provider)
    assert retry_res["failed"] == 2
    assert retry_res["status"] == StageStatus.FAILED.value

    # Second attempt: attempt_count incremented to 2
    with db.connect() as conn:
        failed2 = conn.execute("SELECT attempt_count FROM failed_embedding_chunks WHERE crawl_id = ?", (crawl_id,)).fetchall()
        assert all(r["attempt_count"] == 2 for r in failed2)


# ---------------------------------------------------------------------------
# Test 8: Crawl data byte-for-byte durability across failures
# ---------------------------------------------------------------------------

def test_crawl_data_remains_100_percent_durable_across_all_failures(tmp_path: Path) -> None:
    """Verify pages, links, and issues are never modified or deleted by embedding/indexing failures."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    crawl_id = "crawl-durability"
    page_id, page, link, issue = _seed_durable_crawl(db, crawl_id)

    # Take snapshot of raw crawl data
    pages_snapshot = db.get_pages(crawl_id)
    links_snapshot = db.get_links(crawl_id)
    issues_snapshot = db.get_issues(crawl_id)

    # Trigger indexing failure
    chunk = KnowledgeChunk(
        page_id=page_id, crawl_id=crawl_id, url="https://example.com",
        title="Title", heading_path="H", content="Content",
        chunk_index=0, content_hash="hash",
    )
    failing = MockFailingProvider(fail_mode="always")
    db.index_knowledge_pipeline(crawl_id, [chunk], embedder=failing)

    # Trigger retry failure
    db.retry_failed_embeddings(crawl_id, failing)

    # Verify pages, links, and issues remain byte-for-byte identical
    current_pages = db.get_pages(crawl_id)
    current_links = db.get_links(crawl_id)
    current_issues = db.get_issues(crawl_id)

    assert current_pages == pages_snapshot
    assert current_links == links_snapshot
    assert current_issues == issues_snapshot


# ---------------------------------------------------------------------------
# Test 9: Observability API endpoints
# ---------------------------------------------------------------------------

def test_pipeline_api_endpoints(tmp_path: Path) -> None:
    """Verify GET /crawls/{crawl_id}/pipeline and POST /crawls/{crawl_id}/pipeline/retry-embedding."""
    from app import main

    # Use test db
    test_db = Database(tmp_path / "test_api.db")
    test_db.initialize()
    original_db = main.database
    main.database = test_db

    try:
        crawl_id = "crawl-api-test"
        page_id, _, _, _ = _seed_durable_crawl(test_db, crawl_id)

        # Set up stages
        test_db.update_pipeline_stage(crawl_id, PipelineStage.CRAWL, StageStatus.SUCCESS, total_items=1, successful_items=1)
        test_db.update_pipeline_stage(crawl_id, PipelineStage.STORAGE, StageStatus.SUCCESS, total_items=2, successful_items=2)
        test_db.update_pipeline_stage(crawl_id, PipelineStage.EXTRACTION, StageStatus.SUCCESS, total_items=1, successful_items=1)

        chunk = KnowledgeChunk(
            page_id=page_id, crawl_id=crawl_id, url="https://example.com",
            title="Title", heading_path="H", content="Content",
            chunk_index=0, content_hash="hash",
        )
        failing = MockFailingProvider(fail_mode="always")
        test_db.index_knowledge_pipeline(crawl_id, [chunk], embedder=failing)

        client = TestClient(app)

        # 1. GET pipeline status
        resp = client.get(f"/crawls/{crawl_id}/pipeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["crawl_id"] == crawl_id
        assert "stages" in data
        assert data["stages"]["crawl"]["status"] == "success"
        assert data["stages"]["storage"]["status"] == "success"
        assert data["stages"]["embedding"]["status"] == "failed"
        assert data["failed_chunks_count"] == 1
        assert "model_mismatch" in data

        # 2. POST retry-embedding
        retry_resp = client.post(f"/crawls/{crawl_id}/pipeline/retry-embedding")
        assert retry_resp.status_code == 200
        retry_data = retry_resp.json()
        assert "retried" in retry_data
        assert "pipeline" in retry_data
        assert retry_data["succeeded"] >= 1
        assert retry_data["pipeline"]["stages"]["embedding"]["status"] == "success"

        # 3. GET pipeline status after retry reflects success
        resp2 = client.get(f"/crawls/{crawl_id}/pipeline")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["stages"]["embedding"]["status"] == "success"
        assert data2["failed_chunks_count"] == 0
    finally:
        main.database = original_db


def test_dimension_change_after_partial_index(tmp_path: Path) -> None:
    """Verify dimension mismatch is flagged and isolated when dimension changes after partial index."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    crawl_id = "crawl-dim-change-partial"
    page_id, _, _, _ = _seed_durable_crawl(db, crawl_id)

    chunks = [
        KnowledgeChunk(
            page_id=page_id, crawl_id=crawl_id, url=f"https://example.com/p{i}",
            title=f"Page {i}", heading_path="H", content=f"Content for chunk {i}",
            chunk_index=i, content_hash=f"hash_dim_{i}",
        )
        for i in range(4)
    ]

    # Partial index with 64-dim model
    failing_64 = MockFailingProvider(dimension=64, fail_mode="after_n", fail_after=2)
    failing_64.batch_size = 2
    res = db.index_knowledge_pipeline(crawl_id, chunks, embedder=failing_64)
    assert res["status"] == StageStatus.PARTIAL.value

    # Check mismatch with 128-dim provider
    provider_128 = HashEmbeddingProvider(dimension=128)
    mismatch = db.detect_embedding_generation_mismatch(crawl_id, provider_128)
    assert mismatch["mismatch"] is True
    assert mismatch["requires_reindex"] is True
    assert mismatch["existing"]["dimension"] == 64
    assert mismatch["requested"]["dimension"] == 128

    # Re-indexing with 128-dim provider updates vectors cleanly
    reindex_res = db.index_knowledge_pipeline(crawl_id, chunks, embedder=provider_128, force_reembed=True)
    assert reindex_res["status"] == StageStatus.SUCCESS.value
    assert reindex_res["dimension"] == 128

    # Vector search with 128-dim works and does not mix with 64-dim
    search_res = db.search_hybrid_knowledge(crawl_id, "Content", limit=5, embedder=provider_128)
    assert len(search_res) >= 1


def test_model_change_forces_reembedding_of_identical_text(tmp_path: Path) -> None:
    """Verify that when the model changes, chunks are re-embedded even if text hash is unchanged."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    crawl_id = "crawl-model-reembed-identical"
    page_id, _, _, _ = _seed_durable_crawl(db, crawl_id)

    chunk = KnowledgeChunk(
        page_id=page_id, crawl_id=crawl_id, url="https://example.com",
        title="Title", heading_path="H", content="Identical Content",
        chunk_index=0, content_hash="same_exact_hash",
    )

    # Initial indexing with model "model_a"
    mock_model_a = MagicMock(wraps=HashEmbeddingProvider(dimension=64))
    mock_model_a.dimension = 64
    mock_model_a.name = "provider_a"
    mock_model_a.model_name = "model_a"
    mock_model_a.provider_type = "provider_a"
    mock_model_a.batch_size = 10

    res_a = db.index_knowledge_pipeline(crawl_id, [chunk], embedder=mock_model_a)
    assert res_a["status"] == StageStatus.SUCCESS.value
    assert mock_model_a.embed_batch.call_count == 1

    # Second indexing with model "model_b" and identical chunk content_hash
    mock_model_b = MagicMock(wraps=HashEmbeddingProvider(dimension=64))
    mock_model_b.dimension = 64
    mock_model_b.name = "provider_b"
    mock_model_b.model_name = "model_b"
    mock_model_b.provider_type = "provider_b"
    mock_model_b.batch_size = 10

    res_b = db.index_knowledge_pipeline(crawl_id, [chunk], embedder=mock_model_b, force_reembed=False)
    assert res_b["status"] == StageStatus.SUCCESS.value
    # Crucial assertion: embed_batch WAS called because model changed, even though text hash was identical!
    assert mock_model_b.embed_batch.call_count == 1
    assert res_b["skipped_unchanged"] == 0


def test_provider_type_vs_name_harmony_and_rag_retry_propagation(tmp_path: Path) -> None:
    """Verify provider_type vs name harmony, RAG stage retry propagation, and ghost chunk pruning."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    crawl_id = "crawl-provider-harmony"
    page_id, _, _, _ = _seed_durable_crawl(db, crawl_id)

    # 1. Provider with differing provider_type and name (like GeminiEmbeddingProvider)
    class GeminiMockProvider:
        provider_type = "google"
        model_name = "text-embedding-004"
        dimension = 64
        batch_size = 10

        @property
        def name(self) -> str:
            return "google:text-embedding-004"

        def embed(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
            base = HashEmbeddingProvider(dimension=64).embed(text)
            return base

        def embed_batch(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
            return [self.embed(t, task_type=task_type) for t in texts]

    gemini_mock = GeminiMockProvider()

    chunks_3 = [
        KnowledgeChunk(
            page_id=page_id, crawl_id=crawl_id, url="https://example.com",
            title="Title", heading_path="H", content=f"Distinct Content Chunk {i}",
            chunk_index=i, content_hash=f"hash_harmony_{i}",
        )
        for i in range(3)
    ]

    # Initial indexing with 3 chunks
    res = db.index_knowledge_pipeline(crawl_id, chunks_3, embedder=gemini_mock)
    assert res["status"] == StageStatus.SUCCESS.value
    assert res["successful_items"] == 3

    # Verification 1: detect_embedding_generation_mismatch recognizes identical provider/model/dimension
    mismatch_info = db.detect_embedding_generation_mismatch(crawl_id, gemini_mock)
    assert mismatch_info["mismatch"] is False
    assert mismatch_info["requires_reindex"] is False

    # Verification 2: search_hybrid_knowledge queries vector_embeddings successfully without provider mismatch
    search_res = db.search_hybrid_knowledge(crawl_id, "Distinct Content", limit=5, embedder=gemini_mock)
    assert len(search_res) >= 1

    # Verification 3: Prune stale ghost chunks when page chunks shrink from 3 to 1
    chunks_1 = [chunks_3[0]]
    res_prune = db.index_knowledge_pipeline(crawl_id, chunks_1, embedder=gemini_mock)
    assert res_prune["status"] == StageStatus.SUCCESS.value
    with db.connect() as conn:
        all_chunks = conn.execute("SELECT id, chunk_index FROM knowledge_chunks WHERE crawl_id = ?", (crawl_id,)).fetchall()
        assert len(all_chunks) == 1
        assert all_chunks[0]["chunk_index"] == 0

    # Verification 4: Simulate partial failure and verify retry propagates RAG stage to SUCCESS and clears pause_reason
    db.update_crawl(crawl_id, pause_reason="Degraded to lexical-first due to partial embedding index")
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO failed_embedding_chunks (
                   crawl_id, chunk_id, provider, model, dimension, attempt_count, last_error, retryable, failed_at
               ) VALUES (?, ?, ?, ?, ?, 1, 'Temporary HTTP 429', 1, ?)""",
            (crawl_id, all_chunks[0]["id"], gemini_mock.name, gemini_mock.model_name, gemini_mock.dimension, now()),
        )
    db.update_pipeline_stage(crawl_id, PipelineStage.EMBEDDING, StageStatus.PARTIAL, error_message="Rate limit")
    db.update_pipeline_stage(crawl_id, PipelineStage.INDEXING, StageStatus.PARTIAL, error_message="Rate limit")
    db.update_pipeline_stage(crawl_id, PipelineStage.RAG, StageStatus.PARTIAL, error_message="Degraded")

    retry_res = db.retry_failed_embeddings(crawl_id, gemini_mock)
    assert retry_res["status"] == StageStatus.SUCCESS.value
    assert retry_res["remaining_failed"] == 0

    # RAG stage MUST now be SUCCESS and pause_reason MUST be cleared
    rag_stage = db.get_pipeline_stage(crawl_id, PipelineStage.RAG)
    assert rag_stage is not None
    assert rag_stage["status"] == StageStatus.SUCCESS.value
    crawl_rec = db.get_crawl(crawl_id)
    assert crawl_rec is not None
    assert crawl_rec.get("pause_reason") == ""


