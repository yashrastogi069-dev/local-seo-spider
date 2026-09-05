# COMPREHENSIVE TEST MATRIX

This document provides a detailed inventory of all 125 automated unit, integration, and security tests across all 23 test modules in `local-seo-spider`.

---

## Overall Summary
- **Total Test Files**: 23
- **Total Test Cases**: 125
- **Passed**: 123
- **Skipped**: 2 (both gracefully skipped due to optional `sentence-transformers` dependency)
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
| [`tests/test_comparison.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_comparison.py) | Integration | 1 | PASSED | Crawl comparison and differential ledger calculation |
| [`tests/test_concurrency.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_concurrency.py) | Integration | 3 | PASSED | Threaded static, async coroutine, and multiprocess static crawl execution |
| [`tests/test_controls_and_exports.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_controls_and_exports.py) | Integration | 12 | PASSED | CSV/JSON exports, robots.txt exclusions, redirect hops limit, error logging |
| [`tests/test_documents.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_documents.py) | Unit | 4 | PASSED | HTML, PDF, Markdown text extraction, deep JSON semantics preservation |
| [`tests/test_embeddings.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_embeddings.py) | Unit | 5 | 4 PASS, 1 SKIP* | Hash embeddings determinism, normalization, cosine bounds, dimension consistency |
| [`tests/test_extraction_profiles.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_extraction_profiles.py) | Unit | 2 | PASSED | Custom extraction profiles and schema mappings |
| [`tests/test_job_ledger.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_job_ledger.py) | Integration | 2 | PASSED | Persistent crawl state, job queue, restartability |
| [`tests/test_knowledge.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_knowledge.py) | Unit | 5 | PASSED | Chunking, heading path provenance, chunk deduplication |
| [`tests/test_metrics_math.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_metrics_math.py) | Unit | 8 | PASSED | Hand-computed IR metrics, edge cases, mathematical bounding in $[0.0, 1.0]$ |
| [`tests/test_observed_regressions.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_observed_regressions.py) | Regression | 11 | PASSED | Permanent regression suite covering all 11 historic failures |
| [`tests/test_playwright_browser.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_playwright_browser.py) | Integration | 3 | PASSED | Playwright Chromium launch, dynamic JS DOM rendering, live loopback app test |
| [`tests/test_rag_benchmark.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_benchmark.py) | Benchmark | 10 | PASSED | 14-point architectural verification (canonicalization, JSON, RRF, citations) |
| [`tests/test_rag_end_to_end.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_end_to_end.py) | E2E | 2 | 1 PASS, 1 SKIP* | End-to-end crawl, indexing, and grounded answer synthesis (hash & neural) |
| [`tests/test_rag_evaluation.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_evaluation.py) | Integration | 2 | PASSED | Golden corpus indexing, retrieval recall sanity |
| [`tests/test_rag_evaluation_harness.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_rag_evaluation_harness.py) | Benchmark | 3 | PASSED | 155-case benchmark evaluation, 6 retrieval ablations, 5 split tests |
| [`tests/test_ssrf_and_redaction.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_ssrf_and_redaction.py) | Security | 23 | PASSED | SSRF IP formats (octal, hex, dword, IPv6-mapped), cloud metadata, secret tokens |
| [`tests/test_tooling.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_tooling.py) | Unit | 2 | PASSED | CLI argument parsing, environment variable loading |
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
