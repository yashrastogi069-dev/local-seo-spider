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
- [x] HTTP connection pooling, exponential backoff on 429/5xx errors.
- [x] Concurrency modes verified (serial, thread, async, multiprocess).
- [x] Outbound SSRF protection across all IP representations (octal, hex, dword, IPv6-mapped) and cloud metadata endpoints.
- [x] URL canonicalization and parameter sorting.
- [ ] Comprehensive live internet soak test under high latency and network drops.
- **GATE STATUS**: **PARTIAL**

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
