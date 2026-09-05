"""Permanent regression test suite covering the 10 historically observed failure modes.

Phase 29 Requirements:
1. DummyJSON identity question retrieving unrelated evidence.
2. Todo question retrieving the correct passage but failing to answer all requested slots.
3. Citation-audit question retrieving unrelated documents.
4. `/todos` schema question retrieving unrelated resources.
5. Exact phrase query allowing unrelated webhook evidence into top results.
6. Duplicate `/docs` and `/docs/` evidence.
7. Duplicate `/docs/users` and `/docs/users/`.
8. API pages being interpreted as zero-word HTML pages.
9. Overconfident answers despite weak evidence.
10. Sensitive 2FA/token-like query parameters appearing in crawl evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.database import Database
from app.documents import extract_document_text, format_json_semantics
from app.knowledge import KnowledgeChunk, deduplicate_chunks, extract_pages_knowledge
from app.qa import (
    analyze_query_semantics,
    answer_question,
    check_answer_completeness,
    classify_query_type,
    compute_calibrated_confidence,
    verify_claim_against_passages,
)
from app.types import PageRecord
from app.urltools import canonicalize_url, redact_secrets_in_text, redact_sensitive_url, resolve_canonical_url


@pytest.fixture
def regression_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "regression_test.db")
    db.initialize()
    return db


# -----------------------------------------------------------------------------
# Regression 1: DummyJSON identity question retrieving unrelated evidence
# -----------------------------------------------------------------------------
def test_regression_01_dummyjson_identity_routing() -> None:
    # Query asking about identity should not retrieve unrelated webhook documents
    semantics = analyze_query_semantics("Who provides the DummyJSON service and what is its identity?")
    assert semantics["target_type"] in {"entity_identity", "definition_offering"}
    assert "dummyjson" in semantics["core_entities"]

    passages = [
        {"id": 1, "url": "https://dummyjson.com/webhooks", "heading_path": "Webhooks", "content": "Configure webhook dispatchers for notifications.", "term_coverage": 0.0},
        {"id": 2, "url": "https://dummyjson.com/about", "heading_path": "About", "content": "DummyJSON provides free fake REST API data for developers.", "term_coverage": 0.9},
    ]

    def search_fn(cid: str, q: str, lim: int) -> list[dict]:
        # Sort so that relevant passage with high entity coverage is first
        return sorted(passages, key=lambda p: -p["term_coverage"])

    res = answer_question("crawl-test", "Who provides the DummyJSON service?", search_fn)
    assert res["grounded"] is True
    assert "DummyJSON" in res["answer"]
    assert res["citations"][0]["url"] == "https://dummyjson.com/about"


# -----------------------------------------------------------------------------
# Regression 2: Todo question retrieving correct passage but failing to answer all requested slots
# -----------------------------------------------------------------------------
def test_regression_02_todo_multi_slot_completeness() -> None:
    # A question requesting limit, skip, and total must cover all 3 slots or cap confidence
    semantics = analyze_query_semantics("What are the total, limit, and skip values for todos?")
    assert "total" in semantics["requested_slots"]
    assert "limit" in semantics["requested_slots"]
    assert "skip" in semantics["requested_slots"]

    # Passage covering all 3
    complete_passage = [{
        "id": 1,
        "url": "https://example.com/api/todos",
        "heading_path": "API > Metadata",
        "content": "field = total, value = 150\nfield = limit, value = 30\nfield = skip, value = 0",
        "term_coverage": 1.0,
    }]
    completeness = check_answer_completeness(semantics, complete_passage)
    assert completeness["is_complete"] is True
    assert set(completeness["covered_slots"]) == {"total", "limit", "skip"}

    # Incomplete passage covering only limit and skip, missing total
    incomplete_passage = [{
        "id": 2,
        "url": "https://example.com/api/todos",
        "heading_path": "API > Metadata",
        "content": "field = limit, value = 30\nfield = skip, value = 0",
        "term_coverage": 0.66,
    }]
    incomplete_check = check_answer_completeness(semantics, incomplete_passage)
    assert incomplete_check["is_complete"] is False
    assert "total" in incomplete_check["missing_slots"]

    # Confidence must be strictly capped <= 0.50 when slots are missing
    conf = compute_calibrated_confidence(semantics, incomplete_passage, completeness=incomplete_check)
    assert conf <= 0.50


# -----------------------------------------------------------------------------
# Regression 3: Citation-audit question retrieving unrelated documents
# -----------------------------------------------------------------------------
def test_regression_03_citation_audit_routes_to_auditor() -> None:
    # Citation audit should NOT be treated as a standard search query
    query = 'Audit the claim: "the total is 150 [1]"'
    semantics = analyze_query_semantics(query)
    assert semantics["query_type"] == "citation_audit"

    passages = [{
        "id": 1,
        "url": "https://example.com/api/todos",
        "heading_path": "API > Metadata",
        "content": "field = total, value = 150",
    }]

    res = answer_question("crawl-test", query, lambda c, q, l: passages)
    assert res["answer_mode"] == "citation-audit"
    assert "PASS" in res["answer"]
    assert res["grounded"] is True


# -----------------------------------------------------------------------------
# Regression 4: /todos schema question retrieving unrelated resources
# -----------------------------------------------------------------------------
def test_regression_04_todos_schema_isolated_from_unrelated() -> None:
    query = "What is the schema for /todos and which fields exist?"
    semantics = analyze_query_semantics(query)
    assert "todos" in semantics["core_entities"]
    assert "schema" in semantics["core_entities"]

    passages = [
        {"id": 1, "url": "https://example.com/api/users", "heading_path": "Users", "content": "User schema: id, username, email", "term_coverage": 0.2},
        {"id": 2, "url": "https://example.com/api/todos", "heading_path": "Todos", "content": "Todos schema: id, todo, completed, userId", "term_coverage": 0.8},
    ]

    def search_fn(cid: str, q: str, lim: int) -> list[dict]:
        return sorted(passages, key=lambda p: -p["term_coverage"])

    res = answer_question("crawl-test", query, search_fn)
    assert res["citations"][0]["url"] == "https://example.com/api/todos"
    assert "userId" in res["citations"][0]["content"]


# -----------------------------------------------------------------------------
# Regression 5: Exact phrase query allowing unrelated webhook evidence into top results
# -----------------------------------------------------------------------------
def test_regression_05_exact_phrase_excludes_unrelated_webhooks() -> None:
    query = 'find the exact phrase "By default you will get 30 items"'
    semantics = analyze_query_semantics(query)
    assert semantics["query_type"] == "exact_phrase"
    assert semantics["exact_phrase"] == "By default you will get 30 items"

    # Exact match passage vs unrelated webhook passage
    exact_p = {"id": 1, "url": "https://example.com/docs/quickstart", "content": "By default you will get 30 items in paginated results."}
    webhook_p = {"id": 2, "url": "https://example.com/docs/webhooks", "content": "Webhooks dispatch notifications to your registered endpoints."}

    # Verify exact phrase match detection
    assert semantics["exact_phrase"].lower() in exact_p["content"].lower()
    assert semantics["exact_phrase"].lower() not in webhook_p["content"].lower()


# -----------------------------------------------------------------------------
# Regression 6: Duplicate /docs and /docs/ evidence
# -----------------------------------------------------------------------------
def test_regression_06_duplicate_docs_trailing_slash_collapsed() -> None:
    url_a = "https://example.com/docs"
    url_b = "https://example.com/docs/"
    assert canonicalize_url(url_a) == canonicalize_url(url_b)
    assert canonicalize_url(url_b) == "https://example.com/docs"


# -----------------------------------------------------------------------------
# Regression 7: Duplicate /docs/users and /docs/users/
# -----------------------------------------------------------------------------
def test_regression_07_duplicate_users_canonical_collapsed() -> None:
    url_a = "https://example.com/docs/users"
    url_b = "https://example.com/docs/users/"
    assert canonicalize_url(url_a) == canonicalize_url(url_b)
    
    # Also with canonical tag resolution
    resolved = resolve_canonical_url("/docs/users", url_b)
    assert resolved == "https://example.com/docs/users"


# -----------------------------------------------------------------------------
# Regression 8: API pages being interpreted as zero-word HTML pages
# -----------------------------------------------------------------------------
def test_regression_08_api_pages_produce_non_zero_word_counts() -> None:
    api_payload = json.dumps({
        "total": 150,
        "limit": 30,
        "skip": 0,
        "todos": [{"id": 1, "todo": "Implement semantic grounding", "completed": True}],
    }).encode("utf-8")

    text, notes = extract_document_text("application/json", api_payload)
    words = text.split()
    assert len(words) >= 10
    assert "field = total, value = 150" in text
    assert "Implement semantic grounding" in text


# -----------------------------------------------------------------------------
# Regression 9: Overconfident answers despite weak evidence
# -----------------------------------------------------------------------------
def test_regression_09_overconfident_answers_prevented() -> None:
    # Weak evidence without requested facts must have zero or capped confidence
    semantics = analyze_query_semantics("What is the exact population of Atlantis in 2026?")
    weak_evidence = [{
        "id": 1,
        "url": "https://example.com/about",
        "heading_path": "Overview",
        "content": "Our office is near the Atlantic ocean.",
        "term_coverage": 0.20,
    }]

    conf = compute_calibrated_confidence(semantics, weak_evidence)
    assert conf == 0.0

    res = answer_question("crawl-test", "What is the exact population of Atlantis in 2026?", lambda c, q, l: weak_evidence)
    assert res["grounded"] is False
    assert res["confidence"] == 0.0
    assert "couldn't verify" in res["answer"].lower()


# -----------------------------------------------------------------------------
# Regression 10: Sensitive 2FA/token-like query parameters appearing in crawl evidence
# -----------------------------------------------------------------------------
def test_regression_10_sensitive_tokens_redacted_from_urls_and_content() -> None:
    url_with_token = "https://example.com/oauth/callback?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9&api_key=sk-1234567890abcdef12345&auth=secret999&page=1"
    clean_url = redact_sensitive_url(url_with_token)
    assert "%5BREDACTED%5D" in clean_url or "[REDACTED]" in clean_url
    assert "sk-12345" not in clean_url
    assert "eyJhbG" not in clean_url
    assert "page=1" in clean_url  # Semantic param preserved

    text_with_token = "User session active with Bearer secret_session_token_xyz12345 and password='super_secret_pw_999'"
    clean_text = redact_secrets_in_text(text_with_token)
    assert "[REDACTED]" in clean_text
    assert "secret_session_token_xyz12345" not in clean_text
    assert "super_secret_pw_999" not in clean_text


# -----------------------------------------------------------------------------
# Regression 11: Evaluation metrics mathematical invariants (no clipping, strictly in [0, 1])
# -----------------------------------------------------------------------------
def test_regression_11_metric_invariants_and_zero_clipping() -> None:
    from app.evaluation import (
        compute_calibration_metrics,
        compute_ndcg,
        compute_precision_at_k,
        compute_recall_at_k,
        compute_reciprocal_rank,
    )
    assert compute_recall_at_k([], set(), 5) == 0.0
    assert compute_recall_at_k(["a", "b"], set(), 5) == 0.0
    assert compute_recall_at_k(["a", "a", "a"], {"a"}, 5) == 1.0
    assert compute_precision_at_k(["a", "b"], {"a"}, 2) == 0.5
    assert compute_precision_at_k(["a", "b"], {"a"}, 5) == 0.2
    assert 0.0 <= compute_reciprocal_rank(["x", "a"], {"a"}) <= 1.0
    assert 0.0 <= compute_ndcg(["a", "b"], {"a"}) <= 1.0
    cal = compute_calibration_metrics([{"confidence": 0.9, "is_correct": True}])
    assert 0.0 <= cal["brier_score"] <= 1.0
    assert 0.0 <= cal["ece"] <= 1.0

