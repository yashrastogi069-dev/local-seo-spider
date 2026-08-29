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
