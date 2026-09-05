# API CONTRACTS & INTERFACE SPECIFICATIONS

This document defines the HTTP API contracts, request/response JSON schemas, and error conventions exposed by the FastAPI server in `app/main.py`.

---

## 1. Global Conventions
- **Base URL**: `http://127.0.0.1:3000` (or configured host/port)
- **Content-Type**: `application/json` (unless requesting HTML views or CSV exports)
- **Error Format**:
  ```json
  {
    "detail": "Error description message"
  }
  ```

---

## 2. Endpoints

### A. Crawl Lifecycle

#### 1. `POST /crawls`
Initiate a new crawl job.
- **Request Body** (`application/x-www-form-urlencoded` or JSON):
  - `start_url` (string, required): Seed URL.
  - `mode` (string): `site` (default) or `list`.
  - `max_urls` (integer): Maximum URLs to crawl (default: 50).
  - `delay_seconds` (float): Delay between requests (default: 0.1).
  - `concurrency_mode` (string): `thread`, `serial`, `async`, `multiprocess`.
  - `render_javascript` (boolean): Whether to launch Playwright Chromium (default: false).
  - `authorization_acknowledgment` (boolean, required): Must be `true` confirming ownership or explicit permission.
- **Response** (HTTP 303 Redirect to `/crawls/{crawl_id}` on HTML form, or HTTP 201 JSON):
  ```json
  {
    "crawl_id": "crawl-a1b2c3d4",
    "status": "queued",
    "start_url": "https://example.com/"
  }
  ```

#### 2. `GET /crawls/{crawl_id}`
Retrieve crawl ledger, pages, and audit metrics.
- **Path Parameters**: `crawl_id` (string).
- **Response**: HTML dashboard view or JSON ledger object.

#### 3. `POST /crawls/{crawl_id}/pause` / `POST /crawls/{crawl_id}/resume` / `POST /crawls/{crawl_id}/cancel`
Manage crawl execution state.

---

### B. Knowledge & Hybrid Search

#### 1. `GET /crawls/{crawl_id}/knowledge`
Perform hybrid lexical (BM25) + dense vector search across indexed knowledge chunks.
- **Query Parameters**:
  - `q` (string, required): Search query text.
  - `limit` (integer, optional): Maximum results to return (default: 5).
- **Response** (HTTP 200 JSON):
  ```json
  [
    {
      "chunk_id": "doc-1-chunk-0",
      "url": "https://example.com/api/todos",
      "title": "Todos API",
      "heading_path": "API > Todos",
      "content": "field = total, value = 150\nfield = limit, value = 30",
      "hybrid_score": 0.824,
      "term_coverage": 1.0,
      "source_type": "official_api"
    }
  ]
  ```

---

### C. Grounded Question Answering & Citation Verification

#### 1. `POST /crawls/{crawl_id}/ask`
Generate a strictly grounded answer with claim-level citation verification.
- **Request Body**:
  - `query` (string, required): Question text.
- **Response** (HTTP 200 JSON):
  ```json
  {
    "query": "What are the total and limit values for todos?",
    "answer": "The total is 150 and limit is 30 [1].",
    "answer_mode": "grounded_synthesis",
    "grounded": true,
    "confidence": 0.95,
    "citations": [
      {
        "citation_id": 1,
        "url": "https://example.com/api/todos",
        "title": "Todos API",
        "heading_path": "API > Todos",
        "content": "field = total, value = 150\nfield = limit, value = 30",
        "source_type": "official_api"
      }
    ],
    "claim_verifications": [
      {
        "claim_text": "The total is 150 and limit is 30",
        "verdict": "PASS",
        "grounded": true,
        "cited_passages": [1]
      }
    ],
    "completeness": {
      "is_complete": true,
      "covered_slots": ["total", "limit"],
      "missing_slots": []
    }
  }
  ```
- **Abstention Example** (Unanswerable query):
  ```json
  {
    "query": "What is the return policy for Mars colonies?",
    "answer": "I couldn't verify that from the crawled sources.",
    "answer_mode": "abstention",
    "grounded": false,
    "confidence": 0.0,
    "citations": [],
    "claim_verifications": []
  }
  ```

---

### D. Crawl Coverage & Audit Analytics

#### 1. `GET /crawls/{crawl_id}/coverage`
Retrieve mathematically verified crawl coverage and distribution statistics.
- **Response** (HTTP 200 JSON):
  ```json
  {
    "crawl_id": "crawl-a1b2c3d4",
    "total_crawled_urls": 45,
    "total_discovered_urls": 50,
    "crawl_coverage_rate": 0.90,
    "status_code_distribution": {
      "200": 42,
      "404": 3
    },
    "content_type_distribution": {
      "text/html": 40,
      "application/json": 5
    },
    "duplicates_detected": 4,
    "api_endpoints_indexed": 5,
    "average_word_count": 342.5
  }
  ```

---

### E. Data Exports

#### 1. `GET /crawls/{crawl_id}/export/csv`
Downloads full crawl audit ledger in RFC 4180 compliant CSV format.

#### 2. `GET /crawls/{crawl_id}/export/json`
Downloads full crawl audit ledger in structured JSON format.
