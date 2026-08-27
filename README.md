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

## Architecture

```text
Browser + HTMX form
       │ explicit ownership/permission acknowledgement
       ▼
FastAPI request validation ──► SQLite crawl record (local `data/`)
       │                              │
       ▼                              ▼
Bounded same-host crawl        persisted pages, links, issues
       │                              │
       ├── robots.txt + request delay │
       ├── HTTP source + headers      ├── HTML ledger
       └── Playwright render          ├── Pages CSV / Issues CSV
                                      └── self-contained HTML report
```

`app/crawler.py` owns collection and is deliberately limited to a single host and local crawl settings. `app/parser.py` converts source or rendered HTML into structured records. `app/analyzer.py` is a deterministic transformation from persisted evidence to issue rows. `app/database.py` is the SQLite persistence boundary, while `app/exports.py` writes reproducible local exports. `app/templates/` and `app/static/` provide the Field Manual HTMX interface.

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

The tests include a focused transformation test for technical-issue evidence and a FastAPI/HTMX happy path that confirms the permission block, authorized crawl completion, audit rendering, and CSV and HTML exports.

## References

The implementation follows documented crawler and search signals: the reference crawler describes local site-audit checks for broken links, redirects, metadata, duplicate content, robots directives, JavaScript rendering, and crawl comparison.[1] Google documents `robots.txt` as a crawler-access mechanism rather than indexing control, and distinguishes it from `noindex`.[2] It also documents canonical signals,[3] link qualification values such as `nofollow`,[4] quality meta-description principles,[5] and structured-data expectations.[6] Playwright provides the browser page abstraction used for bounded rendered DOM inspection.[7]

[1]: https://www.screamingfrog.co.uk/seo-spider/ "Screaming Frog SEO Spider Website Crawler"
[2]: https://developers.google.com/search/docs/crawling-indexing/robots/intro "Google Search Central: Robots.txt Introduction"
[3]: https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls "Google Search Central: Canonicalization"
[4]: https://developers.google.com/search/docs/crawling-indexing/qualify-outbound-links "Google Search Central: Qualify Outbound Links"
[5]: https://developers.google.com/search/docs/appearance/snippet "Google Search Central: Snippets and Meta Descriptions"
[6]: https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data "Google Search Central: Structured Data Introduction"
[7]: https://playwright.dev/python/docs/pages "Playwright Python: Pages"
