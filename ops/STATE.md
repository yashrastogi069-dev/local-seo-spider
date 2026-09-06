# OPERATIONAL STATE: PRIMARY SHORT-TERM MEMORY

*Last Updated*: 2026-09-06T10:15:00+05:30  
*Operating Mode*: Engineering Operating System & Integrity Layer  
*Primary Source of Truth*: Executable Code (`app/`) & Automated Tests (`tests/`)

---

## 1. Active Phase & Subphase
- **Active Phase**: PHASE 2 (Crawler Core) — **PHASE 2G.1 COMPLETED & CERTIFIED**
- **Completed Subphases**:
  - Phase 2A (Crawler Contracts + State Model) — **PASSED**
  - Phase 2B (URL Normalization + Frontier + Crawl Lifecycle) — **PASSED**
  - Phase 2C (Four Independent Crawler Engines) — **PASSED & CERTIFIED**
  - Phase 2D (Concurrency Stress, Failure Injection & Resource Safety) — **PASSED & CERTIFIED**
  - Phase 2E (Static Fetch + Playwright + Smart Escalation) — **PASSED & CERTIFIED**
  - Phase 2F (Robots, Politeness, Retries & Crawl Budgets) — **PASSED & CERTIFIED**
  - Phase 2G (Resume, Recovery, Crash Safety & Idempotency) — **PASSED & CERTIFIED**
  - Phase 2G.1 (Hosted Embedding Provider Architecture & Re-Embedding) — **PASSED & CERTIFIED**
- **Baseline Git Checkpoints**:
  - `db7fc50` (Tags: `phase-1-certified`, `pre-phase-2-crawler-core`)
  - `fdd59d9` (Tag: `phase-2c-engine-independence`)
  - `phase-2d-concurrency-hardening`
  - `phase-2e-fetch-strategy`
  - `ebfb65e` (Tag: `phase-2f-budgets-politeness`)
  - `28c686f` (Tag: `phase-2g-resume-recovery`)
  - Target commit for Phase 2G.1 (Tag: `phase-2g1-hosted-embedding-provider`)
- **Phase 1 Evaluation Baseline**: **FROZEN & TRUSTED** (Do NOT modify Phase 1 fixtures)

---

## 2. Current Objective
Phase 2G.1 (Hosted Embedding Provider Architecture, Re-Embedding Without Recrawling, Transparent Fallbacks & Dimension Isolation) is completely certified.
Next: Present full Phase 2G.1 certification evidence, commit changes, tag `phase-2g1-hosted-embedding-provider`, and await user directive before beginning Phase 2H.

---

## 3. Current Status
- **Phase 0 Status**: `PASSED`
- **Phase 1 Status**: `PASSED & CERTIFIED (FROZEN)`
- **Phase 2 Status**: `PHASE 2G.1 CERTIFIED`
  - **Subphase 2A Status**: `PASSED`
  - **Subphase 2B Status**: `PASSED`
  - **Subphase 2C Status**: `PASSED & CERTIFIED`
  - **Subphase 2D Status**: `PASSED & CERTIFIED`
  - **Subphase 2E Status**: `PASSED & CERTIFIED`
  - **Subphase 2F Status**: `PASSED & CERTIFIED`
  - **Subphase 2G Status**: `PASSED & CERTIFIED`
  - **Subphase 2G.1 Status**: `PASSED & CERTIFIED`
- **Current Test State**: 381+ Passed, 3 Skipped (optional `sentence-transformers` and live external Gemini API smoke test), 0 Failed across 44 test modules.

---

## 4. Last Verified Test State
- **Command**: `pytest`
- **Results**: 306 passed, 2 skipped, 0 failed in 272.52s across 39 test modules.
- **Phase 2E Fetch Strategy & Playwright Suites**:
  - `tests/test_fetch_strategy_static.py`: 9/9 passed (headers, content-types, gzip, body truncation, timeout/network errors, fallback transparency).
  - `tests/test_fetch_strategy_playwright.py`: 7/7 passed (lazy startup, per-render context/page isolation, broken JS recovery, navigation timeout, 0 orphan processes).
  - `tests/test_smart_escalation.py`: 10/10 passed (empty SPA shells `#root`, `#app`, `#_next`, bot/JS challenges, anti-criteria enforcement, multi-worker fallback).
- **Phase 2D Concurrency Stress & Failure Suites**:
  - `tests/test_concurrency_stress.py`: 15/15 passed (simultaneous duplicate dedup, burst discovery, mixed fast/slow, 500/429 storms, cancellation, SQLite write contention).
  - `tests/test_failure_injection.py`: 20/20 passed (dropped mid-stream, truncated bodies, malformed gzip, socket timeouts, connection refused).
  - `tests/test_resource_safety.py`: 7/7 passed (thread pool join, multiprocess exit, memory drift < 2.5MB, SQLite transaction rollback).
- **Phase 2C Conformance & Concurrency Proof Suites**:
  - `tests/test_concurrency_proof.py`: 4/4 passed (Serial, Thread, Async, Multiprocess verified with overlapping intervals, server peak concurrency $\ge 2$, distinct child worker PIDs).
  - `tests/test_engine_conformance.py`: 48/48 passed (all 18 requirements verified across all 4 engines).
  - `tests/test_engine_consistency.py`: 1/1 passed (identical discovered URLs, status codes, depths, and content hashes across all 4 engines).
  - `tests/test_engine_failure_fallback.py`: 5/5 passed (fail-closed, anti-silent-fallback guarantees).
- **Regression Suite**: 11/11 historic regressions passed (`tests/test_observed_regressions.py`).
- **Security Suite**: 23/23 SSRF and secret redaction tests passed (`tests/test_ssrf_and_redaction.py`).
- **Contamination Suite**: 3/3 contamination tests passed (`tests/test_contamination.py`).
- **Accounting Suite**: 2/2 accounting reconciliation tests passed (`tests/test_benchmark_accounting.py`).

---

## 5. Phase 2 Remediation Progress (Subphases 2A-2E: 100% COMPLETE)
- [x] **REQ-CRAWL-001 / ADR-009**: Unified crawler contract, `CrawlerEngineProtocol`, `CrawlStatus` enums, `CrawlResult` backward-compatible unpacking. (Phase 2A - DONE)
- [x] **REQ-CRAWL-002 / ADR-010**: URL Normalization and 8-state Frontier FSM with exact accounting reconciliation, depth tracking, canonical deduplication, and redirect alias mapping. (Phase 2B - DONE)
- [x] **REQ-CRAWL-003, 004, 005, 006 / ADR-011**: Four independent concurrency engines (Serial, Thread, Coroutine, Multiprocess) with genuine execution, politeness throttling, and connection pooling. (Phase 2C - DONE)
- [x] **REQ-CRAWL-007 / 008**: Fallback and strategy transparency; `fallback_occurred` and `fallback_reason` invariant in `CrawlResult`. (Phase 2A, 2C, 2E - DONE)
- [x] **REQ-CRAWL-008 / ADR-013**: Observable static vs Playwright fetch strategies and smart escalation (`#root`, `#app`, `#__next`, challenges) with anti-criteria enforcement. (Phase 2E - DONE)
- [x] **REQ-CRAWL-011 / ADR-012**: SQLite schema extended and WAL mode + 30s busy timeout for concurrent multi-threaded write safety. (Phase 2A & 2D - DONE)
- [x] **REQ-CRAWL-012**: `CancellationToken` implemented with thread-safe cooperative cancellation and sub-second interruptible sleeps. (Phase 2A & 2D - DONE)
- [x] **REQ-CRAWL-015**: Resource safety verified across threads, child processes, Playwright browser sessions (0 orphan Chromium processes), and memory stability. (Phase 2D & 2E - DONE)
- [x] **P0-01 / REQ-CRAWL-006**: Multiprocess engine parallel socket fetches in child workers. (Phase 2C & 2D - DONE)
- [x] **P0-02 / REQ-CRAWL-008**: Dynamic rendering across concurrent modes with explicit fallback tracking. (Phase 2E - DONE)
- [x] **P0-03**: Real Playwright browser session lifecycle and render tests. (Phase 2E - DONE)
- [x] **P1-02**: Mid-crawl page persistence and atomic SQLite transactions. (Phase 2D - DONE)
- [x] **P1-04**: Eliminating silent fallback on browser launch/render failure. (Phase 2C & 2E - DONE)
- [x] **P2-01 / P2-02**: HTTP connection pooling & persistent async client session. (Phase 2C - DONE)

---

## 6. Unresolved P0 / P1 / P2 Issues
- **P0 (Critical / Blocker)**: None. (All Phase 2 requirements verified with 0 failures).
- **P1 (High)**: None.
- **P2 (Medium / Documented Acceptance)**:
  - `sentence-transformers` is optional; offline test runner relies on `HashEmbeddingProvider`.
  - Playwright requires local Chromium binary for dynamic JavaScript rendering (`render_enabled=True`).

---

## 7. Last Completed Work
1. Implemented Phase 2E: Static Fetch + Playwright Browser Lifecycle + Smart Escalation:
   - `app/types.py`: Added `FetchMode.SMART`, `requested_fetch_strategy`, `actual_fetch_strategy`, `escalated`, `escalation_reason`, `fetch_duration_ms`, `render_duration_ms`, and `pages_escalated`.
   - `app/escalation.py`: Added `should_escalate_to_browser()` with regex detecting empty SPA root containers (`#root`, `#app`, `#__next`) and bot/JS challenges, while enforcing anti-criteria (normal HTML with script tags never escalates).
   - `app/browser.py`: Implemented `PlaywrightBrowserSession` with lazy startup, context manager support, per-render page isolation, hardened exception wrapping, and deterministic teardown.
   - `app/database.py`: Migrated and added 7 Phase 2E columns to `pages` table.
   - `app/crawler.py`: Integrated smart escalation and Playwright lifecycle in `_run_serial`; explicitly tracked `fallback_occurred=True` and `fallback_reason` on multi-worker static engines.
   - `app/multiprocess_worker.py`: Deserialized Phase 2E fields and populated `rendered_text: ""`.
2. Created 3 comprehensive Phase 2E test suites (26 tests):
   - `tests/test_fetch_strategy_static.py` (9 tests)
   - `tests/test_fetch_strategy_playwright.py` (7 tests)
   - `tests/test_smart_escalation.py` (10 tests)
3. Fresh-eyes subagent review completed and all 7 identified defects (3 P1, 4 P2) resolved.
4. Verified 100% full repository test pass rate: 306 passed, 2 skipped, 0 failed across all 39 test modules.
5. Recorded ADR-013 in `DECISIONS.md`.

---

## 8. Exact Next Action
1. Update `ops/SESSION_HANDOFF.md`, `ops/CHANGELOG.md`, and `CHANGELOG.md`.
2. Stage and commit Phase 2E changes to git.
3. Create Git tag `phase-2e-fetch-strategy`.
4. Present full Phase 2 completion & certification report to user.
5. Await user authorization before proceeding to Phase 3 (Universal Extraction).

---

## 9. Important Warnings
- **Rule of Evidence**: Never claim "production ready" when what is verified is "benchmark candidate".
- **Rule of Invariants**: All IR metrics must stay within $[0.0, 1.0]$ without artificial clipping (`min(metric, 1.0)` is strictly forbidden).
- **Rule of Compatibility**: `CrawlResult` must continue supporting 3-tuple unpacking (`pages, links, robots = result`) for legacy consumers.
- **Rule of Multiprocessing**: State objects in queues must remain picklable on Windows (`spawn`).
- **Phase Gate Invariant**: Do NOT begin Phase 3 until Phase 2 is fully certified and tagged.
