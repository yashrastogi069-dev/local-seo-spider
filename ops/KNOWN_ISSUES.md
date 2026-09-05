# KNOWN ISSUES & OPERATIONAL CONSTRAINTS

This document tracks known architectural limitations, operational requirements, and external dependency constraints for the Local SEO Spider & Semantic RAG system.

---

## 1. Embedding Provider Dependency
- **Issue**: Deep neural semantic embedding requires the heavy optional dependency `sentence-transformers` (and its dependencies `torch`, `transformers`, `huggingface-hub`).
- **Current Mitigation**: When `sentence-transformers` is unavailable, the system defaults to `HashEmbeddingProvider`, an offline, deterministic 64-dimensional pseudo-random projection.
- **Impact**: In the offline fallback mode, vector-only retrieval produces low recall for conceptual paraphrase matching because hash projections lack deep semantic language representations. However, hybrid retrieval with BM25 lexical indexing (`FTS5`) compensates effectively.
- **Resolution for Production**: In production environments requiring conceptual paraphrasing, install the optional extra:
  ```bash
  pip install sentence-transformers
  ```
  and configure `SPIDER_EMBEDDING_PROVIDER=sentence-transformers`.

---

## 2. Playwright Chromium Binary Requirement
- **Issue**: The Playwright browser automation module (`app/browser.py`) requires a local Chromium binary to render dynamic JavaScript DOM content.
- **Current Mitigation**: The crawler defaults to static HTTP fetching (`render_enabled=False`). Dynamic rendering is only activated when explicitly requested (`render_enabled=True`).
- **Resolution for Production**: In containerized or stripped server environments where dynamic rendering is required, run:
  ```bash
  playwright install chromium
  ```

---

## 3. Local LLM Server Availability
- **Issue**: Generative conversational answer synthesis depends on an external or local LLM server (e.g. Ollama at `http://127.0.0.1:11434`).
- **Current Mitigation**: If the LLM endpoint is offline, unreachable, or returns malformed responses, the system automatically falls back to [`LocalAnswerer`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/answering.py), a deterministic, extractive synthesis engine that produces strictly grounded answers from retrieved passage spans with zero hallucinations.

---

## 4. Open Internet Network Latency & External Rate-Limiting
- **Issue**: Live web crawls against arbitrary third-party websites can experience HTTP 429 (Too Many Requests), connection resets, or network timeouts.
- **Current Mitigation**: The crawler implements exponential backoff retries, enforces polite delay configurations (`delay_seconds`), and caps redirect hops (`max_redirects = 5`).

---

## 5. Starlette / FastAPI TestClient Deprecation Warning
- **Issue**: FastAPI / Starlette emits a minor warning: `StarletteDeprecationWarning: Using 'httpx' with 'starlette.testclient' is deprecated; install 'httpx2' instead.`
- **Impact**: Harmless deprecation warning emitted during test suite execution; does not affect runtime application or test passes.

---

## 6. Phase 2 Crawler Forensic Baseline Defects (Discovered 2026-09-05)

### P0 (Critical / Blockers for Production):
- **DEF-P0-01 (Process Mode Sequential I/O)**: `process` mode does not fetch concurrently in worker processes. It fetches sequentially in the main thread via list comprehension and only maps CPU HTML parsing to `ProcessPoolExecutor`.
- **DEF-P0-02 (Silent Browser Bypass in Concurrent Modes)**: `thread`, `async`, and `process` modes silently ignore `render_enabled=True` and execute static HTTP fetches without notification.
- **DEF-P0-03 (Fake Playwright Test Assertion)**: `test_crawl_engine_playwright_rendering` instantiates `CrawlEngine` but never executes `engine.run()`, testing raw Playwright rather than the engine.

### P1 (High Severity Functional Defects):
- **DEF-P1-01 (Depth & Provenance Amnesia)**: `PageRecord.depth` and `parent_url` are hardcoded to `0` and `""` on every page. Tree hierarchy and depth limits cannot be enforced.
- **DEF-P1-02 (All-or-Nothing Persistence)**: Crawl pages held only in memory; mid-crawl crash discards all pages; resume starts from 0.
- **DEF-P1-03 (No In-Flight Cancellation)**: `/pause` endpoint explicitly rejects running crawls with HTTP 409; running crawls cannot be stopped via API.
- **DEF-P1-04 (Silent Browser Launch Fallback)**: Naked `except Exception:` catches Chromium launch failure, silently falling back to static fetch.
- **DEF-P1-05 (Frontier Premature Capping)**: `len(queued) >= max_urls` caps discovered candidate links instead of crawled pages, halting discovery prematurely.
- **DEF-P1-06 (Redirect Destination Duplicate Fetching)**: Redirect destinations not added to `queued`, causing subsequent links to the destination URL to fetch it again.

### P2 (Medium Severity Operational Deficiencies):
- **DEF-P2-01 (Zero HTTP Connection Pooling in Concurrent Modes)**: `thread` and `process` modes open a new `httpx.Client` per URL; `async` creates a new client per batch.
- **DEF-P2-02 (Async Event Loop Churn)**: `asyncio.run()` called on every batch inside the while loop, recreating the event loop every iteration.
- **DEF-P2-03 (Global Thread Delay Lock)**: `thread_gate` lock serializes sleep delay across all worker threads.
- **DEF-P2-04 (DNS Rebinding Vulnerability)**: SSRF check is string-based without socket-level pre-connection DNS validation.

