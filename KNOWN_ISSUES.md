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
