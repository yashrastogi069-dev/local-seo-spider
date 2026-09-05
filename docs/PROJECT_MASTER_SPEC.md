# PROJECT MASTER SPECIFICATION: CRAWLER + SEMANTIC RAG SYSTEM

## 1. Vision & Core Objectives
Transform Local SEO Spider into an enterprise-grade, evidence-grounded semantic web crawler and RAG system characterized by:
1. **Mathematical Invariant Rigor**: All normalized evaluation metrics strictly within $[0.0, 1.0]$ without artificial clamping or self-deception.
2. **Authoritative Evidence Grounding**: The LLM is never the source of truth. Every empirical claim must be verified against crawled source evidence.
3. **Strict Citation Verification**: Verification of citation targets, numerical values, entities, and qualifiers with explicit PASS / PARTIAL / FAIL reporting.
4. **Hard Abstention**: Conservative zero-confidence abstention on unanswerable, near-miss, or contradictory queries.
5. **Security Hardening**: Untrusted web data isolation, rigorous SSRF protection across all IP representations, secret redaction, and prompt injection defense.
6. **Architectural Modularity**: Clean interfaces for `LLMProvider`, `EmbeddingProvider`, `Retriever`, `Reranker`, `Extractor`, and `CrawlerEngine`.
7. **Persistent Provenance**: Complete end-to-end traceability from claim to chunk, document, and exact source URL.

---

## 2. Source of Truth Priority
When conflicting information arises, precedence is strictly ordered as follows:
1. **Actual executable code** in `app/`
2. **Passing reproducible tests** in `tests/`
3. **Test fixtures & independently defined ground truth** in `tests/fixtures/`
4. **Architecture documentation** (`ARCHITECTURE.md`, `DECISIONS.md`)
5. **Project specification** (`PROJECT_MASTER_SPEC.md`)
6. **Previous agent claims or notes** (never trusted without executable verification)

---

## 3. The 9 Controlled Phases

### PHASE 0: Baseline & Forensic Audit
- Complete inspection of the existing codebase, identifying false claims, brittle patterns, and untested behaviors.
- Baseline test suite execution and gap identification.
- Establishment of persistent project memory files.

### PHASE 1: Evaluation Integrity
- Implementation of standard, unclipped IR metrics: Recall@K, Precision@K, MRR, NDCG@K (deduplicated), Brier score, ECE.
- Hand-computed test fixtures covering all edge cases (zero retrieved, zero relevant, ties, duplicates).
- 5-way benchmark partitioning (Development, Calibration, Blind Test, Adversarial, Regression).
- Complete elimination of metric self-deception (`min(metric, 1.0)`).

### PHASE 2: Crawler Core
- Robust HTTP fetching with connection pooling, retries, and exponential backoff on 429/5xx.
- URL canonicalization: trailing slashes, duplicate slashes, parameter sorting, tracking parameter stripping (`utm_*`, `fbclid`).
- Deduplication: URL-level, canonical tag resolution, and content hash deduplication.
- Concurrency modes: Serial Playwright, Threaded static, Async coroutine, Multiprocess static.
- Outbound SSRF protection: strict IP validation blocking loopback, private, link-local, and cloud metadata in all encodings (octal, hex, dword, IPv6-mapped).

### PHASE 3: Universal Extraction
- Document extractors for HTML, rendered JavaScript DOM, JSON, and PDF/Markdown.
- Preservation of deep JSON semantics: scalars, nested objects, array structures, and field-value associations.
- Secret & token redaction across URLs, headers, and extracted text.

### PHASE 4: Knowledge / Indexing / Search
- Knowledge chunking preserving complete provenance: `chunk_id`, `document_id`, `url`, `title`, `heading_path`, `section`, `content_hash`.
- Chunk deduplication preventing duplicate chunks from consuming retrieval capacity.
- Hybrid indexing: SQLite FTS5 (BM25 lexical) and vector store (dense embeddings).
- Modular embedding interface: `HashEmbeddingProvider` (offline fallback) and `SentenceTransformerEmbeddingProvider` (neural).
- Reciprocal Rank Fusion (RRF) combining lexical and vector results.

### PHASE 5: RAG Intelligence
- Query-type classification: exact phrase, identifier, factoid, numerical/structured, comparison, multi-hop, citation audit.
- Multi-factor reranking: term coverage, semantic similarity, phrase matching, heading alignment, source-type weighting (`official_api` bonus), and duplicate penalization.
- Generalized answer planning: dynamic comparisons, structured slot extraction, collection lookups, and multi-hop decomposition.
- Claim-level evidence grounding & citation verification (PASS, PARTIAL, FAIL).
- Conflict detection between contradictory sources.
- Calibrated confidence scoring reflecting slot completeness, evidence support, and conflict penalties.

### PHASE 6: Web Intelligence
- Crawler coverage metrics: exact set union of crawled URLs and discovered link targets.
- Playwright browser automation: dynamic client-side JS rendering, timeout resilience, crash recovery.
- Content inventory generation and issue analysis (broken links, missing tags, canonical conflicts).

### PHASE 7: UI / UX & API Layer
- Clean FastAPI endpoints for crawls, knowledge search, question answering, and exports (CSV/JSON).
- Server-rendered HTML templates with full accessibility (ARIA roles, semantic markup).
- Interactive question-answering with citation highlights and confidence badges.

### PHASE 8: Final Certification
- Independent blind-test execution against frozen golden corpus.
- Verification of all 11 historic regression cases.
- Final production certification statement with empirical confidence bounds.

---

## 4. Invariant Rules
1. **Never game tests**: Do not alter test expectations to match implementation flaws.
2. **Never clip metrics**: Metric exceedance signals a bug in the formula or denominator; fix the root cause.
3. **No hardcoded answers**: All answers must be dynamically extracted from retrieved evidence.
4. **Permanent regressions**: Every discovered bug must have a permanent regression test.
5. **Untrusted web input**: All scraped content is treated as untrusted data; prompt injections must never override system logic.
