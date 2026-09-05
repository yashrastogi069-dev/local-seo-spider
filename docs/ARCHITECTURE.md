# ARCHITECTURE BLUEPRINT: LOCAL SEO SPIDER & SEMANTIC RAG

## 1. System Overview
Local SEO Spider combines a high-concurrency web crawler with an evidence-grounded semantic retrieval-augmented generation (RAG) system. The system treats all crawled web content as untrusted evidence and enforces strict citation verification and abstention.

```
                  +----------------------------------------------+
                  |               Web / Target URL               |
                  +----------------------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |      CrawlEngine Subsystem    |
                         |  (Serial / Thread / Async /   |
                         |         Multiprocess)         |
                         +-------------------------------+
                                         |
                       +-----------------+-----------------+
                       |                                   |
                       v                                   v
             +--------------------+              +--------------------+
             | Static HTTP Fetch  |              | Playwright Browser |
             | (urllib / httpx)   |              |  (Dynamic JS DOM)  |
             +--------------------+              +--------------------+
                       |                                   |
                       +-----------------+-----------------+
                                         |
                                         v
                         +-------------------------------+
                         |      Universal Extractor      |
                         |  (HTML, JSON, PDF, Markdown)  |
                         +-------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |  Knowledge & Chunking Engine  |
                         | (Provenance, Structure, Hashes)|
                         +-------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |      Database Layer (SQLite)   |
                         |  - Pages, Crawls, Links       |
                         |  - FTS5 Inverted Index (BM25) |
                         |  - Vector Embeddings Storage  |
                         +-------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |    Hybrid Retrieval Engine    |
                         |  BM25 Lexical + Dense Vectors |
                         |   Reciprocal Rank Fusion (RRF)|
                         +-------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |      Multi-Factor Reranker    |
                         | (Term Cov, Source Type, Phr.) |
                         +-------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |    Grounded Answer Planner    |
                         |  - Dynamic Slot Extraction    |
                         |  - Claim Verification         |
                         |  - Conflict Detection         |
                         |  - Calibrated Confidence      |
                         |  - Hard Abstention Gate       |
                         +-------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |    FastAPI / User Interface   |
                         | (Grounded Answers & Citations)|
                         +-------------------------------+
```

---

## 2. Core Subsystems

### A. Crawler Engine (`app/crawler.py`)
- **Concurrency Modes**:
  - `serial`: Single-process, serial fetcher.
  - `thread`: Multi-threaded worker pool (`ThreadPoolExecutor`) for static HTTP.
  - `async`: Non-blocking coroutine-based fetcher (`asyncio` / `httpx`).
  - `multiprocess`: Multi-process parallel crawl (`ProcessPoolExecutor`).
- **Resilience**: Exponential backoff on HTTP 429 and 5xx errors; configurable crawl depth, delay, and URL limits.
- **SSRF Defense**: Outbound connection pre-validation rejecting private/internal networks and cloud metadata in all IP representations.

### B. URL Normalization & Deduplication (`app/urltools.py`)
- **Canonicalization**: Strips tracking parameters (`utm_*`, `fbclid`, `gclid`), normalizes schemes/ports, deduplicates redundant path slashes (`//` -> `/`), strips URL fragments, sorts query parameters.
- **Deduplication**: Resolves `<link rel="canonical">` tags, relative canonical references, and hashes raw content for near-duplicate identification.

### C. Universal Document Extractor (`app/documents.py`)
- **Formats**: HTML (BeautifulSoup), JSON, Markdown, and PDF.
- **JSON Semantics**: Preserves field-value bindings, scalar types, array records, and nested hierarchical relationships rather than flattening into plain unstructured text.

### D. Knowledge Representation & Storage (`app/knowledge.py`, `app/database.py`)
- **KnowledgeChunk Model**: Stores `chunk_id`, `page_id`, `crawl_id`, `url`, `canonical_url`, `title`, `heading_path`, `section`, `content`, `content_type`, `source_type`, and `content_hash`.
- **Hybrid Index**:
  - Full-Text Search: SQLite `FTS5` virtual table providing BM25 scoring.
  - Vector Storage: SQLite table storing normalized dense float vectors with cosine similarity calculation.

### E. Replaceable Provider Interfaces
To ensure architectural stability, provider interfaces are decoupled:
1. **`EmbeddingProvider`**: Protocol with `embed(text: str) -> list[float]` and `embed_batch(texts: list[str]) -> list[list[float]]`.
   - `HashEmbeddingProvider`: Deterministic, offline 64-dimensional pseudo-random projections for resource-constrained test environments.
   - `SentenceTransformerEmbeddingProvider`: Neural contextual representation (`sentence-transformers/all-MiniLM-L6-v2`).
2. **`LLMProvider` / `LocalAnswerer`**:
   - `OllamaAnswerer`: Communicates with a local LLM server via JSON-instruct prompt templates.
   - `LocalAnswerer`: Deterministic, rule-grounded synthesis engine providing zero-hallucination fallback.

### F. Retrieval & Reranking Subsystem (`app/database.py`, `app/agentic.py`)
- **RRF (Reciprocal Rank Fusion)**: Merges ranks from lexical FTS5 ($R_{\text{lex}}$) and vector cosine similarity ($R_{\text{vec}}$):
  $$RRF(d) = \frac{1}{60 + R_{\text{lex}}(d)} + \frac{1}{60 + R_{\text{vec}}(d)}$$
- **Reranker Scoring Factors**:
  - Lexical term coverage ($w = 0.25$)
  - Vector semantic similarity ($w = 0.25$)
  - Source type boost (`official_api`: $+0.25$)
  - Exact phrase match bonus ($+0.20$)
  - Structured data bonus ($+0.15$)
  - Duplicate source penalty (subsequent chunks from same URL penalized by 50%).

### G. Evidence Grounding, Verification & Abstention (`app/qa.py`)
- **Query Semantics Analysis**: Classifies query types (exact phrase, factoid, numerical, comparison, multi-hop, unanswerable).
- **Atomic Claim Extraction**: Splits prospective answers into atomic factual claims.
- **Verification Engine**: Validates claim against cited passages for:
  - Exact number matching
  - Entity match
  - Temporal scope & units
  - Semantic entailment
- **Confidence Calibration**: Formula combining retrieval strength, claim entailment, completeness rate, and conflict penalties.
- **Strict Abstention Gate**: When evidence is missing, contradictory, or below confidence thresholds, the system unconditionally abstains with `confidence = 0.0`.
