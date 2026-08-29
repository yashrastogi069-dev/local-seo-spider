from pathlib import Path

from app.database import Database
from app.knowledge import compare_knowledge, extract_knowledge_chunks, extract_pages_knowledge
from app.qa import answer_question
from app.types import CrawlRequest, PageRecord


def page() -> PageRecord:
    return PageRecord(
        url="https://owned.example/services", final_url="https://owned.example/services", status_code=200,
        content_type="text/html", title="Services", description="", headings={"h1": ["Services"]}, canonical="",
        meta_robots="", x_robots="", source_html="<html><body><h1>Services</h1><p>We provide audits and training for small teams.</p><h2>Training</h2><p>Training includes workshops and documentation.</p></body></html>",
        rendered_html="", rendered_text="", images=[], structured_data=[], redirect_chain=[], fetch_error="", render_error="",
        robots_allowed=True, body_truncated=False, discovered_at="2026-08-29T00:00:00+00:00", internal_inlinks=0, content_hash="hash",
    )


def test_extract_chunks_preserves_heading_provenance() -> None:
    chunks = extract_knowledge_chunks(page().to_dict() | {"id": 1}, "crawl-1")
    assert len(chunks) == 2
    assert chunks[0].heading_path == "Services"
    assert chunks[0].content.startswith("We provide audits")
    assert chunks[1].heading_path == "Services > Training"
    assert "workshops" in chunks[1].content


def test_search_is_crawl_scoped_and_answer_abstains_without_evidence(tmp_path: Path) -> None:
    database = Database(tmp_path / "knowledge.sqlite")
    database.initialize()
    crawl_id = database.create_crawl(CrawlRequest("https://owned.example/", "site", max_urls=5, acknowledgment=True))
    database.replace_pages_and_links(crawl_id, [page()], [])
    stored = database.get_pages(crawl_id)
    chunks = extract_knowledge_chunks(stored[0], crawl_id)
    database.replace_knowledge_chunks(crawl_id, chunks)

    matches = database.search_knowledge(crawl_id, "What training is provided?")
    assert matches
    assert matches[0]["url"] == "https://owned.example/services"
    assert "Training" in matches[0]["heading_path"]

    answer = answer_question(crawl_id, "What training is provided?", database.search_knowledge)
    assert answer["grounded"] is True
    assert answer["citations"][0]["url"] == "https://owned.example/services"

    assert database.search_knowledge("different-crawl", "training") == []
    unknown = answer_question(crawl_id, "What is the moon made of?", database.search_knowledge)
    assert unknown["grounded"] is False
    assert unknown["citations"] == []


def test_hybrid_retrieval_persists_vectors_and_keeps_answer_grounded(tmp_path: Path) -> None:
    database = Database(tmp_path / "hybrid.sqlite")
    database.initialize()
    crawl_id = database.create_crawl(CrawlRequest("https://owned.example/", "site", max_urls=5, acknowledgment=True))
    database.replace_pages_and_links(crawl_id, [page()], [])
    chunks = extract_knowledge_chunks(database.get_pages(crawl_id)[0], crawl_id)
    database.replace_knowledge_chunks(crawl_id, chunks)

    assert database.vector_count(crawl_id) == len(chunks)
    matches = database.search_hybrid_knowledge(crawl_id, "training workshops")
    assert matches
    assert matches[0]["retrieval_mode"] == "hybrid"
    assert matches[0]["url"] == "https://owned.example/services"
    unknown = answer_question(crawl_id, "What is the moon made of?", database.search_hybrid_knowledge)
    assert unknown["grounded"] is False
    assert unknown["citations"] == []


def test_knowledge_comparison_and_non_html_empty_state() -> None:
    current = [{"url": "https://owned.example/", "heading_path": "Home", "content": "New text", "title": "Home"}]
    baseline = [{"url": "https://owned.example/", "heading_path": "Home", "content": "Old text", "title": "Home"}]
    comparison = compare_knowledge(current, baseline)
    assert comparison["added"][0]["content"] == "New text"
    assert comparison["removed"][0]["content"] == "Old text"

    pdf_page = page().to_dict() | {"id": 1, "content_type": "application/pdf", "source_html": "", "extracted_text": "PDF policy text is searchable locally."}
    pdf_chunks = extract_pages_knowledge([pdf_page], "crawl-pdf")
    assert len(pdf_chunks) == 1
    assert "PDF policy text" in pdf_chunks[0].content
