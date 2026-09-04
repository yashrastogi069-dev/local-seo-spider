from dataclasses import replace
from pathlib import Path

import app.main as main
from app.answering import LocalAnswerer
from app.database import Database
from app.qa import answer_question
from app.types import CrawlRequest, LinkRecord, PageRecord


def test_worker_crawl_indexes_real_semantic_corpus_and_answers_groundedly(tmp_path: Path, monkeypatch) -> None:
    local_settings = replace(main.settings, data_dir=tmp_path / "data", render_enabled=False, embedding_provider="sentence-transformers")
    database = Database(local_settings.database_path)
    database.initialize()
    monkeypatch.setattr(main, "settings", local_settings)
    monkeypatch.setattr(main, "database", database)

    def fake_run(self, request, progress):
        progress(1, 0, "loaded")
        pages = [
            PageRecord(
                url=request.start_url,
                final_url=request.start_url,
                status_code=200,
                content_type="text/html",
                title="Refund policy",
                description="",
                headings={"h1": ["Refund policy"]},
                canonical=request.start_url,
                meta_robots="",
                x_robots="",
                source_html="<html><body><h1>Refund policy</h1><p>Eligible customers can request a refund within fourteen days.</p></body></html>",
                rendered_html="",
                rendered_text="Eligible customers can request a refund within fourteen days.",
                images=[], structured_data=[], redirect_chain=[], fetch_error="", render_error="",
                robots_allowed=True, body_truncated=False, discovered_at="2026-01-01T00:00:00+00:00", internal_inlinks=0, content_hash="refund",
            ),
            PageRecord(
                url="https://owned.example/eligibility",
                final_url="https://owned.example/eligibility",
                status_code=200,
                content_type="text/html",
                title="Eligibility",
                description="",
                headings={"h1": ["Eligibility"]},
                canonical="https://owned.example/eligibility",
                meta_robots="",
                x_robots="",
                source_html="<html><body><h1>Eligibility</h1><p>Eligible customers are account holders.</p></body></html>",
                rendered_html="",
                rendered_text="Eligible customers are account holders.",
                images=[], structured_data=[], redirect_chain=[], fetch_error="", render_error="",
                robots_allowed=True, body_truncated=False, discovered_at="2026-01-01T00:00:00+00:00", internal_inlinks=0, content_hash="eligibility",
            ),
            PageRecord(
                url="https://owned.example/about",
                final_url="https://owned.example/about",
                status_code=200,
                content_type="text/html",
                title="About",
                description="",
                headings={"h1": ["About"]},
                canonical="https://owned.example/about",
                meta_robots="",
                x_robots="",
                source_html="<html><body><h1>About</h1><p>Our offices close on public holidays.</p></body></html>",
                rendered_html="",
                rendered_text="Our offices close on public holidays.",
                images=[], structured_data=[], redirect_chain=[], fetch_error="", render_error="",
                robots_allowed=True, body_truncated=False, discovered_at="2026-01-01T00:00:00+00:00", internal_inlinks=0, content_hash="about",
            ),
        ]
        links = [LinkRecord(request.start_url, request.start_url, "/", "Home", "", True, False)]
        return pages, links, "loaded"

    monkeypatch.setattr(main.CrawlEngine, "run", fake_run)
    crawl_id = database.create_crawl(CrawlRequest("https://owned.example/", "site", max_urls=5, acknowledgment=True))
    main._run_claimed_crawl(crawl_id, database.get_crawl_request(crawl_id))

    assert database.knowledge_count(crawl_id) >= 2
    paraphrase = answer_question(crawl_id, "How long can an eligible customer ask to get their money back?", main._search_knowledge)
    assert paraphrase["grounded"] is True
    assert "fourteen days" in paraphrase["answer"]
    assert paraphrase["citations"]
    assert all(citation["url"] != "https://owned.example/about" for citation in paraphrase["citations"])
    assert paraphrase["citations"][0]["url"] == "https://owned.example/"

    unsupported = answer_question(crawl_id, "What is the chemical composition of the moon?", main._search_knowledge)
    assert unsupported["grounded"] is False
    assert unsupported["citations"] == []

    multi_hop = answer_question(crawl_id, "Which customers are eligible and how long can they request a refund?", main._search_knowledge)
    multi_hop_urls = {citation["url"] for citation in multi_hop["citations"]}
    assert multi_hop["grounded"] is True
    assert "account holders" in multi_hop["answer"]
    assert "fourteen days" in multi_hop["answer"]
    assert "https://owned.example/" in multi_hop_urls
    assert "https://owned.example/eligibility" in multi_hop_urls
    assert any(citation.get("hop_indexes") for citation in multi_hop["citations"])

    class MalformedResponse:
        def raise_for_status(self) -> None:
            return None
        def json(self) -> dict[str, str]:
            return {"response": "not-json"}

    monkeypatch.setattr("app.answering.httpx.post", lambda *args, **kwargs: MalformedResponse())
    fallback = answer_question(crawl_id, "How long is the refund window?", main._search_knowledge, generator=LocalAnswerer())
    assert fallback["answer_mode"] == "evidence"
    assert "fourteen days" in fallback["answer"]
