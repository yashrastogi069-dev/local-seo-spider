# Crawler Research Notes

## Initial findings

The reference product is a **local desktop website crawler** that combines discovery, page-level inspection, issue reporting, exports, JavaScript rendering, and crawl comparison. Its public documentation specifically describes checks for broken links and server errors, redirect chains and loops, page titles and descriptions, duplicate elements, robots directives, canonical elements, JavaScript rendering, and comparison between crawls.[1]

The local implementation should therefore make each page record independently auditable: original URL, final URL, redirect hops, response status, raw HTML-derived fields, rendered DOM-derived fields, discovered links, and an associated issue evidence payload. Multiple completed crawl records should remain locally stored so later runs can be compared without uploading crawl data.

Google’s robots guidance states that a `robots.txt` file tells crawlers which URLs they can access and that the convention relies on the crawler obeying the file.[2] The crawler will fetch and parse robots.txt before enqueueing a URL, mark blocked URLs as `robots_blocked` rather than fetching them, and use a documented local user agent. It will not treat robots.txt as an indexing control: `noindex` in HTML metadata or the `X-Robots-Tag` response header is recorded separately because robots access and indexability are distinct signals.[2]

## Implementation implications

| Concern | Local behavior |
| --- | --- |
| Authorization | A crawl cannot be queued until the operator affirms ownership or authorization for the exact target host. |
| Scope | Discovery remains on the normalized start host. External links are collected as link targets but never crawled. |
| Respectful requests | A host-level delay is enforced between requests; the operator can increase it. A conservative URL cap is enforced per crawl. |
| Redirects | Each hop is recorded up to a small fixed safety maximum; chains are reported with full hop evidence. |
| Canonicals | Canonical URLs are normalized and recorded. A canonical points out of scope or conflicts with indexability becomes an evidence-backed issue. |
| Rendering | A direct HTTP fetch collects response headers and source HTML. Playwright then renders eligible HTML pages to collect final title, headings, rendered text, and post-JavaScript links. Rendering failure remains a recoverable per-page warning, not a failed crawl. |
| Repeatable audits | Settings and crawl timestamps are stored alongside the results. A later completed crawl can be compared by canonicalized URL and issue fingerprint. |

Google describes redirects, `rel="canonical"` annotations, and sitemap inclusion as signals for preferred canonical URLs, and documents both HTML `link` elements and HTTP response headers as canonical declarations.[3] The crawler will therefore collect canonical declarations from raw HTML and response headers, resolve relative canonical targets against the response URL, retain the normalized target as evidence, and report conflicting declarations or a canonical that resolves to a different host.

For link qualification, Google documents `sponsored`, `ugc`, and `nofollow` as `rel` values; links with those values are generally not followed, although they can be discovered through other paths.[4] The crawler will preserve every source-link record, classify all `rel` values, and keep `nofollow` links out of the discovery queue by default. This behavior is configurable in the local settings but is displayed prominently in the crawl record so a repeat audit remains reproducible.

The reference crawler’s configuration guide separates resource storage from crawling and supports an explicit-list workflow that audits supplied URLs without discovering additional internal links.[5] The local scope will support two deliberately bounded modes: **Site crawl**, which discovers same-host followable links until the cap, and **Exact URL list**, which fetches only the supplied same-host URLs. Both require an ownership acknowledgement. The first release will not add scheduling, automated production changes, authentication bypasses, or external service integration.

Playwright’s Python documentation defines a `Page` as a browser tab used to navigate URLs and interact with page content, with multiple pages able to share a browser context.[6] The crawler will use one isolated browser context for a crawl, a single page at a time, and a bounded navigation timeout. It extracts only browser-rendered page state and follows no interaction flows, form submission, login prompt, popup, or mutation action.

For marketing-oriented content review, Google explains that snippets are primarily constructed from page content and may use a meta description when it better describes the page. It describes the meta description as a short, relevant summary and discourages keyword-stuffed descriptions.[7] The local audit will therefore record description presence, duplicate values, character count, and a non-judgmental rendered-text preview. It will phrase missing and duplicate descriptions as content opportunities, not predictions of rankings, click-through rate, or search-result appearance.

Google also describes structured data as standardized information that helps systems understand and classify page content, while stating that required properties must be present for potential enhanced display and that accuracy and completeness matter more than volume.[8] The crawler will inventory JSON-LD `@type` values, capture parsing errors, and show type coverage by crawl. It will not promise rich-result eligibility or attempt to add markup to a live site.

## Marketing insight scope

The product will include a **Content Inventory** view for completed authorized crawls. It groups concrete page evidence by missing or duplicate title, missing or duplicate description, missing H1, thin rendered text, images without alternate text, and structured-data parse errors. It adds an internal-link context count so users can prioritize changes within their own information architecture. It deliberately excludes keyword scraping, backlink harvesting, competitor dataset collection, rank tracking, ad-platform integration, and publishing or changing any production content.

## Sources

[1]: https://www.screamingfrog.co.uk/seo-spider/ "Screaming Frog SEO Spider Website Crawler"
[2]: https://developers.google.com/search/docs/crawling-indexing/robots/intro "Google Search Central: Robots.txt Introduction and Guide"
[3]: https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls "Google Search Central: Canonicalization"
[4]: https://developers.google.com/search/docs/crawling-indexing/qualify-outbound-links "Google Search Central: Qualify Outbound Links"
[5]: https://www.screamingfrog.co.uk/seo-spider/user-guide/configuration/ "Screaming Frog SEO Spider Configuration"
[6]: https://playwright.dev/python/docs/pages "Playwright Python: Pages"
[7]: https://developers.google.com/search/docs/appearance/snippet "Google Search Central: Snippets and Meta Descriptions"
[8]: https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data "Google Search Central: Structured Data Introduction"
