"""End-to-end happy path: authorized form submission, audit, and local export."""

from dataclasses import replace
import time

from fastapi.testclient import TestClient

import app.main as main
from app.database import Database
from app.knowledge import extract_knowledge_chunks
from app.types import CrawlRequest, LinkRecord, PageRecord


def test_authorized_crawl_renders_audit_and_exports(tmp_path, monkeypatch) -> None:
    local_settings = replace(main.settings, data_dir=tmp_path / "data", render_enabled=False, embedding_provider="hash")
    monkeypatch.setattr(main, "settings", local_settings)
    monkeypatch.setattr(main, "database", Database(local_settings.database_path))

    def fake_run(self, request, progress):
        progress(1, 0, "loaded")
        record = PageRecord(
            url=request.start_url, final_url=request.start_url, status_code=200, content_type="text/html", title="", description="A useful page",
            headings={"h1": ["A useful page"]}, canonical=request.start_url, meta_robots="", x_robots="", source_html="<html></html>", rendered_html="",
            rendered_text="Useful local inspection text.", images=[], structured_data=[], redirect_chain=[], content_hash="happy-path", discovered_at="2026-01-01T00:00:00+00:00",
        )
        return [record], [LinkRecord(request.start_url, request.start_url, "/", "Home", "", True, False)], "loaded"

    monkeypatch.setattr(main.CrawlEngine, "run", fake_run)
    with TestClient(main.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        home = client.get("/")
        assert home.status_code == 200
        assert home.headers["x-content-type-options"] == "nosniff"
        assert home.headers["x-frame-options"] == "DENY"
        assert "form-action 'self'" in home.headers["content-security-policy"]

        rejected = client.post("/crawls", data={"start_url": "https://owned.example/", "max_urls": "5", "delay_seconds": "0.1"})
        assert rejected.status_code == 422
        assert "Confirm that you own this site" in rejected.text

        plain_rejected = client.post("/crawls", data={"start_url": "https://owned.example/", "max_urls": "5", "delay_seconds": "0.1"}, headers={"HX-Request": "false"})
        assert plain_rejected.status_code == 422
        assert "Local SEO Spider" in plain_rejected.text

        created = client.post("/crawls", data={
            "start_url": "https://owned.example/", "mode": "site", "url_list": "", "max_urls": "5", "delay_seconds": "0.1",
            "respect_nofollow": "yes", "authorization_acknowledgment": "yes",
        })
        assert created.status_code == 200
        crawl_id = main.database.list_crawls()[0]["id"]
        status = client.get(f"/crawls/{crawl_id}/status")
        for _ in range(20):
            if "INSPECTION COMPLETE" in status.text:
                break
            time.sleep(0.05)
            status = client.get(f"/crawls/{crawl_id}/status")
        assert "INSPECTION COMPLETE" in status.text

        ledger = client.get(f"/crawls/{crawl_id}")
        for _ in range(300):
            if "1 evidence chunks indexed" in ledger.text:
                break
            time.sleep(0.05)
            ledger = client.get(f"/crawls/{crawl_id}")
        assert ledger.status_code == 200
        assert "Missing page title" in ledger.text
        assert "Self-contained HTML report" in ledger.text
        assert "1 evidence chunks indexed" in ledger.text
        assert "Searching local evidence" in ledger.text
        assert "Rebuilding" in ledger.text

        answer = client.post(f"/crawls/{crawl_id}/ask", data={"question": "What is the useful local inspection text?"})
        assert answer.status_code == 200
        assert "EVIDENCE-BACKED RESULT" in answer.text
        assert "Useful local inspection text." in answer.text
        assert "https://owned.example/" in answer.text

        unanswered = client.post(f"/crawls/{crawl_id}/ask", data={"question": "What is the moon made of?"})
        assert unanswered.status_code == 200
        assert "INSUFFICIENT EVIDENCE" in unanswered.text

        api_answer = client.get(f"/api/crawls/{crawl_id}/ask", params={"q": "useful local inspection"})
        assert api_answer.status_code == 200
        assert api_answer.json()["grounded"] is True
        assert api_answer.json()["citations"][0]["url"] == "https://owned.example/"

        reindexed = client.post(f"/crawls/{crawl_id}/knowledge/reindex", headers={"HX-Request": "true"})
        assert reindexed.status_code == 200
        assert "LOCAL INDEX READY" in reindexed.text

        def fail_index(*args, **kwargs):
            raise RuntimeError("fixture index failure")

        monkeypatch.setattr(main, "extract_pages_knowledge", fail_index)
        failed_reindex = client.post(f"/crawls/{crawl_id}/knowledge/reindex", headers={"HX-Request": "true"})
        assert failed_reindex.status_code == 500
        assert "REBUILD FAILED" in failed_reindex.text
        assert "fixture index failure" in failed_reindex.text

        csv_export = client.get(f"/crawls/{crawl_id}/export/issues-csv")
        report_export = client.get(f"/crawls/{crawl_id}/export/report-html")
        json_export = client.get(f"/crawls/{crawl_id}/export/pages-json")
        jsonl_export = client.get(f"/crawls/{crawl_id}/export/pages-jsonl")
        assert csv_export.status_code == 200 and "Missing page title" in csv_export.text
        assert report_export.status_code == 200 and "SEO inspection ledger" in report_export.text
        assert json_export.status_code == 200 and '"url": "https://owned.example/"' in json_export.text
        assert jsonl_export.status_code == 200 and '"url": "https://owned.example/"' in jsonl_export.text

        fallback = client.post("/crawls", data={
            "start_url": "https://owned.example/", "mode": "site", "url_list": "", "max_urls": "5", "delay_seconds": "0.1",
            "respect_nofollow": "yes", "authorization_acknowledgment": "yes",
        }, headers={"HX-Request": "false"}, follow_redirects=False)
        assert fallback.status_code == 303
        assert fallback.headers["location"].startswith("/crawls/")


def test_form_persists_executor_and_extraction_profile_settings(tmp_path, monkeypatch) -> None:
    local_settings = replace(main.settings, data_dir=tmp_path / "data", render_enabled=False)
    monkeypatch.setattr(main, "settings", local_settings)
    monkeypatch.setattr(main, "database", Database(local_settings.database_path))
    monkeypatch.setattr(main, "_start_worker", lambda: None)
    profile = tmp_path / "profile.json"
    profile.write_text('{"name":"fixture","fields":[{"name":"sku","selector":"[data-sku]"}]}', encoding="utf-8")

    with TestClient(main.app) as client:
        created = client.post("/crawls", data={
            "start_url": "https://owned.example/", "mode": "site", "max_urls": "2", "delay_seconds": "0.1",
            "respect_nofollow": "yes", "authorization_acknowledgment": "yes", "executor_mode": "thread",
            "extraction_profile_path": str(profile),
        }, headers={"HX-Request": "true"})
        assert created.status_code == 200
        crawl_id = main.database.list_crawls()[0]["id"]
        saved = main.database.get_crawl_request(crawl_id)

    assert saved is not None
    assert saved.executor_mode == "thread"
    assert saved.extraction_profile_path == str(profile.resolve())


def test_completed_crawl_with_no_html_shows_dedicated_empty_knowledge_state(tmp_path, monkeypatch) -> None:
    local_settings = replace(main.settings, data_dir=tmp_path / "data", render_enabled=False)
    monkeypatch.setattr(main, "settings", local_settings)
    monkeypatch.setattr(main, "database", Database(local_settings.database_path))
    monkeypatch.setattr(main, "_start_worker", lambda: None)

    with TestClient(main.app) as client:
        crawl_id = main.database.create_crawl(CrawlRequest("https://empty.example/", "site", max_urls=1, acknowledgment=True))
        main.database.update_crawl(crawl_id, status="completed", completed_at="2026-08-29T00:00:00+00:00", robots_status="loaded")
        detail = client.get(f"/crawls/{crawl_id}")

    assert detail.status_code == 200
    assert "0 evidence chunks indexed" in detail.text
    assert "NO SEARCHABLE CONTENT" in detail.text


def test_operator_can_pause_and_resume_a_queued_local_job(tmp_path, monkeypatch) -> None:
    local_settings = replace(main.settings, data_dir=tmp_path / "data", render_enabled=False)
    monkeypatch.setattr(main, "settings", local_settings)
    monkeypatch.setattr(main, "database", Database(local_settings.database_path))
    monkeypatch.setattr(main, "_start_worker", lambda: None)

    with TestClient(main.app) as client:
        created = client.post("/crawls", data={
            "start_url": "https://owned.example/", "mode": "site", "url_list": "", "max_urls": "5", "delay_seconds": "0.1",
            "respect_nofollow": "yes", "authorization_acknowledgment": "yes",
        }, headers={"HX-Request": "true"})
        assert created.status_code == 200 and "LOCAL JOB QUEUED" in created.text
        crawl_id = main.database.list_crawls()[0]["id"]

        paused = client.post(f"/crawls/{crawl_id}/pause", headers={"HX-Request": "true"})
        assert paused.status_code == 200 and "LOCAL JOB PAUSED" in paused.text
        assert main.database.get_crawl(crawl_id)["status"] == "paused"

        resumed = client.post(f"/crawls/{crawl_id}/resume", headers={"HX-Request": "true"})
        assert resumed.status_code == 200 and "LOCAL JOB QUEUED" in resumed.text
        assert main.database.get_crawl(crawl_id)["status"] == "queued"


def test_local_workflow_api_runs_read_only_knowledge_nodes(tmp_path, monkeypatch) -> None:
    local_settings = replace(main.settings, data_dir=tmp_path / "data", render_enabled=False)
    monkeypatch.setattr(main, "settings", local_settings)
    monkeypatch.setattr(main, "database", Database(local_settings.database_path))
    monkeypatch.setattr(main, "_start_worker", lambda: None)

    with TestClient(main.app) as client:
        crawl_id = main.database.create_crawl(CrawlRequest("https://owned.example/", "site", max_urls=1, acknowledgment=True))
        page = PageRecord(
            url="https://owned.example/", final_url="https://owned.example/", status_code=200, content_type="text/html", title="Home", description="",
            headings={"h1": ["Home"]}, canonical="", meta_robots="", x_robots="", source_html="<html><body><h1>Home</h1><p>Workshops are available.</p></body></html>",
            rendered_html="", rendered_text="", images=[], structured_data=[], redirect_chain=[], discovered_at="2026-08-29T00:00:00+00:00", content_hash="workflow",
        )
        main.database.replace_pages_and_links(crawl_id, [page], [])
        main.database.replace_knowledge_chunks(crawl_id, extract_knowledge_chunks(main.database.get_pages(crawl_id)[0], crawl_id))
        main.database.update_crawl(crawl_id, status="completed", pages_crawled=1)
        workflow = {
            "id": "api-read",
            "name": "API read workflow",
            "nodes": [{"id": "search", "type": "knowledge.search", "config": {"crawl_id": crawl_id, "query": "workshops"}}],
        }
        saved = client.post("/api/workflows", json=workflow)
        assert saved.status_code == 200
        run = client.post("/api/workflows/api-read/run", json={})
        assert run.status_code == 200
        assert run.json()["status"] == "completed"
        assert run.json()["outputs"]["search"]["results"]
        history = client.get("/api/workflows/api-read/runs")
        assert history.status_code == 200
        assert history.json()[0]["status"] == "completed"
        trigger = {
            "id": "on-complete",
            "name": "On complete question",
            "active": True,
            "trigger": {"type": "crawl.completed", "start_url": "https://owned.example/"},
            "nodes": [{"id": "ask", "type": "knowledge.ask", "config": {"crawl_id": "{{input.crawl_id}}", "question": "What is available?"}}],
        }
        assert client.post("/api/workflows", json=trigger).status_code == 200
        main._fire_crawl_completed_workflows(crawl_id, "https://owned.example/")
        trigger_history = client.get("/api/workflows/on-complete/runs")
        assert trigger_history.status_code == 200
        assert trigger_history.json()[0]["status"] == "completed"
