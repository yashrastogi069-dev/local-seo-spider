# Local SEO Spider

**Local SEO Spider** is a local-first, evidence-led technical SEO crawler for websites you own or are explicitly authorized to assess. It uses **Python 3.12**, **FastAPI**, **SQLite**, **Playwright**, and an **HTMX** interface. It sends no telemetry, has no accounts or billing, uses no hosted control plane, and makes no changes to a target website.

> Before any crawl can start, the operator must confirm that they own the exact target host or have explicit permission to assess it. The crawler then stays within the normalized start host, respects `robots.txt`, applies its configured delay and URL cap, and records external links only as evidence.

## First local run

From the repository root, run exactly one command:

```bash
./run-local.sh
```

The command requires Python **3.12**, creates `.venv`, copies the safe checked-in configuration template to local `.env` when needed, installs the project and its test dependencies, installs Playwright Chromium, and starts the application at [http://127.0.0.1:3000](http://127.0.0.1:3000). Review the `.env` values before the first crawl if you need a lower cap, a slower delay, or rendering disabled.

The repository includes `local-seo-spider.env.example` as the safe default configuration template; the first run copies it to local `.env`. `.env` is ignored by Git. No API secrets are required for this local application. The managed workspace prevents a literal `.env.example` file from being generated programmatically; the supplied template is functionally equivalent and intentionally contains no credentials.

On **Windows Command Prompt**, use the native launcher instead of `chmod` or Bash:

```bat
cd path\\to\\local-seo-spider
run-local.cmd
```

You can also run `run-local.bat` from CMD or by double-clicking it; it delegates to the same launcher.

This checks that `python` is Python 3.12, creates `.venv`, copies the local configuration template, installs the project, installs Chromium, and starts the app. Git Bash or WSL users can continue using `./run-local.sh`. The repository also includes a Windows CI smoke test that runs this CMD launcher on `windows-latest` and checks `/health`; the sandbox itself cannot execute Windows CMD directly. When the generated visual assets are not present, the app creates an empty local `assets/` directory and remains functional; set `SPIDER_ASSET_DIR` if you want to point the app at a local asset folder.

## What a crawl collects

Each crawl stores raw HTTP and rendered-browser evidence separately where applicable. For eligible HTML responses, the crawler captures the following fields locally.

| Area | Captured evidence |
| --- | --- |
| HTTP and redirects | Requested URL, final URL, status code, content type, full redirect hops, fetch error, and response `X-Robots-Tag`. |
| Source and rendering | Capped source HTML, rendered HTML, rendered visible text, render error, and document-size cap state. |
| Documents and text resources | Bounded text-like resources and text-layer PDFs are extracted locally into searchable evidence; unsupported binaries and image-only PDFs retain an explicit extraction note instead of being treated as readable. |
| On-page SEO | Title, meta description, headings, canonical, meta robots, structured-data blocks, and image `alt` attributes. |
| Link graph | Source URL, normalized target, anchor text, link `rel`, same-host status, and nofollow status. |
| Reproducibility | Crawl creation and completion time, acknowledged authorization, crawl mode, URL cap, delay, and nofollow behavior. |

The crawl engine uses a direct HTTP request for headers and source HTML, then a bounded Playwright page visit for rendered DOM inspection. It does **not** submit forms, sign in, work around access controls, open pop-ups, collect credentials, or mutate target-site content. Playwright failure is a per-page, recoverable inspection warning; raw HTML findings remain available.

### Executor modes

The default `serial` executor is the reference mode. It preserves the full Playwright rendered-DOM path, keeps request ordering easiest to inspect, and is the right choice for JavaScript-heavy or smaller audits. `thread` uses a bounded thread pool for I/O-heavy static acquisition and is useful when a permitted site serves many independent server-rendered pages. `async` uses bounded HTTP coroutines for high-latency static requests and lower per-task overhead. `process` uses bounded worker processes for CPU-heavy static parsing on multi-core machines, but its network fetches and serialized page records add overhead. Thread, async, and process modes intentionally skip Playwright rendering; they are not substitutes for the serial mode when client-side content is the target. All modes retain the same host boundary, robots check, request delay, retry limits, response-size cap, and URL cap. Set `SPIDER_CRAWL_EXECUTOR_MODE` globally or choose a mode per crawl in the local form. Start with `serial`, then use `thread` or `async` for static workloads; use `process` only after measuring a CPU-bound workload.

Target-field extraction is configured with a local JSON profile such as [`extraction-profile.example.json`](extraction-profile.example.json). CSS, XPath, regex, attribute, and JSON-LD selectors can choose `static`, `dynamic`, or `either` sources. Each result stores its values, source, selector, and explicit `found`, `missing`, or `error` status so a failed target does not look like a successful empty value.

## Technical and content audit rules

The first release creates clear, evidence-backed findings for broken internal links, 4xx and 5xx responses, redirect chains, missing and duplicate titles, missing and duplicate descriptions, missing H1s, duplicate rendered content, image alternate-text gaps, invalid JSON-LD, orphan candidates, and canonical or robots indexability conflicts. Every row contains its severity, exact affected URL, collected evidence, and concrete remediation note.

The **Content Inventory** retains marketing-useful signals—heading coverage, description coverage, rendered word count, image alternative-text coverage, JSON-LD types, and internal-inlink context—so the locally exported page list can support editorial planning. These signals are evidence, not rank, traffic, click-through, or rich-result guarantees. The project does not collect web-scale keyword or backlink datasets, crawl unaffiliated sites without authorization, or publish changes to production websites.

Completed crawls of the same normalized start URL can also be compared locally. The comparison identifies added and absent URLs, observable changes to status, metadata, canonical, robots, and rendered-text hash, plus issue fingerprints that are new or no longer present. It does not infer cause, rankings, traffic, or business impact from those changes.

## Local website knowledge and grounded questions

Completed crawls now build a local SQLite FTS5 knowledge index from readable HTML blocks, text resources, and text-layer PDFs. Each indexed passage retains its crawl, page, URL, title, and heading path, so the question surface can show where evidence came from. Open a completed crawl and use **Ask the local crawl** to search the indexed website content. Retrieval now combines lexical FTS5 ranking with deterministic local vector embeddings and a bounded agentic query planner; the default hash embedding is offline and reproducible, while Sentence Transformers is an optional local semantic provider. The answer mode is deliberately citation-first: it returns matching passages, confidence metadata, and abstains when the local crawl does not contain enough evidence. It does not invent facts, infer private content, or treat similarity as proof. The **Rebuild local index** action can recover an index for an older completed crawl after parser improvements or a partial failure, and completed crawls can compare added and removed evidence chunks.

A read-only JSON endpoint is also available for local workflow experiments:

```text
GET /api/crawls/<crawl-id>/ask?q=your+question
```

The endpoint is scoped to one completed crawl and returns the question, grounded status, answer text, and citations. It is intentionally read-only; it cannot start crawls, submit forms to target websites, change production content, or access another crawl's evidence.

## Future automation boundary

The knowledge layer now includes a small local workflow engine for n8n-style composition without importing n8n or exposing a public control plane. A workflow is a validated acyclic graph of bounded nodes. Available nodes are `core.input`, `crawl.status`, `knowledge.search`, `knowledge.ask`, and `local_db.query`. The database node accepts only one bounded read-only `SELECT` or `WITH` statement; no workflow node can start a crawl, submit a target-site form, mutate production content, or execute shell commands.

Workflows can be saved and run through `POST /api/workflows` and `POST /api/workflows/<workflow-id>/run`. The manual run endpoint is the first trigger. An active workflow can also declare `{"type":"crawl.completed"}` with an optional normalized `start_url`; after a successful crawl and knowledge index, the local worker invokes matching workflows with the crawl ID as event input. Run outcomes are persisted and available through `GET /api/workflows/<workflow-id>/runs?limit=20`, capped for local recovery inspection. This provides a stable local boundary that n8n or another tool could call later, but the default application remains local-only and does not connect to n8n or send crawl data anywhere.

A minimal workflow definition is:

```json
{"id":"site-question","name":"Answer site question","active":true,"trigger":{"type":"crawl.completed"},"nodes":[{"id":"ask","type":"knowledge.ask","config":{"crawl_id":"{{input.crawl_id}}","question":"What services are described?"}}],"edges":[]}
```

The knowledge layer is also designed so an external n8n instance can later call the existing read-only question endpoint or workflow API. n8n supports webhook triggers and API-style responses, but any future external integration must add explicit authentication, request validation, idempotency, local-network exposure controls, and operator approval. A local-only deployment should use loopback addresses and never forward crawl content to an untrusted workflow host.

An optional local answer generator is now supported through a loopback-only Ollama-compatible endpoint. Set `SPIDER_ANSWER_PROVIDER=ollama` and configure the local model settings in `.env` only after installing and running the model locally. If the model is unavailable, the application falls back to deterministic evidence output. Hosted models remain intentionally unsupported by default because website passages would leave the machine; retrieval and citations remain the source of truth either way.

## Architecture

```text
Browser + HTMX form
       │ explicit ownership/permission acknowledgement
       ▼
FastAPI request validation ──► SQLite job ledger (local `data/`)
                                      │ queued / running / retryable / paused
                                      ▼
                              one local worker claims one approved job
                                      │
                                      ▼
                            bounded same-host crawl and persisted evidence
                                      │
                 ┌────────────────────┴──────────────────────────┐
                 ▼                                               ▼
    robots.txt + request delay, HTTP source + headers,    pages, links, issues,
    Playwright rendered inspection                        CSV exports, HTML report
                 │
                 ▼
        SQLite FTS5 knowledge chunks ──► cited local questions / read-only API
```

`app/crawler.py` owns collection and is deliberately limited to a single host and local crawl settings. `app/parser.py` converts source or rendered HTML into structured records. `app/documents.py` extracts bounded text-like resources and text-layer PDFs with explicit partial-support errors. `app/knowledge.py` extracts citation-preserving readable chunks. `app/embeddings.py` provides deterministic offline vectors and an optional local Sentence Transformers adapter. `app/agentic.py` provides bounded query planning. `app/qa.py` answers from retrieved local evidence and abstains when support is insufficient; `app/answering.py` provides the optional loopback-only local model adapter. `app/analyzer.py` is a deterministic transformation from persisted evidence to issue rows. `app/database.py` is the SQLite persistence boundary and durable job ledger; it supports safe startup recovery, bounded retry timing, circuit-breaker pauses, explicit operator resume, FTS5 retrieval, vector persistence, and hybrid ranking. `app/exports.py` writes reproducible local exports. `app/templates/` and `app/static/` provide the Field Manual HTMX interface.

### Local worker and recovery behavior

One local worker processes one acknowledged crawl job at a time. The job is written to SQLite before the worker receives it, so a restart does not silently discard a queued request. If the process stops while a job is marked `running`, the next startup changes it to `retryable` instead of pretending it completed. Unexpected worker-level failures are retried only after a bounded delay. After the local maximum attempts, a circuit breaker places the job in `paused`; the operator must review the recorded reason and select **Resume locally**. Normal page-specific fetch and rendering errors remain captured as crawl evidence and do not restart the whole job. See [`docs/LOCAL_JOB_LEDGER.md`](docs/LOCAL_JOB_LEDGER.md) for the exact state model.

## Safe use and permissions

Only begin a crawl when you own the exact host or hold explicit permission from its owner. A host-level rate limit, `robots.txt` check, redirect maximum, source-document size cap, and crawl URL cap reduce load and make the crawl’s boundaries explicit. A standard crawl discovers only followable same-host URLs; external links are stored but not fetched. Exact URL List mode lets an authorized operator inspect an explicit same-host list without further discovery.

The application defaults to a 500 URL cap and a 0.35 second delay. The cap can be lowered or raised only up to `SPIDER_MAX_URL_CAP`; the default template sets that hard maximum to 10,000. Use incremental runs—starting with a low cap—when checking scope. Crawling access-controlled areas, bypassing consent, harvesting third-party data at web scale, or automatically changing production sites is intentionally unsupported.

## Local data, exports, and backup

All collected data is stored in `data/local_seo_spider.sqlite3` by default. Generated export files are written to `data/exports/`. `.env`, `data/`, exports, virtual environments, and test caches are ignored by Git, so sensitive local crawl records do not enter commits accidentally.

To back up a completed audit, copy both the SQLite database and any selected exports to a protected location. Stop the app first if you need a strict point-in-time copy:

```bash
cp -a data "$(date +%Y-%m-%d)-local-seo-spider-backup"
```

To restore, replace the local `data/` directory while the application is stopped. The HTML report is self-contained and can be archived or opened locally without the application. Export filenames are constructed from a sanitized crawl identifier to prevent path traversal or unsafe filenames.

## Development and tests

Run the focused test suite after creating the local environment:

```bash
.venv/bin/python -m pytest
```

The tests cover deterministic technical-issue evidence, URL validation and safe filename behavior, robots and redirect handling, recoverable rendering fallback, bounded PDF/text extraction, CSV/HTML export safety, contrast regression, FastAPI security headers, permission blocking, HTMX and non-HTMX form paths, crawl comparison, durable SQLite job claim/retry/pause/resume/startup-recovery behavior, knowledge chunk provenance, crawl-scoped FTS5/vector hybrid retrieval, bounded agentic planning, citation-first answers, local-model fallback, abstention, and the completed-crawl question endpoint.

## References

The implementation follows documented crawler and search signals: the reference crawler describes local site-audit checks for broken links, redirects, metadata, duplicate content, robots directives, JavaScript rendering, and crawl comparison.[1] Google documents `robots.txt` as a crawler-access mechanism rather than indexing control, and distinguishes it from `noindex`.[2] It also documents canonical signals,[3] link qualification values such as `nofollow`,[4] quality meta-description principles,[5] and structured-data expectations.[6] Playwright provides the browser page abstraction used for bounded rendered DOM inspection.[7] SQLite FTS5 supplies the local full-text retrieval index used for knowledge chunks, supporting MATCH queries, phrase/prefix/Boolean search, snippets, highlighting, and relevance ranking.[8] The original RAG formulation combines a generator with explicit retrieved non-parametric memory, which informs this project’s citation-first and abstention behavior.[9] n8n’s Webhook node supports a future narrow HTTP workflow boundary with separate test/production endpoints and configurable responses.[10]

[1]: https://www.screamingfrog.co.uk/seo-spider/ "Screaming Frog SEO Spider Website Crawler"
[2]: https://developers.google.com/search/docs/crawling-indexing/robots/intro "Google Search Central: Robots.txt Introduction"
[3]: https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls "Google Search Central: Canonicalization"
[4]: https://developers.google.com/search/docs/crawling-indexing/qualify-outbound-links "Google Search Central: Qualify Outbound Links"
[5]: https://developers.google.com/search/docs/appearance/snippet "Google Search Central: Snippets and Meta Descriptions"
[6]: https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data "Google Search Central: Structured Data Introduction"
[7]: https://playwright.dev/python/docs/pages "Playwright Python: Pages"
[8]: https://www.sqlite.org/fts5.html "SQLite FTS5 Extension"
[9]: https://proceedings.neurips.cc/paper_files/paper/2020/hash/6b493230-Abstract.html "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
[10]: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/ "n8n Webhook node"
