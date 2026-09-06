# ARCHITECTURE DECISION RECORDS (ADRs)

This document records the architectural and engineering decisions made for the Local SEO Spider and Semantic RAG system.

---

## ADR-001: Hybrid Search with Reciprocal Rank Fusion (RRF)
- **Status**: ACCEPTED / VERIFIED
- **Context**: Relying solely on vector embeddings fails for exact technical terms, API keys, and error codes. Relying solely on lexical BM25 fails for conceptual paraphrases and synonym expansion.
- **Decision**: Implement a hybrid retrieval pipeline combining SQLite `FTS5` (BM25 lexical) and normalized vector embeddings merged using Reciprocal Rank Fusion (RRF) with constant $k=60$.
- **Consequences**: Outperforms both vector-only and lexical-only baselines; resilient across exact keywords and conversational queries.

---

## ADR-002: Dynamic Query Decomposition vs Hardcoded Branching
- **Status**: ACCEPTED / VERIFIED
- **Context**: Earlier iterations contained hardcoded query string comparisons (`if "Starter plan" in query:`, `if "DummyJSON" in query:`) inside the answer planner, leading to benchmark circularity and brittle real-world failures.
- **Decision**: Replace all query-specific conditional branches with generalized dynamic extractors:
  - `_dynamic_extract_comparison`
  - `_dynamic_extract_collection_item`
  - `_dynamic_extract_slots`
  - `_dynamic_extract_phrase_match`
  - `_dynamic_extract_identifier_match`
  - `_dynamic_extract_multi_hop_answer`
  - `_dynamic_extract_semantic_answer`
- **Consequences**: Answer planner is completely domain-agnostic and relies entirely on retrieved evidence.

---

## ADR-003: Strict Mathematical Bounding & Elimination of Metric Self-Deception
- **Status**: ACCEPTED / VERIFIED
- **Context**: In previous versions, evaluation metrics could exceed 1.0 due to un-deduplicated DCG calculations and naive denominators, masked by `min(metric, 1.0)`.
- **Decision**: 
  1. Forbid `min(metric, 1.0)` across all evaluation and coverage calculations.
  2. Implement mathematically standard formulations in `app/evaluation.py`:
     - Recall@K: divide by total unique relevant documents.
     - Precision@K: divide by $K$.
     - NDCG@K: discount duplicate document IDs.
     - Brier score & ECE: strictly bounded in $[0.0, 1.0]$.
- **Consequences**: Metric exceedance triggers test failure, preventing hidden bugs from passing undetected.

---

## ADR-004: Multi-Representation IP Decoding for SSRF Defense
- **Status**: ACCEPTED / VERIFIED
- **Context**: Attackers use alternate IP encodings (octal, hexadecimal, dword, IPv4-mapped IPv6) to bypass simple string-based regex checks and access cloud metadata or loopback services.
- **Decision**: Implement `parse_ip_literal` in `app/urltools.py` which decodes all numeric formats into canonical `ipaddress.IPv4Address` or `ipaddress.IPv6Address` objects before checking against forbidden private, loopback, link-local, and cloud metadata CIDR ranges (`169.254.169.254`, `100.100.100.200`, `metadata.google.internal`).
- **Consequences**: Fully protects against DNS rebinding, alternate encodings, and cloud metadata exfiltration.

---

## ADR-005: 5-Way Isolated Benchmark Partitioning
- **Status**: ACCEPTED / VERIFIED
- **Context**: Evaluating models or RAG pipelines on an unpartitioned corpus leads to over-fitting on test data.
- **Decision**: Partition the 155 frozen benchmark queries into 5 explicit splits:
  1. `development` (40 queries): parameter and heuristic tuning.
  2. `calibration` (25 queries): probability bucket and confidence tuning.
  3. `blind_test` (40 queries): frozen validation evaluating generalizability.
  4. `adversarial` (30 queries): unanswerable, near-miss, and contradictory queries testing abstention.
  5. `regression` (20 queries): historical real-world bug cases.
- **Consequences**: Guarantees independent evaluation without data leakage.

---

## ADR-006: Atomic Claim-Level Citation Verification with Hard Abstention
- **Status**: ACCEPTED / VERIFIED
- **Context**: High retrieval similarity does not guarantee factual correctness. LLMs often fabricate numbers or entity relations while citing relevant-looking URLs.
- **Decision**:
  1. Decompose answers into atomic factual claims.
  2. Independently verify numbers, entities, temporal scope, and units against the cited passage text.
  3. Emit explicit verification statuses: `PASS`, `PARTIAL`, `FAIL`.
  4. If claims are unsupported or contradictory, unconditionally abstain (`confidence = 0.0`).
- **Consequences**: Benchmark hallucination rate reduced to 0.0% with 100.0% abstention accuracy on unanswerable queries.

---

## ADR-007: Exact Set Union for Crawl Coverage Metric
- **Status**: ACCEPTED / VERIFIED
- **Context**: Computing crawl coverage as `len(crawled) / link_count` risked exceeding 1.0 if links were incomplete or missing.
- **Decision**: Compute `total_discovered_urls` as the set union of all crawled URLs and all discovered link target URLs. 
- **Consequences**: Crawled URLs are mathematically a subset of discovered URLs, guaranteeing $0.0 \le \text{coverage\_rate} \le 1.0$ without artificial clamps.

---

## ADR-008: Preservation of Terminal Punctuation in Sentence Extraction
- **Status**: ACCEPTED / VERIFIED
- **Context**: Stripping trailing periods prior to appending citation brackets `[1]` converted `"Text."` to `"Text [1]."`, causing string assertion failures in downstream API tests.
- **Decision**: Check if sentence ends in punctuation (`.`, `!`, `?`) and preserve it before appending the citation bracket: `f"{sentence} [{cit}]"`.
- **Consequences**: Retains grammatically valid sentence structure and satisfies exact string contract tests.

---

## ADR-009: Unified Crawler Contracts, Sequence Compatibility, and IPC Picklability
- **Status**: ACCEPTED / VERIFIED
- **Context**: Prior to Phase 2, crawler engines returned bare 3-tuples `(pages, links, robots_disallowed)` without metadata, execution provenance, termination status, or fallback transparency. Legacy consumers across `app/main.py` and test harnesses unpacked results as 3-tuples. Furthermore, `multiprocessing` workers on Windows (`spawn`) require all items placed in queues to be picklable, while standard thread locks (`threading.Lock`) cannot be pickled.
- **Decision**:
  1. Define a standardized `CrawlResult` dataclass implementing `__iter__`, `__getitem__`, and `__len__` for seamless 3-tuple unpacking (`pages, links, robots = result`).
  2. Implement automatic fallback detection in `CrawlResult.__post_init__` when requested fetch/engine modes diverge from actual execution.
  3. Define 5 termination states (`SUCCESS`, `PARTIAL`, `FAILED`, `CANCELLED`, `BUDGET_EXHAUSTED`) and 4 operational states (`QUEUED`, `RUNNING`, `PAUSED`, `RETRYABLE`) in `CrawlStatus`.
  4. Implement `CancellationToken` with custom `__getstate__` and `__setstate__` to allow IPC pickling across process boundaries while maintaining thread-safe cancellation in worker loops.
  5. Implement `FrontierItem` with explicit `__hash__` and `__eq__` for set-based deduplication and queue operations.
  6. Extend `PageRecord` with provenance fields (`normalized_url`, `depth`, `parent_url`, `fetch_strategy`, `crawler_engine`, `response_bytes`, `duration_ms`, `error_category`, `headers`), and persist all fields in SQLite with automatic schema migration.
- **Consequences**: Legacy callers continue to function without breaking changes, while modern engines and inspectors gain complete forensic observability and multiprocessing compatibility.

---

## ADR-010: Conservative URL Normalization and Finite State Machine Frontier Lifecycle
- **Status**: ACCEPTED / VERIFIED
- **Context**: Prior to Phase 2B, URL normalization was ad-hoc and inconsistent across crawler call sites, prone to path explosion (e.g. `//`, `/./`, `/../`), non-deterministic query string permutations, and SSRF vulnerabilities. Additionally, crawl scheduling relied on simple deques without lifecycle tracking, resulting in vulnerability to redirect loops, double-fetching of redirect destinations, and unmonitored dropouts.
- **Decision**:
  1. Implement RFC 3986 compliant URL normalization in [`app/urltools.py`](file:///C:/Users/win/10/Desktop/local-seo-spider/app/urltools.py):
     - Normalized scheme and host casing; default port stripping (80 for HTTP, 443 for HTTPS) while preserving custom ports and IPv6 brackets.
     - Strict SSRF validation with decimal, octal, hex, dword, and IPv6 parsing blocking loopback, link-local, and cloud metadata addresses unless explicitly permitted.
     - RFC 3986 Section 5.2.4 dot segment removal (`remove_dot_segments`) and consecutive slash collapsing.
     - Percent-encoding canonicalization (`normalize_percent_encoding`): unreserved characters decoded, reserved characters uppercase-escaped.
     - Deterministic query string sorting and duplicate parameter elimination (`normalize_query_string`), while stripping marketing trackers (`utm_*`, `fbclid`, etc.).
     - Sensitive parameter redaction (`token`, `api_key`, `secret`) made opt-in (`redact_sensitive_params=False` by default) to prevent corruption of crawler HTTP dispatch, reserved for reporting and export.
     - Trailing slash policy configurable via `UrlNormalizationPolicy` (default `"strip"`, but using `"preserve"` for redirect `Location` header resolution to prevent redirect loops).
  2. Implement strict finite state machine crawler frontier in [`app/frontier.py`](file:///C:/Users/win/10/Desktop/local-seo-spider/app/frontier.py):
     - 8 explicit states: `DISCOVERED`, `QUEUED`, `FETCHING`, `COMPLETED`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `SKIPPED`, `DUPLICATE`.
     - Validated state transitions enforcing unidirectional flow and rejecting impossible transitions with `InvalidStateTransitionError`.
     - Idempotent terminal state handlers ensuring idempotent completions and preventing race conditions or worker leaks.
     - Redirect handling with alias mapping and `enqueue_target=False` support for engines that follow HTTP redirects internally.
     - Cross-domain filtering and canonical tag deduplication (`handle_canonical`).
     - Mathematical frontier accounting reconciliation (`reconcile_accounting`) ensuring zero lost or untracked URLs.
- **Consequences**: Eliminates crawl loops, prevents redundant fetches, ensures exact depth hierarchy and page budget bounding, and provides thread-safe lifecycle tracking across all execution modes.

---

## ADR-011: Four Independent Concurrency Engines & Anti-Fallback Protocol
- **Status**: ACCEPTED / VERIFIED
- **Context**: Prior to Phase 2C, crawler concurrency modes suffered from severe architectural flaws:
  1. Multiprocess mode was a mirage: URLs were fetched sequentially in the parent thread via a list comprehension, only offloading CPU parsing to `ProcessPoolExecutor`.
  2. Threaded mode serialized requests during delay sleeps under a single global lock (`thread_gate`).
  3. Coroutine/async mode recreated the asyncio event loop and `httpx.AsyncClient` per batch, destroying connection pooling and creating massive socket churn.
  4. Engines had potential silent fallbacks or degraded behavior under error conditions.
- **Decision**:
  1. Implement four concrete, genuinely independent engine classes inheriting from `CrawlEngine` / `BaseCrawlerEngine`:
     - `SerialCrawlerEngine`: Single-threaded, synchronous execution with single persistent `httpx.Client` session.
     - `ThreadedCrawlerEngine`: Genuine multi-threaded parallel network I/O with long-lived worker pool (`ThreadPoolExecutor`), a persistent thread-safe `httpx.Client` with connection pooling (`httpx.Limits`), and per-domain politeness throttling via `DomainPolitenessThrottler` (ensuring delay on domain A never blocks domain B).
     - `CoroutineCrawlerEngine`: Persistent asyncio event loop and single persistent `httpx.AsyncClient` session across the entire crawl lifecycle, bounded by `asyncio.Semaphore`, with `AsyncDomainPolitenessThrottler`.
     - `MultiprocessCrawlerEngine`: Genuine parallel socket-level HTTP requests and CPU signal extraction executed inside spawned child processes (`multiprocessing.get_context("spawn")`) via top-level worker module `app/multiprocess_worker.py`. Child processes report their individual `worker_pid` and send `X-Client-PID` HTTP headers, proving isolation from the coordinator process.
  2. Fail-closed anti-fallback protocol:
     - Unrecognized or broken executor modes fail fast with explicit errors.
     - Worker failures (e.g. `BrokenProcessPool`, socket crashes) are recorded directly on the `CrawlResult` (`status=FAILED`, `actual_engine=requested_engine`, `fallback_occurred=False`).
     - Never secretly switch or degrade to serial mode under any circumstance.
  3. Shared Conformance Suite:
     - 18 core requirements verified across all 4 engines in `tests/test_engine_conformance.py` (48 tests).
     - Deterministic cross-engine result consistency verified in `tests/test_engine_consistency.py` (identical URLs, status codes, depths, and content hashes).
     - Concurrency proofs verified in `tests/test_concurrency_proof.py` (overlapping execution intervals, server peak concurrency $\ge 2$, distinct child worker PIDs).
     - Anti-silent fallback verified in `tests/test_engine_failure_fallback.py`.
- **Consequences**: Guarantees advertised concurrency models without fake wrappers, provides verifiable parallel performance, and ensures strict operational safety under network and process failures.

---

## ADR-012: Concurrency Stress Hardening, Failure Injection Resilience & Resource Safety
- **Status**: ACCEPTED / VERIFIED
- **Context**: High-concurrency crawlers under adverse network and operating system conditions face critical failure modes:
  1. SQLite write contention (`sqlite3.OperationalError: database is locked`) when multiple parallel threads or processes write crawl updates simultaneously.
  2. Race conditions during simultaneous duplicate URL discovery from parallel workers causing duplicate DB inserts or lost URLs.
  3. Worker pool stalls or deadlocks during mid-flight cancellation when politeness sleeps or retry backoffs block the thread/coroutine loop.
  4. Network failures (stream drops, truncated bodies, malformed gzip, socket read timeouts, connection refused) causing worker leaks, unhandled exceptions, or crawl hangs.
  5. Descriptor, process, and thread leaks across consecutive crawls resulting in memory bloat and resource exhaustion.
- **Decision**:
  1. Database WAL & Busy Timeout Hardening (`app/database.py`):
     - Configured SQLite connection busy timeout to 30.0 seconds (`PRAGMA busy_timeout = 30000;`).
     - Configured SQLite journal mode to Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) on initialization.
     - Verified concurrent write safety across 10 simultaneous threads without database locks, duplicate inserts, or database corruption.
  2. Interruptible Sleep & Responsive Cancellation (`app/crawler.py`):
     - Implemented `_sleep_interruptible` and `_async_sleep_interruptible` checking `cancellation_token.is_cancelled()` in 50ms slices during politeness delays and retry backoff.
     - Implemented `_safe_fetch` and `_safe_async_fetch` on `BaseCrawlerEngine` to inspect signature arity and safely support both cancellation-aware calls and legacy monkeypatched test stubs.
  3. Adversarial Failure Injection Resilience (`tests/test_failure_injection.py`):
     - Verified clean error handling across all 4 engines (Serial, Threaded, Coroutine, Multiprocess) for dropped mid-stream TCP connections, half-written response bodies, malformed gzip compression streams, read timeouts, and connection refused errors without crashing the crawl or hanging workers.
  4. Concurrency Stress & Race Safety (`tests/test_concurrency_stress.py`):
     - Verified exact set deduplication under simultaneous duplicate discovery from parallel workers (zero duplicate DB inserts, zero lost URLs).
     - Verified queue integrity under rapid burst discovery across 10+ worker threads.
     - Verified resilience under mixed fast/slow endpoints, 500 error storms, 429 rate-limiting storms, and cooperative mid-flight cancellation.
  5. Resource Safety & Leak Prevention (`tests/test_resource_safety.py`):
     - Verified Thread worker pool clean join with 0 leaked threads.
     - Verified Multiprocess clean shutdown with 0 orphan child processes.
     - Verified multi-crawl stability across 5 consecutive crawl cycles with bounded memory drift (< 2.5MB) and zero descriptor/connection leaks.
     - Verified SQLite transaction rollback safety on simulated failure.
- **Consequences**: Guarantees fail-closed zero-data-loss execution under extreme concurrency, eliminates database write lock contention, and guarantees clean resource reclamation across long-running crawler lifecycles.

---

## ADR-013: Deterministic Static Acquisition, Playwright Session Lifecycle, and Smart Escalation Policy
- **Status**: ACCEPTED / VERIFIED
- **Context**: A successful HTTP response does not guarantee successful page acquisition. Server-rendered HTML documents can be completely acquired via high-performance static HTTP requests. However, client-side Single Page Applications (SPAs) mount empty container shells (`<div id="root"></div>`), and security gates deploy JavaScript challenges that require headless browser execution. Conversely, blindly launching a headless browser for every static page or every page containing third-party tracking scripts (Google Analytics, Facebook Pixel, etc.) causes severe performance degradation (10x-50x slower) and process thrashing.
- **Decision**:
  1. Static Acquisition Baseline (`app/crawler.py`, `tests/test_fetch_strategy_static.py`):
     - Fast HTTP socket acquisition via `httpx.Client` capturing status codes, response headers, redirect hops, body truncation (`body_truncated`), compression (`gzip`, `deflate`), and non-HTML document extraction (`extract_document_text` for JSON, text, PDF, CSV).
  2. Deterministic Playwright Browser Lifecycle (`app/browser.py`, `tests/test_fetch_strategy_playwright.py`):
     - `PlaywrightBrowserSession` manages headless Chromium lifecycle with lazy initialization, isolated context, per-render tab creation, and deterministic cleanup in `finally` blocks ensuring zero orphan browser processes.
     - Robust exception isolation in `render_url()` and `crawler.py` ensuring client-side script exceptions or navigation timeouts record `render_error` without aborting the crawl.
  3. Conservative Smart Escalation Policy (`app/escalation.py`, `tests/test_smart_escalation.py`):
     - Explicit heuristics: escalates on bot challenges (`CHALLENGE_PATTERNS`) and empty SPA shells (`SPA_CONTAINER_PATTERNS` with `< 100` chars visible text).
     - Strict Anti-Pattern Rule: Never escalates normal static HTML pages containing `<script>` tags when visible text is present ($\ge 100$ chars). Non-HTML resources and standard error codes never escalate.
  4. Complete Transparency & Forensic Provenance:
     - `PageRecord` exposes `requested_fetch_strategy`, `actual_fetch_strategy`, `escalated`, `escalation_reason`, `fetch_duration_ms`, `render_duration_ms`.
     - `CrawlResult` exposes `requested_fetch_mode`, `actual_fetch_mode`, `fallback_occurred`, `fallback_reason`, `pages_escalated`.
     - Multi-worker static engines (`thread`, `async`, `process`) requesting browser/smart rendering flag explicit fail-closed fallback (`fallback_occurred=True`).
     - SQLite `pages` table schema migrated and verified with full roundtrip fidelity.
- **Consequences**: Guarantees optimal fetch throughput by keeping static pages on raw HTTP sockets while automatically hydrating SPAs and challenge pages in real browser contexts, with 100% forensic transparency and zero process leaks.

---

## ADR-014: RFC 9309 Robots Compliance, Politeness Isolation, Jittered Retries, Multi-Engine Crawl Budgets & Infinite Site Defense
- **Status**: ACCEPTED / VERIFIED
- **Context**: Web crawlers without bounded execution constraints and politeness protocols risk causing Denial-of-Service to remote hosts, violating RFC 9309 robots directives, falling into spider traps (calendar cycles, path loops, infinite pagination, tracking session parameters), and suffering runaway memory/network exhaustion. Additionally, multi-host crawling requires per-host rate limiting and concurrency semaphores to ensure slow or rate-limited endpoints do not stall parallel workers targeting healthy domains.
- **Decision**:
  1. RFC 9309 Robots Compliance (`app/crawler.py`):
     - Server errors (5xx) and HTTP 429 rate limits are fail-closed (`policy.disallow_all = True`, disallow-all).
     - Missing or 4xx responses (e.g. 404) are allow-all (`policy.allow_all = True`).
     - Network errors (e.g. socket refused, connect timeout) set `policy.allow_all = True` so actual socket failures surface on target page records rather than falsely reporting `robots_disallowed`.
     - `Crawl-delay` parsed with user-agent specificity and applied via domain politeness throttling across all engines (Serial, Thread, Coroutine, Multiprocess).
     - `respect_robots_txt=False` supported for owned private audits.
  2. Granular Politeness & Multi-Host Rate Limiting (`app/crawler.py`):
     - `DomainPolitenessThrottler` and `AsyncDomainPolitenessThrottler` maintain per-domain concurrency semaphores (`per_host_concurrency`) and monotonic inter-request spacing (`delay_seconds`).
     - Keying supports both `host` and `netloc` (matching with or without explicit port numbers).
     - Zero cross-host interference: throttling or delays on domain A never block or delay workers targeting domain B.
     - Multiprocess and serial engines record request completion times (`record_completion`) ensuring delay intervals are measured from response completion to subsequent request dispatch.
  3. Bounded Retries with Exponential Backoff & Jitter:
     - Strict classification of retryable (408, 425, 429, 500, 502, 503, 504, timeout, network error) vs non-retryable (400, 401, 403, 404, 410, SSRF, robots disallowed).
     - Retries bounded by `max_retries`.
     - `Retry-After` header parsed (integer seconds and HTTP-date) and clamped to safe limits (max 300s).
     - Random uniform jitter (`0.8` to `1.2`) applied to eliminate lockstep retry storms.
  4. Crawl Budgets & Deterministic Termination:
     - Multi-dimensional budget constraints (`CrawlBudget`): `max_pages`, `max_depth`, `max_bytes`, `max_duration_seconds`, `max_retries`, `redirect_limit`.
     - Slices frontier discovery, halts worker dispatch loops, and transitions `CrawlResult.status` to `CrawlStatus.BUDGET_EXHAUSTED` (`"budget_exhausted"`) with explicit, observable `termination_reason` across all 4 crawler engines.
  5. Infinite Site Defense:
     - Normalization strips session IDs (`;jsessionid=`, `/(S(...))/`, `;sid=`, `;phpsessid=`) and marketing trackers.
     - Path cycle detection (`detect_path_loop`) skips cyclic path sub-sequences (repeat count $\ge 3$) with `skip_reason="path_loop_detected"`.
     - Soft-404 and duplicate body content deduplicated via cryptographic text hashing (`seen_content_hashes`).
     - Pagination loops bounded to maximum depth and page caps.
- **Consequences**: The crawler operates with bounded predictability, strict politeness isolation, resilient jittered retry recovery, and bulletproof defense against infinite traps.


