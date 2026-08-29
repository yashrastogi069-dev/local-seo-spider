# Knowledge Crawler Architecture Findings

## SQLite FTS5

The official SQLite FTS5 documentation describes FTS5 as a virtual table module that provides full-text search for database applications. It supports MATCH queries, phrases, prefix queries, NEAR queries, Boolean combinations, column filters, snippets, highlighting, and relevance ranking via bm25(). This supports a local-first retrieval index over crawl sections while retaining the canonical page records in SQLite.

Source: https://www.sqlite.org/fts5.html

## n8n webhook automation

The official n8n Webhook documentation states that a Webhook node can trigger workflows through HTTP requests, has separate test and production URLs, and can return workflow-generated results as an API endpoint. This supports a future adapter where the local crawler emits explicitly approved events or exposes a narrow, authenticated local API for workflow orchestration. It does not justify adding unrestricted outbound automation or production-site mutation.

Source: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook

## Design decision

Implement the first knowledge layer with SQLite FTS5 and citation-first retrieval. Keep answer generation deterministic or explicitly optional; never claim an answer when retrieved evidence is insufficient. Treat n8n as a future integration boundary using narrow webhook/API contracts, explicit user approval, idempotency, and no default write actions against target websites.

## References

1. [SQLite FTS5 Extension](https://www.sqlite.org/fts5.html)
2. [n8n Webhook node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook)

## RAG grounding

The NeurIPS 2020 RAG paper frames retrieval-augmented generation as combining a parametric language model with explicit non-parametric memory, improving access to precise knowledge and provenance. For this project, the non-parametric memory is the locally indexed crawl corpus; the application should pass retrieved passages into an answerer and expose provenance instead of treating model output as unsupported truth.

Source: https://proceedings.neurips.cc/paper_files/paper/2020/hash/6b493230-Abstract.html

## References

3. [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://proceedings.neurips.cc/paper_files/paper/2020/hash/6b493230-Abstract.html)

## Expanded ingestion and vector storage research

Playwright’s official Python documentation provides a Download API for obtaining a download URL, filename, and payload stream, which supports treating authorized downloadable documents as bounded crawl artifacts rather than silently ignoring them: https://playwright.dev/python/docs/downloads

The official pypdf documentation supports extracting text from text-layer PDFs, while image-only or heavily graphical PDFs require a separate OCR path and should be reported as partial extraction rather than treated as complete: https://pypdf.readthedocs.io/en/latest/user/extract-text.html

The sqlite-vec project documents a SQLite extension for storing and querying float, int8, and binary vectors across Linux, macOS, and Windows. It is a promising optional vector-search adapter, but the implementation should retain a pure-Python/SQLite fallback because extension availability and approximate-nearest-neighbor behavior must be tested on the user’s machine: https://github.com/asg017/sqlite-vec

## References

4. [Playwright Python Downloads](https://playwright.dev/python/docs/downloads)
5. [pypdf Extract Text from a PDF](https://pypdf.readthedocs.io/en/latest/user/extract-text.html)
6. [sqlite-vec](https://github.com/asg017/sqlite-vec)

## Hybrid RAG research

Sentence Transformers documents semantic search as encoding queries and corpus passages into a shared embedding space, which supports a dense retrieval stage alongside lexical search: https://sbert.net/examples/sentence_transformer/applications/semantic-search/README.html

The design will use hybrid retrieval rather than replacing FTS5: lexical search is valuable for exact names, identifiers, prices, and policy terms, while embeddings help with paraphrases. A pure SQLite fallback remains the baseline, with an optional sqlite-vec adapter and model-backed embeddings behind explicit local configuration. Any generated answer must retain retrieved evidence, source citations, confidence signals, and abstention when retrieval is weak.

## References

7. [Sentence Transformers Semantic Search](https://sbert.net/examples/sentence_transformer/applications/semantic-search/README.html)
