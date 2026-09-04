# RAG and crawler upgrade notes

The current implementation uses SQLite FTS5 plus a deterministic feature-hash vector provider by default. Hash vectors are reproducible lexical features, not semantic embeddings. The existing optional Sentence Transformers adapter is the correct local semantic direction, but the application silently falls back to hash retrieval when the semantic dependency or model is unavailable; this makes the UI appear operational while failing the user's expectation of semantic understanding.

Northstar operations agent (`yashrastogi069-dev/northstar-operations-agent`) provides useful patterns: explicit retrieval candidates and ranked evidence, separate keyword/semantic/rerank scores, query-term normalization, phrase bonuses, decline thresholds, retrieval-only query expansion, strict evidence-only prompts, citation requirements, and evaluation cases for retrieval passes. Its implementation is TypeScript/Drizzle/hosted-LLM oriented, so only the quality contracts should be adapted to this local Python/SQLite project.

Crawl4AI documentation emphasizes clean structured Markdown, preservation of headings and links, and optional query-aware content filtering. Scrapling emphasizes adaptive selectors that remember structural properties and relocate elements after site changes. ScrapeGraphAI emphasizes graph-driven structured extraction with an LLM layer. For this project, these ideas translate into structure-aware chunks, provenance-preserving link references, reusable extraction profiles, and an optional post-retrieval LLM—not stealth, proxy rotation, access-control bypass, or unaffiliated web-scale collection.

The upgrade should make semantic-provider availability explicit, isolate vectors by provider/model/version, use semantic retrieval as a required mode when configured, keep lexical retrieval as a transparent fallback only when explicitly selected, rerank by semantic similarity plus lexical/phrase coverage and source diversity, and validate every generated claim against cited retrieved evidence. SQLite FTS5 remains useful for exact terms and structured retrieval, not as a substitute for semantic embeddings.

References:

1. https://docs.crawl4ai.com/core/markdown-generation/ — Crawl4AI Markdown generation and content filtering.
2. https://scrapling.readthedocs.io/en/latest/parsing/adaptive.html — Scrapling adaptive scraping.
3. https://docs.scrapegraphai.com/introduction — ScrapeGraphAI overview and graph-driven extraction.
4. https://www.sqlite.org/fts5.html — SQLite FTS5 search and relevance behavior.
