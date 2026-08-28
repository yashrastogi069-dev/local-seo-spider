# Authorized Crawl Reliability Matrix

This application is designed to finish bounded audits without silently losing evidence. Its recovery model is deliberately conservative: a transient failure may be retried a small number of times, while repeated failures remain visible and never trigger evasive behavior or a different network identity.

| Failure mode | Handling | Evidence / operator outcome |
| --- | --- | --- |
| Temporary 408, 425, 429, 500, 502, 503, or 504 response | Retry up to `SPIDER_MAX_REQUEST_RETRIES` with exponential backoff capped by the configured retry count. | Every attempt remains in the redirect/evidence chain; a persistent status becomes a page error. |
| Transport timeout or connection error | Retry within the same host and request policy; after the final attempt, record a fetch error and continue the queue. | The failed URL is retained in the audit instead of stalling the crawl. |
| `robots.txt` unavailable | Continue with an explicit unavailable status and the documented local policy. | The crawl ledger records the robots status for review. |
| Robots denial | Do not fetch the URL. | A page record marks `robots_allowed=false`. |
| Redirect loop or excessive chain | Stop after `SPIDER_MAX_REDIRECTS`. | The chain and redirect-limit issue are retained. |
| Invalid or non-normalizable redirect location | Stop that URL safely. | A fetch error explains that the redirect could not be normalized. |
| Non-HTML response | Retain status and content type; skip HTML parsing and browser rendering. | The page remains in the inventory without fabricated SEO fields. |
| Oversized document | Store only up to `SPIDER_MAX_DOCUMENT_BYTES` for analysis and mark the body truncated. | The page remains auditable without unbounded stored HTML. |
| Malformed HTML | Parse with the tolerant HTML parser and continue. | Available signals are retained; missing signals can become evidence-backed issues. |
| Playwright/Chromium unavailable or render timeout | Continue with source HTML when available and record a render error. | Rendering failure is recoverable and visible per page. |
| Worker interruption | Startup recovery transitions an interrupted running job into a retryable or paused state according to the ledger policy. | The operator can review and explicitly resume it. |
| Repeated worker-level failure | Circuit breaker pauses the job rather than retrying forever. | The Field Manual exposes a paused state and explicit resume control. |

## Deliberate limits

The reliability controls never rotate identity, spoof a browser, bypass robots policy, submit forms, change production content, or broaden a crawl beyond the normalized authorized host and configured URL cap. Retries are for transient transport conditions within the same declared request policy; they are not a method for evading a site’s refusal.

## Configuration

Use `SPIDER_MAX_REQUEST_RETRIES=2` for the default maximum of three total attempts and `SPIDER_RETRY_BACKOFF_SECONDS=0.5` for a conservative backoff base. Set retries to `0` for a single-attempt audit. All local settings are loaded from `.env`, while the safe template remains in `local-seo-spider.env.example`.
