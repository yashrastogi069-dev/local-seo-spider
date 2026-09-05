# PHASE 2: CRAWLER CORE — BASELINE FORENSIC AUDIT REPORT

**Phase**: PHASE 2 — Crawler Core  
**Milestone**: Phase 2 Forensic Kickoff (Zero Implementation Baseline)  
**Baseline Git Checkpoint**: `db7fc50` (Tag: `pre-phase-2-crawler-core`, Tag: `phase-1-certified`)  
**Audit Status**: **FORENSIC AUDIT COMPLETED — IMPLEMENTATION LOCKED**  
**Auditor**: Principal Systems Engineer & QA Forensic Auditor  
**Date**: 2026-09-05  

---

## 1. Executive Summary & Forensic Scope

This document provides a deep forensic reconstruction of the crawler architecture in `local-seo-spider` as it exists at the start of Phase 2. 

In accordance with the **Antigravity Engineering Operating System**:
- Previous claims of multi-engine parity and production readiness are **untrusted**.
- Implementation code (`app/crawler.py`, `app/urltools.py`, `app/main.py`, `app/parser.py`, `app/database.py`) was inspected line-by-line.
- Every concurrency mode (`serial`, `thread`, `async`, `process`) and fetch strategy (`static`, `browser`) was traced to its actual physical execution path.

### Critical Kickoff Findings (P0 / P1 Summary):
1. **Multiprocess Mode is a Mirage (P0)**: In `process` mode, HTTP network fetching is **not multiprocess**. URLs are fetched sequentially in the main thread via a Python list comprehension; the `ProcessPoolExecutor` is only used to run CPU-bound BeautifulSoup parsing on the already-downloaded bytes.
2. **Playwright is Silently Bypassed in Concurrent Modes (P0)**: If `render_enabled=True` and an operator selects `thread`, `async`, or `process`, the crawler silently ignores the rendering setting and executes static HTTP fetching without any warning, error, or UI notification.
3. **Silent Degradation on Browser Launch Failure (P1)**: In `serial` mode, if Chromium fails to launch, a naked `except Exception:` catches the error, sets `browser_page = None`, and silently falls back to static fetching.
4. **Permanent Depth & Provenance Amnesia (P1)**: `PageRecord.depth` and `PageRecord.parent_url` are hardcoded to `0` and `""` respectively on every single page record created. Crawl depth is never incremented, and tree hierarchy is never tracked.
5. **Zero Mid-Crawl Persistence & All-or-Nothing Loss (P1)**: Crawled pages are held solely in Python memory (`pages: list[PageRecord]`). If a crawl of 500 pages fails on page 499, all 499 pages are discarded; nothing is committed to SQLite until the full loop completes.
6. **No In-Flight Cancellation (P1)**: An active crawl cannot be paused or aborted via API/UI. The `/crawls/{id}/pause` endpoint explicitly rejects running crawls with HTTP 409 (`status not in {'queued', 'retryable'}`).
7. **HTTP Client & Event Loop Churn (P2)**: In `thread` mode, a brand new `httpx.Client` is created and destroyed for every single URL (zero connection pooling). In `async` mode, a brand new event loop and `httpx.AsyncClient` are created and destroyed for every batch.
8. **SSRF DNS Rebinding Gap (P2)**: Hostname validation in `validate_hostname_ssrf()` is lexical only; DNS is not pre-resolved at socket connection time, leaving a vulnerability to DNS rebinding attacks pointing to loopback or cloud metadata.

---

## 2. End-to-End Architecture Map & Actual Execution Graph

Tracing a user crawl request from API submission to SQLite persistence:

```
[User Request / Web UI]
         │  POST /crawls (Form Data: start_url, mode, executor_mode, max_urls, delay_seconds, etc.)
         ▼
[app/main.py: _parse_request()]
         │  Normalizes start_url, validates inputs, checks ownership acknowledgment
         ▼
[app/database.py: create_crawl()]
         │  Inserts row into `crawls` table with status='queued'
         │  Signals worker_wake.set()
         ▼
[app/main.py: _worker_loop()]  <--- Runs in single background daemon thread
         │  Calls database.claim_next_job() -> status becomes 'running'
         ▼
[app/main.py: _run_claimed_crawl()]
         │  Instantiates CrawlEngine(settings)
         │  Calls CrawlEngine.run(crawl_request, progress)
         ▼
============================ CRAWL ENGINE EXECUTION ============================
[app/crawler.py: CrawlEngine.run()]
         │
         ├── Mode Check: executor_mode == 'serial'?
         │     │
         │     ├── YES: Executes inline serial loop (app/crawler.py:330-405)
         │     │     ├── Client: Reuses single httpx.Client across URLs
         │     │     └── Browser: If render_enabled=True, launches Playwright Chromium
         │     │
         │     └── NO ('thread', 'async', 'process'):
         │           Calls _run_static_mode() (app/crawler.py:236-306)
         │           [CRITICAL: Browser rendering is completely bypassed!]
         │
         ├── [Frontier Initialization]
         │     Queue: in-memory deque([start_url])
         │     Queued set: in-memory set([start_url])
         │     Seen hashes: dict() (in-memory)
         │     Seen canonicals: dict() (in-memory)
         │
         ├── [Robots.txt Evaluation]
         │     Calls _robots() -> synchronous HTTP GET /robots.txt
         │     If 200: parses robotparser.RobotFileParser()
         │     If error: sets allow_all = True
         │
         ├── [Batch Extraction & Execution Loop]
         │     Pulls batch of size _worker_count(request) from queue
         │     Checks robots.can_fetch()
         │     │
         │     ├── If 'async':
         │     │     Creates new event loop via asyncio.run()
         │     │     Creates new httpx.AsyncClient
         │     │     Fetches batch concurrently via asyncio.gather()
         │     │
         │     ├── If 'thread':
         │     │     Creates ThreadPoolExecutor(max_workers=thread_workers)
         │     │     Fetches URLs via _thread_fetch_with_gate()
         │     │     [CRITICAL: Each URL creates a NEW httpx.Client]
         │     │     [CRITICAL: thread_gate lock serializes sleep delay]
         │     │
         │     └── If 'process':
         │           [CRITICAL: Fetches URLs SEQUENTIALLY in main thread!]
         │           Dispatches CPU parsing to ProcessPoolExecutor
         │
         ├── [Response Materialization: _build_page()]
         │     Extracts headers, content_type, etag, last_modified
         │     Parses HTML via BeautifulSoup or documents.py:extract_document_text()
         │     If serial & browser active: calls _render() for dynamic DOM
         │     Discovers internal links via app/parser.py:extract_links()
         │     Checks deduplication: canonical tag match OR content_hash match
         │
         ├── [Frontier Discovery: _enqueue_discovered()]
         │     Normalizes discovered target URLs
         │     Filters by is_same_host()
         │     Enqueues new URLs if len(queued) < max_urls
         │
         └── [Loop Termination]
               Terminates when queue is empty OR len(pages) >= max_urls
================================================================================
         ▼
[app/main.py: _run_claimed_crawl() post-processing]
         │
         ├── 1. SEO Analysis: analyze_pages(pages, links)
         ├── 2. DB Persistence: database.replace_pages_and_links(crawl_id, pages, links)
         │      [CRITICAL: Entire crawl written in one single all-or-nothing transaction!]
         ├── 3. Issues Persistence: database.replace_issues(crawl_id, issues)
         ├── 4. Knowledge Indexing: extract_pages_knowledge() -> replace_knowledge_chunks()
         ├── 5. Status Update: status='completed', completed_at=now()
         └── 6. Automations: _fire_crawl_completed_workflows()
```

---

## 3. Engine Forensics & Concurrency Execution Matrix

| Engine | Entrypoint | Scheduler | Fetcher Implementation | Concurrency Model | Shared Components | Fallback Path | Failure Propagation | Verification Status |
|:---|:---|:---|:---|:---|:---|:---|:---|:---:|
| **`serial`** | `CrawlEngine.run()` L330 | In-memory `deque` FIFO loop | Single persistent `httpx.Client` + optional sync Playwright | 1 (strictly serial) | `_fetch()`, `_render()`, `_build_page()` | Catches Playwright launch failure; silently degrades to static | Per-page fetch error recorded in `PageRecord`; unhandled crashes job | **PARTIAL** |
| **`thread`** | `_run_static_mode()` L281 | Batch slices of `thread_workers` | `_thread_fetch_with_gate()` -> new `httpx.Client` per URL | Multi-threaded HTTP fetches, serialized during sleep by `thread_gate` | `_run_static_mode()`, `_materialize_static()` | Ignores `render_enabled=True`; always static | Traps HTTP errors into page record; thread crash bubbles to job failure | **PARTIAL** |
| **`async`** | `_run_static_mode()` L260 | Batch slices of `async_concurrency` | `_fetch_one_async()` with batch-scoped `httpx.AsyncClient` | Coroutine `asyncio.gather` within batch; loop recreated per batch | `_run_static_mode()`, `_materialize_static()` | Ignores `render_enabled=True`; nested loop uses 1-thread ThreadPool | Traps HTTP errors into page record; unhandled coroutine error crashes job | **PARTIAL** |
| **`process`** | `_run_static_mode()` L272 | Batch slices of `process_workers` | **Sequential main-thread HTTP** via list comprehension | **Pseudo-concurrent**: I/O is sequential in parent; only HTML parsing in workers | `_thread_fetch_with_gate()`, `_materialize_static_process()` | Ignores `render_enabled=True`; I/O never runs in worker processes | `except Exception: raise RuntimeError("Process executor mode failed")` | **FAILED / FAKE** |

### Detailed Engine Architectural Deficiencies:

#### 1. Multiprocess Mode (`process`) is Broken by Design
In `app/crawler.py` lines 272–279:
```python
elif self._executor_mode(request) == "process":
    try:
        fetched = [self._thread_fetch_with_gate(url, thread_gate, last_request, request.delay_seconds) for url in batch]
        with ProcessPoolExecutor(max_workers=self.settings.process_workers) as executor:
            processed = list(executor.map(_materialize_static_process, [(self.settings, request, result) for result in fetched]))
```
- **The Reality**: The list comprehension `[self._thread_fetch_with_gate(...) for url in batch]` executes synchronously and sequentially in the parent process. The worker processes in `ProcessPoolExecutor` receive the already-downloaded raw bytes to execute BeautifulSoup parsing.
- **Verdict**: Multiprocess crawling does **not** provide parallel network fetching. It adds massive IPC serialization overhead for HTML parsing without network parallelism.

#### 2. Thread Mode Sleep Lock Serialization
In `app/crawler.py` lines 201–206:
```python
def _wait_thread_slot(self, gate: Lock, last_request: dict[str, float], delay_seconds: float) -> None:
    with gate:
        pause = delay_seconds - (time.monotonic() - last_request["value"])
        if pause > 0:
            time.sleep(pause)
        last_request["value"] = time.monotonic()
```
- **The Reality**: All worker threads share a single `thread_gate` lock. If `delay_seconds = 1.0`, thread 0 sleeps for 1.0s while **holding the lock**. Threads 1, 2, and 3 are blocked waiting to acquire `gate`. They do not begin fetching until the previous thread releases the lock.
- **Verdict**: Thread dispatch is completely serialized.

#### 3. Async Mode Event Loop & Client Churn
In `app/crawler.py` lines 260–270 & 212–217:
- Every iteration of `while queue:` calls `asyncio.run(self._async_batch(...))`.
- `asyncio.run()` creates a brand new asyncio event loop, runs the batch, closes the loop, and destroys it.
- Inside `_async_batch`, `async with httpx.AsyncClient(...) as client:` creates a brand new client, negotiates TLS, fetches the batch, and closes all sockets.
- **Verdict**: Severe resource churn, zero connection pooling across batches, high overhead.

---

## 4. Fetch Strategy Forensics: Static vs Browser

| Requested Mode | Requested Executor | Actual Fetch Strategy | Escalation / Fallback Behavior | Observable in UI / DB? |
|:---|:---|:---|:---|:---:|
| `render_enabled=False` | `serial` | Static HTTP (`httpx.Client`) | None. Direct static fetch. | Yes |
| `render_enabled=False` | `thread` | Static HTTP (`ThreadPoolExecutor`) | None. Direct static fetch. | Yes |
| `render_enabled=False` | `async` | Static HTTP (`httpx.AsyncClient`) | None. Direct static fetch. | Yes |
| `render_enabled=False` | `process` | Static HTTP (Sequential fetch + Process parse) | None. Direct static fetch. | Yes |
| `render_enabled=True` | `serial` | Playwright Chromium (`browser_page.goto`) | **Silent fallback**: If browser fails to launch, sets `browser_page=None`, silently fetches static | **NO** (Only recorded as `render_error` string) |
| `render_enabled=True` | `thread` | **Static HTTP ONLY** | **Silent bypass**: Browser is never launched; static fetch used | **NO** (Completely unobservable) |
| `render_enabled=True` | `async` | **Static HTTP ONLY** | **Silent bypass**: Browser is never launched; static fetch used | **NO** (Completely unobservable) |
| `render_enabled=True` | `process` | **Static HTTP ONLY** | **Silent bypass**: Browser is never launched; static fetch used | **NO** (Completely unobservable) |

### Playwright Resource Lifecycle Deficiencies:
1. `context = browser.new_context(...)` is created, but `context.close()` is never called in `finally`.
2. A single `browser_page` is reused across all URLs in the crawl loop. If a page causes memory leakage or crashes the tab, subsequent pages in the crawl fail.
3. No per-page isolation or context cleanup.

---

## 5. Frontier Forensics: Queue, Visited, Depth & Traps

### 5.1 Depth & Parent Provenance Amnesia (P1)
- `PageRecord` defines `depth: int = 0` and `parent_url: str = ""`.
- In `_build_page()`:
  - Line 107 has signature: `def _build_page(..., parent_url: str = "", depth: int = 0)`
  - When called from `_materialize_static` (L225): `parent_url` and `depth` are omitted.
  - When called from `run` (L377): `parent_url` and `depth` are omitted.
- **Result**: **Every page in the database has `depth = 0` and `parent_url = ""`**. Depth limits are impossible to enforce because depth is never incremented.

### 5.2 Redirect Destination Duplication Bug
- In `_fetch()`: When `http://example.com/a` redirects to `http://example.com/b`, `_fetch` returns final response from `/b`.
- `queued` set only contains `http://example.com/a`.
- If `/c` later links to `http://example.com/b`, the check `target in queued` returns `False`.
- The crawler enqueues `http://example.com/b` and fetches it again, creating duplicate page records in the database.

### 5.3 Premature Discovery Frontier Halting
In `_enqueue_discovered` line 428:
```python
if not target or target in queued or len(queued) >= request.max_urls:
    continue
```
- `request.max_urls` is the budget for **crawled pages**, but line 428 caps **discovered candidate URLs** in the frontier!
- If the homepage has 500 links and `max_urls = 100`, only the first 100 links on the homepage are added to `queued`.
- Once `len(queued) == 100`, **all future link discovery is permanently halted**. If any of those 100 URLs are 404s, redirects, or duplicates, the crawl terminates prematurely without discovering deeper pages.

### 5.4 API Pagination Budgeting
In `_enqueue_discovered` lines 431–436:
- `detect_api_pagination(target)` checks for parameters: `skip`, `offset`, `page`, `p`, `start`, `from`, `limit`, `size`.
- Caps requests per path at 3, or offset value $> 90$.
- **Finding**: Well-implemented guard against infinite API pagination loops, but hardcoded to 3 pages without configuration override.

---

## 6. Error Handling & Exception Swallowing Forensics

| File & Line | Code Snippet | Exception Caught | Actual Behavior | Severity | Root Cause & Impact |
|:---|:---|:---|:---|:---:|:---|
| `app/crawler.py:353` | `except Exception: browser_page = None` | `Exception` | Silently swallows browser crash | **P1** | Hides missing Chromium, driver errors, or memory faults. Crawl silently proceeds in static mode. |
| `app/crawler.py:426` | `except Exception: continue` | `Exception` | Silently skips link | **P2** | Swallows URL parsing errors without logging or diagnostics. |
| `app/crawler.py:104` | `except Exception as exc: return "", "", f"Rendered inspection failed: ..."` | `Exception` | Returns empty rendered strings | **P2** | Browser timeouts or navigation errors are recorded as page strings, but no retry is attempted. |
| `app/main.py:160` | `except Exception as exc: database.defer_or_pause_job(...)` | `Exception` | Drops all in-memory pages | **P1** | A single crash at page 499 of 500 discards all 499 fetched pages; nothing is saved to DB. |
| `app/main.py:173` | `except Exception: continue` | `Exception` | Silently skips workflow | **P3** | Automation failure is suppressed. |

---

## 7. Resource Management & Concurrency Lifecycle Forensics

1. **HTTP Connection Pooling**:
   - `serial` mode: **Pooled** (single `httpx.Client` used in loop).
   - `thread` mode: **NOT Pooled** (new `httpx.Client` opened and closed per URL).
   - `async` mode: **NOT Pooled across batches** (new `httpx.AsyncClient` opened and closed per batch).
   - `process` mode: **NOT Pooled** (new `httpx.Client` opened and closed per URL).
2. **Executor Churn**:
   - In `thread` mode: `with ThreadPoolExecutor(...) as executor:` is executed **inside the while loop on every batch**. Threads are created, pooled for 2 URLs, and destroyed every single iteration.
   - In `process` mode: `with ProcessPoolExecutor(...) as executor:` is executed **inside the while loop on every batch**. New OS processes are spawned, mapped, and terminated on every batch.
3. **Database Concurrency**:
   - Database operations use `with self.connect() as conn:`. SQLite handles write locking via WAL mode, but since only one crawl runs at a time (controlled by `_worker_loop`), database concurrency contention is low.
   - However, because persistence only occurs at crawl completion, intermediate progress cannot be queried by other processes.

---

## 8. Security & SSRF Defense Forensics

### 8.1 Current Defenses in `app/urltools.py`:
- `validate_hostname_ssrf()` detects:
  - Blocked hostnames: `localhost`, `metadata.google.internal`, AWS/GCP/Alibaba metadata endpoints.
  - IP literals in all encodings: standard decimal (`127.0.0.1`), octal (`0177.0.0.1`), hex (`0x7f000001`), dword (`2130706433`), IPv6-mapped IPv4 (`::ffff:127.0.0.1`).
  - Private / loopback / link-local / multicast ranges.
- URL credential stripping: URLs with `user:pass@host` are rejected with `UrlValidationError`.
- Token redaction in URLs and text.

### 8.2 Discovered Security Gaps:
1. **No Pre-Connection DNS Resolution (DNS Rebinding Vulnerability)**:
   - `validate_hostname_ssrf("safe.evil.com")` passes if `safe.evil.com` is a domain name.
   - If `safe.evil.com` resolves via DNS to `169.254.169.254` or `127.0.0.1`, `httpx.Client.get()` connects directly to the private address!
   - Neither `_fetch()` nor `httpx.Client` validates the resolved socket IP address before sending HTTP requests.
2. **Redirect DNS Rebinding**:
   - When following redirects, `current = normalize_url(location)` checks the redirect URL string, but also lacks socket IP validation.

---

## 9. Test Forensics & Test Gap Matrix

| Test File | Test Name | What Test Claims to Test | What Test ACTUALLY Does | Test Gap Severity |
|:---|:---|:---|:---|:---:|
| `test_playwright_browser.py` | `test_crawl_engine_playwright_rendering` | Claims to test `CrawlEngine` Playwright rendering | Instantiates `CrawlEngine`, but **never calls `engine.run()`**! Manually runs `sync_playwright` on a hardcoded HTML string | **CRITICAL (P0)** |
| `test_concurrency.py` | `test_static_executor_modes_preserve_page_records` | Claims to test `thread`, `async`, and `process` executor modes | Monkeypatches `_fetch_one_sync` and `_async_batch` with instant dummy returns; **zero network I/O or concurrency executes** | **HIGH (P1)** |
| `test_concurrency.py` | `test_thread_executor_performs_bounded_parallel_work` | Tests parallel execution of thread mode | Uses dummy sleep; does not test real HTTP or connection pooling | **MEDIUM (P2)** |
| `test_controls_and_exports.py` | Various crawl control tests | Tests crawl lifecycle | Tests database state transitions, but does not test stopping a running worker | **MEDIUM (P2)** |

---

## 10. Phase 2 Formal Requirements Specification

The following formal requirement contracts govern Phase 2 (Crawler Core):

| Requirement ID | Requirement Name | Precise Contract & Acceptance Criteria |
|:---|:---|:---|
| **REQ-CRAWL-001** | **Engine Contract** | All 4 crawl executors (`serial`, `thread`, `async`, `process`) must implement a common `CrawlerEngine` interface with identical inputs (`CrawlRequest`, `progress_callback`, `cancellation_token`) and identical output guarantees (`PageRecord` list, `LinkRecord` list, status). |
| **REQ-CRAWL-002** | **URL Frontier Correctness** | Frontier must store `(url, depth, parent_url)`. Depth must increment correctly from seed (`depth=0`). Enqueueing must check canonical and redirected URLs. `max_urls` budget must apply to **crawled pages**, not candidate links. |
| **REQ-CRAWL-003** | **Serial Independence** | `serial` mode must execute single-threaded, reusing an HTTP connection pool, with full browser rendering support when enabled. |
| **REQ-CRAWL-004** | **Threaded Independence** | `thread` mode must execute parallel network I/O using a shared, persistent `httpx.Client` connection pool. Per-host politeness must not serialize requests across different hosts. |
| **REQ-CRAWL-005** | **Coroutine Independence** | `async` mode must execute within a persistent asyncio event loop and single persistent `httpx.AsyncClient` session across the entire crawl lifecycle. Zero loop recreation. |
| **REQ-CRAWL-006** | **Multiprocess Independence** | `process` mode must perform genuine parallel network fetching and CPU parsing across independent worker processes. No sequential main-thread fetching. |
| **REQ-CRAWL-007** | **No Silent Fallback** | Engines must never silently fall back or degrade. If an engine or browser fails, it must emit explicit diagnostics, record the failure in the database, and notify the operator. |
| **REQ-CRAWL-008** | **Fetch Strategy Transparency** | Requested fetch mode (`static` vs `browser`) must be strictly honored or fail explicitly. If browser rendering is requested in an unsupported mode, the request must fail with clear error. |
| **REQ-CRAWL-009** | **Retry & Budget Correctness** | Exponential backoff on HTTP 429/5xx must honor `Retry-After` (both seconds and HTTP-dates). Retry attempts must decrement a per-crawl retry budget. |
| **REQ-CRAWL-010** | **Robots & Politeness** | Robots.txt must be fetched, parsed, and respected per-host. Politeness delay (`delay_seconds`) must be tracked per host/domain, not globally locked. |
| **REQ-CRAWL-011** | **Incremental Persistence & Recovery** | Crawled pages must be persisted incrementally to SQLite in batches (e.g. every 5 pages or per page), not held exclusively in memory until crawl end. |
| **REQ-CRAWL-012** | **Cancellation & Graceful Shutdown** | Active crawls must check cancellation tokens on every page. Operators must be able to pause, cancel, or abort an in-flight crawl at any second. |
| **REQ-CRAWL-013** | **SSRF DNS Rebinding Defense** | Socket connections must pre-resolve DNS and validate destination IP address against private/metadata ranges before establishing TCP handshake. |
| **REQ-CRAWL-014** | **Crawl Observability** | Real-time progress updates must report pages crawled, queue size, active workers, current URL, and per-engine status. |
| **REQ-CRAWL-015** | **Resource Safety & Leak Prevention** | All HTTP connections, browser contexts, thread pools, and process pools must be deterministically closed via context managers and finalizers. |
| **REQ-CRAWL-016** | **Performance & Soak Verification** | All 4 engines must pass live benchmark soak tests under simulated high latency (200ms) and network drops without deadlocks or memory leaks. |

---

## 11. Defect Classification & Priority Backlog

### P0 (Critical Architectural Defects — Blockers for Production):
1. **DEF-P0-01**: `process` executor mode does not execute multiprocess network fetching. Fetches sequentially in main thread.
2. **DEF-P0-02**: `thread`, `async`, and `process` modes silently bypass `render_enabled=True` (zero browser rendering).
3. **DEF-P0-03**: `test_crawl_engine_playwright_rendering` test is fake (does not call `CrawlEngine`).

### P1 (High Severity Functional Defects):
4. **DEF-P1-01**: Depth and parent URL are hardcoded to `0` and `""` on all pages. Tree provenance is lost.
5. **DEF-P1-02**: Crawled pages held only in memory; single crash at end loses all crawl results.
6. **DEF-P1-03**: No in-flight cancellation or pause support for running crawls.
7. **DEF-P1-04**: Silent fallback on Chromium launch failure.
8. **DEF-P1-05**: Frontier halts URL discovery prematurely when `len(queued) >= max_urls`.
9. **DEF-P1-06**: Redirect target URLs not tracked in `queued`, causing duplicate fetches.

### P2 (Medium Severity Operational & Security Deficiencies):
10. **DEF-P2-01**: Zero HTTP connection pooling in `thread`, `async`, and `process` modes (client churn).
11. **DEF-P2-02**: Async event loop and thread pool recreated on every batch inside while loop.
12. **DEF-P2-03**: Global lock serializes thread delay across all workers.
13. **DEF-P2-04**: DNS rebinding vulnerability in SSRF check (no socket-level IP validation).

### P3 (Low Severity Cleanups):
14. **DEF-P3-01**: Browser context is not explicitly closed in finally block.
15. **DEF-P3-02**: Hardcoded API pagination budget (max 3 pages).

---

## 12. Recommended Phase 2 Subphase Execution Plan

To remediate these issues systematically without regressions, Phase 2 will execute across 5 disciplined subphases:

1. **Phase 2A — Engine Architecture & Contract Unification**:
   - Define formal `EngineProtocol` with `EngineResult` and `CancellationToken`.
   - Implement genuine connection-pooled HTTP client session management.
   - Build unified URL frontier tracking `(url, depth, parent_url)` with redirect tracking and correct page-based budget capping.
2. **Phase 2B — Concurrency Engines Remediation**:
   - Fix `process` mode to execute genuine multiprocessing network fetching.
   - Fix `thread` mode with per-domain rate limiting and shared connection pool.
   - Fix `async` mode with single persistent event loop and AsyncClient session.
3. **Phase 2C — Fetch Strategy & Browser Parity**:
   - Explicit browser escalation and transparent error reporting (no silent fallbacks).
   - Multi-mode browser support or explicit fail-fast validation when browser requested with incompatible executor.
   - Context isolation per page in browser rendering.
4. **Phase 2D — Incremental Persistence, Cancellation & Resilience**:
   - Incremental SQLite page/link writing during crawl loop.
   - Real-time in-flight crawl pause, cancel, and abort.
   - Durable crawl resume from existing database records.
5. **Phase 2E — Security (SSRF DNS Resolution) & Soak Verification**:
   - Pre-socket DNS resolution to prevent DNS rebinding attacks.
   - Real HTTP live server soak test across all 4 engines under latency and 429 backoff.
   - Phase 2 release gate certification.

---

## 13. Baseline Forensic Sign-Off

Phase 2 baseline forensic reconstruction is complete. All architectural truths, hidden fallbacks, test mocks, and technical debt have been laid bare.

**Next Step**: Await user command to begin **Subphase 2A — Engine Architecture & Contract Unification**.
