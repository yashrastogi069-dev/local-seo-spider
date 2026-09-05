"""Independent evaluation metrics for Information Retrieval and RAG generation.

Implements mathematically sound, standard IR metrics strictly bounded in [0.0, 1.0]:
- Recall@K
- HitRate@K (Success@K)
- Precision@K
- Mean Reciprocal Rank (MRR)
- Normalized Discounted Cumulative Gain (NDCG@K)
- Citation Precision & Recall
- Brier Score & Expected Calibration Error (ECE)
"""

from __future__ import annotations

import math
from typing import Any, Sequence, Set


def compute_recall_at_k(
    retrieved: Sequence[str],
    relevant: Set[str] | Sequence[str],
    k: int,
) -> float:
    """Compute standard IR Recall@K = |Retrieved@K ∩ Relevant| / |Relevant|.

    Always strictly bounded in [0.0, 1.0].
    Returns 0.0 if relevant set is empty or k <= 0.
    """
    rel_set = set(relevant)
    if not rel_set or k <= 0:
        return 0.0
    k_retrieved = set(retrieved[:k])
    hits = len(k_retrieved & rel_set)
    return hits / len(rel_set)


def compute_hit_at_k(
    retrieved: Sequence[str],
    relevant: Set[str] | Sequence[str],
    k: int,
) -> float:
    """Compute binary HitRate@K (Success@K) = 1.0 if any retrieved@K is relevant else 0.0."""
    rel_set = set(relevant)
    if not rel_set or k <= 0:
        return 0.0
    k_retrieved = set(retrieved[:k])
    return 1.0 if bool(k_retrieved & rel_set) else 0.0


def compute_precision_at_k(
    retrieved: Sequence[str],
    relevant: Set[str] | Sequence[str],
    k: int,
) -> float:
    """Compute IR Precision@K = |Retrieved@K ∩ Relevant| / K.

    Always strictly bounded in [0.0, 1.0].
    """
    rel_set = set(relevant)
    if not rel_set or k <= 0:
        return 0.0
    # Use unique retrieved in top k to avoid artificial inflation from duplicates
    k_retrieved = set(retrieved[:k])
    hits = len(k_retrieved & rel_set)
    return hits / float(k)


def compute_reciprocal_rank(
    retrieved: Sequence[str],
    relevant: Set[str] | Sequence[str],
) -> float:
    """Compute Reciprocal Rank = 1.0 / rank of first relevant item (1-indexed).

    Returns 0.0 if no relevant document was retrieved.
    Always strictly bounded in [0.0, 1.0].
    """
    rel_set = set(relevant)
    if not rel_set:
        return 0.0
    for rank_idx, doc in enumerate(retrieved, start=1):
        if doc in rel_set:
            return 1.0 / rank_idx
    return 0.0


def compute_dcg(relevances: Sequence[float | int], k: int = 5) -> float:
    """Compute Discounted Cumulative Gain over top k entries."""
    dcg = 0.0
    for i, rel in enumerate(relevances[:k], start=1):
        if rel > 0:
            dcg += rel / math.log2(i + 1)
    return dcg


def compute_ndcg(
    retrieved: Sequence[str],
    relevant: Set[str] | Sequence[str],
    k: int = 5,
) -> float:
    """Compute Normalized Discounted Cumulative Gain at rank K with binary relevance.

    Deduplicates retrieved results so identical documents cannot receive multiple relevance credit.
    Always strictly bounded in [0.0, 1.0].
    Returns 0.0 if relevant set is empty or k <= 0.
    """
    rel_set = set(relevant)
    if not rel_set or k <= 0:
        return 0.0

    seen: set[str] = set()
    actual_rel: list[float] = []
    for doc in retrieved[:k]:
        if doc in rel_set and doc not in seen:
            actual_rel.append(1.0)
            seen.add(doc)
        else:
            actual_rel.append(0.0)

    actual_dcg = compute_dcg(actual_rel, k)

    ideal_rel = [1.0] * min(len(rel_set), k)
    ideal_dcg = compute_dcg(ideal_rel, k)

    if ideal_dcg <= 0.0:
        return 0.0
    return actual_dcg / ideal_dcg


def compute_citation_metrics(
    cited_sources: Sequence[str],
    ground_truth_relevant: Set[str],
) -> dict[str, float]:
    """Compute Citation Precision and Citation Recall.

    Citation Precision = |Cited ∩ Relevant| / |Cited|
    Citation Recall    = |Cited ∩ Relevant| / |Relevant|
    """
    cited_set = set(cited_sources)
    if not cited_set:
        return {"citation_precision": 0.0, "citation_recall": 0.0}
    if not ground_truth_relevant:
        return {"citation_precision": 0.0, "citation_recall": 1.0}

    hits = len(cited_set & ground_truth_relevant)
    precision = hits / len(cited_set)
    recall = hits / len(ground_truth_relevant)
    return {
        "citation_precision": round(precision, 4),
        "citation_recall": round(recall, 4),
    }


def compute_calibration_metrics(
    records: Sequence[dict[str, Any]],
    num_buckets: int = 5,
) -> dict[str, Any]:
    """Compute Brier Score and Expected Calibration Error (ECE) across prediction records.

    Each record must have:
    - 'confidence': float in [0.0, 1.0]
    - 'is_correct': bool

    Invariants:
    - Brier score in [0.0, 1.0]
    - ECE in [0.0, 1.0]
    """
    if not records:
        return {"brier_score": 0.0, "ece": 0.0, "buckets": []}

    total = len(records)
    brier_sum = 0.0

    step = 1.0 / num_buckets
    buckets = []
    for b_idx in range(num_buckets):
        lower = round(b_idx * step, 4)
        upper = round((b_idx + 1) * step, 4)
        buckets.append({
            "range": f"{lower:.1f}-{upper:.1f}",
            "lower": lower,
            "upper": upper,
            "count": 0,
            "conf_sum": 0.0,
            "correct_count": 0,
        })

    for rec in records:
        conf = max(0.0, min(1.0, float(rec.get("confidence", 0.0))))
        is_corr = 1.0 if rec.get("is_correct", False) else 0.0
        brier_sum += (conf - is_corr) ** 2

        placed = False
        for b in buckets:
            if b["lower"] <= conf < b["upper"] or (b["upper"] >= 1.0 and conf >= 1.0):
                b["count"] += 1
                b["conf_sum"] += conf
                b["correct_count"] += int(is_corr)
                placed = True
                break
        if not placed and buckets:
            buckets[-1]["count"] += 1
            buckets[-1]["conf_sum"] += conf
            buckets[-1]["correct_count"] += int(is_corr)

    brier_score = round(brier_sum / total, 4)
    ece_sum = 0.0
    bucket_results = []

    for b in buckets:
        cnt = b["count"]
        if cnt > 0:
            avg_conf = b["conf_sum"] / cnt
            acc = b["correct_count"] / cnt
            ece_sum += (cnt / total) * abs(avg_conf - acc)
            bucket_results.append({
                "bucket": b["range"],
                "count": cnt,
                "avg_confidence": round(avg_conf, 4),
                "accuracy": round(acc, 4),
                "calibration_gap": round(abs(avg_conf - acc), 4),
            })
        else:
            bucket_results.append({
                "bucket": b["range"],
                "count": 0,
                "avg_confidence": 0.0,
                "accuracy": 0.0,
                "calibration_gap": 0.0,
            })

    return {
        "brier_score": brier_score,
        "ece": round(ece_sum, 4),
        "buckets": bucket_results,
    }
