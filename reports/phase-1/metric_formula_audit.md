# METRIC FORMULA AUDIT & MATHEMATICAL PROOFS

This document provides independent mathematical formulations, boundary proofs, and hand-computed test fixtures for all Information Retrieval (IR) and QA metrics implemented in `app/evaluation.py`.

---

## 1. Metric Formulations & Bounded Invariants

### A. Recall@K
$$\text{Recall@K}(q) = \frac{|\text{Retrieved@K}(q) \cap \text{Relevant}(q)|}{|\text{Relevant}(q)|}$$
- **Boundary Proof**: Since $\text{Retrieved@K}(q) \cap \text{Relevant}(q) \subseteq \text{Relevant}(q)$, the numerator $|\text{Retrieved@K}(q) \cap \text{Relevant}(q)| \le |\text{Relevant}(q)|$. Therefore, $0 \le \text{Recall@K}(q) \le 1.0$ unconditionally.
- **Edge Cases**:
  - If $|\text{Relevant}(q)| = 0$: Returns `0.0` (nothing relevant to recall).
  - If $K \le 0$: Returns `0.0`.
  - If $|\text{Retrieved@K}(q)| = 0$ with $|\text{Relevant}(q)| > 0$: Returns `0.0`.
- **Zero-Clipping Invariant**: No `min(metric, 1.0)` is used; the bound is mathematically guaranteed.

### B. HitRate@K (Success@K)
$$\text{Hit@K}(q) = \begin{cases} 1.0 & \text{if } |\text{Retrieved@K}(q) \cap \text{Relevant}(q)| > 0 \\ 0.0 & \text{otherwise} \end{cases}$$
- **Boundary Proof**: Binary indicator in $\{0.0, 1.0\}$.

### C. Precision@K
$$\text{Precision@K}(q) = \frac{|\text{Unique Retrieved@K}(q) \cap \text{Relevant}(q)|}{K}$$
- **Boundary Proof**: Since $|\text{Unique Retrieved@K}(q)| \le K$ and $|\text{Unique Retrieved@K}(q) \cap \text{Relevant}(q)| \le |\text{Unique Retrieved@K}(q)|$, the numerator is at most $K$. Dividing by $K$ yields a value strictly in $[0.0, 1.0]$.
- **Deduplication Invariant**: If duplicate document IDs appear in the top $K$, only unique IDs are intersected, preventing duplicates from claiming multiple relevance points.

### D. Mean Reciprocal Rank (MRR)
$$\text{RR}(q) = \begin{cases} \frac{1}{\text{rank}_1(q)} & \text{if a relevant document is retrieved} \\ 0.0 & \text{otherwise} \end{cases}$$
$$\text{MRR} = \frac{1}{|Q|} \sum_{q \in Q} \text{RR}(q)$$
- **Boundary Proof**: Since $\text{rank}_1(q) \ge 1$, $\frac{1}{\text{rank}_1(q)} \le 1.0$. The mean of non-negative values $\le 1.0$ is strictly in $[0.0, 1.0]$.

### E. Normalized Discounted Cumulative Gain (NDCG@K)
$$\text{DCG@K}(q) = \sum_{i=1}^K \frac{\text{rel}_i}{\log_2(i + 1)}$$
$$\text{IDCG@K}(q) = \sum_{i=1}^{\min(|\text{Relevant}(q)|, K)} \frac{1}{\log_2(i + 1)}$$
$$\text{NDCG@K}(q) = \begin{cases} \frac{\text{DCG@K}(q)}{\text{IDCG@K}(q)} & \text{if } \text{IDCG@K}(q) > 0 \\ 0.0 & \text{otherwise} \end{cases}$$
- **Deduplication Invariant**: Once a document ID is scored as relevant at rank $i$, subsequent occurrences of that same document ID in the top $K$ receive $\text{rel} = 0.0$. Thus, $\text{DCG@K}(q) \le \text{IDCG@K}(q)$ is mathematically guaranteed, and $\text{NDCG@K}(q) \le 1.0$ unconditionally without clipping.

### F. Brier Score
$$\text{Brier Score} = \frac{1}{N} \sum_{i=1}^N (c_i - y_i)^2$$
- Where $c_i \in [0.0, 1.0]$ is the predicted confidence and $y_i \in \{0.0, 1.0\}$ is binary correctness.
- **Boundary Proof**: Since $0 \le c_i \le 1$ and $y_i \in \{0, 1\}$, $(c_i - y_i) \in [-1.0, 1.0]$, so $(c_i - y_i)^2 \in [0.0, 1.0]$. The mean is strictly within $[0.0, 1.0]$.

### G. Expected Calibration Error (ECE)
$$\text{ECE} = \sum_{b=1}^B \frac{|B_b|}{N} |\text{acc}(B_b) - \text{conf}(B_b)|$$
- Where $\text{acc}(B_b)$ is the empirical accuracy of bucket $b$ and $\text{conf}(B_b)$ is the average predicted confidence in bucket $b$.
- **Boundary Proof**: Weighted average of absolute differences in $[0.0, 1.0]$, strictly bounded in $[0.0, 1.0]$.

---

## 2. Hand-Computed Verification Test Suite

All formulas are independently verified by 8 hand-computed unit tests in [`tests/test_metrics_math.py`](file:///C:/Users/win%2010/Desktop/local-seo-spider/tests/test_metrics_math.py):

```python
# 2 relevant out of 4 docs in corpus: {"docA", "docB"}
# Retrieved: ["docA", "docC", "docD", "docB"]
assert compute_recall_at_k(retrieved, relevant, k=1) == 0.5   # 1/2
assert compute_recall_at_k(retrieved, relevant, k=2) == 0.5   # 1/2
assert compute_recall_at_k(retrieved, relevant, k=4) == 1.0   # 2/2

# Precision@K hand-computed:
# Top 2 retrieved: ["docA", "docC"] -> 1 relevant in top 2 = 1/2 = 0.5
assert compute_precision_at_k(retrieved, relevant, k=2) == 0.5
# Top 4 retrieved: ["docA", "docC", "docD", "docB"] -> 2 relevant in top 4 = 2/4 = 0.5
assert compute_precision_at_k(retrieved, relevant, k=4) == 0.5

# Deduplicated NDCG hand-computed:
# Retrieved with duplicates: ["docA", "docA", "docB"]
# DCG = 1/log2(2) + 0 + 1/log2(4) = 1.0 + 0.5 = 1.5
# IDCG = 1/log2(2) + 1/log2(3) = 1.0 + 0.6309 = 1.6309
# NDCG = 1.5 / 1.6309 = 0.9197 <= 1.0
assert compute_ndcg(["docA", "docA", "docB"], {"docA", "docB"}, k=3) == pytest.approx(1.5 / (1.0 + 1 / math.log2(3)))
```
All 8 tests pass independently without mock objects.
