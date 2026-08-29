from app.agentic import agentic_retrieve, plan_queries


def test_plan_queries_is_bounded_and_keeps_original_question() -> None:
    queries = plan_queries("What services are offered and what is the refund policy?", max_subqueries=3)
    assert queries[0] == "What services are offered and what is the refund policy?"
    assert len(queries) <= 3
    assert any("refund policy" in query.lower() for query in queries)


def test_agentic_retrieve_deduplicates_and_preserves_best_provenance() -> None:
    calls: list[str] = []

    def search(crawl_id: str, query: str, limit: int) -> list[dict[str, object]]:
        calls.append(query)
        return [{"id": 1, "url": "https://owned.example/", "chunk_index": 0, "content": "Refunds are available.", "hybrid_score": 0.04}]

    results = agentic_retrieve("crawl-1", "What is the refund policy and what are the refund terms?", search)
    assert len(results) == 1
    assert results[0]["url"] == "https://owned.example/"
    assert results[0]["agentic_query"] in calls
