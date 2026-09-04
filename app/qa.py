"""Evidence-grounded question answering over the local crawl index."""

from __future__ import annotations

import re
from typing import Any, Callable


SearchFn = Callable[[str, str, int], list[dict[str, Any]]]


def _has_contradictory_evidence(question: str, results: list[dict[str, Any]]) -> bool:
    terms = {term for term in re.findall(r"[a-z0-9][a-z0-9'-]{2,}", question.lower()) if term not in {"what", "which", "where", "when", "does", "this", "that", "the", "and", "for", "with", "are", "is", "how", "can", "tell", "about"}}
    polarity: set[str] = set()
    for result in results:
        content = str(result.get("content", "")).lower()
        if not terms.intersection(re.findall(r"[a-z0-9][a-z0-9'-]{2,}", content)):
            continue
        if re.search(r"\b(?:not|never|no|without|cannot|can't|isn't|doesn't)\b", content):
            polarity.add("negative")
        else:
            polarity.add("affirmative")
    return polarity == {"affirmative", "negative"}


def _validated_generated_answer(answer: str, evidence_count: int) -> str:
    normalized = " ".join(answer.split())
    if not normalized:
        return ""
    if "insufficient" in normalized.lower() and not re.findall(r"\[(\d+)\]", normalized):
        return normalized
    citations = [int(value) for value in re.findall(r"\[(\d+)\]", normalized)]
    if not citations or any(value < 1 or value > evidence_count for value in citations):
        return ""
    return answer.strip()
AnswerGenerator = Callable[[str, list[dict[str, Any]]], str]


def answer_question(crawl_id: str, question: str, search: SearchFn, limit: int = 6, generator: AnswerGenerator | None = None) -> dict[str, Any]:
    """Return a deterministic, citation-backed answer without inventing unsupported facts."""
    cleaned = " ".join(question.split())
    if len(cleaned) < 3:
        return {"question": cleaned, "answer": "Ask a more specific question about the crawled website.", "grounded": False, "citations": [], "confidence": 0.0, "retrieval_mode": "agentic-hybrid"}

    results = search(crawl_id, cleaned, limit)
    if not results:
        return {
            "question": cleaned,
            "answer": "I could not find enough matching evidence in this crawl to answer that reliably.",
            "grounded": False,
            "citations": [],
            "confidence": 0.0,
            "retrieval_mode": "agentic-hybrid",
        }

    scored_results = [
        result for result in results
        if ("term_coverage" not in result and "vector_similarity" not in result)
        or float(result.get("term_coverage", 0.0)) >= 0.5
        or float(result.get("vector_similarity", 0.0)) >= 0.38
    ]
    if not scored_results:
        return {
            "question": cleaned,
            "answer": "I could not find enough matching evidence in this crawl to answer that reliably.",
            "grounded": False,
            "citations": [],
            "confidence": 0.0,
            "retrieval_mode": "agentic-hybrid",
        }
    # Keep dense semantic matches even when exact lexical overlap is low; use coverage as a tie-breaker.
    if any("vector_similarity" in result for result in scored_results):
        best_score = max(float(result.get("vector_similarity", 0.0)) for result in scored_results)
        scored_results = [result for result in scored_results if float(result.get("vector_similarity", 0.0)) >= max(0.38, best_score - 0.22) or float(result.get("term_coverage", 0.0)) >= 0.5]

    if _has_contradictory_evidence(cleaned, scored_results):
        return {
            "question": cleaned,
            "answer": "The indexed evidence contains conflicting statements about this question, so I cannot answer it reliably without clarification or a newer crawl.",
            "grounded": False,
            "citations": [],
            "confidence": 0.0,
            "retrieval_mode": "agentic-hybrid",
        }

    evidence_lines: list[str] = []
    citations: list[dict[str, Any]] = []
    for position, result in enumerate(scored_results, start=1):
        heading = result.get("heading_path") or "Page content"
        evidence_lines.append(f"{position}. {result['content']} ({result['url']} · {heading})")
        citations.append({
            "url": result["url"],
            "title": result.get("title", ""),
            "heading_path": heading,
            "content": result["content"],
            "page_id": result.get("page_id"),
            "hop_indexes": result.get("hop_indexes", []),
            "evidence_set_role": result.get("evidence_set_role", "single-hop"),
            "semantic_score": result.get("semantic_score", result.get("vector_similarity", 0.0)),
            "lexical_match": result.get("lexical_match", False),
        })

    top_result = scored_results[0]
    top_score = float(top_result.get("agentic_score", top_result.get("hybrid_score", 0.0)))
    coverage = float(top_result.get("term_coverage", 1.0))
    confidence = min(0.99, max(0.2, 0.35 + top_score * 0.12 + coverage * 0.45))
    generated = ""
    if generator:
        try:
            generated = _validated_generated_answer(generator(cleaned, scored_results), len(scored_results))
        except Exception:
            # Optional local synthesis must never erase a usable, deterministic answer.
            generated = ""
    return {
        "question": cleaned,
        "answer": generated or "I found the following evidence in the local crawl. Verify the cited passages before treating them as a final answer:\n\n" + "\n".join(evidence_lines),
        "grounded": True,
        "citations": citations,
        "answer_mode": "local-model" if generated else "evidence",
        "confidence": round(confidence, 2),
        "retrieval_mode": "agentic-hybrid",
    }
