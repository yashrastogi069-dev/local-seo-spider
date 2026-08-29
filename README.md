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
| On-page SEO | Title, meta description, headings, canonical, meta robots, structured-data blocks, and image `alt` attributes. |
| Link graph | Source URL, normalized target, anchor text, link `rel`, same-host status, and nofollow status. |
| Reproducibility | Crawl creation and completion time, acknowledged authorization, crawl mode, URL cap, delay, and nofollow behavior. |

The crawl engine uses a direct HTTP request for headers and source HTML, then a bounded Playwright page visit for rendered DOM inspection. It does **not** submit forms, sign in, work around access controls, open pop-ups, collect credentials, or mutate target-site content. Playwright failure is a per-page, recoverable inspection warning; raw HTML findings remain available.

## Technical and content audit rules

The first release creates clear, evidence-backed findings for broken internal links, 4xx and 5xx responses, redirect chains, missing and duplicate titles, missing and duplicate descriptions, missing H1s, duplicate rendered content, image alternate-text gaps, invalid JSON-LD, orphan candidates, and canonical or robots indexability conflicts. Every row contains its severity, exact affected URL, collected evidence, and concrete remediation note.

The **Content Inventory** retains marketing-useful signals—heading coverage, description coverage, rendered word count, image alternative-text coverage, JSON-LD types, and internal-inlink context—so the locally exported page list can support editorial planning. These signals are evidence, not rank, traffic, click-through, or rich-result guarantees. The project does not collect web-scale keyword or backlink datasets, crawl unaffiliated sites without authorization, or publish changes to production websites.

Completed crawls of the same normalized start URL can also be compared locally. The comparison identifies added and absent URLs, observable changes to status, metadata, canonical, robots, and rendered-text hash, plus issue fingerprints that are new or no longer present. It does not infer cause, rankings, traffic, or business impact from those changes.

## Local website knowledge and grounded questions

Completed crawls now build a local SQLite FTS5 knowledge index from readable HTML blocks. Each indexed passage retains its crawl, page, URL, title, and heading path, so the question surface can show where evidence came from. Open a completed crawl and use **Ask the local crawl** to search the indexed website content. The answer mode is deliberately citation-first: it returns matching passages and abstains when the local crawl does not contain enough evidence. It does not invent facts, infer private content, or treat search ranking as proof. The **Rebuild local index** action can recover an index for an older completed crawl after parser improvements or a partial failure, and completed crawls can compare added and removed evidence chunks.

A read-only JSON endpoint is also available for local workflow experiments:

```text
GET /api/crawls/<crawl-id>/ask?q=your+question
```

The endpoint is scoped to one completed crawl and returns the question, grounded status, answer text, and citations. It is intentionally read-only; it cannot start crawls, submit forms to target websites, change production content, or access another crawl's evidence.

## Future automation boundary

The knowledge layer is designed so an automation tool such as n8n can later call the read-only question endpoint or receive explicit crawl-completed events. The current `/api/crawls/<crawl-id>/ask` endpoint is read-only and local. n8n supports webhook triggers and API-style responses, but any future integration must add explicit authentication, request validation, idempotency, local-network exposure controls, and operator approval. The default application remains local-only and does not connect to n8n or send crawl data anywhere.

A natural-language generator can be added later as an opt-in layer. To preserve the local-only promise, the preferred design is a model running on the same computer; any hosted model would require a separate, explicit privacy decision because website passages would leave the machine. Retrieval and citations remain the source of truth either way.

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

`app/crawler.py` owns collection and is deliberately limited to a single host and local crawl settings. `app/parser.py` converts source or rendered HTML into structured records. `app/knowledge.py` extracts citation-preserving readable chunks. `app/qa.py` answers from retrieved local evidence and abstains when support is insufficient. `app/analyzer.py` is a deterministic transformation from persisted evidence to issue rows. `app/database.py` is the SQLite persistence boundary and durable job ledger; it supports safe startup recovery, bounded retry timing, circuit-breaker pauses, explicit operator resume, and FTS5 knowledge retrieval. `app/exports.py` writes reproducible local exports. `app/templates/` and `app/static/` provide the Field Manual HTMX interface.

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

The tests cover deterministic technical-issue evidence, URL validation and safe filename behavior, robots and redirect handling, recoverable rendering fallback, CSV/HTML export safety, contrast regression, FastAPI security headers, permission blocking, HTMX and non-HTMX form paths, crawl comparison, durable SQLite job claim/retry/pause/resume/startup-recovery behavior, knowledge chunk provenance, crawl-scoped FTS5 retrieval, citation-first answers, abstention, and the completed-crawl question endpoint.

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
