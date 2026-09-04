from app.agentic import agentic_retrieve, plan_queries


def test_plan_queries_is_bounded_and_keeps_original_question() -> None:
    queries = plan_queries("What services are offered and what is the refund policy?", max_subqueries=3)
    assert queries[0] == "What services are offered and what is the refund policy?"
    assert len(queries) <= 3
    assert any("refund policy" in query.lower() for query in queries)


def test_agentic_retrieve_applies_source_diversity_and_keeps_multi_part_evidence() -> None:
    def search(crawl_id: str, query: str, limit: int) -> list[dict[str, object]]:
        if "refund" in query.lower():
            return [
                {"id": 1, "url": "https://owned.example/refunds", "chunk_index": 0, "content": "Refunds are available.", "hybrid_score": 0.9, "term_coverage": 1.0},
                {"id": 2, "url": "https://owned.example/refunds", "chunk_index": 1, "content": "Refunds are processed in five days.", "hybrid_score": 0.8, "term_coverage": 1.0},
            ]
        return [{"id": 3, "url": "https://owned.example/services", "chunk_index": 0, "content": "Audits are offered.", "hybrid_score": 0.7, "term_coverage": 1.0}]

    results = agentic_retrieve("crawl-1", "What services are offered and what is the refund policy?", search, limit=3)
    assert len(results) == 3
    assert {item["url"] for item in results} == {"https://owned.example/refunds", "https://owned.example/services"}
    assert all(item["source_diversity_applied"] is True for item in results)


def test_agentic_retrieve_marks_multi_hop_support() -> None:
    def search(crawl_id: str, query: str, limit: int) -> list[dict[str, object]]:
        if "refund" in query.lower():
            return [{"id": 7, "url": "https://owned.example/faq", "chunk_index": 0, "content": "Refunds are available within five days.", "hybrid_score": 0.8, "term_coverage": 1.0}]
        if "five days" in query.lower():
            return [{"id": 7, "url": "https://owned.example/faq", "chunk_index": 0, "content": "Refunds are available within five days.", "hybrid_score": 0.9, "term_coverage": 1.0}]
        return []

    results = agentic_retrieve("crawl-1", "What is the refund policy and how many days?", search, limit=3)
    assert results
    assert results[0]["evidence_set_role"] == "multi-hop"
    assert len(results[0]["hop_indexes"]) >= 2


def test_agentic_retrieve_deduplicates_and_preserves_best_provenance() -> None:
    calls: list[str] = []

    def search(crawl_id: str, query: str, limit: int) -> list[dict[str, object]]:
        calls.append(query)
        return [{"id": 1, "url": "https://owned.example/", "chunk_index": 0, "content": "Refunds are available.", "hybrid_score": 0.04}]

    results = agentic_retrieve("crawl-1", "What is the refund policy and what are the refund terms?", search)
    assert len(results) == 1
    assert results[0]["url"] == "https://owned.example/"
    assert results[0]["agentic_query"] in calls
