# PROJECT CHANGELOG

All notable changes, phase executions, and architectural transitions for Local SEO Spider & Semantic RAG are documented in this file.

---

## Current Status: Phase 0 & 1 Complete, Subphase 2A Complete / Transitioning to Subphase 2B

### Current Phase State:
- **PHASE 0 (Baseline & Forensic Audit)**: COMPLETED / PASSED
- **PHASE 1 (Evaluation Integrity)**: COMPLETED / PASSED
- **PHASE 2 (Crawler Core)**: ACTIVE
  - **Subphase 2A (Contracts & State Model)**: COMPLETED / PASSED
  - **Subphase 2B (Engine Independence & Browser)**: NEXT IN LINE
  - **Subphase 2C (Concurrency Engines)**: PENDING
  - **Subphase 2D (Frontier & Persistence)**: PENDING
  - **Subphase 2E (Security & Hardening)**: PENDING
- **PHASE 3 (Universal Extraction)**: PENDING
- **PHASE 4 (Knowledge/Indexing/Search)**: PENDING
- **PHASE 5 (RAG Intelligence)**: PENDING
- **PHASE 6 (Web Intelligence)**: PENDING
- **PHASE 7 (UI/UX)**: PENDING
- **PHASE 8 (Final Certification)**: PENDING

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
