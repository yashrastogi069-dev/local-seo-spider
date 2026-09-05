---
name: playwright-verifier
description: Playwright-based browser automation, dynamic JavaScript rendering, and live UI verification for Local SEO Spider.
---

# Playwright Browser Verifier Skill

This skill provides procedures and test scripts for automated end-to-end browser verification of the Local SEO Spider web application using Playwright.

## Capabilities
1. **Headless Chromium Execution**: Verifies that Playwright Chromium starts up cleanly in headless mode.
2. **Dynamic Client-Side Render Verification**: Tests that pages with JavaScript-rendered DOM elements are fully resolved and captured by `CrawlEngine`.
3. **Full UI & HTMX Interaction**: Automates form submission, live polling, and question-answering verification via real browser sessions.

## Execution
Run the browser verification suite:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_playwright_browser.py -v
```
