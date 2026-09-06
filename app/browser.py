"""Deterministic Playwright browser session management and lifecycle control (Phase 2E)."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def is_playwright_available() -> bool:
    """Check if Playwright and Chromium are installed and runnable."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
            browser.close()
        return True
    except Exception:
        return False


class PlaywrightBrowserSession:
    """Manages the lifecycle of a Playwright headless browser session with deterministic teardown."""

    def __init__(self, user_agent: str, render_timeout_ms: int = 5000, headless: bool = True) -> None:
        self.user_agent = user_agent
        self.render_timeout_ms = render_timeout_ms
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._is_active = False

    def start(self) -> None:
        if self._is_active:
            return
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            self._context = self._browser.new_context(
                user_agent=self.user_agent,
                java_script_enabled=True,
            )
            self._is_active = True
        except Exception:
            self.close()
            raise

    @property
    def is_active(self) -> bool:
        return self._is_active

    def render_url(self, url: str, max_document_bytes: int = 200_000) -> tuple[str, str, str, float]:
        """Render a URL in an isolated page and extract rendered DOM and text.

        Returns:
            tuple[str, str, str, float]: (rendered_html, rendered_text, render_error, duration_ms)
        """
        t_start = time.monotonic()
        page = None
        try:
            if not self._is_active:
                self.start()

            page = self._context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=self.render_timeout_ms)
            page.wait_for_timeout(150)
            html = page.content()
            try:
                text = page.locator("body").inner_text(timeout=min(self.render_timeout_ms, 3000))
            except Exception:
                text = ""
            duration_ms = (time.monotonic() - t_start) * 1000.0
            return html[:max_document_bytes], text, "", duration_ms
        except Exception as exc:
            duration_ms = (time.monotonic() - t_start) * 1000.0
            html = ""
            text = ""
            if page:
                try:
                    html = page.content()[:max_document_bytes]
                    text = page.locator("body").inner_text(timeout=500)
                except Exception:
                    pass
            return html, text, f"{type(exc).__name__}: {exc}", duration_ms
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    def close(self) -> None:
        """Deterministically close context, browser, and playwright process."""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        self._is_active = False

    def __enter__(self) -> "PlaywrightBrowserSession":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
