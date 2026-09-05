# RELEASE GATES & CRITERIA

This document defines the strict, non-negotiable release gates for every phase of the project. No phase may be marked `PASSED` without reproducible test evidence.

---

## Gate Status Summary

| Phase | Title | Gate Status | Certified Date | Key Evidence / Tests |
|:---:|:---|:---:|:---:|:---|
| **0** | Baseline & Forensic Audit | **PASSED** | 2026-09-04 | 125 tests cataloged, historic bugs identified, memory files initialized |
| **1** | Evaluation Integrity | **PASSED** | 2026-09-05 | `test_metrics_math.py` (8/8), 155-query benchmark split evaluation (3/3), Brier = 0.0433 |
| **2** | Crawler Core | **PARTIAL** | Pending | Concurrency & SSRF tests pass (26 tests); core retry/timeout limits verified |
| **3** | Universal Extraction | **PARTIAL** | Pending | JSON deep semantics, HTML, PDF extractors pass; token redaction verified |
| **4** | Knowledge/Indexing/Search | **PARTIAL** | Pending | Hybrid BM25+Vector search, RRF, chunk provenance verified in benchmark |
| **5** | RAG Intelligence | **PARTIAL** | Pending | Claim grounding, citation verifier, and dynamic answer planner verified |
| **6** | Web Intelligence | **PARTIAL** | Pending | Crawl coverage set union, Playwright DOM rendering verified |
| **7** | UI/UX & API | **PARTIAL** | Pending | E2E FastAPI tests, accessible views, CSV/JSON exports verified |
| **8** | Final Certification | **UNVERIFIED**| Pending | Final release certification gate pending completion of full phase cycle |

---

## Phase Gate Criteria

### PHASE 0: Baseline & Forensic Audit
- [x] Full codebase inspected.
- [x] All 7 persistent memory files initialized (`PROJECT_MASTER_SPEC.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `CHANGELOG.md`, `KNOWN_ISSUES.md`, `TEST_MATRIX.md`, `RELEASE_GATES.md`).
- [x] Baseline test suite execution recorded.
- [x] False positives, brittle shortcuts, and unproven claims identified.
- **GATE STATUS**: **PASSED**

### PHASE 1: Evaluation Integrity
- [x] All normalized IR metrics mathematically bounded in $[0.0, 1.0]$.
- [x] Zero artificial clamping (`min(metric, 1.0)` eliminated).
- [x] Hand-computed ground truth tests with edge cases (zero retrieved, zero relevant, ties, duplicates).
- [x] 155-query benchmark partitioned into 5 explicit splits (Development: 40, Calibration: 25, Blind Test: 40, Adversarial: 30, Regression: 20).
- [x] Calibration Brier score $\le 0.15$ and ECE $\le 0.15$ demonstrated.
- [x] Benchmark ground truth decoupled from production answer planner.
- **GATE STATUS**: **PASSED**

### PHASE 2: Crawler Core

#### Subphase 2A: Crawler Contracts + State Model
- [x] Stable crawler contract (`CrawlerEngineProtocol`, `CrawlRequest`, `CrawlResult`) established without forcing engines into monolithic execution.
- [x] All 5 required termination states (`SUCCESS`, `PARTIAL`, `FAILED`, `CANCELLED`, `BUDGET_EXHAUSTED`) and operational states (`QUEUED`, `RUNNING`, `PAUSED`, `RETRYABLE`) defined in `CrawlStatus`.
- [x] Backward-compatible sequence unpacking (`pages, links, robots = result`, `result[0]`, `len(result) == 3`) verified.
- [x] No-silent-fallback invariants (`fallback_occurred`, `fallback_reason`) implemented and tested.
- [x] `FrontierItem` defined with URL, depth, parent_url, hashability, and IPC picklability.
- [x] `CancellationToken` implemented with thread-safe cooperative cancellation and picklability for multiprocess execution.
- [x] `PageRecord` extended with full provenance (`normalized_url`, `depth`, `parent_url`, `fetch_strategy`, `requested_fetch_strategy`, `actual_fetch_strategy`, `crawler_engine`, `response_bytes`, `duration_ms`, `error_category`, `headers`).
- [x] SQLite schema extended in `app/database.py` with automatic column migrations and retrieval verification.
- [x] Contract test suite (`tests/test_crawler_contracts.py`) passes 16/16 tests. Full regression suite passes 145/145 tests.
- [x] Fresh-Eyes Architecture Review completed by subagent; all P0/P1 contract issues addressed.
- **SUBPHASE 2A GATE STATUS**: **PASSED**

#### Subphase 2B: URL Normalization + Frontier + Crawl Lifecycle
- [x] RFC 3986 URL normalization policy: scheme/host casing, default port stripping, dot segment removal, percent-encoding canonicalization, deterministic query sorting & deduplication, marketing parameter stripping.
- [x] Sensitive parameters (`token`, `api_key`, `secret`) preserved by default during HTTP crawler dispatch to avoid broken requests; opt-in redaction for reports and exports.
- [x] Conservative trailing slash policy (default `"strip"`, preserving slash for redirect `Location` header resolution to prevent redirect loops).
- [x] Strict 8-state frontier finite state machine (`DISCOVERED`, `QUEUED`, `FETCHING`, `COMPLETED`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `SKIPPED`, `DUPLICATE`).
- [x] Invalid transition rejection (`InvalidStateTransitionError`) and idempotent terminal state handling preventing race conditions or worker leaks.
- [x] Exponential backoff retry pool with jitter/delay calculation and max retry enforcement.
- [x] Redirect destination alias mapping and target completion tracking (`enqueue_target=False`) preventing duplicate fetches.
- [x] Canonical tag duplicate detection with domain filtering.
- [x] Exact mathematical frontier accounting reconciliation (`admitted == queued + fetching + completed + failed + skipped + duplicate`).
- [x] Controlled crawler fixture (`tests/controlled_crawler_server.py`) with 19 deterministic endpoints verifying circular link termination, A-B-A cycle bounding, fragment deduplication, canonical duplicates, depth bounds, page budgets, and 429 retries.
- [x] 100% test pass rate across targeted suites (52/52) and full repository regression suite (182 passed, 2 skipped, 0 failed).
- [x] Fresh-Eyes subagent review completed with all findings addressed.
- **SUBPHASE 2B GATE STATUS**: **PASSED**

#### Subphase 2C: Concurrency Engines (Threaded, Async, Multiprocess)
- [x] Four genuinely independent concrete engines (`SerialCrawlerEngine`, `ThreadedCrawlerEngine`, `CoroutineCrawlerEngine`, `MultiprocessCrawlerEngine`).
- [x] Threaded engine with per-domain politeness throttling (`DomainPolitenessThrottler`) and shared connection pool (`httpx.Client(transport=HTTPTransport(limits=Limits(...)))`).
- [x] Async coroutine engine with persistent single event loop, `AsyncClient`, semaphore-bounded concurrency, and `AsyncDomainPolitenessThrottler`.
- [x] Multiprocess engine with genuine parallel process socket fetching and signal parsing in spawned child processes (`multiprocessing.get_context("spawn")`, `app/multiprocess_worker.py`).
- [x] Proof of non-serialized parallel execution: overlapping intervals, server peak concurrency $\ge 2$, and distinct child worker PIDs verified in `tests/test_concurrency_proof.py` (4/4 passed).
- [x] Shared Engine Conformance Suite: 18 requirements verified identically across all 4 engines in `tests/test_engine_conformance.py` (48/48 passed).
- [x] Cross-engine deterministic result consistency verified in `tests/test_engine_consistency.py` (1/1 passed).
- [x] Fail-closed anti-silent fallback verified in `tests/test_engine_failure_fallback.py` (5/5 passed).
- [x] Zero regressions across entire repository test suite (238 passed, 2 skipped, 0 failed across 240 items).
- **SUBPHASE 2C GATE STATUS**: **PASSED**

#### Subphase 2D: Resilient Frontier & Persistence
- [ ] Incremental page-by-page persistence to SQLite during crawl.
- [ ] URL frontier tracking (url, depth, parent_url) with redirect targets queued.
- [ ] Pause, resume, and cancellation via API / CLI endpoints.
- **SUBPHASE 2D GATE STATUS**: **PENDING**

#### Subphase 2E: Security, Politeness & Resource Verification
- [ ] Pre-socket DNS resolution blocking private/metadata IPs across all IP formats.
- [ ] Resource leak tests verifying zero HTTP client or browser zombie processes.
- **SUBPHASE 2E GATE STATUS**: **PENDING**

- **GATE STATUS**: **PARTIAL (Subphases 2A, 2B, 2C PASSED)**

### PHASE 3: Universal Extraction
- [x] Preservation of JSON deep semantics, scalar types, and nested object relationships.
- [x] Multi-format extractors for HTML, rendered DOM, JSON, and PDF/Markdown.
- [x] Secret token redaction across URLs, headers, and text.
- [ ] Extended XML / RSS / Atom feed validation.
- **GATE STATUS**: **PARTIAL**

### PHASE 4: Knowledge / Indexing / Search
- [x] Chunk deduplication and heading path provenance preservation.
- [x] Hybrid indexing combining SQLite FTS5 (BM25) and dense float vectors.
- [x] Reciprocal Rank Fusion (RRF) combining lexical and semantic rankings.
- [x] Modular `EmbeddingProvider` interface supporting hash fallback and neural models.
- [ ] Incremental index updates and index rebuild performance benchmarks.
- **GATE STATUS**: **PARTIAL**

### PHASE 5: RAG Intelligence
- [x] Query-type classification across 12 distinct query categories.
- [x] Dynamic, domain-agnostic answer planning (eliminated hardcoded query shortcuts).
- [x] Atomic claim extraction and citation verification (PASS, PARTIAL, FAIL).
- [x] Conflict detection between contradictory sources.
- [x] Strict abstention ($confidence = 0.0$) on unanswerable and adversarial questions.
- [ ] Extended multi-lingual support and complex cross-document graph reasoning.
- **GATE STATUS**: **PARTIAL**

### PHASE 6: Web Intelligence
- [x] Crawl coverage metric computed via exact set union of crawled and discovered URLs.
- [x] Playwright dynamic DOM execution and error recovery.
- [x] Automated SEO issue detection (broken links, missing alt, canonical conflicts).
- [ ] Visual regression verification and screenshot diffing.
- **GATE STATUS**: **PARTIAL**

### PHASE 7: UI/UX & API Layer
- [x] FastAPI endpoints for crawls, knowledge search, question answering, and exports.
- [x] Accessible HTML templates with ARIA roles and semantic layout.
- [x] Client validation feedback and ownership acknowledgment.
- [ ] End-to-end frontend Cypress / Playwright user journey testing under simulated user loads.
- **GATE STATUS**: **PARTIAL**

### PHASE 8: Final Certification
- [ ] Independent blind-test evaluation executed after freezing all phases.
- [ ] 100% pass rate across all unit, integration, and security suites.
- [ ] Zero unverified production claims.
- [ ] Formal certification document signed off.
- **GATE STATUS**: **UNVERIFIED**
