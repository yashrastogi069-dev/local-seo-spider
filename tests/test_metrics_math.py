"""Independent unit tests verifying mathematical correctness and invariants of evaluation metrics.

Phase 1 compliance:
- Hand-computed ground truth values
- Edge cases: zero relevant, zero retrieved, all relevant, none relevant, duplicates, fewer than K
- Mathematical invariants: all values strictly in [0.0, 1.0] without artificial clamping
"""

from __future__ import annotations

import math
import pytest

from app.evaluation import (
    compute_recall_at_k,
    compute_hit_at_k,
    compute_precision_at_k,
    compute_reciprocal_rank,
    compute_dcg,
    compute_ndcg,
    compute_citation_metrics,
    compute_calibration_metrics,
)


def test_recall_at_k_hand_computed() -> None:
    # 2 relevant out of 4 docs in corpus
    relevant = {"docA", "docB"}

    # Top 3 retrieved: docA is retrieved at rank 1, docC at 2, docD at 3
    retrieved = ["docA", "docC", "docD", "docB"]

    # Recall@1: docA is in retrieved[:1] -> 1/2 = 0.5
    assert compute_recall_at_k(retrieved, relevant, k=1) == 0.5

    # Recall@2: docA in retrieved[:2] -> 1/2 = 0.5
    assert compute_recall_at_k(retrieved, relevant, k=2) == 0.5

    # Recall@3: docA in retrieved[:3] -> 1/2 = 0.5
    assert compute_recall_at_k(retrieved, relevant, k=3) == 0.5

    # Recall@4: docA and docB in retrieved[:4] -> 2/2 = 1.0
    assert compute_recall_at_k(retrieved, relevant, k=4) == 1.0


def test_recall_edge_cases() -> None:
    # Zero relevant documents -> 0.0
    assert compute_recall_at_k(["docA"], set(), k=5) == 0.0

    # Zero retrieved results -> 0.0
    assert compute_recall_at_k([], {"docA"}, k=5) == 0.0

    # None relevant in retrieved -> 0.0
    assert compute_recall_at_k(["docX", "docY"], {"docA", "docB"}, k=5) == 0.0

    # All retrieved are relevant
    assert compute_recall_at_k(["docA", "docB"], {"docA", "docB"}, k=2) == 1.0

    # Duplicates in retrieved list must not artificially inflate recall
    retrieved_with_dups = ["docA", "docA", "docA"]
    assert compute_recall_at_k(retrieved_with_dups, {"docA", "docB"}, k=3) == 0.5

    # k <= 0
    assert compute_recall_at_k(["docA"], {"docA"}, k=0) == 0.0


def test_precision_at_k_hand_computed() -> None:
    relevant = {"docA", "docB"}
    retrieved = ["docA", "docC", "docB", "docD", "docE"]

    # Precision@1: 1 hit in 1 = 1.0
    assert compute_precision_at_k(retrieved, relevant, k=1) == 1.0

    # Precision@2: 1 hit in 2 = 0.5
    assert compute_precision_at_k(retrieved, relevant, k=2) == 0.5

    # Precision@3: 2 hits in 3 = 2/3
    assert abs(compute_precision_at_k(retrieved, relevant, k=3) - (2.0 / 3.0)) < 1e-6

    # Precision@5: 2 hits in 5 = 0.4
    assert compute_precision_at_k(retrieved, relevant, k=5) == 0.4


def test_precision_edge_cases() -> None:
    # Zero relevant -> 0.0
    assert compute_precision_at_k(["docA"], set(), k=5) == 0.0

    # Zero retrieved -> 0.0
    assert compute_precision_at_k([], {"docA"}, k=5) == 0.0

    # None relevant -> 0.0
    assert compute_precision_at_k(["docX", "docY"], {"docA"}, k=5) == 0.0

    # Duplicates in retrieved must not count multiple times
    retrieved_dups = ["docA", "docA", "docC"]
    assert compute_precision_at_k(retrieved_dups, {"docA"}, k=2) == 0.5


def test_mrr_hand_computed() -> None:
    relevant = {"target"}

    # First relevant at rank 1 -> RR = 1.0
    assert compute_reciprocal_rank(["target", "other"], relevant) == 1.0

    # First relevant at rank 2 -> RR = 0.5
    assert compute_reciprocal_rank(["other", "target"], relevant) == 0.5

    # First relevant at rank 4 -> RR = 0.25
    assert compute_reciprocal_rank(["a", "b", "c", "target"], relevant) == 0.25

    # Multiple relevant docs: only first relevant doc counts
    assert compute_reciprocal_rank(["a", "target1", "target2"], {"target1", "target2"}) == 0.5

    # No relevant doc retrieved -> 0.0
    assert compute_reciprocal_rank(["a", "b", "c"], relevant) == 0.0

    # Zero relevant set -> 0.0
    assert compute_reciprocal_rank(["target"], set()) == 0.0


def test_ndcg_hand_computed() -> None:
    # 2 relevant documents: docA and docB
    relevant = {"docA", "docB"}

    # Case 1: Ideal ranking: docA, docB at rank 1 and 2
    # Actual DCG@2 = 1/log2(2) + 1/log2(3) = 1.0 + 0.63092975 = 1.63092975
    # Ideal DCG@2 = 1.63092975
    # NDCG@2 = 1.0
    assert abs(compute_ndcg(["docA", "docB"], relevant, k=2) - 1.0) < 1e-6

    # Case 2: Sub-optimal ranking: docC, docA at rank 1 and 2
    # Actual DCG@2 = 0 + 1/log2(3) = 0.63092975
    # Ideal DCG@2 = 1.63092975
    # NDCG@2 = 0.63092975 / 1.63092975 = 0.38685
    expected_ndcg_2 = (1.0 / math.log2(3)) / (1.0 / math.log2(2) + 1.0 / math.log2(3))
    assert abs(compute_ndcg(["docC", "docA"], relevant, k=2) - expected_ndcg_2) < 1e-6

    # Case 3: Empty relevant or empty retrieved
    assert compute_ndcg([], relevant, k=5) == 0.0
    assert compute_ndcg(["docA"], set(), k=5) == 0.0

    # Case 4: Zero hits
    assert compute_ndcg(["docX", "docY"], relevant, k=5) == 0.0


def test_calibration_brier_and_ece_hand_computed() -> None:
    # 4 predictions:
    # 1. conf=0.8, is_correct=True  -> diff = (0.8 - 1)^2 = 0.04
    # 2. conf=0.8, is_correct=False -> diff = (0.8 - 0)^2 = 0.64
    # 3. conf=0.2, is_correct=False -> diff = (0.2 - 0)^2 = 0.04
    # 4. conf=0.2, is_correct=False -> diff = (0.2 - 0)^2 = 0.04
    # Brier = (0.04 + 0.64 + 0.04 + 0.04) / 4 = 0.76 / 4 = 0.19
    records = [
        {"confidence": 0.8, "is_correct": True},
        {"confidence": 0.8, "is_correct": False},
        {"confidence": 0.2, "is_correct": False},
        {"confidence": 0.2, "is_correct": False},
    ]
    res = compute_calibration_metrics(records, num_buckets=5)
    assert abs(res["brier_score"] - 0.19) < 1e-4

    # Check ECE:
    # Bucket 0.2-0.4 has 2 samples: avg_conf = 0.2, acc = 0.0, gap = 0.2. Weight = 2/4 = 0.5. Contrib = 0.10
    # Bucket 0.8-1.0 has 2 samples: avg_conf = 0.8, acc = 0.5, gap = 0.3. Weight = 2/4 = 0.5. Contrib = 0.15
    # ECE = 0.10 + 0.15 = 0.25
    assert abs(res["ece"] - 0.25) < 1e-4


def test_mathematical_invariants_all_within_unit_interval() -> None:
    """Invariant test: for any arbitrary retrieval inputs, all metrics MUST strictly be in [0.0, 1.0]."""
    test_cases = [
        (["a", "b", "c"], {"a", "b", "c"}),
        (["x", "y", "z"], {"a"}),
        (["a", "a", "a", "a"], {"a"}),
        ([], {"a"}),
        (["a"], set()),
        (["a", "b"], {"c", "d", "e", "f", "g"}),
    ]

    for ret, rel in test_cases:
        for k in [1, 2, 5, 10]:
            r = compute_recall_at_k(ret, rel, k)
            h = compute_hit_at_k(ret, rel, k)
            p = compute_precision_at_k(ret, rel, k)
            nd = compute_ndcg(ret, rel, k)
            assert 0.0 <= r <= 1.0, f"Recall out of bounds: {r}"
            assert 0.0 <= h <= 1.0, f"HitRate out of bounds: {h}"
            assert 0.0 <= p <= 1.0, f"Precision out of bounds: {p}"
            assert 0.0 <= nd <= 1.0, f"NDCG out of bounds: {nd}"

        rr = compute_reciprocal_rank(ret, rel)
        assert 0.0 <= rr <= 1.0, f"Reciprocal Rank out of bounds: {rr}"
