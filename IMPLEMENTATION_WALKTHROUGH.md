# Local SEO Spider: Implementation Walkthrough

## 1. Local-first foundation

The project is a Python 3.12 application built with **FastAPI**, **SQLite**, **Playwright**, and server-rendered **HTMX** templates. The `run-local.sh` command creates the local virtual environment, installs declared dependencies, installs Chromium for rendered-page analysis, and starts the app on port 3000. Application records, crawl evidence, and generated exports are retained under the configured local data directory.

## 2. Permission and request boundary

Every crawl request must include an explicit ownership-or-permission acknowledgement. Requests without it are rejected before a crawl record is created. Input validation normalizes HTTP(S) URLs, removes fragments, rejects embedded credentials, constrains the URL cap and delay, and requires exact-list URLs to use the same normalized scheme and host as the declared target.

## 3. Controlled crawl loop

The crawler first requests `robots.txt`, reports whether it could be loaded, and checks every queued URL against the resulting policy. It uses a declared user agent, a configurable inter-request delay, a same-host discovery boundary, an explicit URL cap, and a redirect-hop limit. Internal `nofollow` links remain retained as evidence, but are not placed in the discovery queue when that control is active. The crawler does not submit forms, authenticate, alter target websites, or invoke write endpoints.

## 4. Source and rendered evidence

For each permitted response, the crawler stores response status, response type, redirect chain, source HTML, and selected SEO signals. When Playwright rendering is enabled and Chromium is available, it additionally captures a bounded rendered HTML snapshot and rendered text. A rendering failure is stored as page-level evidence while source-HTML analysis continues, which makes the failure recoverable rather than silently dropping the page.

## 5. Signals and audit rules

The parser collects titles, descriptions, headings, canonical declarations, meta and HTTP robots directives, links, images and alternate-text state, JSON-LD data, and rendered text. The deterministic analyzer turns those records into severity-labelled findings with the affected URL, observed evidence, and a concrete remediation note. It covers response errors, broken internal links, redirects chains, duplicate titles, descriptions and content, missing metadata, missing H1, missing image alternate text, invalid structured data, thin rendered content, and indexability conflicts.

## 6. Local marketing and comparison workflow

The **Content inventory** presents deliberately bounded page-level evidence for editorial planning: metadata coverage, H1 coverage, rendered word count, image-alternative coverage, JSON-LD types, and internal-link counts. It does not claim rankings, traffic, click-through rate, or rich-result eligibility. Completed crawls with the same normalized start URL can be compared locally for added or absent pages, observable metadata/text/status changes, and new or resolved issue fingerprints.

## 7. Interface and resilience

The Field Manual interface uses a responsive inspection-workbench layout. Its Target, Boundary, and Permission stages reinforce the crawl contract, while explicit empty, active, completed, failed, and validation-error states explain the next action. HTMX progressively enhances the form and status polling. A normal `POST /crawls` fallback redirects to the whole crawl-ledger page when the enhancement script is unavailable. The app sets `nosniff`, frame-denial, no-referrer, permissions-policy, and content-security headers.

## 8. Exports and backups

Each completed crawl can create a pages CSV, an issues CSV, and a standalone HTML report locally. Export names are sanitized and bounded. The repository ignores local crawl state, SQLite files, generated exports, virtual environments, package metadata, and local configuration; only code, documentation, test fixtures, and safe configuration templates are committed. The private repository is [yashrastogi069-dev/local-seo-spider](https://github.com/yashrastogi069-dev/local-seo-spider).

## 9. Verification performed

The automated suite verifies crawler rule transformation, comparison logic, URL scope and credential rejection, robots and redirect behavior, recoverable rendering fallback, CSV/report export generation and HTML escaping, contrast thresholds, local security headers, permission rejection, HTMX output, non-HTMX whole-page fallback, and the authorized crawl happy path. The final run was `./.venv/bin/python -m pytest -q && ./.venv/bin/python -m compileall -q app`, which completed with **7 passing tests**. Browser checks also confirmed desktop and 375 px mobile layouts, asset loading, visible skip-link focus, HTMX availability, standard form fallback attributes, and no runtime or content-security errors.
