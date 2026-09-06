# OPERATIONAL STATE: PRIMARY SHORT-TERM MEMORY

*Last Updated*: 2026-09-06T13:35:00+05:30  
*Operating Mode*: Engineering Operating System & Integrity Layer  
*Primary Source of Truth*: Executable Code (`app/`) & Automated Tests (`tests/`)

---

## 1. Active Phase & Subphase
- **Active Phase**: PHASE 2 (Crawler Core) — **PHASE 2G.2 COMPLETED & CERTIFIED**
- **Completed Subphases**:
  - Phase 2A (Crawler Contracts + State Model) — **PASSED**
  - Phase 2B (URL Normalization + Frontier + Crawl Lifecycle) — **PASSED**
  - Phase 2C (Four Independent Crawler Engines) — **PASSED & CERTIFIED**
  - Phase 2D (Concurrency Stress, Failure Injection & Resource Safety) — **PASSED & CERTIFIED**
  - Phase 2E (Static Fetch + Playwright + Smart Escalation) — **PASSED & CERTIFIED**
  - Phase 2F (Robots, Politeness, Retries & Crawl Budgets) — **PASSED & CERTIFIED**
  - Phase 2G (Resume, Recovery, Crash Safety & Idempotency) — **PASSED & CERTIFIED**
  - Phase 2G.1 (Hosted Embedding Provider Architecture & Re-Embedding) — **PASSED & CERTIFIED**
  - Phase 2G.2 (Pipeline Decoupling, Status Tracking & Re-Indexability) — **PASSED & CERTIFIED**
- **Baseline Git Checkpoints**:
  - `db7fc50` (Tags: `phase-1-certified`, `pre-phase-2-crawler-core`)
  - `fdd59d9` (Tag: `phase-2c-engine-independence`)
  - `phase-2d-concurrency-hardening`
  - `phase-2e-fetch-strategy`
  - `ebfb65e` (Tag: `phase-2f-budgets-politeness`)
  - `28c686f` (Tag: `phase-2g-resume-recovery`)
  - `3115cc0` (Tag: `phase-2g1-hosted-embedding-provider`)
  - Target commit for Phase 2G.2 (Tag: `phase-2g2-pipeline-decoupling`)
- **Phase 1 Evaluation Baseline**: **FROZEN & TRUSTED** (Do NOT modify Phase 1 fixtures)

---

## 2. Current Objective
Phase 2G.2 (Pipeline Decoupling, Lifecycle Status Architecture, Durable Lexical Persistence, Partial Indexing, Model Mismatch Detection, Content Hashing Skip Logic, and Targeted Retry Workflow) is certified.
Next: Run fresh-eyes subagent review, stage and commit changes, tag `phase-2g2-pipeline-decoupling`, and await user directive.

---

## 3. Current Status
- **Phase 0 Status**: `PASSED`
- **Phase 1 Status**: `PASSED & CERTIFIED (FROZEN)`
- **Phase 2 Status**: `PHASE 2G.2 CERTIFIED`
  - **Subphase 2A Status**: `PASSED`
  - **Subphase 2B Status**: `PASSED`
  - **Subphase 2C Status**: `PASSED & CERTIFIED`
  - **Subphase 2D Status**: `PASSED & CERTIFIED`
  - **Subphase 2E Status**: `PASSED & CERTIFIED`
  - **Subphase 2F Status**: `PASSED & CERTIFIED`
  - **Subphase 2G Status**: `PASSED & CERTIFIED`
  - **Subphase 2G.1 Status**: `PASSED & CERTIFIED`
  - **Subphase 2G.2 Status**: `PASSED & CERTIFIED`
- **Current Test State**: 393 Passed, 3 Skipped, 0 Failed across 45 test modules (100% pass rate).

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

## 5. Phase 2 Remediation Progress (Subphases 2A-2G.2: 100% COMPLETE)
- [x] **REQ-CRAWL-001 / ADR-009**: Unified crawler contract, `CrawlerEngineProtocol`, `CrawlStatus` enums, `CrawlResult` backward-compatible unpacking. (Phase 2A - DONE)
- [x] **REQ-CRAWL-002 / ADR-010**: URL Normalization and 8-state Frontier FSM with exact accounting reconciliation, depth tracking, canonical deduplication, and redirect alias mapping. (Phase 2B - DONE)
- [x] **REQ-CRAWL-003, 004, 005, 006 / ADR-011**: Four independent concurrency engines (Serial, Thread, Coroutine, Multiprocess) with genuine execution, politeness throttling, and connection pooling. (Phase 2C - DONE)
- [x] **REQ-CRAWL-007 / 008**: Fallback and strategy transparency; `fallback_occurred` and `fallback_reason` invariant in `CrawlResult`. (Phase 2A, 2C, 2E - DONE)
- [x] **REQ-CRAWL-008 / ADR-013**: Observable static vs Playwright fetch strategies and smart escalation (`#root`, `#app`, `#__next`, challenges) with anti-criteria enforcement. (Phase 2E - DONE)
- [x] **REQ-CRAWL-011 / ADR-012**: SQLite schema extended and WAL mode + 30s busy timeout for concurrent multi-threaded write safety. (Phase 2A & 2D - DONE)
- [x] **REQ-CRAWL-012**: `CancellationToken` implemented with thread-safe cooperative cancellation and sub-second interruptible sleeps. (Phase 2A & 2D - DONE)
- [x] **REQ-CRAWL-013 / ADR-014**: RFC 9309 robots compliance, per-host politeness isolation, jittered retries, and multi-engine crawl budgets. (Phase 2F - DONE)
- [x] **REQ-CRAWL-014 / ADR-015**: Crash recovery, checkpoint rollback, resumed state machine reconciliation, and auto-fallback. (Phase 2G - DONE)
- [x] **REQ-CRAWL-015**: Resource safety verified across threads, child processes, Playwright browser sessions (0 orphan Chromium processes), and memory stability. (Phase 2D & 2E - DONE)
- [x] **REQ-EMBED-001 / ADR-016**: Hosted embedding provider architecture, Gemini REST integration, multi-generation vector schema, and re-embedding without recrawl. (Phase 2G.1 - DONE)
- [x] **REQ-PIPE-001 / ADR-017**: Pipeline decoupling (7 stages, 7 statuses), durable lexical priority, partial indexing fault isolation, content-hash skip logic, model mismatch detection, and targeted retry workflow. (Phase 2G.2 - DONE)

---

## 6. Unresolved P0 / P1 / P2 Issues
- **P0 (Critical / Blocker)**: None. (All Phase 2 requirements verified with 0 failures).
- **P1 (High)**: None.
- **P2 (Medium / Documented Acceptance)**:
  - `sentence-transformers` is optional; offline test runner relies on `HashEmbeddingProvider`.
  - Playwright requires local Chromium binary for dynamic JavaScript rendering (`render_enabled=True`).

---

## 7. Last Completed Work
1. Implemented Phase 2G.2: Pipeline Decoupling, Status Tracking & Re-Indexability:
   - `app/types.py`: Added `PipelineStage` enum, `StageStatus` enum, and `StageRecord` dataclass.
   - `app/database.py`: Created `pipeline_stage_records` and `failed_embedding_chunks` tables; implemented `index_knowledge_pipeline()` with two-stage commit (lexical first), rowid-preserving upserts, `content_hash` skip logic, and partial batch failure isolation; implemented `detect_embedding_generation_mismatch()` and `retry_failed_embeddings()`.
   - `app/main.py`: Instrumented `_run_claimed_crawl()` with all 7 pipeline stages; added API endpoints `GET /crawls/{crawl_id}/pipeline`, `POST /crawls/{crawl_id}/pipeline/retry-embedding`, and `POST /crawls/{crawl_id}/reembed`.
   - `tests/test_pipeline_decoupling.py`: 11 comprehensive tests verifying provider outage durability, partial batch recovery, 429 backoff tracking, content hash dedup, model mismatch detection, and targeted retries.
2. Verified 100% full repository test pass rate: 393 passed, 3 skipped, 0 failed across all 45 test modules.
3. Recorded ADR-017 in `DECISIONS.md`.

---

## 8. Exact Next Action
1. Execute independent fresh-eyes subagent review.
2. Stage and commit Phase 2G.2 changes to git.
3. Create Git tag `phase-2g2-pipeline-decoupling`.
4. Present full Phase 2G.2 completion & certification report to user.
5. Await user authorization before proceeding to Phase 2H (SSRF Defense, Security & Allowed Hosts Enforcement).

---

## 9. Important Warnings
- **Rule of Evidence**: Never claim "production ready" when what is verified is "benchmark candidate".
- **Rule of Invariants**: All IR metrics must stay within $[0.0, 1.0]$ without artificial clipping (`min(metric, 1.0)` is strictly forbidden).
- **Rule of Compatibility**: `CrawlResult` must continue supporting 3-tuple unpacking (`pages, links, robots = result`) for legacy consumers.
- **Rule of Multiprocessing**: State objects in queues must remain picklable on Windows (`spawn`).
- **Phase Gate Invariant**: Do NOT begin Phase 3 until Phase 2 is fully certified and tagged.
