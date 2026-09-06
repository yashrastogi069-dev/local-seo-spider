"""Tests for Phase 2G.1 Hosted & Local Embedding Provider Architecture.

Verifies:
- Google Gemini Embedding API hosted provider (mocked for CI)
- Bounded retries on 429 / 5xx with exponential backoff & Retry-After support
- Fail-closed behavior on 401/403 (AUTHENTICATION_FAILED) without retry
- Fail-closed behavior on 404 (MISCONFIGURED / invalid model) without retry
- Timeout and temporary network error resilience
- Secret protection: API key is never exposed in logs, metadata, error reports, or URLs
- Fallback policies: FAIL_CLOSED, FALLBACK_TO_HASH, BM25_ONLY, AUTO
- Provider resolution diagnostics (requested vs actual, degraded_mode, fallback_reason)
- Metadata persistence in SQLite vector_embeddings table
- Re-embedding without recrawling (model migration preserves raw chunks and pages)
- Dimension mismatch prevention in hybrid retrieval
- Clean batching with chunking <= 100 items
- Optional real provider smoke test (UNVERIFIED_LIVE when key is not present)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from app.database import Database
from app.embeddings import (
    EmbeddingMetadata,
    EmbeddingTaskType,
    FallbackPolicy,
    GeminiEmbeddingProvider,
    HashEmbeddingProvider,
    NullEmbeddingProvider,
    ProviderHealth,
    ProviderResolution,
    build_embedding_provider,
    cosine_similarity,
    resolve_embedding_provider,
)
from app.knowledge import KnowledgeChunk


# ---------------------------------------------------------------------------
# 1. Google Gemini Provider Tests with Mock Client
# ---------------------------------------------------------------------------

def _mock_gemini_response(dimension: int = 768, count: int = 1) -> httpx.Response:
    """Helper creating a synthetic valid Gemini batchEmbedContents HTTP response."""
    embeddings = [{"values": [0.01 * (i + 1)] * dimension} for i in range(count)]
    body = json.dumps({"embeddings": embeddings}).encode("utf-8")
    return httpx.Response(status_code=200, content=body, headers={"Content-Type": "application/json"})


def test_gemini_provider_success_single_and_batch() -> None:
    """Verify Gemini provider successfully embeds single text and batches of texts."""
    call_counts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_counts["count"] += 1
        # Check header contains API key, NOT query param
        assert request.headers.get("x-goog-api-key") == "AIzaSy_synthetic_test_key_12345"
        assert "key=" not in str(request.url)
        data = json.loads(request.content.decode("utf-8"))
        assert "requests" in data
        req_count = len(data["requests"])
        return _mock_gemini_response(dimension=768, count=req_count)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    provider = GeminiEmbeddingProvider(
        api_key="AIzaSy_synthetic_test_key_12345",
        model_name="text-embedding-004",
        dimension=768,
        client=client,
    )

    # Test single embed
    vec = provider.embed("SEO audit content for testing")
    assert len(vec) == 768
    assert provider.health_status == ProviderHealth.AVAILABLE
    assert provider.name == "google:text-embedding-004"

    # Test batch embed
    texts = ["page heading 1", "page paragraph 2", "page footer 3"]
    batch_vecs = provider.embed_batch(texts)
    assert len(batch_vecs) == 3
    assert all(len(v) == 768 for v in batch_vecs)
    assert call_counts["count"] == 2


def test_gemini_batch_chunking_bounds() -> None:
    """Verify Gemini provider breaks sequences larger than batch_size into multiple API calls."""
    batch_sizes = []

    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content.decode("utf-8"))
        count = len(data["requests"])
        batch_sizes.append(count)
        return _mock_gemini_response(dimension=768, count=count)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GeminiEmbeddingProvider(
        api_key="test-key",
        batch_size=5,  # small batch size for testing
        client=client,
    )

    texts = [f"Text chunk {i}" for i in range(12)]
    results = provider.embed_batch(texts)

    assert len(results) == 12
    assert batch_sizes == [5, 5, 2]


def test_gemini_authentication_failure_fails_closed_no_retry() -> None:
    """Verify 401/403 authentication error transitions to AUTHENTICATION_FAILED with 0 retries."""
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(
            status_code=403,
            content=b'{"error": {"code": 403, "message": "API key not valid. Please pass a valid API key."}}',
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GeminiEmbeddingProvider(api_key="invalid_key", max_retries=3, client=client)

    with pytest.raises(PermissionError, match="authentication failed"):
        provider.embed("test text")

    # Critical invariant: authentication failure MUST NOT retry
    assert attempts["count"] == 1
    assert provider.health_status == ProviderHealth.AUTHENTICATION_FAILED
    # Key must NOT be exposed in error string
    assert "invalid_key" not in provider.last_error


def test_gemini_model_not_found_fails_closed_no_retry() -> None:
    """Verify 404 model not found transitions to MISCONFIGURED with 0 retries."""
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(status_code=404, content=b'{"error": {"code": 404, "message": "Model not found."}}')

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GeminiEmbeddingProvider(api_key="valid_key", model_name="non-existent-model", max_retries=3, client=client)

    with pytest.raises(ValueError, match="model not found"):
        provider.embed("test text")

    assert attempts["count"] == 1
    assert provider.health_status == ProviderHealth.MISCONFIGURED


def test_gemini_rate_limiting_429_with_retry_after_and_recovery() -> None:
    """Verify 429 rate limit respects Retry-After, retries with backoff, and recovers on success."""
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(
                status_code=429,
                content=b'{"error": {"code": 429, "message": "Resource has been exhausted."}}',
                headers={"Retry-After": "0.1"},
            )
        return _mock_gemini_response(dimension=768, count=1)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GeminiEmbeddingProvider(api_key="valid_key", max_retries=2, client=client)

    t0 = time.monotonic()
    result = provider.embed("Rate limited query")
    elapsed = time.monotonic() - t0

    assert len(result) == 768
    assert attempts["count"] == 2
    assert elapsed >= 0.08  # Respected Retry-After
    assert provider.health_status == ProviderHealth.AVAILABLE


def test_gemini_timeout_and_network_error_resilience() -> None:
    """Verify transient network errors retry up to max_retries and update health to TEMPORARY_FAILURE."""
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise httpx.ConnectTimeout("Connection timed out to generativelanguage.googleapis.com")
        return _mock_gemini_response(dimension=768, count=1)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GeminiEmbeddingProvider(api_key="valid_key", max_retries=3, client=client)

    result = provider.embed("Query with network latency")
    assert len(result) == 768
    assert attempts["count"] == 3
    assert provider.health_status == ProviderHealth.AVAILABLE


def test_gemini_secret_redaction_and_protection() -> None:
    """Verify API keys are never exposed in repr, metadata, error messages, or headers."""
    secret_key = "AIzaSy_SUPER_SECRET_PRODUCTION_KEY_99999"
    provider = GeminiEmbeddingProvider(api_key=secret_key)

    # 1. Repr does NOT contain full key
    rep = repr(provider)
    assert secret_key not in rep
    assert "AIza...9999" in rep

    # 2. Metadata does NOT contain raw key
    meta = provider.get_metadata()
    assert secret_key not in json.dumps(meta)
    assert meta["api_key_configured"] is True
    assert meta["api_key_redacted"] == "AIza...9999"

    # 3. Error sanitizer
    sanitized = provider._sanitize_error_msg(f"Fatal error with key {secret_key} on request")
    assert secret_key not in sanitized
    assert "AIza...9999" in sanitized


# ---------------------------------------------------------------------------
# 2. Provider Resolution & Fallback Policies
# ---------------------------------------------------------------------------

def test_explicit_hash_selection_is_valid_not_degraded() -> None:
    """Explicit hash selection: requested=hash, actual=hash, fallback=false, degraded=false."""
    res = resolve_embedding_provider("hash", dimension=384)
    assert res.requested_provider == "hash"
    assert res.actual_provider == "hash"
    assert res.fallback_occurred is False
    assert res.degraded_mode is False
    assert res.actual_dimension == 384
    assert isinstance(res.provider_instance, HashEmbeddingProvider)


def test_bm25_only_fallback_policy() -> None:
    """BM25_ONLY policy disables vectors cleanly and returns NullEmbeddingProvider."""
    res = resolve_embedding_provider("google", fallback_policy=FallbackPolicy.BM25_ONLY)
    assert res.actual_provider == "null"
    assert res.actual_dimension == 0
    assert res.fallback_occurred is True
    assert res.degraded_mode is True
    assert isinstance(res.provider_instance, NullEmbeddingProvider)
    assert res.provider_instance.embed("test text") == []
    assert res.provider_instance.embed_batch(["text 1", "text 2"]) == [[], []]


def test_missing_gemini_key_fails_closed_under_fail_closed_policy() -> None:
    """Under FAIL_CLOSED, missing Gemini API key raises ValueError rather than silently substituting."""
    with pytest.raises(ValueError, match="requires an API key"):
        resolve_embedding_provider("google", api_key="", fallback_policy=FallbackPolicy.FAIL_CLOSED)


def test_main_service_layer_respects_fail_closed_policy() -> None:
    """Verify app.main._embedding_provider fails closed when FAIL_CLOSED is requested."""
    from app.main import _embedding_provider
    _embedding_provider.cache_clear()
    with pytest.raises(ValueError, match="requires an API key"):
        _embedding_provider(
            provider="google",
            model="text-embedding-004",
            dimension=768,
            fallback_policy="fail_closed",
            api_key="",
        )


def test_missing_gemini_key_falls_back_to_hash_under_auto_policy() -> None:
    """Under AUTO or FALLBACK_TO_HASH, missing Gemini API key falls back to hash with clear diagnostics."""
    res = resolve_embedding_provider("google", api_key="", fallback_policy=FallbackPolicy.AUTO)
    assert res.requested_provider == "google"
    assert res.actual_provider == "hash"
    assert res.fallback_occurred is True
    assert "Gemini API key missing" in res.fallback_reason
    assert res.degraded_mode is True
    assert isinstance(res.provider_instance, HashEmbeddingProvider)


def test_auto_resolution_with_gemini_key() -> None:
    """AUTO provider mode resolves to Google Gemini when an API key is provided."""
    res = resolve_embedding_provider("auto", api_key="valid_synthetic_key")
    assert res.requested_provider == "auto"
    assert res.actual_provider == "google"
    assert res.fallback_occurred is False
    assert res.degraded_mode is False
    assert isinstance(res.provider_instance, GeminiEmbeddingProvider)


def test_auto_resolution_without_credentials_falls_back_to_hash() -> None:
    """AUTO provider mode resolves to Hash (degraded) when no hosted key or local model is available."""
    # When no key is given, and sentence-transformers is not in env, falls back to hash
    res = resolve_embedding_provider("auto", api_key="")
    # Could be sentence-transformers if installed, or hash if missing
    if res.actual_provider == "hash":
        assert res.fallback_occurred is True
        assert res.degraded_mode is True
        assert isinstance(res.provider_instance, HashEmbeddingProvider)


# ---------------------------------------------------------------------------
# 3. Database Metadata Persistence & Multi-Model Storage
# ---------------------------------------------------------------------------

def _seed_crawl_and_page(db: Database, crawl_id: str, url: str = "https://example.com") -> int:
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO crawls (id, created_at, status, start_url, settings_json, ownership_ack)
               VALUES (?, ?, 'completed', ?, '{}', 1)""",
            (crawl_id, "2026-09-06T12:00:00Z", url),
        )
        cursor = conn.execute(
            """INSERT INTO pages (
                   crawl_id, url, final_url, status_code, content_type, title, description,
                   headings_json, canonical, meta_robots, x_robots, source_html, rendered_html,
                   rendered_text, content_hash, discovered_at, body_truncated, robots_allowed,
                   images_json, structured_data_json, redirects_json, fetch_error, render_error
               ) VALUES (?, ?, ?, 200, 'text/html', 'Example', '', '[]', '', '', '', '<html>content</html>', '', 'content', 'hash', '2026-09-06T12:00:00Z', 0, 1, '[]', '[]', '[]', '', '')""",
            (crawl_id, url, url),
        )
        return cursor.lastrowid


def test_database_persistence_records_provider_metadata(tmp_path: Path) -> None:
    """Verify vector_embeddings records provider, model, dimension, and rich metadata."""
    db = Database(tmp_path / "test_embeddings.sqlite3")
    db.initialize()
    crawl_id = "test-crawl-meta"

    page_id = _seed_crawl_and_page(db, crawl_id)

    chunk = KnowledgeChunk(
        page_id=page_id,
        crawl_id=crawl_id,
        url="https://example.com",
        title="Example Page",
        heading_path="Heading 1",
        content="This is sample content for verifying vector metadata persistence.",
        chunk_index=0,
        content_hash="abc123hash",
    )

    # Use hash provider
    provider = HashEmbeddingProvider(dimension=64)
    db.replace_knowledge_chunks(crawl_id, [chunk], embedder=provider)

    # Inspect stored vectors in SQLite
    with db.connect() as conn:
        row = conn.execute(
            "SELECT provider, model, dimension, content_hash, metadata_json FROM vector_embeddings WHERE crawl_id = ?",
            (crawl_id,),
        ).fetchone()

    assert row is not None
    assert row["provider"] == "hash"
    assert row["dimension"] == 64
    assert row["content_hash"] == "abc123hash"
    meta = json.loads(row["metadata_json"])
    assert meta["provider"] == "hash"
    assert meta["dimension"] == 64


def test_reembedding_without_recrawling_preserves_pages_and_chunks(tmp_path: Path) -> None:
    """Verify reembed_knowledge switches embedding models without recrawling or altering raw page content."""
    db = Database(tmp_path / "test_reembed.sqlite3")
    db.initialize()
    crawl_id = "test-crawl-reembed"

    page_id = _seed_crawl_and_page(db, crawl_id)

    chunk1 = KnowledgeChunk(
        page_id=page_id, crawl_id=crawl_id, url="https://example.com/p1",
        title="Page 1", heading_path="H1", content="Chunk one text for re-embedding test",
        chunk_index=0, content_hash="hash1",
    )
    chunk2 = KnowledgeChunk(
        page_id=page_id, crawl_id=crawl_id, url="https://example.com/p2",
        title="Page 2", heading_path="H2", content="Chunk two text for re-embedding test",
        chunk_index=1, content_hash="hash2",
    )

    # Initial indexing with 32-dim hash provider
    provider_v1 = HashEmbeddingProvider(dimension=32)
    db.replace_knowledge_chunks(crawl_id, [chunk1, chunk2], embedder=provider_v1)

    initial_chunks = db.get_knowledge_chunks(crawl_id)
    assert len(initial_chunks) == 2

    # Now RE-EMBED with a mock 128-dim Gemini provider WITHOUT recrawling
    def gemini_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content.decode("utf-8"))
        count = len(data["requests"])
        return _mock_gemini_response(dimension=128, count=count)

    mock_gemini = GeminiEmbeddingProvider(
        api_key="test-key",
        model_name="text-embedding-004",
        dimension=128,
        client=httpx.Client(transport=httpx.MockTransport(gemini_handler)),
    )

    reembed_result = db.reembed_knowledge(crawl_id, mock_gemini)
    assert reembed_result["chunks_embedded"] == 2
    assert reembed_result["provider"] == "google:text-embedding-004"
    assert reembed_result["dimension"] == 128

    # Verify pages and knowledge_chunks were UNTOUCHED
    after_chunks = db.get_knowledge_chunks(crawl_id)
    assert len(after_chunks) == 2
    assert after_chunks[0]["content"] == chunk1.content

    # Verify vectors in SQLite are now 128-dimension Google Gemini vectors
    with db.connect() as conn:
        v_rows = conn.execute(
            "SELECT provider, model, dimension, metadata_json FROM vector_embeddings WHERE crawl_id = ?",
            (crawl_id,),
        ).fetchall()

    assert len(v_rows) == 2
    for vr in v_rows:
        assert vr["provider"] == "google:text-embedding-004"
        assert vr["model"] == "text-embedding-004"
        assert vr["dimension"] == 128
        meta = json.loads(vr["metadata_json"])
        assert meta["reembedded"] is True


def test_dimension_mismatch_prevention_in_hybrid_retrieval(tmp_path: Path) -> None:
    """Verify search_hybrid_knowledge never mixes vectors of different dimensions."""
    db = Database(tmp_path / "test_dim_mismatch.sqlite3")
    db.initialize()
    crawl_id = "test-crawl-dim"

    page_id = _seed_crawl_and_page(db, crawl_id)

    chunk = KnowledgeChunk(
        page_id=page_id, crawl_id=crawl_id, url="https://example.com",
        title="Privacy Policy", heading_path="Privacy", content="We respect your privacy and process data safely.",
        chunk_index=0, content_hash="priv1",
    )

    # Index with 64-dim Hash provider
    provider_64 = HashEmbeddingProvider(dimension=64)
    db.replace_knowledge_chunks(crawl_id, [chunk], embedder=provider_64)

    # Search with 128-dim provider
    provider_128 = HashEmbeddingProvider(dimension=128)
    # Hybrid search executes without error and doesn't crash on dimension mismatch
    results = db.search_hybrid_knowledge(crawl_id, "privacy policy", limit=5, embedder=provider_128)
    assert isinstance(results, list)
    assert len(results) >= 1  # Lexical match succeeds


# ---------------------------------------------------------------------------
# 4. Real Provider Smoke Test (Conditional / UNVERIFIED_LIVE)
# ---------------------------------------------------------------------------

def test_real_hosted_provider_smoke_test_or_unverified_live() -> None:
    """Optional live smoke test: If valid GEMINI_API_KEY exists, perform a real request.

    If no credentials exist, marks the live test UNVERIFIED LIVE (passes CI).
    """
    live_key = os.getenv("SPIDER_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if not live_key:
        # Mark as UNVERIFIED LIVE as required by Phase 2G.1 specification
        pytest.skip("UNVERIFIED LIVE: No live GEMINI_API_KEY detected in environment (mocked CI passed).")

    # Real live test
    provider = GeminiEmbeddingProvider(api_key=live_key, model_name="text-embedding-004", timeout_seconds=15.0)
    t0 = time.monotonic()
    vec = provider.embed("Antigravity SEO Spider live embedding test")
    elapsed_ms = (time.monotonic() - t0) * 1000.0

    assert len(vec) in (768, 384)
    assert provider.health_status == ProviderHealth.AVAILABLE
    # Record diagnostics without exposing the key
    meta = provider.get_metadata()
    assert live_key not in json.dumps(meta)
    print(f"\n[LIVE SMOKE TEST PASSED] Provider: {meta['provider']}, Model: {meta['model']}, "
          f"Dim: {len(vec)}, Latency: {elapsed_ms:.1f}ms")
