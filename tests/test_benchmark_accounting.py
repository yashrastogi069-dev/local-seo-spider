"""Automated invariant tests for benchmark accounting, splits, and case integrity.

Enforces Phase 1 requirements:
- Total cases == answerable cases + unanswerable cases
- Total cases == sum of split counts
- Unique, stable case IDs across all benchmark cases
- Zero cross-split query leakages
- Exact mathematical reconciliation of retrieval and factual denominators
"""

from __future__ import annotations

import re
from collections import Counter
import pytest

from tests.fixtures.benchmark_cases import BENCHMARK_CASES


def test_benchmark_accounting_invariants() -> None:
    total_cases = len(BENCHMARK_CASES)
    assert total_cases == 155, f"Expected 155 benchmark cases, got {total_cases}"

    # Verify ID uniqueness and non-emptiness
    ids = [c.get("id") for c in BENCHMARK_CASES]
    assert all(bool(cid) for cid in ids), "Found benchmark cases with missing or empty IDs"
    id_counts = Counter(ids)
    duplicates = [cid for cid, count in id_counts.items() if count > 1]
    assert not duplicates, f"Found duplicate case IDs: {duplicates}"

    # Verify splits and counts
    allowed_splits = {"development", "calibration", "blind_test", "adversarial", "regression"}
    splits = [c.get("split") for c in BENCHMARK_CASES]
    assert all(s in allowed_splits for s in splits), "Found cases with invalid or unspecified splits"

    split_counts = Counter(splits)
    assert split_counts["development"] == 40
    assert split_counts["calibration"] == 25
    assert split_counts["blind_test"] == 40
    assert split_counts["adversarial"] == 30
    assert split_counts["regression"] == 20
    assert sum(split_counts.values()) == total_cases

    # Reconcile Answerability and Unanswerability populations
    unanswerable_cases = [c for c in BENCHMARK_CASES if c.get("requires_abstention")]
    answerable_cases = [c for c in BENCHMARK_CASES if not c.get("requires_abstention")]

    assert len(unanswerable_cases) == 30, f"Expected 30 unanswerable cases, got {len(unanswerable_cases)}"
    assert len(answerable_cases) == 125, f"Expected 125 answerable cases, got {len(answerable_cases)}"
    assert len(answerable_cases) + len(unanswerable_cases) == total_cases

    # Reconcile Retrieval-Scored population
    retrieval_scored_cases = [c for c in BENCHMARK_CASES if c.get("relevant_urls")]
    pure_unanswerable_retrieval = [c for c in BENCHMARK_CASES if not c.get("relevant_urls")]

    assert len(retrieval_scored_cases) == 140, f"Expected 140 retrieval cases, got {len(retrieval_scored_cases)}"
    assert len(pure_unanswerable_retrieval) == 15, f"Expected 15 pure unanswerable retrieval cases, got {len(pure_unanswerable_retrieval)}"
    assert len(retrieval_scored_cases) + len(pure_unanswerable_retrieval) == total_cases

    # Reconcile Overlap (Near-Miss, Distractor, and Conflict cases with target URLs)
    overlap_cases = [c for c in BENCHMARK_CASES if c.get("requires_abstention") and c.get("relevant_urls")]
    assert len(overlap_cases) == 15, f"Expected 15 overlap cases, got {len(overlap_cases)}"

    # Invariant formula: |A U B| = |A| + |B| - |A n B|
    # Where A = answerable (125), B = retrieval_scored (140)
    # Total unique cases = 140 retrieval-scored + 15 pure unanswerable without URLs = 155
    assert (len(retrieval_scored_cases) + len(unanswerable_cases) - len(overlap_cases)) == total_cases


def test_zero_cross_split_query_leakage() -> None:
    """Verify no exact or normalized query appears in multiple distinct splits."""
    cases = BENCHMARK_CASES
    leakages = []

    for i in range(len(cases)):
        for j in range(i + 1, len(cases)):
            c1, c2 = cases[i], cases[j]
            if c1["split"] != c2["split"]:
                q1_norm = re.sub(r"[^a-z0-9 ]", "", c1["query"].lower()).strip()
                q2_norm = re.sub(r"[^a-z0-9 ]", "", c2["query"].lower()).strip()
                if q1_norm == q2_norm:
                    leakages.append((c1["id"], c1["split"], c2["id"], c2["split"], c1["query"]))

    assert not leakages, f"Found cross-split query leakages: {leakages}"
