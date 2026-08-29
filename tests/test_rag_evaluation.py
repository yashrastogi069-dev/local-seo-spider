from app.qa import answer_question


def search_fixture(crawl_id: str, query: str, limit: int) -> list[dict[str, object]]:
    if "training" in query.lower() or "workshop" in query.lower():
        return [{"url": "https://owned.example/services", "heading_path": "Training", "content": "Training includes workshops.", "agentic_score": 0.04}]
    return []


def test_grounded_question_has_confidence_and_citations() -> None:
    result = answer_question("crawl-1", "What training is offered?", search_fixture)
    assert result["grounded"] is True
    assert result["confidence"] >= 0.35
    assert result["citations"]


def test_unanswerable_question_abstains_with_zero_confidence() -> None:
    result = answer_question("crawl-1", "What is the moon made of?", search_fixture)
    assert result["grounded"] is False
    assert result["confidence"] == 0.0
    assert result["citations"] == []
