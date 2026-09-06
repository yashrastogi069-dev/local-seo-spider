# PROJECT CHANGELOG

All notable changes, phase executions, and architectural transitions for Local SEO Spider & Semantic RAG are documented in this file.

---

## Current Status: Phase 0, Phase 1, Phase 2 Complete (2A-2G.1 Certified) / Ready for Phase 2H

### Current Phase State:
- **PHASE 0 (Baseline & Forensic Audit)**: COMPLETED / PASSED
- **PHASE 1 (Evaluation Integrity)**: COMPLETED / PASSED
- **PHASE 2 (Crawler Core)**: ACTIVE / SUBPHASES 2A-2G.1 CERTIFIED
  - **Subphase 2A (Contracts & State Model)**: COMPLETED / PASSED
  - **Subphase 2B (URL Normalization + Frontier + Crawl Lifecycle)**: COMPLETED / PASSED
  - **Subphase 2C (Four Independent Concurrency Engines)**: COMPLETED / PASSED & CERTIFIED
  - **Subphase 2D (Concurrency, Races, Failure & Resource Safety)**: COMPLETED / PASSED & CERTIFIED
  - **Subphase 2E (Static Fetch + Playwright + Smart Escalation)**: COMPLETED / PASSED & CERTIFIED
  - **Subphase 2F (Robots, Politeness, Retries & Crawl Budgets)**: COMPLETED / PASSED & CERTIFIED
  - **Subphase 2G (Resume, Recovery, Crash Safety & Embedding Auto-Fallback)**: COMPLETED / PASSED & CERTIFIED
  - **Subphase 2G.1 (Hosted Embedding Provider Architecture & Re-Embedding)**: COMPLETED / PASSED & CERTIFIED
- **Subphase 2H (SSRF Defense, Security & Allowed Hosts Enforcement)**: READY TO BEGIN
- **PHASE 3 (Universal Extraction)**: PENDING
- **PHASE 4 (Knowledge/Indexing/Search)**: PENDING
- **PHASE 5 (RAG Intelligence)**: PENDING
- **PHASE 6 (Web Intelligence)**: PENDING
- **PHASE 7 (UI/UX)**: PENDING
- **PHASE 8 (Final Certification)**: PENDING

---

## [Phase 2G.1: Hosted Embedding Provider Architecture] - 2026-09-06

### Added
- **`app/embeddings.py` Overhaul**:
  - Implemented provider-independent `EmbeddingProvider` Protocol with `embed(text, task_type)`, `embed_batch(texts, task_type)`, and `get_metadata()`.
  - Created `GeminiEmbeddingProvider` supporting Google Gemini REST API (`batchEmbedContents`), model configurability (default `text-embedding-004`), dimension customizability (default 768), secure `x-goog-api-key` header authentication, exponential retry backoff with jitter (0.8-1.2) and `Retry-After` adherence, fail-closed handling for HTTP 401/403 and 404, and bounded sub-batch chunking ($\le 100$).
  - Created `HashEmbeddingProvider` providing deterministic 384-dimensional Blake2b feature hashing for offline unit testing, zero-cost CI, and graceful fallback.
  - Created `SentenceTransformersProvider` wrapping local Hugging Face neural models with clean error isolation if optional dependencies are missing.
  - Created `NullEmbeddingProvider` enabling zero-vector BM25-only operation.
  - Implemented `ProviderHealth` categorization (`AVAILABLE`, `UNAVAILABLE`, `RATE_LIMITED`, `AUTHENTICATION_FAILED`, `TEMPORARY_FAILURE`, `MISCONFIGURED`, `UNVERIFIED_LIVE`).
  - Implemented `FallbackPolicy` modes (`FAIL_CLOSED`, `FALLBACK_TO_HASH`, `BM25_ONLY`, `AUTO`) with full diagnostic resolution tracking (`requested_provider`, `actual_provider`, `fallback_occurred`, `fallback_reason`, `degraded_mode`).
  - Implemented `resolve_embedding_provider(...)` and `build_embedding_provider(...)`.
  - Implemented `cosine_similarity(vec_a, vec_b)` with dimension matching validation.
- **Database Multi-Generation Vector Storage & Re-Embedding (`app/database.py`)**:
  - Added schema migration adding `model`, `dimension`, `created_at`, `content_hash`, and `metadata_json` to SQLite `vector_embeddings`.
  - Implemented `reembed_knowledge(crawl_id, embedder)` allowing seamless vector upgrades across existing crawled chunks without recrawling or mutating `pages` or `links`.
  - Implemented `get_vector_embeddings_metadata(crawl_id)`.
  - Hardened `search_hybrid_knowledge` to filter on `v.provider = ? AND (v.model = ? OR ? = '' OR v.model = '') AND v.dimension = ?`, strictly preventing cross-model or cross-dimension vector corruption.
- **API & Configuration Integration (`app/config.py`, `app/main.py`)**:
  - Added `gemini_api_key`, `embedding_fallback_policy`, `embedding_batch_size`, and `embedding_timeout_seconds` to `Settings`.
  - Pre-flight Gemini API key detection defaulting to `text-embedding-004` (768 dim).
  - Added POST `/crawls/{crawl_id}/knowledge/reembed` endpoint with background execution and forensic logging.
- **Test Suite (`tests/test_hosted_embeddings.py`)**:
  - 17 comprehensive test cases: single/batch embedding, sub-batch chunking, 401/403 fail-closed, 404 model validation, 429 rate limit with `Retry-After`, timeout retries, secret key redaction, fallback policy compliance, auto-resolution with/without keys, database vector metadata persistence, model re-embedding without recrawling, dimension mismatch prevention, and live smoke test.
- Recorded **ADR-016** in `DECISIONS.md` and Section 9 in `TEST_MATRIX.md`.

---

## [Phase 2G: Resume, Recovery, Crash Safety & Embedding Auto-Fallback] - 2026-09-06

### Added
- Created `tests/test_crawl_resume_and_recovery.py` (14 tests, 100% passing):
  - Frontier state persistence across all 8 lifecycle states (`discovered`, `queued`, `fetching`, `completed`, `failed_retryable`, `failed_final`, `skipped`, `duplicate`).
  - Crash recovery of in-flight `FETCHING` entries to `QUEUED` with `_active_workers` reset to 0.
  - Checkpoint transaction rollback safety under interruption (`BEGIN IMMEDIATE` in SQLite WAL mode).
  - Resumption across Serial, Threaded, Coroutine, and Multiprocess engines.
  - Idempotent database persistence: zero duplicate rows in `pages` and `links` on replay/resume.
  - Schema & engine version integrity validation (`IncompatibleStateError` on schema/major engine mismatch).
  - Fail-closed corrupt checkpoint error handling (`CorruptStateError`).
  - Preserved retry counts and exponential backoff windows across resume lifecycles.
  - Mathematical accounting reconciliation verification (`reconcile_accounting`).
  - Budget expansion un-skipping (`restore_state` un-skips `page_limit_reached` URLs when resumed with expanded budget).
- Created `crawl_frontier_checkpoints` table with index `idx_frontier_checkpoints_crawl_state` on `(crawl_id, state)`.
- Added `checkpoint_json`, `schema_version`, and `engine_version` columns to `crawls` table.
- Added `CURRENT_SCHEMA_VERSION = 1` and `CURRENT_ENGINE_VERSION = "2.0.0"` in `app/database.py`.
- Implemented `save_frontier_checkpoint`, `get_frontier_checkpoint`, `validate_checkpoint_compatibility`, `get_crawled_pages`, and `get_crawled_links` in `app/database.py`.
- Added atomic upsert semantics: `ON CONFLICT(crawl_id, url) DO UPDATE` in `pages`, and unique index `idx_links_crawl_source_target` with `ON CONFLICT(crawl_id, source_url, target_url) DO UPDATE` in `links`.
- Implemented `export_state`, `restore_state`, and `get_entries` in `CrawlFrontier` (`app/frontier.py`).
- Added `remaining_delay` serialization to `FrontierEntry` in `app/types.py` for monotonic time continuity across process restarts and OS reboots.
- Deduplicated `pages` and `links` by URL in `CrawlEngine._build_crawl_result` for in-memory uniqueness guarantees.
- Recorded ADR-015 in `DECISIONS.md`.

### Fixed
- **Embedding Provider `NameError` Crash**: Fixed undefined `logger` symbol in `app/main.py` when catching embedding provider errors, which previously broke crawl post-processing.
- **Embedding Provider Auto-Fallback**: Updated `Settings.from_environment()` in `app/config.py` to auto-detect `sentence_transformers` availability and cleanly default/fall back to `"hash"` provider when unavailable, preventing unhandled exceptions.

---

## [Phase 2F: Robots, Politeness, Retries & Crawl Budgets] - 2026-09-06

### Added
- Created `tests/test_robots_and_politeness.py` (12 tests):
  - RFC 9309 robots compliance: 5xx and 429 fail-closed / disallow-all, 4xx allow-all, malformed robots graceful handling, user-agent specificity.
  - Multi-host isolation in `DomainPolitenessThrottler` (slow/rate-limited domain A never stalls domain B).
  - Per-host concurrency bounds (`per_host_concurrency=1` serializes requests to same host).
  - `Crawl-delay` parsing and enforcement across Serial, Thread, Async, and Process engines.
- Created `tests/test_crawl_budgets.py` (14 tests):
  - Multi-engine crawl budget enforcement: `max_pages`, `max_depth`, `max_bytes`, `max_duration_seconds`, `redirect_limit`.
  - Deterministic state transition to `CrawlStatus.BUDGET_EXHAUSTED` with explicit `termination_reason`.
- Created `tests/test_infinite_site_defense.py` (7 tests):
  - Path loop cycle detection (`detect_path_loop`) skipping cyclic sub-sequences.
  - Cookieless session ID stripping (`;jsessionid=`, `/(S(...))/`, `;sid=`, `;phpsessid=`).
  - Pagination limits and soft-404 cryptographic text deduplication.
- Created `CrawlBudget` dataclass in `app/types.py` and integrated into `CrawlRequest`.
- Extended `app/urltools.py` with `detect_path_loop(url_or_path, max_repeats=3)` and session ID regexes in `normalize_url`.
- Enhanced `DomainPolitenessThrottler` and `AsyncDomainPolitenessThrottler` in `app/crawler.py` with dual `host` and `netloc` keying, and explicit `record_completion(url)` response tracking.
- Recorded ADR-014 in `DECISIONS.md`.

---

## [Phase 2E: Static Fetch + Playwright + Smart Escalation] - 2026-09-06

### Added
- Created `app/escalation.py`:
  - `should_escalate_to_browser()` evaluating page status, headers, and body content.
  - Regex detection for empty SPA root containers (`#root`, `#app`, `#__next`) matching arbitrary attributes.
  - Regex detection for bot/JS challenges (Cloudflare, PerimeterX, Datadome, reCAPTCHA, hCaptcha, Turnstile).
  - Anti-criteria enforcement: normal static HTML containing script tags (Google Analytics, Tag Manager, Facebook Pixel, tracking widgets) never triggers escalation.
  - Header case normalization (`headers_lower`) for RFC-compliant header matching.
- Created `app/browser.py`:
  - `PlaywrightBrowserSession` managing asynchronous Chromium lifecycle with lazy startup, context manager support (`async with`), per-render page isolation, hardened exception handling, and deterministic teardown.
  - Zero orphan process guarantee: browser, context, and page instances are guaranteed closed in `finally` blocks.
- Extended `app/types.py`:
  - Added `FetchMode.SMART = "smart"`.
  - Added `mode: str = "site"` and `fetch_mode: str = "static"` defaults to `CrawlRequest`.
  - Added 6 forensic fields to `PageRecord`: `requested_fetch_strategy`, `actual_fetch_strategy`, `escalated`, `escalation_reason`, `fetch_duration_ms`, `render_duration_ms`.
  - Added `pages_escalated: int = 0` to `CrawlResult` and implemented dictionary serialization/deserialization.
- Extended database schema in `app/database.py`:
  - Automatically migrated and persisted 7 Phase 2E columns in SQLite `pages` table.
- Extended `app/multiprocess_worker.py`:
  - Populated all Phase 2E forensic fields and empty `rendered_text: ""` for static worker fetches.
- Created 3 comprehensive verification test suites (26 tests):
  - `tests/test_fetch_strategy_static.py` (9 tests): static HTTP transport distinction, headers, status codes, content-types, gzip encodings, body truncation, timeout/network errors, fallback transparency.
  - `tests/test_fetch_strategy_playwright.py` (7 tests): Playwright lifecycle, lazy startup, per-render context/page isolation, broken JS recovery, navigation timeouts, zero orphan process leaks.
  - `tests/test_smart_escalation.py` (10 tests): empty SPA root containers, bot/JS challenges, anti-criteria enforcement, and multi-worker fallback tracking.
- Added ADR-013 to `DECISIONS.md`.

### Changed
- Refactored `CrawlEngine._run_serial` in `app/crawler.py` to support `FetchMode.STATIC`, `FetchMode.BROWSER`, and `FetchMode.SMART` with lazy Playwright startup, per-render isolation, and timing metrics.
- Updated `_run_threaded`, `_run_coroutine`, and `_run_multiprocess` to record static strategy and explicit `fallback_occurred=True` with descriptive `fallback_reason` when browser/smart mode is requested.
- Updated `_build_page`, `_error_page`, and `_build_crawl_result` to serialize all Phase 2E fields faithfully.

### Fixed
- Fixed `CrawlResult.to_dict()` omission of `pages_escalated` (DEF-2E-01).
- Fixed missing `fallback_reason` on smart multi-worker crawls without escalation (DEF-2E-02).
- Isolated per-page render exceptions preventing crawl worker aborts (DEF-2E-03).
- Supported arbitrary attribute orders and quotes in SPA container tags (DEF-2E-04).
- Normalized header casing in challenge detection (DEF-2E-05).
- Wrapped Playwright launch failures cleanly into `BrowserError` (DEF-2E-06).
- Guaranteed non-null `rendered_text` key in multiprocess worker payload (DEF-2E-07).

### Verified
- 26/26 Phase 2E tests passed.
- 306 passed, 2 skipped, 0 failed across full repository test suite (39 test modules).
- Fresh-eyes subagent review completed; all 7 findings resolved.
- Subphase 2E and Phase 2 overall release gates PASSED.

---

## [Phase 2D: Concurrency Stress, Failure Injection & Resource Safety] - 2026-09-06

### Added
- Database concurrency hardening in `app/database.py`:
  - Configured SQLite connection busy timeout to 30.0s (`PRAGMA busy_timeout = 30000;`).
  - Enabled Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) on initialization.
  - Verified concurrent multi-threaded writes across 10 simultaneous threads without lock errors or corruptions.
- Cooperative mid-flight cancellation & interruptible sleep in `app/crawler.py`:
  - Implemented `_sleep_interruptible` and `_async_sleep_interruptible` checking `cancellation_token.is_cancelled()` in 50ms intervals during politeness pauses and exponential retry backoffs.
  - Implemented `_safe_fetch` and `_safe_async_fetch` on `BaseCrawlerEngine` to transparently bridge cancellation tokens while supporting legacy 2-arg monkeypatched test stubs.
- Controlled server stress endpoints in `tests/controlled_crawler_server.py`:
  - Added endpoints for dropped mid-stream TCP connections, half-written response bodies, malformed gzip streams, 500 error storms, 429 rate-limiting bursts, rapid simultaneous discovery, and interleaved fast/slow responses.
- Created 3 dedicated verification suites (41 tests):
  - `tests/test_concurrency_stress.py` (15 tests): verified exact set deduplication under simultaneous duplicate discovery, rapid burst queue integrity, mixed fast/slow endpoints, 500/429 storms, cooperative cancellation (< 1.0s stop), and SQLite write contention.
  - `tests/test_failure_injection.py` (20 tests): verified adversarial failure handling across all 4 engines for dropped connections, truncated streams, malformed gzip, socket timeouts, and connection refused.
  - `tests/test_resource_safety.py` (6 tests): verified thread pool clean join with 0 leaked threads, multiprocess clean exit with 0 orphan processes, memory stability across 5 consecutive crawls (< 2.5MB drift), and SQLite transaction rollback.
- Added ADR-012 to `DECISIONS.md`.

---

## [Phase 2C: Four Independent Concurrency Engines] - 2026-09-06

### Added
- Implemented 4 concrete crawler engines in `app/crawler.py`:
  - `SerialCrawlerEngine`: Single-threaded, persistent HTTP connection pool.
  - `ThreadedCrawlerEngine`: Genuine multi-threaded parallel fetching via `ThreadPoolExecutor` and shared `httpx.Client(transport=HTTPTransport(limits=Limits(...)))`.
  - `CoroutineCrawlerEngine`: Persistent asyncio event loop and `httpx.AsyncClient` session across the entire crawl with bounded semaphore concurrency.
  - `MultiprocessCrawlerEngine`: Multi-process execution using `spawn` context with child worker tasks running in `app/multiprocess_worker.py`.
- Created `app/multiprocess_worker.py` top-level worker module for Windows `spawn` picklability, executing genuine socket-level HTTP requests and CPU signal extraction in child processes with `X-Client-PID` and `worker_pid` provenance.
- Implemented `DomainPolitenessThrottler` (thread-safe per-domain lock) and `AsyncDomainPolitenessThrottler` (async per-domain lock) eliminating global lock thread serialization.
- Created `tests/test_concurrency_proof.py`: verified overlapping execution intervals, server peak concurrency $\ge 2$, and distinct child worker PIDs across all engines.
- Created `tests/test_engine_conformance.py`: verified 18 core requirements identically across Serial, Threaded, Coroutine, and Multiprocess engines (48 tests).
- Created `tests/test_engine_consistency.py`: verified cross-engine result parity (identical URLs, status codes, depths, and content hashes).
- Created `tests/test_engine_failure_fallback.py`: verified fail-closed anti-silent-fallback guarantees (invalid modes reject, BrokenProcessPool fails explicitly, zero silent serial fallback).
- Added ADR-011 to `DECISIONS.md`.

---

## [Phase 2B: URL Normalization + Frontier + Crawl Lifecycle] - 2026-09-05

### Added
- Created `app/frontier.py` implementing strict finite state machine crawler frontier `CrawlFrontier`:
  - 8 lifecycle states (`DISCOVERED`, `QUEUED`, `FETCHING`, `COMPLETED`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `SKIPPED`, `DUPLICATE`).
  - State transition validation (`validate_frontier_transition`) rejecting illegal transitions with `InvalidStateTransitionError`.
  - Idempotent terminal state handlers (`mark_completed`, `mark_failed`, `mark_skipped`, `mark_duplicate`) preventing double-transition crashes and worker leaks.
  - Redirect handling (`handle_redirect`) with alias mapping and `enqueue_target=False` support for engines that resolve redirects internally.
  - Canonical tag deduplication (`handle_canonical`) with domain filtering.
  - Mathematical accounting reconciliation (`reconcile_accounting`) ensuring exact URL conservation.
- Created `app/urltools.py` normalization functions and policy:
  - `remove_dot_segments()` implementing RFC 3986 Section 5.2.4 path normalization.
  - `normalize_percent_encoding()`: unreserved bytes decoded, reserved characters uppercase-escaped.
  - `normalize_query_string()`: alphabetical key/value sorting, deduplication, marketing tracker stripping.
  - `UrlNormalizationPolicy`: configurable policy defaulting to trailing slash stripping, tracker stripping, and retaining sensitive credentials by default during HTTP dispatch.
  - `_PRESERVE_SLASH_POLICY`: trailing slash preservation for redirect `Location` header resolution.
- Created `tests/controlled_crawler_server.py`: deterministic test website fixture with 19 endpoints.
- Created 3 comprehensive verification test suites:
  - `tests/test_url_normalization.py` (13 tests): RFC 3986 invariants, port normalization, percent encoding, query sorting, tracking strip, sensitive param retention, canonical & redirect resolution.
  - `tests/test_frontier_lifecycle.py` (11 tests): 8-state FSM transitions, illegal transition rejection, idempotent terminal states, retry pool backoff, accounting reconciliation.
  - `tests/test_controlled_crawler.py` (12 tests): circular links, A-B-A cycle bounding, fragment deduplication, canonical duplicates, depth hierarchy, page limit enforcement, redirect chains/loops, HTTP errors, 429 rate-limiting retries.

### Changed
- Integrated `CrawlFrontier` into `CrawlEngine.run()` and `_run_static_mode()` in `app/crawler.py`.
- Resolved redirect `Location` headers using `_PRESERVE_SLASH_POLICY` to prevent redirect loops.
- Avoided duplicate fetching of redirect targets by passing `enqueue_target=False` to `frontier.handle_redirect`.
- Handled BeautifulSoup `rel` attribute representations (string and list) in `app/parser.py` for canonical tags.
- Recorded ADR-010 in `DECISIONS.md`.

### Verified
- 52/52 tests passed across targeted suites (13 normalization, 11 frontier, 12 controlled crawler, 16 contracts).
- 182 passed, 2 skipped, 0 failed across full repository regression suite.
- Fresh-eyes subagent architecture review completed ("Crawler Specialist"); all findings resolved.
- Subphase 2B release gate PASSED.

---

## [Phase 2A: Crawler Contracts + State Model] - 2026-09-05

### Added
- Created `tests/test_crawler_contracts.py` with 16 comprehensive unit tests verifying:
  - `CrawlStatus` operational states (`QUEUED`, `RUNNING`, `PAUSED`, `RETRYABLE`) and termination states (`SUCCESS`, `PARTIAL`, `FAILED`, `CANCELLED`, `BUDGET_EXHAUSTED`).
  - `EngineMode` (`SERIAL`, `THREAD`, `ASYNC`, `PROCESS`) and `FetchMode` (`STATIC`, `BROWSER`).
  - `CrawlResult` dataclass with automatic fallback detection, sequence unpacking (`pages, links, robots = result`), indexing (`result[0]`), and `len(result) == 3`.
  - `CancellationToken` cooperative thread-safe cancellation and IPC picklability for multiprocessing.
  - `FrontierItem` value object with URL, depth, parent URL, retry count, set hashability, and IPC picklability.
  - Runtime checkable `CrawlerEngineProtocol`.
  - Database schema column extensions in SQLite with automatic migrations (`_ensure_page_columns`) and provenance persistence/retrieval.

### Changed
- Refactored `CrawlEngine.run()` and `_run_static_mode()` in `app/crawler.py` to return `CrawlResult` while maintaining 100% backward compatibility with 3-tuple sequence unpacking.
- Connected `cancellation_token` to the crawler queue loop, transitioning status to `CrawlStatus.CANCELLED` with explicit reason when signalled.
- Extended `PageRecord` in `app/types.py` and SQLite `pages` table schema in `app/database.py` with 7 forensic provenance fields: `normalized_url`, `depth`, `parent_url`, `fetch_strategy`, `requested_fetch_strategy`, `actual_fetch_strategy`, `crawler_engine`, `response_bytes`, `duration_ms`, `error_category`, `headers`.
- Recorded ADR-009 in `DECISIONS.md` covering crawler contracts, sequence compatibility, and IPC picklability.

### Verified
- 16/16 contract tests pass (`tests/test_crawler_contracts.py`).
- 145/145 full regression suite tests pass (1 skipped: optional `sentence-transformers`).
- Fresh-eyes architecture review by subagent passed; all P0/P1 contract findings resolved.
- Subphase 2A release gate PASSED.

---

## [Phase 2: Crawler Core — Baseline Forensic Kickoff] - 2026-09-05

### Forensic Audit & Architecture Map
- Conducted deep line-by-line forensic reconstruction of the entire crawler codebase (`app/crawler.py`, `app/urltools.py`, `app/main.py`, `app/parser.py`, `app/database.py`).
- Produced end-to-end architecture execution graph tracing requests from UI/API through engine selection, queueing, fetch, rendering, link discovery, deduplication, and persistence.
- Created `reports/phase-2/phase_2_baseline_forensic_audit.md`.
- Tagged Git commit `db7fc50` as `pre-phase-2-crawler-core`.
- Defined formal requirements `REQ-CRAWL-001` through `REQ-CRAWL-016` in `docs/REQUIREMENTS_TRACEABILITY.md`.

---

## [Unreleased] - 2026-09-05

### Initialized Persistent Project Memory
- Created `PROJECT_MASTER_SPEC.md`: Master specification covering all 9 phases, priority rules, and invariants.
- Created `ARCHITECTURE.md`: Comprehensive system blueprint and modular interface definitions.
- Created `DECISIONS.md`: Architectural decision records ADR-001 through ADR-008.
- Created `CHANGELOG.md`: Chronological history and phase tracking.
- Created `KNOWN_ISSUES.md`: Known operational constraints, dependency notes, and risks.
- Created `TEST_MATRIX.md`: Exhaustive test inventory across all 125 test cases in 23 modules.
- Created `RELEASE_GATES.md`: Strict gate criteria for all 9 phases.

---

## [Phase 1: Evaluation Integrity] - 2026-09-05

### Added
- Created `app/evaluation.py` implementing rigorous, unclipped formulations of:
  - `compute_recall_at_k`
  - `compute_hit_at_k`
  - `compute_precision_at_k`
  - `compute_reciprocal_rank`
  - `compute_dcg` and `compute_ndcg` (with duplicate document discounting)
  - `compute_citation_metrics` (Citation Precision and Recall)
  - `compute_calibration_metrics` (Brier score, ECE, and reliability buckets)
- Created `tests/test_metrics_math.py` with 8 independent unit tests using hand-computed ground truth values for all edge cases (zero retrieved, zero relevant, ties, duplicate documents).
- Expanded benchmark suite to 155 frozen cases across 5 explicit splits in `tests/fixtures/benchmark_cases.py` (Development: 40, Calibration: 25, Blind Test: 40, Adversarial: 30, Regression: 20).
- Created `tests/test_ssrf_and_redaction.py` containing 23 adversarial tests for SSRF (octal, hex, dword, IPv6-mapped, cloud metadata) and secret token redaction (Bearer, JWT, API keys, private keys).
- Added `test_compute_crawl_coverage_metrics_precision_and_bounds` in `tests/test_analyzer.py`.
- Added `test_regression_11_metric_invariants_and_zero_clipping` in `tests/test_observed_regressions.py`.
- Added `test_hash_embedding_cosine_similarity_bounds_and_consistency` in `tests/test_embeddings.py`.
- Added `test_worker_crawl_indexes_hash_corpus_and_answers_groundedly` in `tests/test_rag_end_to_end.py`.

### Changed
- Replaced hardcoded query string comparisons in `plan_grounded_answer` (`app/qa.py`) with generalized dynamic extractors (`_dynamic_extract_comparison`, `_dynamic_extract_collection_item`, `_dynamic_extract_slots`, `_dynamic_extract_phrase_match`, `_dynamic_extract_identifier_match`, `_dynamic_extract_multi_hop_answer`, `_dynamic_extract_semantic_answer`).
- Eliminated `min(metric, 1.0)` across evaluation and crawl coverage calculations.
- Refactored `Database.get_crawl_coverage` in `app/database.py` to use set union of crawled URLs and discovered links.
- Preserved sentence terminal punctuation in `app/qa.py` prior to citation marker injection.

### Fixed
- Fixed SSRF vulnerability in `app/urltools.py` where alternate numeric representations (octal, hex, dword) bypassed string IP checks.
- Fixed secret token exposure for variable-length Google API keys, Slack tokens, and auth headers.
- Fixed 0-word count bug for structured JSON API responses.
- Fixed regression where incomplete multi-slot queries received overconfident scores (now capped at $\le 0.50$).

### Removed
- Removed legacy `manus` artifacts, obsolete comments, and hardcoded test shortcuts.

---

## [Phase 0: Baseline & Forensic Audit] - 2026-09-04

### Completed
- Conducted exhaustive repository audit across all crawler, indexing, QA, and security modules.
- Executed full baseline pytest suite across 23 test modules.
- Verified all 10 historic failure modes and established initial regression tracking.
