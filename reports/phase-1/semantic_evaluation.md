# SEMANTIC EVALUATION & EMBEDDING SUBSYSTEM AUDIT

**Phase**: 1 — Evaluation Integrity, Benchmark Trustworthiness & Certification  
**Benchmark**: `rag-benchmark-v1` (Version 1.1.0)  
**Evaluated Providers**: `HashEmbeddingProvider` (64-dim) vs `SentenceTransformerEmbeddingProvider` (384-dim)  
**Status**: **TRUTHFULLY BOUNDED & DOCUMENTED (PASS)**  
**Audit Date**: 2026-09-05  

---

## 1. Executive Summary & Integrity Mandate

In accordance with the **Absolute Truth Hierarchy** of the Antigravity Engineering Operating System:
> Never claim a capability exists or is verified when running under an offline stub or simulation. A lower trustworthy score is infinitely better than an inflated unearned score.

This document certifies the exact operational capabilities, limits, and fallback behaviors of the semantic embedding subsystem.

---

## 2. Embedding Architecture & Provider Hierarchy

The system defines a modular `EmbeddingProvider` protocol in `app/embeddings.py`:

```python
class EmbeddingProvider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def dimension(self) -> int: ...
    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
```

Two concrete implementations are provided:

### 1. `SentenceTransformerEmbeddingProvider`
- **Model**: `all-MiniLM-L6-v2` (384 dimensions, float32).
- **Capability**: Full dense semantic retrieval, cosine similarity, synonym mapping, cross-lingual capability.
- **Dependency**: `sentence-transformers`, `torch`, HuggingFace model cache (~90MB).
- **CI / Offline Status**: Optional extra (`pip install sentence-transformers`). In the standard offline test environment, tests requiring this provider are skipped with an explicit diagnostic (`pytest.skip("sentence-transformers not installed")`).

### 2. `HashEmbeddingProvider`
- **Algorithm**: Deterministic 64-dimensional pseudo-random token projection.
- **Dimensions**: 64 (normalized unit vector).
- **Dependencies**: Pure Python standard library (`hashlib`, `math`, `array`). Zero external dependencies.
- **Capability**: Schema-compliant placeholder ensuring database tables (`vector_embeddings`), serialization, and RRF fusion code paths execute without error.
- **Semantic Ability**: **0.000**. It does not capture synonyms, antonyms, or semantic proximity.

---

## 3. Empirical Behavior Under Hash Fallback

During the Phase 1 benchmark evaluation, all runs were performed using `HashEmbeddingProvider` to guarantee deterministic, offline-reproducible results without network dependencies.

As proven in `retrieval_ablation.md`:
- **Vector-Only Recall@1**: `0.0000`
- **Vector-Only Recall@5**: `0.0000`
- **Vector-Only MRR**: `0.0000`

### Why Vector Scoring is Skipped for Hash Embeddings:
In `app/database.py` (lines 610–611):
```python
if active_embedder.name == "hash":
    continue
```
This check ensures that pseudo-random hash collisions are **never mistakenly interpreted as semantic relevance**. The system intentionally declines to produce false semantic matches.

---

## 4. Semantic Search vs Lexical Retrieval Verification Matrix

| Evaluation Dimension | Under `HashEmbeddingProvider` (Offline CI) | Under `SentenceTransformerEmbeddingProvider` (Production / Extra) |
|:---|:---|:---|
| **Execution Environment** | Fully offline, zero dependencies | Requires Python package & weight download |
| **Benchmark Status** | **VERIFIED & CERTIFIED** | **UNVERIFIED IN OFFLINE CI** (Documented Pending) |
| **Exact Keyword Matches** | Handled by BM25 (Recall@5 = 98.57%) | Handled by BM25 + Vector Fusion |
| **Synonym Retrieval** (e.g. `cost` $\to$ `price`) | Handled by query synonym expansion in `app/qa.py` | Handled by dense embedding cosine similarity |
| **Vector Similarity Threshold** | N/A (bypassed) | Strict cutoff at $\text{sim} \ge 0.35$ |
| **Vector Storage Schema** | SQLite `vector_embeddings` table (`BLOB`) | SQLite `vector_embeddings` table (`BLOB`) |

---

## 5. Certification Finding

1. The Local SEO Spider evaluation harness **does not game or simulate** neural semantic performance.
2. In the offline test suite, 2 tests (`test_embeddings.py:25` and `test_rag_end_to_end.py:17`) are transparently skipped with proper decorators.
3. Hybrid search gracefully falls back to high-precision BM25 + heading provenance when operating without neural models, maintaining **98.57% Recall@5** on the 140 retrieval-scored queries.
