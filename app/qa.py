"""Evidence-grounded question answering over the local crawl index."""

from __future__ import annotations

from typing import Any, Callable


SearchFn = Callable[[str, str, int], list[dict[str, Any]]]
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

    scored_results = [result for result in results if "term_coverage" not in result or float(result.get("term_coverage", 0.0)) >= 0.5]
    if not scored_results:
        return {
            "question": cleaned,
            "answer": "I could not find enough matching evidence in this crawl to answer that reliably.",
            "grounded": False,
            "citations": [],
            "confidence": 0.0,
            "retrieval_mode": "agentic-hybrid",
        }
    if any("term_coverage" in result for result in scored_results):
        best_coverage = max(float(result.get("term_coverage", 0.0)) for result in scored_results)
        scored_results = [result for result in scored_results if float(result.get("term_coverage", 0.0)) >= max(0.5, best_coverage - 0.25)]

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
        })

    top_result = scored_results[0]
    top_score = float(top_result.get("agentic_score", top_result.get("hybrid_score", 0.0)))
    coverage = float(top_result.get("term_coverage", 1.0))
    confidence = min(0.99, max(0.2, 0.35 + top_score * 0.12 + coverage * 0.45))
    generated = ""
    if generator:
        try:
            generated = generator(cleaned, scored_results).strip()
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
