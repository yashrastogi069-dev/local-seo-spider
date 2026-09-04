"""Small, deterministic agentic retrieval controls for local website questions."""

from __future__ import annotations

import re


def _meaningful_terms(value: str) -> set[str]:
    stop_words = {"what", "which", "where", "when", "does", "this", "that", "the", "and", "for", "from", "with", "about", "are", "is", "how", "can", "tell", "please", "who", "was", "were", "will", "would", "could", "should", "has", "have", "had", "into", "your", "our", "their"}
    return {term for term in re.findall(r"[\w][\w'-]{1,}", value.lower()) if term not in stop_words}
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
    for hop_index, subquery in enumerate(subqueries, start=1):
        for rank, result in enumerate(search(crawl_id, subquery, max(2, min(limit, 8))), start=1):
            coverage = float(result.get("term_coverage", 1.0))
            # A result from the real index must overlap the subquery; otherwise a
            # semantic/hash collision or broad FTS match can become fake evidence.
            semantic_similarity = float(result.get("vector_similarity", result.get("semantic_score", 0.0)))
            if "term_coverage" in result and coverage < 0.5 and semantic_similarity < 0.38:
                continue
            key = (str(result.get("url", "")), int(result.get("chunk_index", result.get("id", 0))))
            existing = candidates.get(key)
            score = (0.72 * semantic_similarity) + (0.20 * coverage) + float(result.get("hybrid_score", 0.0)) * 0.08 + (1 / (50 + rank))
            item = dict(result, agentic_query=subquery, agentic_hop=hop_index, agentic_score=score, hop_indexes=[hop_index])
            if existing:
                item["hop_indexes"] = sorted(set(existing.get("hop_indexes", []) + [hop_index]))
                item["agentic_score"] = max(score, float(existing.get("agentic_score", 0.0)))
                if score <= float(existing.get("agentic_score", 0.0)):
                    item["agentic_query"] = existing.get("agentic_query", subquery)
            if not existing or score > float(existing.get("agentic_score", 0.0)):
                candidates[key] = item
            elif existing:
                existing["hop_indexes"] = item["hop_indexes"]
    ranked = sorted(candidates.values(), key=lambda item: (-float(item.get("agentic_score", 0.0)), -float(item.get("term_coverage", 1.0)), str(item.get("url", ""))))
    # Round-robin across source URLs first, then fill remaining slots by score.
    target = max(1, min(limit, 20))
    selected: list[dict[str, Any]] = []
    remaining = list(ranked)
    per_source: dict[str, int] = {}
    while remaining and len(selected) < target:
        progressed = False
        for item in list(remaining):
            source = str(item.get("url", ""))
            if per_source.get(source, 0) >= 2:
                continue
            selected.append(dict(item, source_rank=per_source.get(source, 0) + 1, source_diversity_applied=True, evidence_set_role="multi-hop" if len(item.get("hop_indexes", [])) > 1 else "single-hop"))
            per_source[source] = per_source.get(source, 0) + 1
            remaining.remove(item)
            progressed = True
            if len(selected) >= target:
                break
        if not progressed:
            break
    return selected
