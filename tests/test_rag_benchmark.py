"""Comprehensive benchmark and evaluation test suite for Local SEO Spider.

Verifies the 14-point architectural overhaul:
 1. URL canonicalization + deduplication
 2. Proper JSON/API ingestion
 3. Hybrid retrieval: BM25 + dense embeddings
 4. Multi-factor reranking
 5. Claim-level evidence grounding
 6. Citation verification (PASS / PARTIAL / FAIL)
 7. Answer completeness checking
 8. Strict abstention
 9. Confidence recalibration
10. Conflict detection
11. Query-type routing
12. Benchmark/evaluation framework
13. Crawl coverage metrics
14. Secret/token redaction
"""

from __future__ import annotations

import json
from dataclasses import replace
import pytest

from app.analyzer import compute_crawl_coverage_metrics
from app.database import Database
from app.documents import extract_document_text, format_json_semantics
from app.knowledge import KnowledgeChunk, _chunks_from_json, deduplicate_chunks, infer_source_type
from app.qa import (
    analyze_query_semantics,
    answer_question,
    check_answer_completeness,
    classify_query_type,
    compute_calibrated_confidence,
    extract_claims,
    extract_numbers_from_text,
    plan_grounded_answer,
    verify_all_claims,
    verify_claim_against_passages,
)
from app.types import CrawlRequest, LinkRecord, PageRecord
from app.urltools import (
    canonicalize_url,
    detect_api_pagination,
    redact_secrets_in_text,
    redact_sensitive_url,
    resolve_canonical_url,
)


# =========================================================================
# 1. URL Canonicalization + Deduplication
# =========================================================================

def test_benchmark_canonicalization_and_deduplication() -> None:
    # Tracking parameters stripped and query params sorted
    url1 = "https://example.com/api/items?utm_source=twitter&b=2&utm_medium=cpc&a=1"
    url2 = "https://example.com/api/items?a=1&b=2"
    assert canonicalize_url(url1) == canonicalize_url(url2)
    assert canonicalize_url("https://example.com/docs//guide/") == "https://example.com/docs/guide"

    # Canonical URL resolution
    resolved = resolve_canonical_url("/canonical-page", "https://example.com/original-page?ref=home")
    assert resolved == "https://example.com/canonical-page"

    # Chunk deduplication across pages
    chunk_a = KnowledgeChunk("crawl-1", "p1", "https://example.com/p1", "Intro", "Shared paragraph.", "doc", 0)
    chunk_b = KnowledgeChunk("crawl-1", "p2", "https://example.com/p2", "Intro", "Shared paragraph.", "doc", 0)
    deduped = deduplicate_chunks([chunk_a, chunk_b])
    assert len(deduped) == 1
    assert deduped[0].url == "https://example.com/p1"


# =========================================================================
# 2. Proper JSON/API Ingestion (Word Count & Semantic Structure)
# =========================================================================

def test_benchmark_proper_json_api_ingestion() -> None:
    payload = {
        "total": 150,
        "limit": 30,
        "skip": 0,
        "todos": [
            {"id": 1, "todo": "Audit crawl pipeline", "completed": False, "userId": 26},
            {"id": 2, "todo": "Verify citation entailment", "completed": True, "userId": 42},
        ],
    }
    raw_json = json.dumps(payload).encode("utf-8")

    # Document text extraction parses JSON structure
    text, notes = extract_document_text("application/json", raw_json)
    assert "field = total, value = 150" in text
    assert "field = limit, value = 30" in text
    assert "Audit crawl pipeline" in text
    
    formatted_text = format_json_semantics(payload)
    assert "field = total, value = 150" in formatted_text
    assert "field = limit, value = 30" in formatted_text

    # Ensure rendered word count is non-zero
    word_count = len(text.split())
    assert word_count >= 15

    # Knowledge chunk generation for JSON creates structured field chunks
    page_rec = PageRecord(
        url="https://example.com/api/todos", final_url="https://example.com/api/todos",
        status_code=200, content_type="application/json", title="Todos API", description="",
        headings={}, canonical="https://example.com/api/todos", meta_robots="", x_robots="",
        source_html=raw_json.decode("utf-8"), rendered_html="", rendered_text=text,
        images=[], structured_data=[], redirect_chain=[], content_hash="hash_api",
        discovered_at="2026-01-01T00:00:00Z", source_type="official_api",
    )
    chunks = _chunks_from_json(page_rec, "crawl-1")
    assert len(chunks) >= 2
    assert any("field = total, value = 150" in c.content for c in chunks)
    assert any("Audit crawl pipeline" in c.content for c in chunks)


# =========================================================================
# 3. Hybrid Retrieval & Reranking
# =========================================================================

def test_benchmark_hybrid_retrieval_and_reranking(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    db.initialize()
    req = CrawlRequest(start_url="https://example.com/", mode="site", max_urls=10, delay_seconds=0.1, respect_nofollow=True, acknowledgment=True)
    crawl_id = db.create_crawl(req)
    db.update_crawl(crawl_id, status="completed")

    pages = [
        PageRecord(
            url="https://example.com/api/data", final_url="https://example.com/api/data",
            status_code=200, content_type="application/json", title="API", description="",
            headings={}, canonical="https://example.com/api/data", meta_robots="", x_robots="",
            source_html="{}", rendered_html="", rendered_text="field = total, value = 250",
            images=[], structured_data=[], redirect_chain=[], content_hash="h1",
            discovered_at="2026-01-01T00:00:00Z", source_type="official_api",
        ),
        PageRecord(
            url="https://example.com/blog/general", final_url="https://example.com/blog/general",
            status_code=200, content_type="text/html", title="Blog", description="",
            headings={}, canonical="https://example.com/blog/general", meta_robots="", x_robots="",
            source_html="<html></html>", rendered_html="<html></html>", rendered_text="Our general blog discussion.",
            images=[], structured_data=[], redirect_chain=[], content_hash="h2",
            discovered_at="2026-01-01T00:00:00Z", source_type="html_page",
        ),
    ]
    db.replace_pages_and_links(crawl_id, pages, [])
    stored = db.get_pages(crawl_id)
    p1_id = stored[0]["id"]
    p2_id = stored[1]["id"]

    chunks = [
        KnowledgeChunk(
            page_id=p1_id, crawl_id=crawl_id, url="https://example.com/api/data",
            title="API Summary", heading_path="API Summary",
            content="field = total, value = 250\nfield = limit, value = 50\nfield = skip, value = 0",
            chunk_index=0, canonical_url="https://example.com/api/data", section="json_fields",
            source_type="official_api", content_type="application/json",
        ),
        KnowledgeChunk(
            page_id=p2_id, crawl_id=crawl_id, url="https://example.com/blog/general",
            title="Overview", heading_path="Overview",
            content="Our general blog discussion about web auditing and optimization standards.",
            chunk_index=0, canonical_url="https://example.com/blog/general", section="content",
            source_type="html_page", content_type="text/html",
        ),
        KnowledgeChunk(
            page_id=p2_id, crawl_id=crawl_id, url="https://example.com/blog/general",
            title="Overview", heading_path="Section 2",
            content="More general talking points without numerical values.",
            chunk_index=1, canonical_url="https://example.com/blog/general", section="content",
            source_type="html_page", content_type="text/html",
        ),
    ]
    db.replace_knowledge_chunks(crawl_id, chunks)

    # Hybrid search for structured numerical query should prioritize official_api chunk
    results = db.search_hybrid_knowledge(crawl_id, "what is the total and limit?", limit=5)
    assert len(results) >= 1
    top = results[0]
    assert top["url"] == "https://example.com/api/data"
    assert "field = total, value = 250" in top["content"]
    assert top.get("source_type") == "official_api"
    assert top.get("hybrid_score", 0.0) > 0.0


# =========================================================================
# 4. Claim-Level Evidence Grounding & 5. Citation Verification
# =========================================================================

def test_benchmark_claim_level_evidence_grounding_and_citation_verifier() -> None:
    passages = [
        {"url": "https://example.com/pricing", "heading_path": "Plans", "content": "The Starter plan costs nineteen dollars per month with five users included."},
        {"url": "https://example.com/terms", "heading_path": "Refunds", "content": "Refund requests are accepted within fourteen days of initial purchase."},
    ]

    # Valid entailment -> PASS
    v_pass = verify_claim_against_passages(
        {"claim_text": "The Starter plan costs nineteen dollars per month with five users [1].", "citations": [1], "is_empirical": True},
        passages,
    )
    assert v_pass["verdict"] == "PASS"
    assert v_pass["grounded"] is True

    # Hallucinated number -> FAIL
    v_num_fail = verify_claim_against_passages(
        {"claim_text": "The Starter plan costs forty-nine dollars per month [1].", "citations": [1], "is_empirical": True},
        passages,
    )
    assert v_num_fail["verdict"] == "FAIL"
    assert v_num_fail["status"] == "unsupported_number"

    # Hallucinated entity -> FAIL
    v_entity_fail = verify_claim_against_passages(
        {"claim_text": "The Starter plan includes unmetered GPU compute clusters and Kubernetes hosting [1].", "citations": [1], "is_empirical": True},
        passages,
    )
    assert v_entity_fail["verdict"] == "FAIL"
    assert v_entity_fail["status"] == "unsupported_terms"

    # Full answer verification rejects partially or fully unsupported outputs
    answer_with_hallucination = "The Starter plan costs nineteen dollars per month [1]. It also provides dedicated quantum servers [1]."
    verified = verify_all_claims(answer_with_hallucination, passages)
    assert verified["all_grounded"] is False
    assert verified["grounding_rate"] < 1.0


# =========================================================================
# 6. Answer Completeness Checking
# =========================================================================

def test_benchmark_answer_completeness_checking() -> None:
    query_semantics = analyze_query_semantics("what is the total count, skip, and limit?")
    assert "total" in query_semantics["requested_slots"]
    assert "limit" in query_semantics["requested_slots"]
    assert "skip" in query_semantics["requested_slots"]

    passages = [
        {"url": "https://example.com/api", "content": "field = total, value = 100\nfield = limit, value = 20"},
    ]
    completeness = check_answer_completeness(query_semantics, passages)
    assert completeness["is_complete"] is False
    assert "skip" in completeness["missing_slots"]
    assert "total" in completeness["covered_slots"]
    assert completeness["completeness_rate"] < 1.0


# =========================================================================
# 7. Strict Abstention & 8. Confidence Recalibration
# =========================================================================

def test_benchmark_strict_abstention_and_confidence_recalibration() -> None:
    # 1. Total lack of matching evidence
    abstention = answer_question("crawl-1", "What is the return policy for outer space colonies?", lambda *_: [])
    assert abstention["grounded"] is False
    assert abstention["confidence"] == 0.0
    assert "couldn't verify that from the crawled sources" in abstention["answer"].lower()

    # 2. Similarity without answer bearing content (e.g. phone number asked, only general hours retrieved)
    passages = [{
        "url": "https://example.com/support",
        "heading_path": "Support",
        "content": "Our support center is open from 9am to 5pm Monday through Friday.",
        "vector_similarity": 0.88,
        "term_coverage": 0.35,
    }]
    no_answer = answer_question("crawl-1", "What is the support telephone phone number?", lambda *_: passages)
    assert no_answer["grounded"] is False
    assert no_answer["confidence"] == 0.0
    assert no_answer["citations"] == []

    # 3. Confidence recalibration caps incomplete answers at <= 0.50
    semantics = analyze_query_semantics("what is the total and limit?")
    incomplete = {"is_complete": False, "missing_slots": ["limit"], "completeness_rate": 0.5}
    ev = [{"content": "field = total, value = 50", "is_answer_bearing": True, "vector_similarity": 0.9}]
    conf = compute_calibrated_confidence(semantics, ev, [], completeness=incomplete)
    assert conf <= 0.50


# =========================================================================
# 9. Conflict Detection
# =========================================================================

def test_benchmark_conflict_detection() -> None:
    conflicting_passages = [
        {"url": "https://example.com/page1", "heading_path": "Refunds", "content": "Refunds are available for all customers within 30 days."},
        {"url": "https://example.com/page2", "heading_path": "Refunds", "content": "Items are strictly non-refundable with no refunds offered."},
    ]
    result = answer_question("crawl-1", "Are refunds available?", lambda *_: conflicting_passages)
    assert result["grounded"] is False
    assert result["confidence"] == 0.0
    assert "conflicting statements" in result["answer"].lower()


# =========================================================================
# 10. Query-Type Routing
# =========================================================================

def test_benchmark_query_type_routing() -> None:
    # Exact phrase query
    q1 = classify_query_type('"all items must be returned in original packaging"')
    assert q1["query_type"] == "exact_phrase"
    assert q1["exact_phrases"] == ["all items must be returned in original packaging"]

    # Numerical / structured query
    q2 = classify_query_type("how many total items and what is the limit?")
    assert q2["query_type"] == "numerical_structured"
    assert "total" in q2["requested_slots"]
    assert "limit" in q2["requested_slots"]

    # Comparative query
    q3 = classify_query_type("compare basic plan vs premium plan difference")
    assert q3["query_type"] == "comparative"

    # Factoid / definition query
    q4 = classify_query_type("what is canonical URL tag?")
    assert q4["query_type"] == "factoid_definition"


# =========================================================================
# 11. Secret & Token Redaction
# =========================================================================

def test_benchmark_secret_token_redaction() -> None:
    # Sensitive URL query parameters
    url = "https://api.example.com/v1/data?token=eyJhbGciOiJIUzI1NiJ9.test&api_key=supersecret99&page=2"
    redacted_url = redact_sensitive_url(url)
    assert "supersecret99" not in redacted_url
    assert "token=%5BREDACTED%5D" in redacted_url or "token=[REDACTED]" in redacted_url
    assert "page=2" in redacted_url

    # In-text secret tokens (OpenAI, AWS, JWT)
    text = "Here is the key sk-1234567890abcdef1234567890abcdef and AWS AKIAIOSFODNN7EXAMPLE for access."
    redacted_text = redact_secrets_in_text(text)
    assert "sk-1234567890abcdef1234567890abcdef" not in redacted_text
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted_text
    assert "[REDACTED]" in redacted_text


# =========================================================================
# 12. Crawl Coverage Metrics & Duplicate Tracking
# =========================================================================

def test_benchmark_crawl_coverage_metrics(tmp_path) -> None:
    pages = [
        PageRecord(
            url="https://example.com/", final_url="https://example.com/", status_code=200, content_type="text/html",
            title="Home", description="Home page", headings={"h1": ["Home"]}, canonical="https://example.com/",
            meta_robots="", x_robots="", source_html="<html></html>", rendered_html="<html></html>",
            rendered_text="Welcome to the main homepage with plenty of descriptive content for visitors.",
            images=[], structured_data=[], redirect_chain=[], content_hash="hash1", discovered_at="2026-01-01T00:00:00Z",
            is_duplicate=False, source_type="html_page",
        ),
        PageRecord(
            url="https://example.com/api/items", final_url="https://example.com/api/items", status_code=200, content_type="application/json",
            title="Items API", description="", headings={}, canonical="https://example.com/api/items",
            meta_robots="", x_robots="", source_html="{}", rendered_html="",
            rendered_text="field = total, value = 50 field = limit, value = 10",
            images=[], structured_data=[], redirect_chain=[], content_hash="hash2", discovered_at="2026-01-01T00:00:00Z",
            is_duplicate=False, source_type="official_api",
        ),
        PageRecord(
            url="https://example.com/mirror", final_url="https://example.com/mirror", status_code=200, content_type="text/html",
            title="Mirror", description="", headings={}, canonical="https://example.com/",
            meta_robots="", x_robots="", source_html="<html></html>", rendered_html="<html></html>",
            rendered_text="Welcome to the main homepage with plenty of descriptive content for visitors.",
            images=[], structured_data=[], redirect_chain=[], content_hash="hash1", discovered_at="2026-01-01T00:00:00Z",
            is_duplicate=True, duplicate_of="https://example.com/", source_type="html_page",
        ),
    ]
    links = [
        LinkRecord("https://example.com/", "https://example.com/api/items", "api", "API", "", True, False),
        LinkRecord("https://example.com/", "https://example.com/mirror", "mirror", "Mirror", "", True, False),
        LinkRecord("https://example.com/", "https://example.com/unvisited", "unvisited", "Unvisited", "", True, False),
    ]

    metrics = compute_crawl_coverage_metrics(pages, links)
    assert metrics["total_crawled_urls"] == 3
    assert metrics["total_discovered_urls"] == 4  # 3 crawled + 1 unvisited link
    assert metrics["crawl_coverage_rate"] == 0.75
    assert metrics["duplicates_detected"] == 1
    assert metrics["api_endpoints_indexed"] == 1
    assert metrics["status_code_distribution"].get("200") == 3
    assert "text/html" in metrics["content_type_distribution"]
    assert "application/json" in metrics["content_type_distribution"]
    assert metrics["average_word_count"] > 0

    # Test Database.get_crawl_coverage
    db = Database(tmp_path / "test_metrics.db")
    db.initialize()
    req = CrawlRequest(start_url="https://example.com/", mode="site", max_urls=10, delay_seconds=0.1, respect_nofollow=True, acknowledgment=True)
    crawl_id = db.create_crawl(req)
    db.replace_pages_and_links(crawl_id, pages, links)
    db_metrics = db.get_crawl_coverage(crawl_id)
    assert db_metrics["total_crawled_urls"] == 3
    assert db_metrics["total_discovered_urls"] == 4
    assert db_metrics["crawl_coverage_rate"] == 0.75
    assert db_metrics["duplicates_detected"] == 1
    assert db_metrics["api_endpoints_indexed"] == 1
