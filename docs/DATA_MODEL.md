# DATA MODEL & SCHEMA SPECIFICATION

This document defines the database schemas, entity relationships, dataclasses, and data provenance models for Local SEO Spider & Semantic RAG.

---

## 1. Relational Schema Architecture (SQLite)

The persistence layer uses SQLite with write-ahead logging (WAL), foreign key enforcement, and the FTS5 full-text search engine.

```
 +--------------------+       1:N       +----------------------+
 |       crawls       |---------------->|        pages         |
 +--------------------+                 +----------------------+
           |                                       |
           | 1:N                                   | 1:N
           v                                       v
 +--------------------+                 +----------------------+
 |       links        |                 |   knowledge_chunks   |
 +--------------------+                 +----------------------+
                                                   |
                                                   | 1:1
                                                   v
                                        +----------------------+
                                        |  knowledge_vectors   |
                                        +----------------------+
                                                   |
                                                   | Virtual FTS
                                                   v
                                        +----------------------+
                                        | knowledge_chunks_fts |
                                        +----------------------+
```

---

## 2. Table Specifications

### A. `crawls`
Tracks execution state, configuration, and audit metrics for crawl sessions.
- `id` (TEXT, PRIMARY KEY): Unique UUID string (`crawl-<uuid>`).
- `created_at` (TEXT): ISO 8601 UTC timestamp.
- `status` (TEXT): State lifecycle: `queued`, `running`, `completed`, `failed`, `paused`, `cancelled`.
- `start_url` (TEXT): Initial seed URL.
- `settings_json` (TEXT): Serialized crawl settings (depth, max URLs, delay, concurrency mode, render flags).
- `ownership_ack` (INTEGER): Binary authorization flag (1 = confirmed authorized site owner/manager).

### B. `pages`
Stores raw and extracted representations of every discovered web resource.
- `id` (INTEGER, PRIMARY KEY AUTOINCREMENT).
- `crawl_id` (TEXT, FOREIGN KEY -> `crawls(id)`).
- `url` (TEXT): Canonicalized fetch URL.
- `final_url` (TEXT): Target URL after all redirect hops.
- `status_code` (INTEGER): HTTP status code (or NULL on network error).
- `content_type` (TEXT): MIME type (e.g. `text/html`, `application/json`, `application/pdf`).
- `title` (TEXT): Extracted `<title>` or document title.
- `description` (TEXT): Meta description text.
- `headings_json` (TEXT): JSON dictionary mapping heading tags (`h1`, `h2`, `h3`) to lists of heading text.
- `canonical` (TEXT): Raw `<link rel="canonical">` value.
- `meta_robots` (TEXT): Value of `<meta name="robots">`.
- `x_robots` (TEXT): Value of `X-Robots-Tag` HTTP header.
- `source_html` (TEXT): Raw unrendered HTML/payload.
- `rendered_html` (TEXT): Post-JavaScript DOM snapshot (when Playwright render enabled).
- `rendered_text` (TEXT): Cleaned, normalized visible text content.
- `extracted_text` (TEXT): Semantic text extracted via document extractors.
- `images_json` (TEXT): JSON array of image objects (`src`, `alt`, `has_alt`).
- `structured_data_json` (TEXT): Extracted JSON-LD and microdata schemas.
- `redirects_json` (TEXT): Full redirect hop chain with status codes and locations.
- `fetch_error` (TEXT): Low-level HTTP/network error message if fetch failed.
- `render_error` (TEXT): Playwright execution error message if rendering failed.
- `robots_allowed` (INTEGER): Whether robots.txt permitted access (1 = true).
- `body_truncated` (INTEGER): Whether response exceeded byte limit (1 = true).
- `discovered_at` (TEXT): Timestamp of discovery.
- `content_hash` (TEXT): SHA-256 hash of normalized text for near-duplicate detection.
- `is_duplicate` (INTEGER): 1 if canonical or content duplicate of another page.
- `duplicate_of` (TEXT): URL of primary canonical document.
- `source_type` (TEXT): `html_page`, `official_api`, `pdf_document`, `markdown`.
- `depth` (INTEGER): Crawl tree depth (seed = 0).
- `parent_url` (TEXT): Referrer URL that linked to this resource.

### C. `links`
Stores all discovered internal and external hyperlinks.
- `crawl_id` (TEXT, FOREIGN KEY -> `crawls(id)`).
- `source_url` (TEXT): Page URL containing the link.
- `target_url` (TEXT): Normalized destination URL.
- `href` (TEXT): Raw `href` attribute string.
- `anchor_text` (TEXT): Visible clickable text.
- `rel` (TEXT): Link `rel` attribute (`nofollow`, `canonical`, etc.).
- `is_internal` (INTEGER): 1 if same-origin as seed URL.
- `is_nofollow` (INTEGER): 1 if `nofollow` specified.

### D. `knowledge_chunks`
Stores segmented, searchable knowledge passages with complete provenance.
- `id` (INTEGER, PRIMARY KEY AUTOINCREMENT).
- `chunk_id` (TEXT, UNIQUE): Unique identifier (`doc-<page_id>-chunk-<index>`).
- `page_id` (INTEGER, FOREIGN KEY -> `pages(id)`).
- `crawl_id` (TEXT, FOREIGN KEY -> `crawls(id)`).
- `url` (TEXT): Page URL.
- `canonical_url` (TEXT): Canonical URL.
- `title` (TEXT): Page title.
- `heading_path` (TEXT): Hierarchical breadcrumb (`Docs > API > Authentication`).
- `section` (TEXT): Semantic section category (`intro`, `body`, `json_fields`, `table`).
- `content` (TEXT): Cleaned textual content of the chunk.
- `content_type` (TEXT): Document content type.
- `source_type` (TEXT): Source categorization (`official_api`, `html_page`, etc.).
- `content_hash` (TEXT): SHA-256 hash of chunk content for deduplication.
- `chunk_index` (INTEGER): 0-indexed position within parent document.

### E. `knowledge_chunks_fts` (FTS5 Virtual Table)
Inverted index enabling fast BM25 ranking across `content`, `heading_path`, and `title`:
```sql
CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(
    chunk_id UNINDEXED,
    crawl_id UNINDEXED,
    title,
    heading_path,
    content,
    tokenize = 'porter unicode61'
);
```

### F. `knowledge_vectors`
Stores dense float vector embeddings for semantic similarity search.
- `chunk_id` (TEXT, PRIMARY KEY).
- `crawl_id` (TEXT).
- `vector_json` (TEXT): JSON serialized array of normalized float values.
- `dimension` (INTEGER): Vector dimensionality (e.g. 64 for Hash, 384 for MiniLM).

---

## 3. Data Integrity & Invariants
1. **Rebuildability**: The knowledge chunk index, FTS5 table, and vector store can be completely regenerated from the `pages` table at any time via `extract_pages_knowledge`.
2. **Provenance Traceability**: Every claim in a RAG answer maps to citation numbers, which map to `knowledge_chunks`, which map directly to `pages` and source URLs.
3. **No Orphan Records**: Cascading deletes or explicit cleanup transactions ensure no orphaned chunks or vector rows remain upon crawl deletion or re-crawl.
