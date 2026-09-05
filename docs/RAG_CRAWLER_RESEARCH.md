# RAG and crawler upgrade notes

The current implementation uses SQLite FTS5 plus a deterministic feature-hash vector provider by default. Hash vectors are reproducible lexical features, not semantic embeddings. The existing optional Sentence Transformers adapter is the correct local semantic direction, but the application silently falls back to hash retrieval when the semantic dependency or model is unavailable; this makes the UI appear operational while failing the user's expectation of semantic understanding.

Northstar operations agent (`yashrastogi069-dev/northstar-operations-agent`) provides useful patterns: explicit retrieval candidates and ranked evidence, separate keyword/semantic/rerank scores, query-term normalization, phrase bonuses, decline thresholds, retrieval-only query expansion, strict evidence-only prompts, citation requirements, and evaluation cases for retrieval passes. Its implementation is TypeScript/Drizzle/hosted-LLM oriented, so only the quality contracts should be adapted to this local Python/SQLite project.

Crawl4AI documentation emphasizes clean structured Markdown, preservation of headings and links, and optional query-aware content filtering. Scrapling emphasizes adaptive selectors that remember structural properties and relocate elements after site changes. ScrapeGraphAI emphasizes graph-driven structured extraction with an LLM layer. For this project, these ideas translate into structure-aware chunks, provenance-preserving link references, reusable extraction profiles, and an optional post-retrieval LLM—not stealth, proxy rotation, access-control bypass, or unaffiliated web-scale collection.

The upgrade should make semantic-provider availability explicit, isolate vectors by provider/model/version, use semantic retrieval as a required mode when configured, keep lexical retrieval as a transparent fallback only when explicitly selected, rerank by semantic similarity plus lexical/phrase coverage and source diversity, and validate every generated claim against cited retrieved evidence. SQLite FTS5 remains useful for exact terms and structured retrieval, not as a substitute for semantic embeddings.

## Real Semantic Search vs. Geometric Similarity Search

Naive RAG pipelines conflate high vector cosine similarity with factual answer correctness. For instance, a query such as "How much does the annual maintenance fee cost?" might achieve a 0.85 cosine similarity against an "About Our Maintenance Department" page simply because of topical keyword overlap, despite the passage containing zero fee numbers or cost information.

To ensure genuine semantic understanding rather than superficial geometric proximity:
1. **Query Intent & Semantic Target Classification**: Every question is parsed to determine its semantic target category (`quantity_cost`, `temporal_duration`, `condition_eligibility`, `procedure_method`, `entity_identity`, `location`, `definition_offering`, or `general`), along with core required entities.
2. **Semantic Support & Target Verification**: Retrieved candidate passages are evaluated for whether they actually contain information satisfying the question's target type (e.g. numeric prices/currencies for `quantity_cost`, durations/dates/hours for `temporal_duration`, condition markers for eligibility) and grounded mentions of key entities.
3. **Abstention on Non-Answer-Bearing Evidence**: If retrieved passages are merely topically adjacent but fail semantic answer support, the system explicitly abstains rather than inventing answers or awarding false high confidence.
4. **Calibrated Confidence**: Confidence is never derived purely from raw vector cosine distances. It is calibrated from passage answer support, entity grounding, absence of contradictions, and claim verification rates.

## Mandatory Claim-Level Grounding

Generated text from LLMs can suffer from subtle hallucinations—fabricating specific numbers, inventing dates, hallucinating entities, or introducing uncited assertions. To prevent this:
1. **Atomic Claim Decomposition**: Any generated answer is decomposed into individual factual sentences/claims, with their cited passages identified (e.g., `[1]`, `[2]`).
2. **Strict Entity & Number Consistency**: Every number, date, and named entity appearing in a factual claim is strictly checked against the cited passage. Hallucinated numbers or entities trigger immediate claim rejection.
3. **Mandatory Citations**: Every empirical factual assertion must cite at least one retrieved passage. Non-empirical meta-statements (e.g., "Based on the crawl...") are recognized as non-empirical, while empirical claims without valid citations fail verification.
4. **Zero-Tolerance Fallback**: If even a single factual claim in an LLM-generated answer fails verification (hallucinated number, ungrounded entity, missing citation, or contradictory polarity), the entire generated response is rejected and replaced with deterministic, verified evidence quotes.

References:

1. https://docs.crawl4ai.com/core/markdown-generation/ — Crawl4AI Markdown generation and content filtering.
2. https://scrapling.readthedocs.io/en/latest/parsing/adaptive.html — Scrapling adaptive scraping.
3. https://docs.scrapegraphai.com/introduction — ScrapeGraphAI overview and graph-driven extraction.
4. https://www.sqlite.org/fts5.html — SQLite FTS5 search and relevance behavior.

