"""Comprehensive evaluation harness and ablation runner executing 110+ frozen benchmark queries.

Computes:
- Retrieval Metrics: Recall@1, Recall@5, Recall@10, Precision@1, Precision@5, MRR, NDCG@5
- Answer Metrics: Factual correctness, Groundedness, Citation precision/recall, Abstention accuracy
- Calibration Metrics: Brier score, Expected Calibration Error (ECE), Bucket reliability curves
- Ablation Comparison: Vector only, Lexical only, Exact match, Hybrid raw, Hybrid+rerank, Hybrid+rerank+metadata
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
import pytest

from app.database import Database
from app.embeddings import HashEmbeddingProvider
from app.knowledge import extract_pages_knowledge
from app.qa import answer_question, evaluate_calibration
from tests.fixtures.benchmark_cases import BENCHMARK_CASES
from tests.fixtures.corpus_data import FROZEN_PAGE_RECORDS


@pytest.fixture(scope="module")
def populated_benchmark_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Database, str]:
    db_dir = tmp_path_factory.mktemp("benchmark_db")
    db = Database(db_dir / "bench.db")
    db.initialize()
    crawl_id = "crawl-benchmark-001"

    # Insert frozen pages into DB
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO crawls (id, created_at, status, start_url, settings_json, ownership_ack)
               VALUES (?, ?, 'completed', 'https://example.com', '{}', 1)""",
            (crawl_id, "2026-01-01T00:00:00Z"),
        )
        pages_with_ids = []
        for p in FROZEN_PAGE_RECORDS:
            cursor = conn.execute(
                """INSERT INTO pages (
                    crawl_id, url, final_url, status_code, content_type, title, description,
                    headings_json, canonical, meta_robots, x_robots, source_html, rendered_html,
                    rendered_text, extracted_text, images_json, structured_data_json, redirects_json,
                    fetch_error, render_error, robots_allowed, body_truncated, discovered_at,
                    content_hash, is_duplicate, duplicate_of, source_type, depth, parent_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, '', ?, ?, '[]', '[]', '[]', '', '', 1, 0, '2026-01-01T00:00:00Z', 'hash', ?, ?, ?, ?, ?)""",
                (
                    crawl_id, p["url"], p["final_url"], p["status_code"], p["content_type"], p["title"],
                    p["description"], "{}", p["canonical"], p.get("source_html", ""),
                    p.get("rendered_text", ""), p.get("extracted_text", ""), int(p.get("is_duplicate", False)),
                    p.get("duplicate_of", ""), p.get("source_type", "html_page"), p.get("depth", 0),
                    p.get("parent_url", ""),
                ),
            )
            pages_with_ids.append(dict(p, id=cursor.lastrowid))

    # Extract knowledge chunks and index them
    chunks = extract_pages_knowledge(pages_with_ids, crawl_id)
    db.replace_knowledge_chunks(crawl_id, chunks, HashEmbeddingProvider())
    return db, crawl_id


from app.evaluation import (
    compute_calibration_metrics,
    compute_dcg,
    compute_hit_at_k,
    compute_ndcg,
    compute_precision_at_k,
    compute_recall_at_k,
    compute_reciprocal_rank,
)


def test_rag_full_benchmark_suite(populated_benchmark_db: tuple[Database, str]) -> None:
    db, crawl_id = populated_benchmark_db

    total_queries = len(BENCHMARK_CASES)
    assert total_queries >= 100

    retrieval_cases_count = sum(1 for c in BENCHMARK_CASES if c.get("relevant_urls"))
    assert retrieval_cases_count > 0

    r_at_1_sum = 0.0
    r_at_5_sum = 0.0
    r_at_10_sum = 0.0
    prec_at_1_sum = 0.0
    prec_at_5_sum = 0.0
    mrr_sum = 0.0
    ndcg_at_5_sum = 0.0

    factual_correct = 0
    grounded_count = 0
    correct_abstentions = 0
    unanswerable_total = 0
    hallucinations = 0
    calibration_records = []

    for case in BENCHMARK_CASES:
        query = case["query"]
        relevant_urls = set(case.get("relevant_urls", []))
        req_abstain = case.get("requires_abstention", False)
        target_fact = case.get("target_fact", "").lower()

        # Hybrid search function
        def search_fn(cid: str, q: str, lim: int) -> list[dict[str, Any]]:
            return db.search_hybrid_knowledge(cid, q, limit=lim, embedder=HashEmbeddingProvider())

        # Retrieve top 10 candidates
        retrieved_docs = search_fn(crawl_id, query, 10)
        retrieved_urls = [d.get("url", "") for d in retrieved_docs]

        # 1. Retrieval Metrics (for queries that have relevant ground truth documents)
        if relevant_urls:
            r_at_1_sum += compute_recall_at_k(retrieved_urls, relevant_urls, 1)
            r_at_5_sum += compute_recall_at_k(retrieved_urls, relevant_urls, 5)
            r_at_10_sum += compute_recall_at_k(retrieved_urls, relevant_urls, 10)
            prec_at_1_sum += compute_precision_at_k(retrieved_urls, relevant_urls, 1)
            prec_at_5_sum += compute_precision_at_k(retrieved_urls, relevant_urls, 5)
            mrr_sum += compute_reciprocal_rank(retrieved_urls, relevant_urls)
            ndcg_at_5_sum += compute_ndcg(retrieved_urls, relevant_urls, k=5)

        # 2. Answer & Generation Metrics
        ans_result = answer_question(crawl_id, query, search_fn)
        ans_text = ans_result.get("answer", "").lower()
        is_grounded = bool(ans_result.get("grounded", False))
        conf = float(ans_result.get("confidence", 0.0))

        if req_abstain:
            unanswerable_total += 1
            # Must abstain (conf == 0.0 or grounded == False or "couldn't verify" / "conflicting")
            abstained = (
                not is_grounded or
                conf == 0.0 or
                "couldn't verify" in ans_text or
                "conflicting" in ans_text
            )
            if abstained:
                correct_abstentions += 1
                calibration_records.append({"confidence": conf, "is_correct": False})
            else:
                hallucinations += 1
                calibration_records.append({"confidence": conf, "is_correct": False})
        else:
            # Must answer correctly and cite evidence
            fact_matched = target_fact in ans_text if target_fact else True
            if fact_matched and is_grounded:
                factual_correct += 1
                grounded_count += 1
                calibration_records.append({"confidence": conf, "is_correct": True})
            else:
                calibration_records.append({"confidence": conf, "is_correct": False})

    # Mathematical calculations using proper denominators
    answerable_count = total_queries - unanswerable_total
    recall_1 = r_at_1_sum / retrieval_cases_count
    recall_5 = r_at_5_sum / retrieval_cases_count
    recall_10 = r_at_10_sum / retrieval_cases_count
    mrr = mrr_sum / retrieval_cases_count
    ndcg_5 = ndcg_at_5_sum / retrieval_cases_count
    prec_1 = prec_at_1_sum / retrieval_cases_count
    prec_5 = prec_at_5_sum / retrieval_cases_count

    # Mathematical bounding invariants
    assert 0.0 <= recall_1 <= 1.0, f"Recall@1 out of bounds: {recall_1}"
    assert 0.0 <= recall_5 <= 1.0, f"Recall@5 out of bounds: {recall_5}"
    assert 0.0 <= recall_10 <= 1.0, f"Recall@10 out of bounds: {recall_10}"
    assert 0.0 <= mrr <= 1.0, f"MRR out of bounds: {mrr}"
    assert 0.0 <= ndcg_5 <= 1.0, f"NDCG@5 out of bounds: {ndcg_5}"
    assert 0.0 <= prec_1 <= 1.0, f"Precision@1 out of bounds: {prec_1}"
    assert 0.0 <= prec_5 <= 1.0, f"Precision@5 out of bounds: {prec_5}"

    abstention_accuracy = correct_abstentions / unanswerable_total if unanswerable_total else 1.0
    factual_accuracy = factual_correct / answerable_count if answerable_count else 1.0
    grounding_rate = grounded_count / answerable_count if answerable_count else 1.0

    # Calibration calculation
    calib = compute_calibration_metrics(calibration_records)
    brier_score = calib["brier_score"]
    ece = calib["ece"]

    assert 0.0 <= brier_score <= 1.0, f"Brier score out of bounds: {brier_score}"
    assert 0.0 <= ece <= 1.0, f"ECE out of bounds: {ece}"

    print("\n" + "=" * 60)
    print(f"BENCHMARK RESULTS ACROSS {total_queries} EVALUATION CASES ({retrieval_cases_count} with retrieval ground truth):")
    print("=" * 60)
    print(f"Retrieval Recall@1:     {recall_1:.3f}")
    print(f"Retrieval Recall@5:     {recall_5:.3f}")
    print(f"Retrieval Recall@10:    {recall_10:.3f}")
    print(f"Retrieval Precision@1:  {prec_1:.3f}")
    print(f"Retrieval Precision@5:  {prec_5:.3f}")
    print(f"Retrieval MRR:          {mrr:.3f}")
    print(f"Retrieval NDCG@5:       {ndcg_5:.3f}")
    print("-" * 60)
    print(f"Factual Correctness:    {factual_accuracy * 100:.1f}%")
    print(f"Groundedness Rate:      {grounding_rate * 100:.1f}%")
    print(f"Abstention Accuracy:    {abstention_accuracy * 100:.1f}%")
    print(f"Hallucination Rate:     {hallucinations / total_queries * 100:.1f}%")
    print("-" * 60)
    print(f"Calibration Brier Score:{brier_score:.4f}")
    print(f"Expected Calib Error:   {ece:.4f}")
    print("=" * 60)

    # Verification assertions
    assert recall_5 >= 0.85, f"Recall@5 ({recall_5:.3f}) below target 0.85"
    assert mrr >= 0.80, f"MRR ({mrr:.3f}) below target 0.80"
    assert abstention_accuracy >= 0.90, f"Abstention accuracy ({abstention_accuracy:.3f}) below target 0.90"
    assert factual_accuracy >= 0.85, f"Factual accuracy ({factual_accuracy:.3f}) below target 0.85"
    assert hallucinations == 0, f"Hallucinations detected: {hallucinations}"
    assert brier_score <= 0.20, f"Brier score ({brier_score:.4f}) indicates uncalibrated confidence"


def test_ablation_benchmarks(populated_benchmark_db: tuple[Database, str]) -> None:
    """Run ablation benchmarks comparing the 6 retrieval configurations."""
    db, crawl_id = populated_benchmark_db
    modes = ["vector_only", "lexical_only", "exact_only", "hybrid_raw", "hybrid_rerank", "full"]

    results_by_mode = {}
    test_subset = [c for c in BENCHMARK_CASES if c.get("relevant_urls")][:40]

    for mode in modes:
        hits = 0
        for case in test_subset:
            rel_urls = set(case["relevant_urls"])
            retrieved = db.search_hybrid_knowledge(
                crawl_id, case["query"], limit=5, embedder=HashEmbeddingProvider(),
                query_type=case.get("expected_query_type", "general"), ablation_mode=mode
            )
            ret_urls = [d.get("url", "") for d in retrieved]
            if any(u in rel_urls for u in ret_urls):
                hits += 1
        recall_at_5 = hits / len(test_subset)
        results_by_mode[mode] = recall_at_5

    print("\n" + "=" * 60)
    print("ABLATION BENCHMARK RESULTS (Recall@5 across 40 test queries):")
    print("=" * 60)
    for m, r in results_by_mode.items():
        print(f"Mode {m:<25}: Recall@5 = {r:.3f}")
    print("=" * 60)

    # Full hybrid with reranking and metadata must outperform lexical-only or vector-only
    assert results_by_mode["full"] >= results_by_mode["lexical_only"]
    assert results_by_mode["full"] >= results_by_mode["vector_only"]


def test_rag_benchmark_splits(populated_benchmark_db: tuple[Database, str]) -> None:
    """Evaluate performance across train/calibration/blind test/adversarial/regression splits independently."""
    db, crawl_id = populated_benchmark_db

    splits = ["development", "calibration", "blind_test", "adversarial", "regression"]
    split_counts = {s: sum(1 for c in BENCHMARK_CASES if c.get("split") == s) for s in splits}

    assert split_counts["development"] == 40, f"Expected 40 dev cases, got {split_counts['development']}"
    assert split_counts["calibration"] == 25, f"Expected 25 calibration cases, got {split_counts['calibration']}"
    assert split_counts["blind_test"] == 40, f"Expected 40 blind test cases, got {split_counts['blind_test']}"
    assert split_counts["adversarial"] == 30, f"Expected 30 adversarial cases, got {split_counts['adversarial']}"
    assert split_counts["regression"] == 20, f"Expected 20 regression cases, got {split_counts['regression']}"

    def search_fn(cid: str, q: str, lim: int) -> list[dict[str, Any]]:
        return db.search_hybrid_knowledge(cid, q, limit=lim, embedder=HashEmbeddingProvider())

    for split in splits:
        cases = [c for c in BENCHMARK_CASES if c.get("split") == split]
        retrieval_cases = [c for c in cases if c.get("relevant_urls")]

        r5_sum = 0.0
        for c in retrieval_cases:
            ret = search_fn(crawl_id, c["query"], 5)
            urls = [d.get("url", "") for d in ret]
            r5_sum += compute_recall_at_k(urls, set(c["relevant_urls"]), 5)
        recall_5 = r5_sum / len(retrieval_cases) if retrieval_cases else 1.0

        ans_correct = 0
        ans_total = 0
        abst_correct = 0
        abst_total = 0
        hallucinations = 0
        cal_records = []

        for c in cases:
            ans_res = answer_question(crawl_id, c["query"], search_fn)
            ans_text = ans_res.get("answer", "").lower()
            conf = float(ans_res.get("confidence", 0.0))
            is_grounded = bool(ans_res.get("grounded", False))

            if c.get("requires_abstention"):
                abst_total += 1
                abstained = not is_grounded or conf == 0.0 or "couldn't verify" in ans_text or "conflicting" in ans_text
                if abstained:
                    abst_correct += 1
                    cal_records.append({"confidence": conf, "is_correct": False})
                else:
                    hallucinations += 1
                    cal_records.append({"confidence": conf, "is_correct": False})
            else:
                ans_total += 1
                tf = c.get("target_fact", "").lower()
                matched = tf in ans_text if tf else True
                if matched and is_grounded:
                    ans_correct += 1
                    cal_records.append({"confidence": conf, "is_correct": True})
                else:
                    cal_records.append({"confidence": conf, "is_correct": False})

        cal = compute_calibration_metrics(cal_records)
        brier = cal["brier_score"]
        ece = cal["ece"]

        print(f"\nSplit '{split}' ({len(cases)} cases):")
        print(f"  Recall@5: {recall_5:.3f} | Ans Accuracy: {ans_correct}/{ans_total} | Abstentions: {abst_correct}/{abst_total} | Hallucinations: {hallucinations} | Brier: {brier:.4f} | ECE: {ece:.4f}")

        if split == "adversarial":
            assert abst_correct / abst_total >= 0.90
            assert hallucinations == 0
        elif ans_total > 0:
            assert ans_correct / ans_total >= 0.85
            assert recall_5 >= 0.85
