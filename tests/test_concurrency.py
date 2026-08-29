from pathlib import Path

import pytest

from app.config import Settings
from app.crawler import CrawlEngine
from app.types import CrawlRequest


def settings(mode: str) -> Settings:
    return Settings(
        data_dir=Path("data"), user_agent="LocalSEOSpider/Test", default_url_cap=5, max_url_cap=10,
        default_delay_seconds=0, request_timeout_seconds=2, render_timeout_ms=1_000, max_redirects=2,
        max_document_bytes=20_000, max_request_retries=0, retry_backoff_seconds=0.1, max_concurrent_crawls=1,
        render_enabled=False, crawl_executor_mode=mode, async_concurrency=2, thread_workers=2, process_workers=2,
    )


def request(mode: str = "serial") -> CrawlRequest:
    return CrawlRequest("https://owned.example/", "list", ["https://owned.example/a", "https://owned.example/b"], 2, 0, True, True, mode)


def test_static_executor_modes_preserve_page_records(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = (200, {"content-type": "text/html"}, b"<html><head><title>Fixture</title></head><body><h1>One</h1></body></html>", "https://owned.example/a")
    for mode in ("thread", "async", "process"):
        engine = CrawlEngine(settings(mode))
        monkeypatch.setattr(engine, "_robots", lambda client, start_url: (type("Policy", (), {"can_fetch": lambda self, agent, url: True})(), "loaded"))
        monkeypatch.setattr(engine, "_fetch_one_sync", lambda url: (url, payload, [], ""))
        async def fake_batch(urls: list[str], delay_seconds: float):
            return [(url, payload, [], "") for url in urls]
        monkeypatch.setattr(engine, "_async_batch", fake_batch)
        pages, links, robots_status = engine.run(request(mode), lambda *_: None)
        assert len(pages) == 2
        assert all(page.title == "Fixture" for page in pages)
        assert links == []
        assert robots_status == "loaded"


def test_unknown_executor_mode_fails_closed() -> None:
    engine = CrawlEngine(settings("unsupported"))
    with pytest.raises(ValueError, match="serial, thread, async, or process"):
        engine.run(request("unsupported"), lambda *_: None)
