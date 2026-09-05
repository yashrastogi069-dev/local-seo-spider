# OPERATIONAL STATE: PRIMARY SHORT-TERM MEMORY

*Last Updated*: 2026-09-05T12:15:00+05:30  
*Operating Mode*: Engineering Operating System & Integrity Layer  
*Primary Source of Truth*: Executable Code (`app/`) & Automated Tests (`tests/`)

---

## 1. Active Phase & Subphase
- **Active Phase**: PHASE 0 (Baseline & Forensic Audit / Operating System Initialization)
- **Active Subphase**: Phase 0 Complete -> Establishing Core Integrity & Memory Layer
- **Next Transition Phase**: PHASE 1 (Evaluation Integrity Formal Release Verification)

---

## 2. Current Objective
Establish the Antigravity Engineering Operating System & Integrity Layer across `/docs/` and `/ops/`, ensuring full requirements traceability, evidence ledger accounting, security models, and session handoff mechanisms before proceeding to Phase 1/Phase 2 implementation.

---

## 3. Current Status
- **Phase 0 Status**: `PASSED`
- **Phase 1 Evaluation Formulation & Metrics**: Code implemented and tests passing (8/8 math invariant tests, 155 frozen benchmark cases, 0.0433 Brier score, 0.0966 ECE).
- **Test Suite Pass Rate**: **123 Passed, 2 Skipped, 0 Failed** across 23 test modules.

---

## 4. Last Verified Test State
- **Command**: `pytest`
- **Results**: 123 passed, 2 skipped, 1 warning in 217.23s.
- **Skipped Details**:
  1. `tests/test_embeddings.py:25` (Requires optional `sentence-transformers` package; skipped with clear diagnostic message).
  2. `tests/test_rag_end_to_end.py:17` (Requires optional `sentence-transformers` package; hash provider e2e test companion passes).
- **Regression Suite**: 11/11 historic regressions passed (`tests/test_observed_regressions.py`).
- **Security Suite**: 23/23 SSRF and secret redaction tests passed (`tests/test_ssrf_and_redaction.py`).

---

## 5. Current Blockers
- **None**: No P0 or P1 blockers exist. All test suites pass cleanly.

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
