"""Small, deterministic agentic retrieval controls for local website questions."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

SearchFn = Callable[[str, str, int], list[dict[str, Any]]]


def plan_queries(question: str, max_subqueries: int = 4) -> list[str]:
    """Create bounded focused retrieval queries without external tools or hidden browsing."""
    cleaned = " ".join(question.split())
    parts = re.split(r"\s+(?:and|also|plus|as well as)\s+|[;?]+", cleaned, flags=re.IGNORECASE)
    queries: list[str] = []
    for part in parts:
        candidate = " ".join(part.split()).strip(" ,.")
        if len(candidate) >= 3 and candidate.lower() not in {query.lower() for query in queries}:
            queries.append(candidate)
    if cleaned and cleaned.lower() not in {query.lower() for query in queries}:
        queries.insert(0, cleaned)
    return queries[:max(1, max_subqueries)]


def agentic_retrieve(crawl_id: str, question: str, search: SearchFn, limit: int = 6) -> list[dict[str, Any]]:
    """Retrieve from a crawl using bounded query planning and provenance-preserving deduplication."""
    candidates: dict[tuple[str, int], dict[str, Any]] = {}
    subqueries = plan_queries(question)
    for subquery in subqueries:
        for rank, result in enumerate(search(crawl_id, subquery, max(2, min(limit, 8))), start=1):
            key = (str(result.get("url", "")), int(result.get("chunk_index", result.get("id", 0))))
            existing = candidates.get(key)
            score = float(result.get("hybrid_score", 0.0)) + (1 / (50 + rank))
            item = dict(result, agentic_query=subquery, agentic_score=score)
            if not existing or score > float(existing.get("agentic_score", 0.0)):
                candidates[key] = item
    ranked = sorted(candidates.values(), key=lambda item: (-float(item.get("agentic_score", 0.0)), str(item.get("url", ""))))
    return ranked[: max(1, min(limit, 20))]
