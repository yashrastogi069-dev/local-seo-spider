# REQUIREMENTS TRACEABILITY MATRIX

This document establishes bidirectional traceability between system requirements, architecture, code implementations, test suites, and empirical verification evidence.

---

## Traceability Status Legend
- **VERIFIED**: Code implemented, fully tested by targeted/integration tests, and verified with reproducible evidence.
- **PARTIALLY VERIFIED**: Code implemented and unit tested, but pending broader live soak or external dependency testing.
- **IMPLEMENTED BUT UNPROVEN**: Code exists in codebase but lacks rigorous assertion tests or empirical verification.
- **FAILED**: Implementation or test fails against expected criteria.
- **MISSING**: Requirement not yet implemented.

---

## 1. Evaluation & Invariant Integrity Requirements (Phase 1)

| Requirement ID | Requirement Text | Spec Section | Phase | Implementation Location | Verification Tests | Status | Empirical Evidence | Unresolved Limitations |
|:---|:---|:---:|:---:|:---|:---|:---:|:---|:---|
| **REQ-EVAL-001** | All normalized IR metrics (Recall, Precision, MRR, NDCG) must strictly remain in $[0.0, 1.0]$. | Phase 1 | 1 | [`app/evaluation.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/evaluation.py#L25-L122) | [`tests/test_metrics_math.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_metrics_math.py) | **VERIFIED** | 8/8 unit tests pass with hand-computed edge cases. | None. |
| **REQ-EVAL-002** | Zero metric self-deception: `min(metric, 1.0)` is strictly prohibited. | Phase 1 | 1 | [`app/evaluation.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/evaluation.py), [`app/database.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/database.py#L339) | [`tests/test_metrics_math.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_metrics_math.py), [`tests/test_observed_regressions.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_observed_regressions.py#L256) | **VERIFIED** | Grep confirms 0 occurrences of `min(1.0` in evaluation code. | None. |
| **REQ-EVAL-003** | NDCG calculation must discount duplicate document IDs to prevent ranking capacity inflation. | Phase 1 | 1 | [`app/evaluation.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/evaluation.py#L97) | [`tests/test_metrics_math.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_metrics_math.py#L92) | **VERIFIED** | Duplicate ID tests confirm NDCG stays $\le 1.0$. | None. |
| **REQ-EVAL-004** | Benchmark must be partitioned into 5 independent frozen splits with isolated blind testing. | Phase 4 | 1 | [`tests/fixtures/benchmark_cases.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/fixtures/benchmark_cases.py) | [`tests/test_rag_evaluation_harness.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_evaluation_harness.py#L249) | **VERIFIED** | 155 frozen cases evaluated across Dev (40), Cal (25), Blind (40), Adv (30), Reg (20). | Blind test set is frozen and never tuned against. |
| **REQ-EVAL-005** | Brier score and Expected Calibration Error (ECE) must evaluate probability calibration in $[0.0, 1.0]$. | Phase 24 | 1 | [`app/evaluation.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/evaluation.py#L148) | [`tests/test_metrics_math.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_metrics_math.py#L140), [`tests/test_rag_evaluation_harness.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_evaluation_harness.py#L179) | **VERIFIED** | Brier score = 0.0433, ECE = 0.0966 across 155 cases. | Bucketing uses 5 equal-width buckets. |
| **REQ-EVAL-006** | Contamination resistance: zero hardcoded queries, case IDs, or answers in production code. | Phase 1 | 1 | [`app/qa.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/qa.py) | [`tests/test_contamination.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_contamination.py) | **VERIFIED** | 3/3 automated contamination tests pass; 0 leaks across 23 app modules. | None. |
| **REQ-EVAL-007** | Population accounting reconciliation: 155 total cases reconciled across answerable and retrieval sets with 0 cross-split leakage. | Phase 1 | 1 | [`tests/fixtures/benchmark_cases.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/fixtures/benchmark_cases.py) | [`tests/test_benchmark_accounting.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_benchmark_accounting.py) | **VERIFIED** | 2/2 accounting tests pass; Dev(40)+Cal(25)+Blind(40)+Adv(30)+Reg(20)=155. | None. |

---

## 2. Crawler Core & Security Requirements (Phase 2)

| Requirement ID | Requirement Text | Spec Section | Phase | Implementation Location | Verification Tests | Status | Empirical Evidence | Unresolved Limitations |
|:---|:---|:---:|:---:|:---|:---|:---:|:---|:---|
| **REQ-CRAWL-001** | Support 4 independent concurrency crawl modes: serial, threaded, async, and multiprocess. | Phase 28 | 2 | [`app/crawler.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/crawler.py#L130-L245) | [`tests/test_concurrency.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_concurrency.py) | **VERIFIED** | 3/3 concurrency tests pass including Windows spawn process pool. | Live web rate limits must be configured per host. |
| **REQ-CRAWL-002** | URL canonicalization: strip tracking params, normalize slashes, sort query parameters. | Phase 5 | 2 | [`app/urltools.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/urltools.py#L18) | [`tests/test_rag_benchmark.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_benchmark.py#L56), [`tests/test_observed_regressions.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_observed_regressions.py#L172) | **VERIFIED** | `url1` and `url2` with differing order and `utm_*` params resolve identically. | Semantic query params (e.g. `?id=1`) are strictly preserved. |
| **REQ-SEC-001** | Outbound SSRF defense: block private, loopback, link-local, and cloud metadata across all IP encodings. | Phase 11 | 2 | [`app/urltools.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/urltools.py#L75-L160) | [`tests/test_ssrf_and_redaction.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_ssrf_and_redaction.py#L18) | **VERIFIED** | 23/23 tests pass covering octal, hex, dword, IPv6-mapped, and cloud IPs (`100.100.100.200`, `169.254.169.254`). | DNS re-resolution must be verified at connection socket time. |
| **REQ-SEC-002** | Secret & token redaction across URLs, headers, and text. | Phase 10 | 2 | [`app/urltools.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/urltools.py#L170-L240) | [`tests/test_ssrf_and_redaction.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_ssrf_and_redaction.py#L110) | **VERIFIED** | Redacts Bearer, JWT, Stripe, variable Google API keys, Slack, GitHub, AWS, private keys. | High entropy random strings without keywords are not redacted. |

---

## 3. Universal Extraction Requirements (Phase 3)

| Requirement ID | Requirement Text | Spec Section | Phase | Implementation Location | Verification Tests | Status | Empirical Evidence | Unresolved Limitations |
|:---|:---|:---:|:---:|:---|:---|:---:|:---|:---|
| **REQ-EXT-001** | Multi-format extraction: HTML, rendered JS DOM, JSON, PDF, Markdown. | Phase 7 | 3 | [`app/documents.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/documents.py#L15) | [`tests/test_documents.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_documents.py) | **VERIFIED** | 4/4 document tests pass across all formats. | OCR for scanned image-only PDFs not implemented. |
| **REQ-EXT-002** | Preserve deep JSON semantics: field-value bindings, scalar types, array structures, nested objects. | Phase 7 | 3 | [`app/documents.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/documents.py#L95), [`app/knowledge.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/knowledge.py#L85) | [`tests/test_documents.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_documents.py#L65), [`tests/test_observed_regressions.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_observed_regressions.py#L193) | **VERIFIED** | Structured JSON yields non-zero word counts and field-value chunks (`field = total, value = 150`). | Deeply recursive JSON (>20 levels) truncated. |

---

## 4. Knowledge, Indexing & Hybrid Search (Phase 4)

| Requirement ID | Requirement Text | Spec Section | Phase | Implementation Location | Verification Tests | Status | Empirical Evidence | Unresolved Limitations |
|:---|:---|:---:|:---:|:---|:---|:---:|:---|:---|
| **REQ-IDX-001** | Chunk deduplication across pages and heading path provenance preservation. | Phase 6, 9 | 4 | [`app/knowledge.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/knowledge.py#L140) | [`tests/test_knowledge.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_knowledge.py), [`tests/test_rag_benchmark.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_benchmark.py#L68) | **VERIFIED** | Duplicate chunks sharing content hash collapsed; heading paths preserved. | Very short chunks (<3 words) filtered out. |
| **REQ-IDX-002** | Hybrid indexing: SQLite FTS5 (BM25 lexical) + vector storage combined via RRF. | Phase 13 | 4 | [`app/database.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/database.py#L650-L750) | [`tests/test_rag_benchmark.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_benchmark.py#L124), [`tests/test_rag_evaluation_harness.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_evaluation_harness.py#L215) | **VERIFIED** | Recall@5 = 0.986 across benchmark; RRF merges lexical and vector candidates. | Vector dimension fixed per database. |
| **REQ-IDX-003** | Modular embedding provider interface supporting offline hash fallback and neural models. | Phase 14 | 4 | [`app/embeddings.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/embeddings.py) | [`tests/test_embeddings.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_embeddings.py) | **VERIFIED** | 4/4 active tests pass; HashEmbeddingProvider produces normalized vectors with valid cosine bounds. | Neural sentence-transformers optional extra. |

---

## 5. RAG Intelligence & Citation Verification (Phase 5)

| Requirement ID | Requirement Text | Spec Section | Phase | Implementation Location | Verification Tests | Status | Empirical Evidence | Unresolved Limitations |
|:---|:---|:---:|:---:|:---|:---|:---:|:---|:---|
| **REQ-RAG-001** | Dynamic, domain-agnostic answer planning without hardcoded query shortcuts. | Phase 2 | 5 | [`app/qa.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/qa.py#L425-L600) | [`tests/test_answering.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_answering.py), [`tests/test_rag_evaluation_harness.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_evaluation_harness.py) | **VERIFIED** | Generalized extractors answer comparisons, slots, collections, and semantic questions. | Relies on sentence boundaries for extraction. |
| **REQ-RAG-002** | Atomic claim-level citation verification (PASS / PARTIAL / FAIL). | Phase 19, 20 | 5 | [`app/qa.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/qa.py#L210-L330) | [`tests/test_rag_benchmark.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_benchmark.py#L193) | **VERIFIED** | Detects number, entity, unit mismatches and rejects ungrounded claims. | Complex logical implication without term overlap requires neural NLI. |
| **REQ-RAG-003** | Strict abstention gate with $confidence = 0.0$ on unanswerable and contradictory queries. | Phase 22, 23 | 5 | [`app/qa.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/qa.py#L650-L720) | [`tests/test_rag_benchmark.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_benchmark.py#L254), [`tests/test_rag_evaluation_harness.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_evaluation_harness.py#L289) | **VERIFIED** | 100.0% abstention accuracy on 30 unanswerable/adversarial queries; 0.0% hallucination rate. | Near-misses with very high lexical overlap must be guarded by slot checks. |
| **REQ-RAG-004** | Calibrated confidence formula incorporating slot completeness, evidence support, and conflict penalties. | Phase 24 | 5 | [`app/qa.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/qa.py#L380-L424) | [`tests/test_rag_benchmark.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_benchmark.py#L274) | **VERIFIED** | Missing slots cap confidence at $\le 0.50$; Brier score = 0.0433. | None. |

---

## 6. Web Intelligence & Browser Rendering (Phase 6)

| Requirement ID | Requirement Text | Spec Section | Phase | Implementation Location | Verification Tests | Status | Empirical Evidence | Unresolved Limitations |
|:---|:---|:---:|:---:|:---|:---|:---:|:---|:---|
| **REQ-WEB-001** | Crawl coverage rate computed via exact set union: $len(crawled) / len(discovered)$. | Phase 26 | 6 | [`app/analyzer.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/analyzer.py#L111), [`app/database.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/database.py#L300) | [`tests/test_analyzer.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_analyzer.py#L50), [`tests/test_rag_benchmark.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_benchmark.py#L380) | **VERIFIED** | Set union guarantees coverage rate mathematically stays in $[0.0, 1.0]$. | None. |
| **REQ-WEB-002** | Playwright Chromium launch, dynamic DOM mutation rendering, and error recovery. | Phase 27 | 6 | [`app/browser.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/app/browser.py) | [`tests/test_playwright_browser.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_playwright_browser.py) | **VERIFIED** | 3/3 tests pass verifying dynamic JS rendered text extraction and UI test. | Requires local Chromium installation on host machine. |
