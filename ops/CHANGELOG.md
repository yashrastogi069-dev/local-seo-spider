# PROJECT CHANGELOG

All notable changes, phase executions, and architectural transitions for Local SEO Spider & Semantic RAG are documented in this file.

---

## Current Status: Phase 0 & Phase 1 Complete / Transitioning to Phase 2

### Current Phase State:
- **PHASE 0 (Baseline & Forensic Audit)**: COMPLETED / PASSED
- **PHASE 1 (Evaluation Integrity)**: COMPLETED / PASSED
- **PHASE 2 (Crawler Core)**: NEXT IN LINE
- **PHASE 3 (Universal Extraction)**: PENDING
- **PHASE 4 (Knowledge/Indexing/Search)**: PENDING
- **PHASE 5 (RAG Intelligence)**: PENDING
- **PHASE 6 (Web Intelligence)**: PENDING
- **PHASE 7 (UI/UX)**: PENDING
- **PHASE 8 (Final Certification)**: PENDING

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
