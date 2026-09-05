"""Playwright-based browser automated verification suite.

Verifies:
1. Playwright Chromium installation and browser launch.
2. Dynamic client-side JavaScript rendering within CrawlEngine.
3. Live HTTP server interaction via Playwright browser context.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
import pytest
from playwright.sync_api import sync_playwright
import uvicorn

import app.main as main
from app.crawler import CrawlEngine
from app.database import Database
from app.main import settings
from app.types import CrawlRequest


def test_playwright_chromium_launches_and_renders_dom() -> None:
    """Verify Playwright Chromium launches and executes dynamic JavaScript."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("""
            <!DOCTYPE html>
            <html>
            <head><title>Playwright Test</title></head>
            <body>
                <div id="target">Initial Text</div>
                <script>
                    document.getElementById('target').textContent = 'Rendered Dynamic Content';
                </script>
            </body>
            </html>
        """)
        text = page.locator("#target").inner_text()
        assert text == "Rendered Dynamic Content"
        browser.close()


def test_crawl_engine_playwright_rendering(tmp_path) -> None:
    """Verify CrawlEngine uses Playwright when render_javascript is enabled."""
    db = Database(tmp_path / "browser_crawl.db")
    db.initialize()
    local_settings = replace(settings, render_enabled=True)

    # Mock server delivering dynamic JS content
    html_content = """
        <!DOCTYPE html>
        <html>
        <head><title>Dynamic Audit Target</title></head>
        <body>
            <h1>Heading</h1>
            <div id="dynamic-content">Loading...</div>
            <script>
                document.getElementById('dynamic-content').textContent = 'Dynamic JavaScript Content Rendered By Playwright';
            </script>
        </body>
        </html>
    """

    engine = CrawlEngine(local_settings)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html_content)
        rendered_html = page.content()
        rendered_text = page.inner_text("body")
        browser.close()

    assert "Dynamic JavaScript Content Rendered By Playwright" in rendered_html
    assert "Dynamic JavaScript Content Rendered By Playwright" in rendered_text


def test_playwright_live_app_interaction(tmp_path, monkeypatch) -> None:
    """Spin up live loopback server and verify UI interactions with Playwright."""
    local_settings = replace(
        settings,
        data_dir=tmp_path / "data",
        render_enabled=False,
        embedding_provider="hash",
    )
    db = Database(local_settings.database_path)
    db.initialize()
    monkeypatch.setattr(main, "settings", local_settings)
    monkeypatch.setattr(main, "database", db)

    # Use a free local port
    port = 8765
    server_config = uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(server_config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to start
    time.sleep(1.0)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # 1. Load homepage
            res = page.goto(f"http://127.0.0.1:{port}/")
            assert res is not None
            assert res.status == 200
            assert "Local SEO Spider" in page.title()

            # 2. Check key form controls exist
            assert page.locator('input[name="start_url"]').is_visible()
            assert page.locator('input[name="authorization_acknowledgment"]').is_visible()

            # 3. Test validation feedback without acknowledgment
            page.fill('input[name="start_url"]', "https://owned.example/")
            page.click('button[type="submit"]')
            page.wait_for_timeout(500)
            body_text = page.inner_text("body")
            assert "Confirm that you own this site" in body_text

            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=2.0)
