"""End-to-end happy path: authorized form submission, audit, and local export."""

from dataclasses import replace
import time

from fastapi.testclient import TestClient

import app.main as main
from app.database import Database
from app.types import LinkRecord, PageRecord


def test_authorized_crawl_renders_audit_and_exports(tmp_path, monkeypatch) -> None:
    local_settings = replace(main.settings, data_dir=tmp_path / "data", render_enabled=False)
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
        assert ledger.status_code == 200
        assert "Missing page title" in ledger.text
        assert "Self-contained HTML report" in ledger.text

        csv_export = client.get(f"/crawls/{crawl_id}/export/issues-csv")
        report_export = client.get(f"/crawls/{crawl_id}/export/report-html")
        assert csv_export.status_code == 200 and "Missing page title" in csv_export.text
        assert report_export.status_code == 200 and "SEO inspection ledger" in report_export.text

        fallback = client.post("/crawls", data={
            "start_url": "https://owned.example/", "mode": "site", "url_list": "", "max_urls": "5", "delay_seconds": "0.1",
            "respect_nofollow": "yes", "authorization_acknowledgment": "yes",
        }, headers={"HX-Request": "false"}, follow_redirects=False)
        assert fallback.status_code == 303
        assert fallback.headers["location"].startswith("/crawls/")


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
