# HISTORICAL REGRESSION TEST RESULTS

**Phase**: 1 — Evaluation Integrity, Benchmark Trustworthiness & Certification  
**Test Suite**: `tests/test_observed_regressions.py` (11 Historical Regression Fixtures)  
**Status**: **11 / 11 PASSED (100% REGRESSION-FREE)**  
**Evaluation Date**: 2026-09-05  

---

## 1. Regression Suite Objective

Every historical bug, edge case failure, security loophole, or mathematical flaw discovered in prior audits must have a permanent, automated regression test that guards against reintroduction.

All 11 historical regressions are codified in `tests/test_observed_regressions.py` and execute automatically during every test run.

---

## 2. Catalog of Historical Regressions & Verification Matrix

| Ref ID | Bug Description & Historical Symptom | Root Cause Analysis | Remediation Implemented | Automated Test Function | Test Status |
|:---:|:---|:---|:---|:---|:---:|
| **REG-01** | SSRF Octal & Dword IP Bypass | String matching failed to detect alternative IP representations (`0177.0.0.1`, `2130706433`) | Implemented strict IPv4/IPv6 socket resolution and `ipaddress.ip_address` range checks | `test_regression_ssrf_octal_and_dword_bypass` | **PASSED** |
| **REG-02** | Metric ZeroDivisionError on Empty Retrieval | Computing Precision@K or Recall@K on empty retrieval list crashed with division by zero | Added explicit denominator guards returning `0.0` or `None` on empty populations | `test_regression_metric_division_by_zero_empty_retrieval` | **PASSED** |
| **REG-03** | Artificial NDCG Clamping (`min(metric, 1.0)`) | Inaccurate IDCG calculation caused NDCG to exceed 1.0, hidden by artificial clipping | Recomputed mathematical IDCG using sorted relevance vectors; removed all clipping | `test_regression_ndcg_bounded_no_artificial_clamping` | **PASSED** |
| **REG-04** | Empty Corpus Search Crash | Searching an unindexed or empty crawl threw unhandled SQLite FTS5 syntax error | Added guard check for 0-chunk crawls, returning `[]` safely | `test_regression_empty_corpus_search_crash` | **PASSED** |
| **REG-05** | Whitespace-Only Query Crash | Queries with only spaces/newlines caused `IndexError` in token analyzer | Added query sanitization returning empty results / abstention safely | `test_regression_whitespace_only_query` | **PASSED** |
| **REG-06** | Duplicate Chunk Redundancy | Identical paragraphs across pages produced redundant ranking entries | Added SHA-256 chunk deduplication and URL diversity constraints | `test_regression_duplicate_chunk_deduplication` | **PASSED** |
| **REG-07** | Secret Token Leaks in URL Params | API keys and Bearer tokens in URLs were logged in plain text | Added regex token redaction across URLs, headers, and logs | `test_regression_secret_token_redaction` | **PASSED** |
| **REG-08** | Brier Score Empty Input Crash | Evaluating calibration on empty prediction lists threw `ZeroDivisionError` | Added empty input guard returning `0.0` Brier score | `test_regression_brier_score_empty_predictions` | **PASSED** |
| **REG-09** | Case-Sensitive Exact Phrase Match | Uppercase queries failed exact phrase matching against lowercase corpus text | Normalized both query and passage text to lowercase before matching | `test_regression_exact_phrase_bonus_case_insensitivity` | **PASSED** |
| **REG-10** | Distractor Overconfidence | Plausible distractors received high confidence (> 0.6) due to lexical term overlap | Implemented `classify_evidence_support()` with answer-bearing requirements | `test_regression_near_miss_unanswerable_confidence` | **PASSED** |
| **REG-11** | Loss of Heading Path Provenance | Chunking discarded document heading hierarchy (`h1 > h2 > h3`) | Preserved heading breadcrumbs in `heading_path` and `heading_path_json` columns | `test_regression_heading_provenance_preservation` | **PASSED** |

---

## 3. Negative Failure Discrimination Verification

To prove that the regression tests are discriminative (i.e. capable of catching real bugs rather than trivially passing):
- Modifying `app/urltools.py` to allow decimal IPs causes `REG-01` to immediately fail.
- Modifying `app/evaluation.py` to remove denominator guards causes `REG-02` to throw `ZeroDivisionError`.
- Artificial clipping in `app/evaluation.py` causes `REG-03` to fail with assertion error.

The regression test suite is **fully active, non-vacuous, and reproducible**.
