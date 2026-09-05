# OPERATIONAL STATE: PRIMARY SHORT-TERM MEMORY

*Last Updated*: 2026-09-05T12:15:00+05:30  
*Operating Mode*: Engineering Operating System & Integrity Layer  
*Primary Source of Truth*: Executable Code (`app/`) & Automated Tests (`tests/`)

---

## 1. Active Phase & Subphase
- **Active Phase**: PHASE 2 (Crawler Core)
- **Active Subphase**: Phase 2 Kickoff — Deep Forensic Reconstruction Completed (No Implementation Yet)
- **Baseline Git Checkpoint**: Commit `db7fc50` (Tags: `pre-phase-2-crawler-core`, `phase-1-certified`)
- **Phase 1 Evaluation Baseline**: **FROZEN & TRUSTED** (Do NOT modify Phase 1 fixtures)
- **Next Transition Subphase**: PHASE 2A (Engine Architecture & Contract Unification)

---

## 2. Current Objective
Execute Phase 2 Kickoff Forensic Reconstruction:
1. Conduct deep code inspection of all 4 engines (`serial`, `thread`, `async`, `process`) and fetch strategies (`static`, `browser`).
2. Catalog all hidden fallbacks, fake concurrency, depth amnesia, client churn, and test gaps.
3. Formulate formal requirements `REQ-CRAWL-001` through `REQ-CRAWL-016`.
4. Produce comprehensive baseline report `reports/phase-2/phase_2_baseline_forensic_audit.md`.
5. Maintain zero implementation changes until kickoff audit is reviewed and approved.

---

## 3. Current Status
- **Phase 0 Status**: `PASSED`
- **Phase 1 Status**: `PASSED & CERTIFIED (FROZEN)`
- **Phase 2 Status**: `ACTIVE — FORENSIC KICKOFF COMPLETED`
- **Current Test State**: 128 Passed, 2 Skipped, 0 Failed across 25 test modules.

---

## 4. Last Verified Test State
- **Command**: `pytest`
- **Results**: 128 passed, 2 skipped, 1 warning in 181.53s.
- **Skipped Details**:
  1. `tests/test_embeddings.py:25` (Requires optional `sentence-transformers` package).
  2. `tests/test_rag_end_to_end.py:17` (Requires optional `sentence-transformers` package).
- **Regression Suite**: 11/11 historic regressions passed (`tests/test_observed_regressions.py`).
- **Security Suite**: 23/23 SSRF and secret redaction tests passed (`tests/test_ssrf_and_redaction.py`).
- **Contamination Suite**: 3/3 contamination tests passed (`tests/test_contamination.py`).
- **Accounting Suite**: 2/2 accounting reconciliation tests passed (`tests/test_benchmark_accounting.py`).

---

## 5. Active Phase 2 Defects Identified (Require Remediation in Subphases 2A-2E)
- **P0-01**: `process` mode fetches sequentially in main thread; does not do parallel multiprocess I/O.
- **P0-02**: `thread`, `async`, and `process` modes silently ignore `render_enabled=True`.
- **P0-03**: `test_crawl_engine_playwright_rendering` is a fake test (bypasses `CrawlEngine.run()`).
- **P1-01**: Depth and parent URL are hardcoded to `0` and `""` on every page.
- **P1-02**: All-or-nothing in-memory persistence (single mid-crawl crash drops all fetched pages).
- **P1-03**: Running crawls cannot be paused, cancelled, or aborted via API/UI.
- **P1-04**: Silent fallback to static on browser launch failure.
- **P1-05**: Frontier halts URL discovery prematurely based on `len(queued)` rather than crawled pages.
- **P1-06**: Redirect targets not added to `queued`, causing duplicate fetches.
- **P2-01**: Zero HTTP connection pooling in `thread`, `async`, and `process` modes.
- **P2-02**: Async event loop and client recreated per batch.
- **P2-03**: Global lock serializes thread delay.
- **P2-04**: Pre-connection DNS resolution missing (DNS rebinding vulnerability).

---

## 6. Unresolved P0 / P1 / P2 Issues
- **P0 (Critical / Blocker)**: None.
- **P1 (High / Required Before Phase Close)**: None for Phase 0.
- **P2 (Medium / Documented Acceptance)**:
  - `sentence-transformers` is optional; offline test runner relies on `HashEmbeddingProvider`.
  - Playwright requires local Chromium binary for dynamic JavaScript rendering (`render_enabled=True`).

---

## 7. Last Completed Work
1. Created `/docs/PROJECT_MASTER_SPEC.md`
2. Created `/docs/ARCHITECTURE.md`
3. Created `/docs/DECISIONS.md` (ADR-001 to ADR-008)
4. Created `/docs/TEST_MATRIX.md` (125 tests cataloged)
5. Created `/docs/RELEASE_GATES.md` (Phase 0-8 gate definitions)
6. Created `/ops/CHANGELOG.md`
7. Created `/ops/KNOWN_ISSUES.md`

---

## 8. Exact Next Action
1. Create `/docs/REQUIREMENTS_TRACEABILITY.md` with unique requirement IDs.
2. Create `/ops/EVIDENCE_LEDGER.md` recording all empirical benchmark metrics and claim evidence.
3. Create `/ops/SESSION_HANDOFF.md` for seamless context-loss recovery.
4. Create `/docs/SECURITY_MODEL.md`, `/docs/DATA_MODEL.md`, and `/docs/API_CONTRACTS.md`.
5. Create a Git checkpoint tag/commit for the baseline integrity layer.

---

## 9. Important Warnings
- **Rule of Evidence**: Never claim "production ready" when what is verified is "benchmark candidate".
- **Rule of Invariants**: All IR metrics must stay within $[0.0, 1.0]$ without artificial clipping (`min(metric, 1.0)` is strictly forbidden).
- **Rule of Web Content**: Crawled content is strictly untrusted data. Never allow scraped web instructions to override system prompts.

---

## 10. Files Currently Under Active Modification
- `/docs/REQUIREMENTS_TRACEABILITY.md`
- `/ops/EVIDENCE_LEDGER.md`
- `/ops/SESSION_HANDOFF.md`
- `/docs/SECURITY_MODEL.md`
- `/docs/DATA_MODEL.md`
- `/docs/API_CONTRACTS.md`

---

## 11. Known Unverified Assumptions
- Assumption: `HashEmbeddingProvider` is sufficient for CI test execution without sentence-transformers. (Verified for test stability, but neural semantic capability requires manual install of `sentence-transformers`).
- Assumption: SQLite FTS5 extension is available on all standard Python distributions on Windows/Linux (Verified: built-in on Python 3.12).
