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

    evidence_lines: list[str] = []
    citations: list[dict[str, Any]] = []
    for position, result in enumerate(results, start=1):
        heading = result.get("heading_path") or "Page content"
        evidence_lines.append(f"{position}. {result['content']} ({result['url']} · {heading})")
        citations.append({
            "url": result["url"],
            "title": result.get("title", ""),
            "heading_path": heading,
            "content": result["content"],
            "page_id": result.get("page_id"),
        })

    top_score = float(results[0].get("agentic_score", results[0].get("hybrid_score", 0.0))) if results else 0.0
    confidence = min(0.99, max(0.2, 0.35 + top_score * 12))
    generated = ""
    if generator:
        try:
            generated = generator(cleaned, results).strip()
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
