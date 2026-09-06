# COMPREHENSIVE TEST MATRIX
 
This document provides a detailed inventory of all 343 automated unit, integration, concurrency, stress, failure injection, resource safety, and security tests across all 39 test modules in `local-seo-spider`.

---

### Overall Summary
- **Total Test Files**: 42
- **Total Test Cases**: 343
- **Passed**: 341
- **Skipped**: 2 (gracefully skipped due to optional `sentence-transformers` dependency)
- **Failed**: 0
- **Pass Rate on Active Environment**: 100.0%
 
 ---
 
 ## Detailed Test Module Breakdown
 
 | Module | Type | Tests | Status | Scope & Requirements Covered |
 |:---|:---:|:---:|:---:|:---|
 | [`tests/test_accessibility.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_accessibility.py) | Unit | 1 | PASSED | Accessible HTML markup, ARIA roles, form labels |
 | [`tests/test_agentic.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_agentic.py) | Unit / Int | 4 | PASSED | Multi-hop routing, entity extraction, agentic query plan |
 | [`tests/test_analyzer.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_analyzer.py) | Unit | 2 | PASSED | SEO audit rules, issue prioritization, crawl coverage metrics |
 | [`tests/test_answering.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_answering.py) | Unit | 11 | PASSED | LocalAnswerer, OllamaAnswerer, query type classification, prompt formatting |
 | [`tests/test_app_e2e.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_app_e2e.py) | E2E | 5 | PASSED | FastAPI endpoints, crawl lifecycle, HTML views, question answering |
 | [`tests/test_benchmark_accounting.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_benchmark_accounting.py) | Benchmark | 2 | PASSED | 155-query accounting reconciliation, ID uniqueness, 0 cross-split leakage |
 | [`tests/test_contamination.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_contamination.py) | Security | 3 | PASSED | Zero benchmark case IDs, queries, or target answers hardcoded in app/ |
 | [`tests/test_comparison.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_comparison.py) | Integration | 1 | PASSED | Crawl comparison and differential ledger calculation |
 | [`tests/test_concurrency.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_concurrency.py) | Integration | 3 | PASSED | Threaded static, async coroutine, and multiprocess static crawl execution |
 | [`tests/test_concurrency_proof.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_concurrency_proof.py) | Concurrency Proof | 4 | PASSED | Overlapping intervals, server peak concurrency $\ge 2$, distinct child worker PIDs across Serial, Thread, Async, Multiprocess |
 | [`tests/test_concurrency_stress.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_concurrency_stress.py) | Concurrency Stress | 15 | PASSED | Simultaneous duplicate discovery dedup, rapid burst discovery queue integrity, mixed fast/slow endpoints, 500/429 storms, cancellation, SQLite write contention across 10 threads |
 | [`tests/test_controlled_crawler.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_controlled_crawler.py) | Integration | 12 | PASSED | 19 deterministic server endpoints, circular links termination, A-B-A cycle bounding, fragment deduplication, canonical duplicate detection, external domain exclusion, strict depth hierarchy, page limit enforcement, redirect chain & loops, HTTP error handling, 429 rate limit retry-after |
 | [`tests/test_controls_and_exports.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_controls_and_exports.py) | Integration | 12 | PASSED | CSV/JSON exports, robots.txt exclusions, redirect hops limit, error logging |
 | [`tests/test_crawl_budgets.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_crawl_budgets.py) | Budgets | 14 | PASSED | CrawlBudget bounds (max_pages, max_depth, max_bytes, max_duration_seconds, redirect_limit) across all 4 engines with deterministic BUDGET_EXHAUSTED transitions |
 | [`tests/test_crawler_contracts.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_crawler_contracts.py) | Contract | 16 | PASSED | Unified crawler contracts, CrawlStatus enums, sequence unpacking, fallback invariants, picklability, SQLite schema persistence |
 | [`tests/test_documents.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_documents.py) | Unit | 4 | PASSED | HTML, PDF, Markdown text extraction, deep JSON semantics preservation |
 | [`tests/test_embeddings.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_embeddings.py) | Unit | 5 | 4 PASS, 1 SKIP* | Hash embeddings determinism, normalization, cosine bounds, dimension consistency |
 | [`tests/test_engine_conformance.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_engine_conformance.py) | Conformance | 48 | PASSED | 18 core requirements verified across all 4 engines: seeds, discovery, depth/page limits, duplicates, redirects, 404/500, timeouts, retries, 429, malformed links, external exclusion, cancellation, accounting |
 | [`tests/test_engine_consistency.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_engine_consistency.py) | Parity | 1 | PASSED | Cross-engine parity: all 4 engines yield identical discovered URLs, status codes, depths, and content hashes |
 | [`tests/test_engine_failure_fallback.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_engine_failure_fallback.py) | Resilience | 5 | PASSED | Fail-closed anti-fallback guarantees: invalid modes reject, pool crashes fail explicitly, zero silent serial fallback |
 | [`tests/test_extraction_profiles.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_extraction_profiles.py) | Unit | 2 | PASSED | Custom extraction profiles and schema mappings |
 | [`tests/test_failure_injection.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_failure_injection.py) | Failure Injection | 20 | PASSED | Adversarial network failure resilience across all 4 engines: dropped mid-stream, truncated bodies, malformed gzip, socket timeout, connection refused |
 | [`tests/test_fetch_strategy_playwright.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_fetch_strategy_playwright.py) | Browser Lifecycle | 7 | PASSED | Playwright browser lifecycle, lazy startup, per-render context/page isolation, broken JS recovery, navigation timeouts, zero orphan process leaks |
 | [`tests/test_fetch_strategy_static.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_fetch_strategy_static.py) | Static Strategy | 9 | PASSED | Static HTTP response vs page acquisition, headers, status codes, content-types, gzip encodings, body truncation, timeout/network errors, fallback transparency |
 | [`tests/test_frontier_lifecycle.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_frontier_lifecycle.py) | State Machine | 11 | PASSED | 8-state frontier transitions, illegal transition rejection, terminal idempotency, retry exponential backoff, redirect alias mapping, canonical deduplication, mathematical accounting reconciliation |
 | [`tests/test_infinite_site_defense.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_infinite_site_defense.py) | Infinite Traps | 7 | PASSED | Path loop cycle detection (detect_path_loop), cookieless session ID deduplication, pagination trap limiting, soft-404 cryptographic deduplication |
 | [`tests/test_job_ledger.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_job_ledger.py) | Integration | 2 | PASSED | Persistent crawl state, job queue, restartability |
 | [`tests/test_knowledge.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_knowledge.py) | Unit | 5 | PASSED | Chunking, heading path provenance, chunk deduplication |
 | [`tests/test_metrics_math.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_metrics_math.py) | Unit | 8 | PASSED | Hand-computed IR metrics, edge cases, mathematical bounding in $[0.0, 1.0]$ |
 | [`tests/test_observed_regressions.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_observed_regressions.py) | Regression | 11 | PASSED | Permanent regression suite covering all 11 historic failures |
 | [`tests/test_playwright_browser.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_playwright_browser.py) | Integration | 3 | PASSED | Playwright Chromium launch, dynamic JS DOM rendering, live loopback app test |
 | [`tests/test_rag_benchmark.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_benchmark.py) | Benchmark | 10 | PASSED | 14-point architectural verification (canonicalization, JSON, RRF, citations) |
 | [`tests/test_rag_end_to_end.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_end_to_end.py) | E2E | 2 | 1 PASS, 1 SKIP* | End-to-end crawl, indexing, and grounded answer synthesis (hash & neural) |
 | [`tests/test_rag_evaluation.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_evaluation.py) | Integration | 2 | PASSED | Golden corpus indexing, retrieval recall sanity |
 | [`tests/test_rag_evaluation_harness.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_evaluation_harness.py) | Benchmark | 3 | PASSED | 155-case benchmark evaluation, 6 retrieval ablations, 5 split tests |
 | [`tests/test_resource_safety.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_resource_safety.py) | Resource Safety | 7 | PASSED | Clean thread join with 0 leaked threads, multiprocess clean exit with 0 orphan processes, 5 consecutive crawl cycles memory stability (< 2.5MB drift), SQLite transaction rollback |
 | [`tests/test_robots_and_politeness.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_robots_and_politeness.py) | Robots & Politeness | 12 | PASSED | RFC 9309 compliance (5xx/429 fail-closed, 4xx allow-all, Crawl-delay parsing and user-agent specificity), per-host politeness isolation, domain throttling under concurrency |
 | [`tests/test_smart_escalation.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_smart_escalation.py) | Smart Escalation | 10 | PASSED | Empty SPA containers (#root, #app, #__next), bot/JS challenges, anti-criteria prevention (script tags do not escalate), and multi-worker fallback transparency |
 | [`tests/test_ssrf_and_redaction.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_ssrf_and_redaction.py) | Security | 23 | PASSED | SSRF IP formats (octal, hex, dword, IPv6-mapped), cloud metadata, secret tokens |
 | [`tests/test_tooling.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_tooling.py) | Unit | 2 | PASSED | CLI argument parsing, environment variable loading |
 | [`tests/test_url_normalization.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_url_normalization.py) | Unit / Invariant | 13 | PASSED | RFC 3986 scheme/host/port normalization, dot segments, percent encoding, query parameter sorting & deduplication, tracking strip, safe sensitive param retention, canonical & redirect resolution |
 | [`tests/test_workflows.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_workflows.py) | Integration | 4 | PASSED | Crawl state lifecycle, pausing, resuming, aborting |

*\*Note: The 2 skipped tests require the heavy optional `sentence-transformers` dependency to be present in the Python virtual environment.*

---

## Verification Criteria by Category

### 1. Mathematical Invariant Verification
- `test_recall_at_k_hand_computed`: Hand-computed recall across varying $K$.
- `test_recall_edge_cases`: Zero relevant docs, zero retrieved, all relevant.
- `test_precision_at_k_hand_computed`: Hand-computed precision.
- `test_reciprocal_rank_hand_computed`: Reciprocal rank edge cases.
- `test_ndcg_hand_computed`: DCG / IDCG with ties and duplicate documents.
- `test_citation_metrics_hand_computed`: Citation precision and recall bounds.
- `test_calibration_metrics_hand_computed`: Brier score and ECE bounds.
- `test_calibration_edge_cases`: Extreme confidence cases ($0.0$ and $1.0$).

### 2. Security & Redaction Verification
- Blocks IPv4 loopback (`127.0.0.1`, `127.127.127.127`).
- Blocks IPv6 loopback (`::1`, `0:0:0:0:0:0:0:1`).
- Blocks IPv4-mapped IPv6 (`::ffff:127.0.0.1`).
- Blocks AWS/GCP/Azure cloud metadata (`169.254.169.254`, `169.254.169.253`).
- Blocks Alibaba cloud metadata (`100.100.100.200`).
- Blocks private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
- Blocks encoded IP representations: octal (`0177.0.0.1`), hex (`0x7f000001`), integer dword (`2130706433`).
- Redacts secrets: Bearer tokens, JWTs, OpenAI keys, Stripe keys, variable Google API keys, Slack tokens, GitHub tokens, AWS keys, private keys.

### 3. Concurrency & Execution Verification
- `serial`: Verified in single-process mode.
- `thread`: Verified across multi-threaded static crawl with shared state locks.
- `async`: Verified using non-blocking coroutines in asyncio event loops.
- `multiprocess`: Verified using spawn process pool on Windows.

### 4. Concurrency Stress & Failure Injection
- Simultaneous duplicate discovery exact deduplication (zero duplicate DB inserts, zero lost URLs).
- Rapid discovery queue integrity across 10+ worker threads.
- Interleaved fast and slow endpoints without starvation or deadlock.
- 500 error and 429 rate-limiting storms with exponential backoff and retry categorization.
- Cooperative mid-flight crawl cancellation responsiveness (< 1.0s stop time).
- High write contention across 10 simultaneous threads without database locks or corruptions.
- Adversarial network failure resilience across all 4 engines: dropped mid-stream, truncated response bodies, malformed gzip compression streams, socket timeouts, connection refused.

### 5. Resource Safety & Lifecycle Cleanliness
- Thread worker pool clean join with 0 leaked threads.
- Multiprocess clean exit with 0 orphan child processes.
- Memory and file descriptor stability across 5 consecutive crawls (< 2.5MB drift).
- SQLite atomic transaction rollback on failure without leaving orphaned partial records.

### 6. Fetch Strategies, Playwright Lifecycle & Smart Escalation
- Static HTTP fetch distinction: distinguish transport HTTP status codes from page extraction and body truncation.
- Header preservation, content-type routing (HTML, JSON, PDF, plain text), and gzip/deflate decoding.
- Playwright Chromium lifecycle: lazy launch, per-render page isolation, navigation timeout handling, broken JavaScript resilience.
- Zero browser process leaks: deterministic cleanup of browser, context, and page instances under all exit paths.
- Smart escalation detection: empty application shells (`#root`, `#app`, `#__next`) and bot/JS challenges.
- Anti-criteria enforcement: normal static HTML containing script tags (analytics, tracking, widgets) is never escalated to browser.
- Forensic observability: transparent reporting of `requested_fetch_strategy`, `actual_fetch_strategy`, `escalated`, `escalation_reason`, `fetch_duration_ms`, `render_duration_ms`, and `fallback_occurred` with `fallback_reason`.

### 7. Robots, Politeness, Retries & Crawl Budgets (Phase 2F)
- RFC 9309 robots directives: 5xx and 429 fail-closed, 4xx allow-all, socket errors fail-open with socket failure provenance.
- User-agent specificity and Crawl-delay parsing per domain.
- Granular per-host rate limiting and politeness isolation (`DomainPolitenessThrottler`, `AsyncDomainPolitenessThrottler`).
- Retry classification: retryable transient failures vs non-retryable fatal failures.
- Bounded retry counts, clamped `Retry-After` header adherence, and randomized exponential backoff jitter.
- Multi-dimensional crawl budgets (`max_pages`, `max_depth`, `max_bytes`, `max_duration_seconds`, `max_retries`, `redirect_limit`) with `BUDGET_EXHAUSTED` termination.
- Infinite site defenses: session ID stripping, path loop cycle detection, text content hash deduplication, pagination caps.

### 8. Resume, Recovery, Crash Safety & Idempotency (Phase 2G)
- Complete frontier lifecycle state persistence in SQLite `crawl_frontier_checkpoints` across all 8 states (`discovered`, `queued`, `fetching`, `completed`, `failed_retryable`, `failed_final`, `skipped`, `duplicate`).
- Crash recovery: in-flight `FETCHING` entries automatically recovered to `QUEUED` and `_active_workers` reset to 0.
- Interruption safety: clean recovery after discovery, during fetch, during atomic DB write rollback, during retry backoff, and while multi-workers are active.
- Idempotent storage: `UNIQUE(crawl_id, url)` on `pages` and `UNIQUE(crawl_id, source_url, target_url)` on `links` with atomic `ON CONFLICT DO UPDATE` upserts. Zero duplicate rows on replay.
- Cross-engine resume parity: Serial, Threaded, Coroutine, and Multiprocess engines can resume from checkpoint without refetching completed pages or losing pending queue.
- Version compatibility: schema version (`CURRENT_SCHEMA_VERSION = 1`) and major engine version (`CURRENT_ENGINE_VERSION = "2.0.0"`) validation; fail-closed `IncompatibleStateError`.
- State corruption defense: corrupt checkpoint JSON or invalid state values rejected with `CorruptStateError`.
- Mathematical reconciliation: `reconcile_accounting()` verified to balance across multiple resume cycles (`discovered == completed + queued + fetching + failed_retryable + failed_final + skipped + duplicate`).

### 9. Hosted Embedding Provider Architecture & Model Migration (Phase 2G.1)
- Google Gemini Embedding API integration (`text-embedding-004`) with single and batch embedding (`batchEmbedContents`).
- Bounded retries on HTTP 429 rate limits and 5xx errors with exponential backoff and `Retry-After` adherence.
- Fail-closed behavior on 401/403 authentication failures and 404 model misconfigurations without infinite retries.
- Secret safety: API keys passed via `x-goog-api-key` header and redacted from logs, reprs, metadata, and error strings.
- Fallback policies (`FAIL_CLOSED`, `FALLBACK_TO_HASH`, `BM25_ONLY`, `AUTO`) with full diagnostic reporting.
- Multi-generation vector persistence: `vector_embeddings` records `provider`, `model`, `dimension`, `created_at`, `content_hash`, and `metadata_json`.
- Model migration without recrawling: `reembed_knowledge` updates vector representations while keeping source pages and chunks authoritative.
- Dimension mismatch defense: `search_hybrid_knowledge` filters strictly by provider, model, and matching vector dimension.
- Clean batching bounds (batch size $\le 100$).
- Conditional live smoke testing: live verification when `GEMINI_API_KEY` is present, marked `UNVERIFIED LIVE` in offline/mocked environments.

### 10. Pipeline Decoupling, Fault Isolation & Re-Indexing Suite (Phase 2G.2)
- Independent 7-stage lifecycle tracking (`CRAWL`, `STORAGE`, `EXTRACTION`, `CHUNKING`, `EMBEDDING`, `INDEXING`, `RAG`) in SQLite `pipeline_stage_records`.
- Explicit stage status states: `NOT_STARTED`, `RUNNING`, `SUCCESS`, `PARTIAL`, `FAILED`, `PENDING_RETRY`, `SKIPPED`.
- 100% crawl data durability: raw crawled pages, links, and issues remain byte-for-byte intact across all embedding and indexing failure modes.
- Lexical chunking persistence priority: `knowledge_chunks` and `knowledge_fts` are committed to database before vector embedding begins; lexical retrieval remains operational during embedding failures.
- Fault isolation & partial indexing: provider failures midway through batch processing leave successful vectors intact and log failed chunks to `failed_embedding_chunks` with `retryable=True`.
- Rate limit (429) classification: HTTP 429 and transient provider errors are classified as retryable.
- Content hashing deduplication: chunks with unchanged `content_hash` and matching `(provider, model, dimension)` skip embedding calls.
- Model change detection: `detect_embedding_generation_mismatch` identifies provider, model, or dimension changes and forces clean re-indexing without silent mixing.
- Granular retry workflow: `retry_failed_embeddings` queries and embeds only failed chunks, transitions stages to `SUCCESS`, and avoids recrawling or re-embedding successful chunks.
- Provider naming harmony & state propagation: `embedder.name` and `provider_type` cross-compatibility across vector queries and generation mismatch detection; `PipelineStage.RAG` propagated to `SUCCESS` on retry resolution with crawl pause reason cleared; stale ghost chunks pruned when chunk counts shrink.
- Observability endpoints: `GET /crawls/{crawl_id}/pipeline` (forensic status and model mismatch analysis), `POST /crawls/{crawl_id}/pipeline/retry-embedding` (targeted retry), and `POST /crawls/{crawl_id}/reembed`.
